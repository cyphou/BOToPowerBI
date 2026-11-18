"""BO CMS (Central Management Server) REST API client.

Connects to SAP BusinessObjects server to list, search, and download
reports, universes, and other artifacts for migration.
"""

import base64
import json
import logging
import os
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

DEFAULT_PORT = 6405
API_VERSION = "v1"
_WEBI_RESPONSE_LIMIT = 16 * 1024 * 1024
_WEBI_PLAN_SNAPSHOT_LIMIT = 64 * 1024 * 1024
_WEBI_PLAN_MAX_DEPTH = 256
_WEBI_REQUEST_TIMEOUT = 30
_WEBI_NO_IDENTIFIER = object()


class BOServerClient:
    """Client for SAP BusinessObjects CMS REST API."""

    def __init__(self, server_url, username=None, password=None,
                 auth_type="enterprise", token=None):
        """Initialize BO server connection.

        Args:
            server_url: Base URL (e.g., https://bo-server:6405).
            username: CMS username.
            password: CMS password.
            auth_type: Authentication type (enterprise, ldap, windows, sap).
            token: Pre-authenticated token (optional).
        """
        self.server_url = server_url.rstrip("/")
        self.username = username
        self.password = password
        self.auth_type = auth_type
        self.token = token
        self._session_id = None

    def __enter__(self):
        self.logon()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logoff()

    def logon(self):
        """Authenticate and obtain a session token."""
        if self.token:
            self._session_id = self.token
            return

        url = f"{self.server_url}/biprws/logon/long"
        payload = json.dumps({
            "userName": self.username,
            "password": self.password,
            "auth": self.auth_type.upper(),
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self._session_id = data.get("logonToken", "")
                logger.info("Logged on to BO server: %s", self.server_url)
        except urllib.error.HTTPError as e:
            logger.error("Logon failed: %s %s", e.code, e.reason)
            raise

    def logoff(self):
        """End the session."""
        if not self._session_id:
            return

        url = f"{self.server_url}/biprws/logoff"
        req = self._make_request(url, method="POST")
        try:
            urllib.request.urlopen(req)
        except Exception:
            pass
        self._session_id = None

    def list_documents(self, folder=None, doc_type=None, limit=50, offset=0):
        """List documents (WebI, Crystal, etc.) on the server.

        Args:
            folder: Folder path to filter (e.g., "/Public/Sales").
            doc_type: Document type filter (webi, crystal, universe).
            limit: Max results per page.
            offset: Pagination offset.

        Returns:
            list[dict]: List of document descriptors.
        """
        params = {"limit": limit, "offset": offset}
        if folder:
            params["folder"] = folder
        if doc_type:
            params["type"] = doc_type

        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/documents"
        query = urllib.parse.urlencode(params)
        full_url = f"{url}?{query}"

        documents = []
        data = self._get_json(full_url)
        if data:
            entries = data.get("documents", data.get("entries", []))
            for entry in entries:
                documents.append({
                    "id": entry.get("id", ""),
                    "name": entry.get("name", ""),
                    "type": entry.get("type", ""),
                    "path": entry.get("path", entry.get("parentFolder", "")),
                    "cuid": entry.get("cuid", ""),
                    "modified": entry.get("updated", ""),
                    "owner": entry.get("owner", ""),
                })

        return documents

    def list_universes(self, limit=50, offset=0):
        """List available universes."""
        params = {"limit": limit, "offset": offset}
        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/universes"
        query = urllib.parse.urlencode(params)

        universes = []
        data = self._get_json(f"{url}?{query}")
        if data:
            for entry in data.get("universes", data.get("entries", [])):
                universes.append({
                    "id": entry.get("id", ""),
                    "name": entry.get("name", ""),
                    "type": entry.get("type", "unx"),
                    "path": entry.get("path", ""),
                    "cuid": entry.get("cuid", ""),
                })

        return universes

    def list_folders(self, parent_folder=None):
        """List folders in the CMS repository."""
        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/folders"
        if parent_folder:
            url += f"?folder={urllib.parse.quote(parent_folder)}"

        folders = []
        data = self._get_json(url)
        if data:
            for entry in data.get("folders", data.get("entries", [])):
                folders.append({
                    "id": entry.get("id", ""),
                    "name": entry.get("name", ""),
                    "path": entry.get("path", ""),
                })

        return folders

    def download_document(self, doc_id, output_dir):
        """Download a document binary from the server.

        Args:
            doc_id: Document ID or CUID.
            output_dir: Directory to save the downloaded file.

        Returns:
            str: Path to downloaded file.
        """
        os.makedirs(output_dir, exist_ok=True)

        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/documents/{doc_id}"
        req = self._make_request(url)
        req.add_header("Accept", "application/octet-stream")

        try:
            with urllib.request.urlopen(req) as resp:
                # Get filename from Content-Disposition header
                cd = resp.headers.get("Content-Disposition", "")
                filename = _parse_content_disposition(cd) or f"{doc_id}.wid"

                # Security: sanitize filename
                filename = os.path.basename(filename)
                if not filename or ".." in filename:
                    filename = f"{doc_id}.wid"

                output_path = os.path.join(output_dir, filename)
                with open(output_path, "wb") as f:
                    f.write(resp.read())

                logger.info("Downloaded: %s → %s", doc_id, output_path)
                return output_path

        except urllib.error.HTTPError as e:
            logger.error("Download failed for %s: %s %s", doc_id, e.code, e.reason)
            raise

    def get_document_info(self, doc_id):
        """Get detailed info about a document."""
        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/documents/{doc_id}"
        return self._get_json(url)

    def list_webi_reports(self, document_id):
        """List the report tabs of one Web Intelligence document."""
        payload = self._get_webi_report_resource(document_id)
        return _parse_webi_identified_list(payload, "reports", "report")

    def get_webi_report(self, document_id, report_id):
        """Get original metadata for one Web Intelligence report tab."""
        payload = self._get_webi_report_resource(document_id, report_id)
        data = json.loads(payload.decode("utf-8-sig"))
        report = data.get("report") if isinstance(data, dict) else None
        if not isinstance(report, dict):
            raise ValueError("Unexpected WebI report details response")
        identifier = report.get("id")
        _webi_path_segment(identifier, "report ID")
        if str(identifier) != str(report_id):
            raise ValueError("WebI report details ID does not match")
        return report

    def list_webi_report_elements(self, document_id, report_id, include_details=False):
        """List a report's original element metadata without inferring bindings."""
        if not isinstance(include_details, bool):
            raise ValueError("include_details must be a boolean")
        payload = self._get_webi_report_resource(
            document_id, report_id, resource="elements", include_details=include_details,
        )
        return _parse_webi_identified_list(payload, "elements", "element")

    def get_webi_document_snapshot(self, document_id, include_element_details=False,
                                   include_provider_query_metadata=False):
        """Capture a document's report elements and provider metadata read-only."""
        _webi_path_segment(document_id, "document ID")
        if not isinstance(include_element_details, bool):
            raise ValueError("include_element_details must be a boolean")
        if not isinstance(include_provider_query_metadata, bool):
            raise ValueError("include_provider_query_metadata must be a boolean")

        reports = []
        for summary in self.list_webi_reports(document_id):
            report_id = summary["id"]
            reports.append({
                "summary": summary,
                "details": self.get_webi_report(document_id, report_id),
                "elements": self.list_webi_report_elements(
                    document_id, report_id, include_details=include_element_details,
                ),
            })

        providers = []
        for summary in self.list_webi_data_providers(document_id):
            provider = {
                "summary": summary,
                "details": self.get_webi_data_provider(document_id, summary["id"]),
            }
            if include_provider_query_metadata:
                provider["query_plan"] = self.get_webi_query_plan(
                    document_id, summary["id"],
                )
                provider["query_specification_xml"] = self.get_webi_query_specification(
                    document_id, summary["id"],
                )
            providers.append(provider)

        return {
            "schema_version": "1.0",
            "document_id": str(document_id),
            "reports": reports,
            "data_providers": providers,
        }

    def list_webi_data_providers(self, document_id):
        """List the data providers of one Web Intelligence document."""
        payload = self._get_webi_resource(document_id, accept="application/json")
        data = json.loads(payload.decode("utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("dataproviders"), dict):
            raise ValueError("Unexpected WebI data-provider list response")
        providers = data["dataproviders"].get("dataprovider", [])
        if providers is None:
            providers = []
        elif isinstance(providers, dict):
            providers = [providers]
        if not isinstance(providers, list) or any(
            not isinstance(provider, dict)
            or not isinstance(provider.get("id"), str)
            or not provider["id"].strip()
            for provider in providers
        ):
            raise ValueError("Invalid WebI data-provider list")
        if len({provider["id"] for provider in providers}) != len(providers):
            raise ValueError("Duplicate WebI data-provider IDs")
        return providers

    def get_webi_data_provider(self, document_id, provider_id):
        """Get the original metadata for one Web Intelligence data provider."""
        payload = self._get_webi_resource(
            document_id, provider_id, accept="application/json",
        )
        data = json.loads(payload.decode("utf-8-sig"))
        provider = data.get("dataprovider") if isinstance(data, dict) else None
        if not isinstance(provider, dict) or provider.get("id") != str(provider_id):
            raise ValueError("Unexpected WebI data-provider details response")
        return provider

    def get_webi_query_plan(self, document_id, provider_id):
        """Get a query plan without flattening its SQL operators."""
        payload = self._get_webi_resource(
            document_id, provider_id, "queryplan", accept="application/xml",
        )
        plan = _parse_webi_query_plan(payload)
        if not plan["statements"]:
            logger.warning(
                "WebI query plan contains no SQL statements for document %s, provider %s",
                document_id, provider_id,
            )
        return {
            "document_id": str(document_id),
            "provider_id": str(provider_id),
            **plan,
        }

    def get_webi_query_specification(self, document_id, provider_id):
        """Get the original XML query specification for a data provider."""
        payload = self._get_webi_resource(
            document_id, provider_id, "specification", accept="application/xml",
        )
        text, root = _parse_webi_response_xml(payload)
        if _webi_xml_name(root.tag) not in ("QuerySpec", "QuerySpecification"):
            raise ValueError("Unexpected WebI query-specification response")
        xml_provider_id = root.get("dataProviderId")
        if xml_provider_id is not None and xml_provider_id != str(provider_id):
            raise ValueError("WebI query-specification provider ID does not match")
        return text

    def _get_webi_resource(self, document_id, provider_id=_WEBI_NO_IDENTIFIER, resource=None,
                           accept="application/json"):
        document = _webi_path_segment(document_id, "document ID")
        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/documents/{document}/dataproviders"
        if provider_id is not _WEBI_NO_IDENTIFIER:
            url += "/" + _webi_path_segment(provider_id, "data-provider ID")
        if resource:
            url += "/" + resource
        return self._request_webi_url(url, accept)

    def _get_webi_report_resource(self, document_id, report_id=_WEBI_NO_IDENTIFIER,
                                  resource=None, include_details=False):
        document = _webi_path_segment(document_id, "document ID")
        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/documents/{document}/reports"
        if report_id is not _WEBI_NO_IDENTIFIER:
            url += "/" + _webi_path_segment(report_id, "report ID")
        if resource:
            url += "/" + resource
        if include_details:
            url += "?allInfo=true"
        return self._request_webi_url(url, "application/json")

    def _request_webi_url(self, url, accept):
        if not self._session_id:
            raise RuntimeError("A logged-on BO session is required for WebI metadata")
        request = self._make_request(url)
        request.add_header("Accept", accept)
        with urllib.request.urlopen(request, timeout=_WEBI_REQUEST_TIMEOUT) as response:
            payload = response.read(_WEBI_RESPONSE_LIMIT + 1)
        if len(payload) > _WEBI_RESPONSE_LIMIT:
            raise ValueError("WebI response exceeds the maximum supported size")
        return payload

    def list_schedules(self, doc_id=None):
        """List scheduled instances for a document (or all)."""
        if doc_id:
            url = f"{self.server_url}/biprws/raylight/{API_VERSION}/documents/{doc_id}/schedules"
        else:
            url = f"{self.server_url}/biprws/raylight/{API_VERSION}/schedules"
        return self._get_json(url)

    def list_users(self, limit=50, offset=0):
        """List CMS users."""
        params = {"limit": limit, "offset": offset}
        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/users"
        query = urllib.parse.urlencode(params)
        return self._get_json(f"{url}?{query}")

    def list_groups(self):
        """List CMS user groups."""
        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/usergroups"
        return self._get_json(url)

    def get_server_info(self):
        """Get server version and configuration info."""
        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/serverinfo"
        return self._get_json(url)

    def search_documents(self, query, limit=50):
        """Search for documents by name or keyword."""
        params = {"query": query, "limit": limit}
        url = f"{self.server_url}/biprws/raylight/{API_VERSION}/documents"
        query_str = urllib.parse.urlencode(params)
        return self._get_json(f"{url}?{query_str}")

    def batch_download(self, folder, output_dir, doc_type=None):
        """Download all documents from a folder.

        Args:
            folder: Server folder path.
            output_dir: Local output directory.
            doc_type: Optional type filter.

        Returns:
            list[str]: List of downloaded file paths.
        """
        documents = self._paginated_get(
            lambda offset: self.list_documents(folder=folder, doc_type=doc_type, offset=offset)
        )

        paths = []
        for doc in documents:
            try:
                path = self.download_document(doc["id"], output_dir)
                paths.append(path)
            except Exception as e:
                logger.warning("Failed to download %s: %s", doc.get("name", doc["id"]), e)

        return paths

    def _make_request(self, url, method="GET", data=None):
        """Create an authenticated request."""
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if self._session_id:
            req.add_header("X-SAP-LogonToken", self._session_id)
        return req

    def _get_json(self, url):
        """GET a URL and parse JSON response."""
        req = self._make_request(url)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                logger.warning("Rate limited (429). Retry-After: %s", e.headers.get("Retry-After", "unknown"))
            logger.error("GET %s failed: %s %s", url, e.code, e.reason)
            return None
        except Exception as e:
            logger.error("GET %s failed: %s", url, e)
            return None

    def _paginated_get(self, fetch_fn, limit=50):
        """Fetch all pages of a paginated endpoint."""
        all_items = []
        offset = 0
        while True:
            items = fetch_fn(offset)
            if not items:
                break
            all_items.extend(items)
            if len(items) < limit:
                break
            offset += limit
        return all_items


def _parse_webi_identified_list(payload, container, item):
    data = json.loads(payload.decode("utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get(container), dict):
        raise ValueError(f"Unexpected WebI {item} list response")
    items = data[container].get(item, [])
    if items is None:
        items = []
    elif isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise ValueError(f"Invalid WebI {item} list")
    identifiers = []
    for entry in items:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid WebI {item} list")
        identifier = entry.get("id")
        _webi_path_segment(identifier, f"{item} ID")
        identifiers.append(str(identifier))
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"Duplicate WebI {item} IDs")
    return items


def _webi_path_segment(value, label):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"Invalid WebI {label}")
    value = str(value)
    if (not value.strip() or value in (".", "..") or "/" in value or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"Invalid WebI {label}")
    return urllib.parse.quote(value, safe="")


def _webi_xml_name(tag):
    return tag.rsplit("}", 1)[-1]


def _parse_webi_query_plan(payload):
    if len(payload) > _WEBI_RESPONSE_LIMIT:
        raise ValueError("WebI query plan exceeds the maximum supported size")
    text, root = _parse_webi_response_xml(payload)
    if _webi_xml_name(root.tag) != "queryplan":
        raise ValueError("Unexpected WebI query-plan response")

    statements = []
    pending = [(child, []) for child in reversed(root)]
    while pending:
        child, operators = pending.pop()
        name = _webi_xml_name(child.tag)
        if name == "statement":
            if len(child) or not child.text or not child.text.strip():
                raise ValueError("Invalid statement in WebI query plan")
            statements.append({
                "index": child.get("index"),
                "sql": child.text.strip(),
                "operators": operators,
            })
        else:
            if len(operators) >= _WEBI_PLAN_MAX_DEPTH:
                raise ValueError("WebI query plan exceeds the maximum nesting depth")
            pending.extend(
                (nested, operators + [name]) for nested in reversed(child)
            )

    return {
        "status": "available" if statements else "empty",
        "xml": text,
        "statements": statements,
        "single_statement": (
            len(root) == 1
            and _webi_xml_name(root[0].tag) == "statement"
            and len(statements) == 1
            and not (root.text or "").strip()
            and not (root[0].tail or "").strip()
        ),
    }


def load_webi_query_plan(path):
    """Load a saved API plan and verify its derived fields against its XML."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate key in WebI query-plan JSON")
            result[key] = value
        return result

    with open(path, "rb") as handle:
        content = handle.read(_WEBI_PLAN_SNAPSHOT_LIMIT + 1)
    if len(content) > _WEBI_PLAN_SNAPSHOT_LIMIT:
        raise ValueError("WebI query-plan JSON exceeds the maximum supported size")
    try:
        snapshot = json.loads(content.decode("utf-8-sig"), object_pairs_hook=unique_object)
    except json.JSONDecodeError:
        raise ValueError("Invalid WebI query-plan JSON") from None

    fields = {"document_id", "provider_id", "status", "xml", "statements", "single_statement"}
    if not isinstance(snapshot, dict) or set(snapshot) != fields:
        raise ValueError("WebI query-plan JSON must contain exactly the API plan fields")
    for field in ("document_id", "provider_id"):
        if not isinstance(snapshot[field], str):
            raise ValueError(f"WebI query-plan {field} must be a string")
        _webi_path_segment(snapshot[field], field)
    if not isinstance(snapshot["xml"], str):
        raise ValueError("WebI query-plan XML must be a string")

    parsed = _parse_webi_query_plan(snapshot["xml"].encode("utf-8"))
    if (type(snapshot["single_statement"]) is not bool
            or snapshot["single_statement"] != parsed["single_statement"]
            or snapshot["status"] != parsed["status"]
            or snapshot["statements"] != parsed["statements"]):
        raise ValueError("WebI query-plan JSON does not match its XML")
    return {
        "document_id": snapshot["document_id"],
        "provider_id": snapshot["provider_id"],
        **parsed,
    }


def _parse_webi_response_xml(payload):
    text = payload.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("WebI XML response contains a prohibited declaration")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError("Invalid WebI XML response") from error
    return text, root


def _parse_content_disposition(header):
    """Parse filename from Content-Disposition header."""
    if not header:
        return None
    import re
    match = re.search(r'filename[^;=\n]*=(["\'])(.+?)\1', header)
    if match:
        return match.group(2)
    match = re.search(r'filename[^;=\n]*=(.+?)(?:;|$)', header)
    if match:
        return match.group(1).strip()
    return None
