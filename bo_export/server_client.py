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

logger = logging.getLogger(__name__)

DEFAULT_PORT = 6405
API_VERSION = "v1"


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
