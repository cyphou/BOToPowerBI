"""Generate a local paginated RDL from an explicit mapping or extracted SQL."""

import argparse
import json
import sys
import zipfile
from pathlib import Path

from powerbi_import.paginated_generator import generate_semantic_model_rdl


def _mapping_with_sql(mapping, sql):
    keys = {"title", "source_kind", "server", "database", "columns"}
    if not isinstance(mapping, dict) or set(mapping) not in (
            keys, keys | {"parameters"}):
        raise ValueError("SQL source mode requires the documented SQL mapping without sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("selected SQL source must contain SQL text")
    return {**mapping, "sql": sql}


def _mapping_with_extracted_sql(mapping, entries, sql_name):
    if not sql_name or not sql_name.strip():
        raise ValueError("extracted SQL name must not be empty")
    if not isinstance(entries, list) or not all(isinstance(item, dict) for item in entries):
        raise ValueError("extracted SQL must be a JSON list of objects")
    matches = [item for item in entries if item.get("name") == sql_name]
    if len(matches) != 1:
        raise ValueError("extracted SQL name must match exactly one entry")
    return _mapping_with_sql(mapping, matches[0].get("sql"))


def _sql_from_bo_file(source_path, mapping):
    source = Path(source_path)
    if not source.is_file():
        raise ValueError("BO source must be an existing file")
    suffix = source.suffix.lower()
    source_kinds = {
        ".wid": "webi",
        ".rpt": "crystal",
        ".unx": "universe",
        ".unv": "universe",
    }
    if suffix not in source_kinds:
        raise ValueError("BO source must be a .wid, .rpt, .unx or .unv file")
    expected_kind = source_kinds[suffix]
    if not isinstance(mapping, dict) or mapping.get("source_kind") != expected_kind:
        raise ValueError("source_kind must match the BO source file type")
    if expected_kind == "webi":
        from bo_export.webi_extractor import extract_webi
        extracted = extract_webi(str(source))
    elif expected_kind == "crystal":
        from bo_export.crystal_extractor import extract_crystal
        extracted = extract_crystal(str(source))
    else:
        from bo_export.universe_extractor import extract_universe
        extracted = extract_universe(str(source))
    return extracted["custom_sql"]


def _check_webi_provider_in_wid(source_path, provider_id):
    source = Path(source_path)
    if not source.is_file() or source.suffix.lower() != ".wid":
        raise ValueError("WebI query-plan checking requires an existing .wid file")
    from bo_export.webi_extractor import extract_webi
    queries = extract_webi(str(source))["queries"]
    if sum(query.get("id") == provider_id for query in queries) != 1:
        raise ValueError("WID must contain exactly one provider matching the query-plan ID")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", required=True, help="Local mapping JSON; do not include credentials")
    parser.add_argument("--output", required=True, help="New .rdl file; existing files are not overwritten")
    parser.add_argument("--power-query-output", help="Optional new .m file for the same SQL Server mapping")
    parser.add_argument("--extracted-sql", help="Previously extracted custom_sql.json")
    parser.add_argument("--bo-source", help="Local .wid, .rpt, .unx or .unv file with extractable SQL")
    parser.add_argument("--webi-plan", help="Saved WebI API query-plan JSON")
    parser.add_argument("--sql-name", help="Exact name of one extracted SQL entry")
    args = parser.parse_args(argv)

    try:
        if args.extracted_sql is not None and (
                args.bo_source is not None or args.webi_plan is not None):
            raise ValueError("--extracted-sql cannot be combined with another SQL source")
        if args.webi_plan is not None:
            if args.sql_name is not None:
                raise ValueError("--sql-name cannot be combined with --webi-plan")
        else:
            has_source = args.extracted_sql is not None or args.bo_source is not None
            if has_source != (args.sql_name is not None):
                raise ValueError("--sql-name requires exactly one extracted SQL or BO source")
        output = Path(args.output)
        if output.suffix.lower() != ".rdl":
            raise ValueError("Output must be a new .rdl file.")
        m_output = Path(args.power_query_output) if args.power_query_output is not None else None
        if m_output is not None and m_output.suffix.lower() != ".m":
            raise ValueError("Power Query output must be a new .m file.")
        with Path(args.mapping).open(encoding="utf-8") as handle:
            mapping = json.load(handle)
        if args.extracted_sql is not None:
            with Path(args.extracted_sql).open(encoding="utf-8") as handle:
                entries = json.load(handle)
            mapping = _mapping_with_extracted_sql(mapping, entries, args.sql_name)
        elif args.bo_source is not None:
            if args.webi_plan is None:
                entries = _sql_from_bo_file(args.bo_source, mapping)
                mapping = _mapping_with_extracted_sql(mapping, entries, args.sql_name)
        if args.webi_plan is not None:
            from bo_export.server_client import load_webi_query_plan
            if not isinstance(mapping, dict) or mapping.get("source_kind") != "webi":
                raise ValueError("WebI query-plan mode requires source_kind webi")
            plan = load_webi_query_plan(args.webi_plan)
            if not plan["single_statement"]:
                raise ValueError("WebI query plan must contain one direct SQL statement")
            if args.bo_source is not None:
                _check_webi_provider_in_wid(args.bo_source, plan["provider_id"])
            mapping = _mapping_with_sql(mapping, plan["statements"][0]["sql"])
        content = generate_semantic_model_rdl(mapping) + "\n"
        if m_output is None:
            with output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
        else:
            if "sql" not in mapping:
                raise ValueError("Power Query output requires a SQL Server mapping.")
            if mapping.get("parameters"):
                raise ValueError(
                    "Power Query output does not support RDL report parameters."
                )
            if output.exists() or m_output.exists():
                raise ValueError("RDL and Power Query outputs must both be new files.")
            if not m_output.parent.is_dir():
                raise ValueError("Power Query output directory must already exist.")
            from bo_export.m_query_builder import build_m_query
            m_content = build_m_query(
                {"type": "sql_server", "server": mapping["server"],
                 "database": mapping["database"]},
                custom_sql=mapping["sql"],
            ) + "\n"
            with (output.open("x", encoding="utf-8", newline="\n") as rdl_handle,
                  m_output.open("x", encoding="utf-8", newline="\n") as m_handle):
                rdl_handle.write(content)
                m_handle.write(m_content)
    except json.JSONDecodeError:
        print("Paginated generation failed: an input file is not valid JSON.", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"Paginated generation failed: {error}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError, zipfile.BadZipFile):
        print(
            "Paginated generation failed while reading an input or writing output; "
            "check the paths and any partial files.",
            file=sys.stderr,
        )
        return 2

    targets = "RDL and Power Query" if m_output is not None else "RDL"
    if args.webi_plan is not None:
        print("WebI plan identity is declared; document, provider and report associations "
              "remain unverified.")
    print(f"Local {targets} generated from declarations; Desktop opening, report rendering, "
          "query execution and source equivalence are not_run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
