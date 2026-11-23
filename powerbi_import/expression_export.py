"""Export expressions from locally generated TMDL models for review."""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .file_io import open_new_text

_NAME = r"(?:'(?:''|[^'])*'|[^\s=]+)"
_MEASURE = re.compile(rf"^\tmeasure (?P<name>{_NAME}) = (?P<expression>.*)$")
_COLUMN = re.compile(rf"^\tcolumn (?P<name>{_NAME}) = (?P<expression>.*)$")
_PHYSICAL_COLUMN = re.compile(rf"^\tcolumn {_NAME}$")
_PARTITION = re.compile(rf"^\tpartition (?P<name>{_NAME}) = (?P<kind>\w+)$")
_CALCULATION_ITEM = re.compile(rf"^\t\tcalculationItem (?P<name>{_NAME})$")
_ROLE = re.compile(rf"^role (?P<name>{_NAME})$")
_TABLE_PERMISSION = re.compile(rf"^\ttablePermission (?P<name>{_NAME})$")
_EXPRESSION = re.compile(rf"^expression (?P<name>{_NAME}) =(?P<expression>.*)$")
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT")
    for number in (*"123456789", "\u00b9", "\u00b2", "\u00b3")
}


def _filename(name):
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", name).rstrip(". ")
    if not safe or safe in {".", ".."}:
        raise ValueError(f"Cannot create an expression filename for {name!r}")
    stem, dot, suffix = safe.partition(".")
    if stem.rstrip(" ").upper() in _RESERVED:
        safe = stem + "_" + dot + suffix
    return safe


def _unquote(name):
    return name[1:-1].replace("''", "'") if name.startswith("'") else name


def _indented_expression(lines, start, prefix, source):
    result = []
    index = start
    while index < len(lines) and lines[index].startswith(prefix):
        result.append(lines[index][len(prefix):])
        index += 1
    while result and not result[-1]:
        result.pop()
    if not result:
        raise ValueError(f"Missing expression in {source}")
    return "\n".join(result), index


def _read_dax_expression(lines, expression, start, indent, kind, source):
    if expression != "```":
        if not expression.strip():
            raise ValueError(f"Missing {kind} expression in {source}")
        return expression, start
    result = []
    index = start
    while index < len(lines) and lines[index] != indent + "```":
        if not lines[index].startswith(indent):
            raise ValueError(f"Unsupported multiline {kind} in {source}")
        result.append(lines[index][len(indent):])
        index += 1
    if index == len(lines):
        raise ValueError(f"Unterminated multiline {kind} in {source}")
    expression = "\n".join(result)
    if not expression.strip():
        raise ValueError(f"Missing {kind} expression in {source}")
    return expression, index + 1


def _table_expressions(path):
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines[-1] == "":
        lines.pop()
    partitions = []
    measures = []
    calculated_columns = []
    calculated_partitions = []
    calculation_items = []
    refresh_expressions = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("\tpartition "):
            match = _PARTITION.fullmatch(line)
            if not match:
                raise ValueError(f"Unsupported partition declaration in {path}")
            kind = match.group("kind")
            name = match.group("name")
            index += 1
            if kind not in {"m", "calculated", "calculationGroup", "entity"}:
                raise ValueError(f"Unsupported partition type {kind!r} in {path}")
            if kind in {"calculationGroup", "entity"}:
                continue
            while index < len(lines) and lines[index].startswith("\t\t"):
                source_line = lines[index]
                if kind == "m" and source_line == "\t\tsource =":
                    expression, index = _indented_expression(
                        lines, index + 1, "\t\t\t\t", path
                    )
                    partitions.append(expression)
                    break
                if kind == "calculated" and source_line.startswith("\t\tsource = "):
                    expression, index = _read_dax_expression(
                        lines, source_line[len("\t\tsource = "):], index + 1,
                        "\t\t\t\t", "calculated partition", path,
                    )
                    calculated_partitions.append(f"{name} =\n{expression}")
                    break
                index += 1
            else:
                raise ValueError(f"Missing or unsupported {kind} partition source in {path}")
            continue
        if line.startswith("\tmeasure ") or line.startswith("\tcolumn "):
            is_measure = line.startswith("\tmeasure ")
            match = (_MEASURE if is_measure else _COLUMN).fullmatch(line)
            if not match:
                if not is_measure and _PHYSICAL_COLUMN.fullmatch(line):
                    index += 1
                    continue
                raise ValueError(f"Unsupported {'measure' if is_measure else 'column'} declaration in {path}")
            name, expression = match.group("name", "expression")
            kind = "measure" if is_measure else "calculated column"
            expression, index = _read_dax_expression(
                lines, expression, index + 1, "\t\t\t", kind, path,
            )
            (measures if is_measure else calculated_columns).append(f"{name} =\n{expression}")
            continue
        if line.startswith("\t\tcalculationItem "):
            match = _CALCULATION_ITEM.fullmatch(line)
            if not match:
                raise ValueError(f"Unsupported calculation item declaration in {path}")
            name = match.group("name")
            index += 1
            while index < len(lines) and lines[index].startswith("\t\t\t"):
                if lines[index].startswith("\t\t\texpression = "):
                    expression, index = _read_dax_expression(
                        lines, lines[index][len("\t\t\texpression = "):], index + 1,
                        "\t\t\t\t", "calculation item", path,
                    )
                    calculation_items.append(f"{name} =\n{expression}")
                    break
                index += 1
            else:
                raise ValueError(f"Missing calculation item expression in {path}")
            continue
        if line == "\trefreshPolicy":
            index += 1
            while index < len(lines) and lines[index].startswith("\t\t"):
                for property_name, label in (
                    ("pollingExpression", "Polling"),
                    ("sourceExpression", "Source"),
                ):
                    if lines[index] == f"\t\t{property_name} =":
                        expression, index = _indented_expression(
                            lines, index + 1, "\t\t\t\t", path,
                        )
                        refresh_expressions.append((label, expression))
                        break
                else:
                    index += 1
            continue
        index += 1
    return (partitions, measures, calculated_columns, calculated_partitions,
            calculation_items, refresh_expressions)


def _shared_expressions(path):
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines[-1] == "":
        lines.pop()
    expressions = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("expression "):
            match = _EXPRESSION.fullmatch(line)
            if not match:
                raise ValueError(f"Unsupported shared expression declaration in {path}")
            name = _unquote(match.group("name"))
            expression = match.group("expression").lstrip()
            index += 1
            if not expression:
                expression, index = _indented_expression(lines, index, "\t\t", path)
            expressions.append((name, expression))
            continue
        index += 1
    return expressions


def _role_expressions(path):
    if not path.is_file():
        return []
    roles = []
    current_role = None
    table = None
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.startswith("role "):
            match = _ROLE.fullmatch(line)
            if not match:
                raise ValueError(f"Unsupported role declaration in {path}")
            current_role = (_unquote(match.group("name")), [])
            roles.append(current_role)
            table = None
        elif line.startswith("\ttablePermission "):
            match = _TABLE_PERMISSION.fullmatch(line)
            if not match or current_role is None:
                raise ValueError(f"Unsupported table permission in {path}")
            table = match.group("name")
        elif line.startswith("\t\tfilterExpression"):
            prefix = "\t\tfilterExpression = "
            if not line.startswith(prefix) or current_role is None or table is None:
                raise ValueError(f"Unsupported role filter in {path}")
            expression = line[len(prefix):]
            if not expression.strip():
                raise ValueError(f"Missing role filter in {path}")
            current_role[1].append(f"-- Table permission: {table}\n{expression}")
    return roles


def _dataflow_expressions(model_dir, query_dir):
    project_dir = model_dir.parent.resolve()
    query_dir = Path(os.path.abspath(query_dir))
    try:
        relative_dir = query_dir.relative_to(project_dir)
    except ValueError as error:
        raise ValueError("Dataflow query directory must be within the model project") from error
    for index in range(1, len(relative_dir.parts) + 1):
        directory = project_dir.joinpath(*relative_dir.parts[:index])
        if directory.is_symlink() or directory.is_junction():
            raise ValueError("Dataflow query directory must not contain symbolic links or junctions")
    if not query_dir.is_dir():
        raise ValueError(f"Dataflow query directory not found: {query_dir}")
    result = []
    for path in sorted(query_dir.glob("*.m"), key=lambda item: item.name.casefold()):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Invalid Dataflow query file: {path}")
        result.append((path.stem, path.read_text(encoding="utf-8"),
                       (relative_dir / path.name).as_posix()))
    return result


def validate_expression_export_targets(output_dir, *, allow_missing=False):
    """Reject existing expression outputs before generating or exporting a project."""
    output_dir = Path(output_dir)
    if output_dir.is_symlink() or output_dir.is_junction():
        raise ValueError("Expression output directory must not be a symbolic link or junction")
    if not output_dir.exists() and allow_missing:
        return
    if not output_dir.is_dir():
        raise ValueError("Expression output directory must be an existing directory")
    for name in ("PowerQuery", "DAX", "expression_export.json"):
        target = output_dir / name
        if target.exists() or target.is_symlink():
            raise ValueError(f"Expression export target already exists: {target}")


def export_model_expressions(model_dir, output_dir, *, dataflow_query_dir=None):
    """Write review copies of expressions from generated TMDL and optional Dataflow queries."""
    model_dir, output_dir = Path(model_dir), Path(output_dir)
    definition = model_dir / "definition"
    tables_dir = definition / "tables"
    if not (definition / "model.tmdl").is_file() or not tables_dir.is_dir():
        raise ValueError(f"Not a generated TMDL semantic model: {model_dir}")
    tables = sorted(tables_dir.glob("*.tmdl"), key=lambda path: path.name.casefold())

    exports = []
    for path in tables:
        (partitions, measures, columns, calculated_tables,
         calculation_items, refresh_expressions) = _table_expressions(path)
        stem = _filename(path.stem)
        for index, expression in enumerate(partitions, 1):
            suffix = "" if len(partitions) == 1 else f"__{index}"
            exports.append((Path("PowerQuery") / f"{stem}{suffix}.pq",
                            expression, f"tables/{path.name}", "m_partition", "model"))
        if measures:
            exports.append((Path("DAX") / f"{stem}.dax",
                            "\n\n".join(measures), f"tables/{path.name}", "dax_measures", "model"))
        for directory, kind, expressions in (
            ("CalculatedColumns", "dax_calculated_columns", columns),
            ("CalculatedTables", "dax_calculated_partitions", calculated_tables),
            ("CalculationGroups", "dax_calculation_items", calculation_items),
        ):
            if expressions:
                exports.append((Path("DAX") / directory / f"{stem}.dax",
                                "\n\n".join(expressions), f"tables/{path.name}", kind, "model"))
        for label, expression in refresh_expressions:
            exports.append((Path("PowerQuery") / "RefreshPolicies" / f"{stem}__{label}.pq",
                            expression, f"tables/{path.name}", "m_refresh_policy", "model"))
    for name, expression in _shared_expressions(definition / "expressions.tmdl"):
        exports.append((Path("PowerQuery") / "Expressions" / f"{_filename(name)}.pq",
                        expression, "expressions.tmdl", "shared_m_expression", "model"))
    for name, expressions in _role_expressions(definition / "roles.tmdl"):
        if expressions:
            exports.append((Path("DAX") / "Roles" / f"{_filename(name)}.dax",
                            "\n\n".join(expressions), "roles.tmdl", "dax_role_filters", "model"))
    if dataflow_query_dir is not None:
        for name, expression, source in _dataflow_expressions(model_dir, dataflow_query_dir):
            exports.append((Path("PowerQuery") / "Dataflow" / f"{_filename(name)}.pq",
                            expression, source, "dataflow_m_query", "project"))

    seen = set()
    for relative, _, _, _, _ in exports:
        key = relative.as_posix().casefold()
        if key in seen:
            raise ValueError(f"Expression output filename collision: {relative}")
        seen.add(key)
    validate_expression_export_targets(output_dir)
    directories = {
        parent for relative, _, _, _, _ in exports
        for parent in relative.parents if parent != Path(".")
    }
    for directory in sorted(directories, key=lambda path: (len(path.parts), path.as_posix())):
        (output_dir / directory).mkdir()
    for relative, content, _, _, _ in exports:
        target = output_dir / relative
        with open_new_text(target) as handle:
            handle.write(content)
            if not content.endswith("\n"):
                handle.write("\n")
    manifest = {
        "schema_version": "1.1",
        "scope": ("generated_tmdl_and_dataflow_expressions_only"
                  if dataflow_query_dir is not None else "generated_tmdl_expressions_only"),
        "exports": [
            {"path": relative.as_posix(), "source": source, "kind": kind,
             **({"source_scope": "project"} if source_scope == "project" else {})}
            for relative, _, source, kind, source_scope in exports
        ],
    }
    with open_new_text(output_dir / "expression_export.json") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def export_generated_project(model_dir, *, include_dataflow=False):
    """Export a generated model beside its PBIP or Fabric project."""
    model_dir = Path(model_dir)
    query_dir = (model_dir.parent / f"{model_dir.stem}.Dataflow" / "queries"
                 if include_dataflow else None)
    return export_model_expressions(model_dir, model_dir.parent, dataflow_query_dir=query_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--semantic-model", required=True, help="Local generated .SemanticModel directory")
    parser.add_argument("--output-dir", required=True, help="New or empty output directory")
    parser.add_argument("--include-dataflow", action="store_true",
                        help="Also export the generated Fabric project's Dataflow queries")
    args = parser.parse_args(argv)
    try:
        model = Path(args.semantic_model).resolve()
        output = Path(args.output_dir)
        if output.is_symlink() or output.is_junction():
            raise ValueError("Output directory must not be a symbolic link or junction")
        resolved_output = output.resolve()
        if resolved_output == model or model in resolved_output.parents or resolved_output in model.parents:
            raise ValueError("Output directory must be separate from the semantic model")
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("Output directory must be new or empty")
        output.mkdir(parents=True, exist_ok=True)
        query_dir = (model.parent / f"{model.stem}.Dataflow" / "queries"
                     if args.include_dataflow else None)
        manifest = export_model_expressions(model, output, dataflow_query_dir=query_dir)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Expression export failed: {error}", file=sys.stderr)
        return 2
    print(f"Exported {len(manifest['exports'])} expression file(s) to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
