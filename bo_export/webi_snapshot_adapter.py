"""Adapt a saved WebI CMS document snapshot to the BO extraction collections.

Only evidence present in the snapshot is carried over. SQL comes verbatim from
single-statement query plans and the connection is the caller's explicit
declaration; result columns, layout and report-to-provider links are not inferred.
"""

import logging

logger = logging.getLogger(__name__)

_COLLECTIONS = (
    "reports", "queries", "datasources", "formulas", "prompts", "filters",
    "tables", "columns", "joins", "groups", "sorts", "alerts", "subreports",
    "charts", "custom_sql",
)
_CONNECTION_FIELDS = {"name", "server", "database"}


def _text(value, label):
    if (not isinstance(value, str) or not value.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ValueError(f"{label} must be a non-empty string without control characters")
    return value


def _declared_connection(connection):
    if not isinstance(connection, dict) or set(connection) != _CONNECTION_FIELDS:
        raise ValueError(
            "connection must declare exactly name, server and database; "
            "credentials are not accepted"
        )
    return {
        "name": _text(connection["name"], "connection name"),
        "id": "",
        "connection_id": "",
        "type": "SQL Server",
        "server": _text(connection["server"], "connection server"),
        "database": _text(connection["database"], "connection database"),
        "universe": "",
        "connection_string": "",
    }


def _record_id(record, label):
    identifier = record.get("id") if isinstance(record, dict) else None
    if isinstance(identifier, int) and not isinstance(identifier, bool):
        identifier = str(identifier)
    return _text(identifier, label)


def extract_webi_snapshot(snapshot, connection):
    """Return the 15 BO collections for a snapshot and one declared SQL Server source.

    The declared connection is applied to every provider with exactly one direct
    SQL statement; the snapshot does not prove that this connection is the one
    the provider used. Other providers are skipped with a warning.
    """
    if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != "1.0"
            or not isinstance(snapshot.get("reports"), list)
            or not isinstance(snapshot.get("data_providers"), list)):
        raise ValueError("snapshot must be a version 1.0 WebI document snapshot")
    document_id = _text(snapshot.get("document_id"), "snapshot document_id")
    datasource = _declared_connection(connection)
    extracted = {name: [] for name in _COLLECTIONS}
    extracted["datasources"].append(datasource)

    for report in snapshot["reports"]:
        summary = report.get("summary") if isinstance(report, dict) else None
        report_id = _record_id(summary, "report ID")
        name = summary.get("name")
        if not isinstance(name, str) or not name.strip():
            logger.warning("Skipping snapshot report %s without a usable name", report_id)
            continue
        extracted["reports"].append({
            "id": report_id,
            "name": name,
            "type": "report",
            "cms_snapshot_layout_unconverted": True,
        })

    used_names = set()
    provider_ids = set()
    for provider in snapshot["data_providers"]:
        summary = provider.get("summary") if isinstance(provider, dict) else None
        provider_id = _record_id(summary, "provider ID")
        if provider_id in provider_ids:
            raise ValueError(
                f"duplicate provider summary ID {provider_id!r}; provider IDs must be unique"
            )
        provider_ids.add(provider_id)
        plan = provider.get("query_plan")
        if not isinstance(plan, dict) or plan.get("single_statement") is not True:
            logger.warning(
                "Skipping snapshot provider %s: it has no single direct SQL statement",
                provider_id,
            )
            continue
        for field in ("document_id", "provider_id"):
            plan_id = plan.get(field)
            if not isinstance(plan_id, str) or not plan_id.strip():
                raise ValueError(
                    f"snapshot document {document_id!r}, provider {provider_id!r}: "
                    f"query_plan.{field} must be a non-empty string"
                )
        if plan["document_id"] != document_id:
            raise ValueError(
                f"snapshot document {document_id!r}, provider {provider_id!r}: "
                "query_plan.document_id does not match snapshot document_id"
            )
        if plan["provider_id"] != provider_id:
            raise ValueError(
                f"snapshot document {document_id!r}, provider {provider_id!r}: "
                "query_plan.provider_id does not match provider summary ID"
            )
        if plan.get("status") != "available":
            raise ValueError(
                f"snapshot document {document_id!r}, provider {provider_id!r}: "
                "query_plan.status must be 'available'"
            )
        statements = plan.get("statements")
        if not isinstance(statements, list) or len(statements) != 1:
            raise ValueError(
                f"snapshot document {document_id!r}, provider {provider_id!r}: "
                "query_plan.statements must contain exactly one statement"
            )
        statement = statements[0]
        if not isinstance(statement, dict):
            raise ValueError(
                f"snapshot document {document_id!r}, provider {provider_id!r}: "
                "query_plan.statements[0] must be an object"
            )
        sql = statement.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            raise ValueError(
                f"snapshot document {document_id!r}, provider {provider_id!r}: "
                "query_plan.statements[0].sql must be a non-empty string"
            )
        if statement.get("operators") != []:
            raise ValueError(
                f"snapshot document {document_id!r}, provider {provider_id!r}: "
                "query_plan.statements[0].operators must be an empty list"
            )
        name = summary.get("name")
        if not isinstance(name, str) or not name.strip():
            name = provider_id
        if name.casefold() in used_names:
            name = f"{name} [{provider_id}]"
        used_names.add(name.casefold())
        extracted["queries"].append({
            "id": provider_id,
            "name": name,
            "type": summary.get("dataSourceType") or "",
            "universe": "",
            "datasource": datasource["name"],
            "sql": sql,
            "objects": [],
            "filters": [],
            "cms_snapshot": True,
        })
        extracted["custom_sql"].append({
            "name": name,
            "sql": sql,
            "datasource": datasource["name"],
        })
    return extracted
