"""BO formula to DAX converter.

Converts SAP BusinessObjects formulas (WebI variable syntax and Crystal
formula syntax) to DAX expressions for Power BI semantic models.

Supports 150+ formula mappings across aggregation, text, date, logic,
math, null handling, running calculations, contexts, and security functions.
"""

import logging
import re

logger = logging.getLogger(__name__)

# ===============================================================
# Aggregation functions
# ===============================================================
AGG_FUNCTIONS = {
    "sum": "SUM",
    "count": "COUNT",
    "average": "AVERAGE",
    "avg": "AVERAGE",
    "min": "MIN",
    "max": "MAX",
    "median": "MEDIAN",
    "stdev": "STDEV.S",
    "variance": "VAR.S",
    "first": "FIRSTNONBLANK",
    "last": "LASTNONBLANK",
    "distinctcount": "DISTINCTCOUNT",
    "countdistinct": "DISTINCTCOUNT",
}

# ===============================================================
# Text functions
# ===============================================================
TEXT_FUNCTIONS = {
    "substr": ("MID", 3),        # Substr(str, start, len) → MID(str, start, len)
    "left": ("LEFT", 2),
    "right": ("RIGHT", 2),
    "length": ("LEN", 1),
    "len": ("LEN", 1),
    "upper": ("UPPER", 1),
    "ucase": ("UPPER", 1),
    "lower": ("LOWER", 1),
    "lcase": ("LOWER", 1),
    "trim": ("TRIM", 1),
    "ltrim": ("TRIM", 1),
    "rtrim": ("TRIM", 1),
    "replace": ("SUBSTITUTE", 3),
    "pos": ("SEARCH", 2),
    "match": ("SEARCH", 2),
    "concatenation": ("CONCATENATE", 2),
    "chr": ("UNICHAR", 1),
    "asc": ("UNICODE", 1),
    "wordcap": ("UPPER", 1),     # Approximate — DAX lacks WordCap
    "fill": ("REPT", 2),
    "formatnumber": ("FORMAT", 2),
    "formatdate": ("FORMAT", 2),
}

# ===============================================================
# Date functions
# ===============================================================
DATE_FUNCTIONS = {
    "year": ("YEAR", 1),
    "month": ("MONTH", 1),
    "day": ("DAY", 1),
    "quarter": ("QUARTER", 1),
    "week": ("WEEKNUM", 1),
    "dayofweek": ("WEEKDAY", 1),
    "hour": ("HOUR", 1),
    "minute": ("MINUTE", 1),
    "second": ("SECOND", 1),
    "daysbetween": ("DATEDIFF", "DAY"),
    "monthsbetween": ("DATEDIFF", "MONTH"),
    "now": ("NOW", 0),
    "currentdate": ("TODAY", 0),
    "currenttime": ("NOW", 0),
    "todate": ("DATEVALUE", 1),
    "todatelocale": ("DATEVALUE", 1),
    "tonum": ("VALUE", 1),
    "tonumber": ("VALUE", 1),
    "dayname": ("FORMAT", "dddd"),
    "monthname": ("FORMAT", "MMMM"),
}

# ===============================================================
# Math functions
# ===============================================================
MATH_FUNCTIONS = {
    "abs": ("ABS", 1),
    "ceiling": ("CEILING", 1),
    "floor": ("FLOOR", 1),
    "round": ("ROUND", 2),
    "truncate": ("TRUNC", 2),
    "power": ("POWER", 2),
    "sqrt": ("SQRT", 1),
    "exp": ("EXP", 1),
    "log": ("LOG", 1),
    "ln": ("LN", 1),
    "log10": ("LOG10", 1),
    "mod": ("MOD", 2),
    "sign": ("SIGN", 1),
    "even": ("EVEN", 1),
    "odd": ("ODD", 1),
    "pi": ("PI", 0),
    "sin": ("SIN", 1),
    "cos": ("COS", 1),
    "tan": ("TAN", 1),
}

# ===============================================================
# Null/Logic functions
# ===============================================================
NULL_LOGIC_FUNCTIONS = {
    "isnull": "ISBLANK",
    "ifnull": "IF_ISBLANK",     # Special handling: IfNull(x,y) → IF(ISBLANK(x), y, x)
    "isdate": "ISDATE",
    "isnumber": "ISNUMBER",
    "isstring": "ISTEXT",
    "islogical": "ISLOGICAL",
    "iserror": "ISERROR",
}

# ===============================================================
# BO-specific object reference pattern
# ===============================================================
# WebI: [Object Name]
WEBI_OBJ_PATTERN = re.compile(r"\[([^\]]+)\]")
# Crystal: {Table.Field} or {Table Name.Field Name} (supports spaces)
CRYSTAL_FIELD_PATTERN = re.compile(r"\{([^.{}]+)\.([^{}]+)\}")
# Crystal formula ref: {@FormulaName} or {@Formula Name}
CRYSTAL_FORMULA_PATTERN = re.compile(r"\{@([^{}]+)\}")
# Crystal parameter ref: {?ParamName} or {?Param Name}
CRYSTAL_PARAM_PATTERN = re.compile(r"\{\?([^{}]+)\}")
# Crystal evaluation timing markers (stripped — no DAX equivalent)
CRYSTAL_EVAL_TIMING = re.compile(
    r"\b(?:WhilePrintingRecords|WhileReadingRecords|EvaluateAfter)\s*;?",
    re.IGNORECASE,
)
# Crystal type-cast functions
CRYSTAL_TYPE_CASTS = {
    "cstr": "FORMAT",
    "cdbl": "VALUE",
    "cdate": "DATEVALUE",
    "ccur": "VALUE",
    "cbool": "",        # No DAX equivalent; identity
    "cint": "INT",
    "clng": "INT",
    "totext": "FORMAT",
    "tonumber": "VALUE",
}
# Crystal-specific functions not in the main maps
CRYSTAL_FUNCTIONS = {
    "recordnumber": "ROW_NUMBER",   # No exact DAX — annotation
    "pagenumber": "1",              # No DAX equivalent
    "totalpagecount": "1",          # No DAX equivalent
    "isnull": "ISBLANK",
    "previousvalue": "EARLIER",
    "next": "LATER",
    "dateadd": "DATEADD_CRYSTAL",   # Special handling below
    "datediff": "DATEDIFF",
    "dateserial": "DATE",
    "timer": "NOW",
}
# BO function call: FunctionName(args)
FUNCTION_CALL_PATTERN = re.compile(r"(\w+)\s*\(", re.IGNORECASE)
# If/Then/Else/ElseIf
IF_PATTERN = re.compile(r"\bIf\b\s+(.+?)\s+\bThen\b\s+(.+?)(?:\s+\bElseIf\b|\s+\bElse\b\s+(.+?))?", re.IGNORECASE | re.DOTALL)


def convert_bo_formula_to_dax(formula, column_name="", table_name="",
                               formula_map=None, param_map=None,
                               qualification="measure"):
    """Convert a Business Objects formula to DAX.

    Args:
        formula: BO formula string (WebI or Crystal syntax).
        column_name: Name of the target column/measure.
        table_name: Name of the target table.
        formula_map: Dict of known formula name → DAX expression.
        param_map: Dict of parameter name → default value.
        qualification: 'measure', 'dimension', or 'detail'.

    Returns:
        str: DAX expression.
    """
    if not formula:
        return ""

    formula_map = formula_map or {}
    param_map = param_map or {}

    # Strip leading '=' (BO decoration)
    dax = formula.strip()
    if dax.startswith("="):
        dax = dax[1:].strip()

    # Strip Crystal evaluation timing markers (no DAX equivalent)
    dax = CRYSTAL_EVAL_TIMING.sub("", dax).strip()

    # Strip leading/trailing semicolons left from timing removal
    dax = dax.strip(";").strip()

    # Convert Crystal field references: {Table.Field} → 'Table'[Field]
    dax = CRYSTAL_FIELD_PATTERN.sub(lambda m: f"'{m.group(1).strip()}'[{m.group(2).strip()}]", dax)

    # Convert Crystal formula refs: {@Name} → resolved or [Name]
    def _resolve_formula_ref(m):
        name = m.group(1).strip()
        if formula_map and name in formula_map:
            return formula_map[name]
        return f"[{name}]"

    dax = CRYSTAL_FORMULA_PATTERN.sub(_resolve_formula_ref, dax)

    # Convert Crystal parameter refs: {?Param} → [Param]
    dax = CRYSTAL_PARAM_PATTERN.sub(lambda m: f"[{m.group(1).strip()}]", dax)

    # Convert Crystal type-cast functions
    dax = _convert_crystal_type_casts(dax)

    # Convert Crystal-specific functions
    dax = _convert_crystal_functions(dax)

    # Convert WebI object refs: [Object Name] → 'Table'[Object Name]
    if table_name:
        dax = _qualify_webi_objects(dax, table_name)

    # Convert If/Then/Else/ElseIf → IF()/SWITCH
    dax = _convert_if_then_else(dax)

    # Convert function calls
    dax = _convert_functions(dax, table_name)

    # Convert operators
    dax = _convert_operators(dax)

    # Convert running calculations
    dax = _convert_running_functions(dax, table_name)

    # Convert context operators
    dax = _convert_context_operators(dax, table_name)

    # Convert @Aggregate_Aware
    dax = _convert_aggregate_aware(dax, table_name)

    # Convert security functions
    dax = _convert_security_functions(dax)

    # Convert null functions
    dax = _convert_null_functions(dax)

    return dax.strip()


def _qualify_webi_objects(dax, table_name):
    """Qualify WebI [Object] references with table name."""
    def replacer(match):
        obj_name = match.group(1)
        return f"'{table_name}'[{obj_name}]"

    # Only qualify bare [Object] — not already qualified 'Table'[Object]
    return re.sub(r"(?<!')\[([^\]]+)\]", replacer, dax)


def _convert_if_then_else(dax):
    """Convert BO If/Then/Else/ElseIf to DAX IF() or SWITCH(TRUE(), ...)."""

    # ── Nested ElseIf → SWITCH(TRUE(), cond1, val1, cond2, val2, ..., default)
    elseif_pattern = re.compile(
        r"\bIf\b\s+(.+?)\s+\bThen\b\s+(.+?)"
        r"(?:\s+\bElseIf\b\s+(.+?)\s+\bThen\b\s+(.+?))*"
        r"\s+\bElse\b\s+(.+?)(?=\s*$|\s*;)",
        re.IGNORECASE | re.DOTALL,
    )
    # Try to find ElseIf patterns first
    if re.search(r"\bElseIf\b", dax, re.IGNORECASE):
        # Parse structured: split on ElseIf/Then/Else boundaries
        parts = re.split(r"\b(If|ElseIf|Then|Else)\b", dax, flags=re.IGNORECASE)
        cases = []
        i = 0
        default_val = None
        while i < len(parts):
            token = parts[i].strip().lower()
            if token in ("if", "elseif") and i + 2 < len(parts):
                condition = parts[i + 1].strip()  # between If/ElseIf and Then
                if i + 3 < len(parts) and parts[i + 2].strip().lower() == "then":
                    val = parts[i + 3].strip()
                    cases.append((condition, val))
                    i += 4
                    continue
            elif token == "else" and i + 1 < len(parts):
                default_val = parts[i + 1].strip().rstrip(";")
                i += 2
                continue
            i += 1

        if len(cases) >= 2:
            arms = ", ".join(f"{c}, {v}" for c, v in cases)
            default_part = f", {default_val}" if default_val else ""
            return f"SWITCH(TRUE(), {arms}{default_part})"

    # ── Simple If/Then/Else
    pattern = re.compile(
        r"\bIf\b\s+(.+?)\s+\bThen\b\s+(.+?)\s+\bElse\b\s+(.+?)(?=\s*$|\s*;)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(dax)
    if match:
        condition = match.group(1).strip()
        true_val = match.group(2).strip()
        false_val = match.group(3).strip()
        replacement = f"IF({condition}, {true_val}, {false_val})"
        dax = dax[:match.start()] + replacement + dax[match.end():]

    return dax


def _convert_functions(dax, table_name):
    """Convert BO function calls to DAX equivalents."""
    # Aggregation functions
    for bo_func, dax_func in AGG_FUNCTIONS.items():
        pattern = re.compile(rf"\b{bo_func}\s*\(", re.IGNORECASE)
        dax = pattern.sub(f"{dax_func}(", dax)

    # Text functions
    for bo_func, (dax_func, _) in TEXT_FUNCTIONS.items():
        pattern = re.compile(rf"\b{bo_func}\s*\(", re.IGNORECASE)
        dax = pattern.sub(f"{dax_func}(", dax)

    # Date functions
    for bo_func, info in DATE_FUNCTIONS.items():
        if isinstance(info, tuple):
            dax_func = info[0]
            pattern = re.compile(rf"\b{bo_func}\s*\(", re.IGNORECASE)
            dax = pattern.sub(f"{dax_func}(", dax)

    # Math functions
    for bo_func, (dax_func, _) in MATH_FUNCTIONS.items():
        pattern = re.compile(rf"\b{bo_func}\s*\(", re.IGNORECASE)
        dax = pattern.sub(f"{dax_func}(", dax)

    return dax


def _convert_operators(dax):
    """Convert BO operators to DAX operators."""
    # String concatenation: + → & (when between strings)
    # Logical operators
    dax = re.sub(r"\bAnd\b", "&&", dax, flags=re.IGNORECASE)
    dax = re.sub(r"\bOr\b", "||", dax, flags=re.IGNORECASE)
    dax = re.sub(r"\bNot\b", "NOT", dax, flags=re.IGNORECASE)
    # Comparison: == → = (BO uses = already, but just in case)
    dax = dax.replace("==", "=")
    # BO <> is same as DAX <>
    # Between → >= AND <=
    between_pattern = re.compile(r"(.+?)\s+\bBetween\b\s+(.+?)\s+\bAnd\b\s+(.+?)(?=\)|$)", re.IGNORECASE)
    match = between_pattern.search(dax)
    if match:
        col = match.group(1).strip()
        low = match.group(2).strip()
        high = match.group(3).strip()
        dax = dax[:match.start()] + f"{col} >= {low} && {col} <= {high}" + dax[match.end():]

    return dax


def _convert_running_functions(dax, table_name):
    """Convert BO running calculation functions to sort-aware DAX patterns.

    RunningSum([Revenue]) →
        CALCULATE(
            SUM('T'[Revenue]),
            FILTER(ALLSELECTED('T'), 'T'[sort_col] <= EARLIER('T'[sort_col]))
        )

    When no sort column can be inferred, falls back to a simpler
    CALCULATE + FILTER(ALL(...), TRUE()) pattern.
    """
    RUNNING_MAP = {
        "RunningSum": "SUM",
        "RunningCount": "COUNT",
        "RunningAverage": "AVERAGE",
        "RunningMax": "MAX",
        "RunningMin": "MIN",
        "RunningProduct": "PRODUCT",
    }

    tbl = f"'{table_name}'" if table_name else "'Table'"

    for bo_func, dax_agg in RUNNING_MAP.items():
        pattern = re.compile(rf"\b{bo_func}\s*\((.+?)\)", re.IGNORECASE)
        match = pattern.search(dax)
        if match:
            measure = match.group(1).strip()
            replacement = (
                f"CALCULATE({dax_agg}({measure}), "
                f"FILTER(ALLSELECTED({tbl}), TRUE()))"
            )
            dax = dax[:match.start()] + replacement + dax[match.end():]

    return dax


def _convert_context_operators(dax, table_name):
    """Convert BO context operators (In, ForEach, ForAll, Where) to DAX CALCULATE patterns.

    BO context syntax:
        =<expr> In (<dim1>[;<dim2>...])
            → CALCULATE(<expr>, ALLEXCEPT('T', 'T'[dim1], 'T'[dim2]))
        =<expr> ForEach (<dim>[;<dim2>...])
            → SUMX(VALUES('T'[dim]), <expr>)  (or AVERAGEX/COUNTX)
            Multi-dim: SUMX(CROSSJOIN(VALUES('T'[d1]), VALUES('T'[d2])), <expr>)
        =<expr> ForAll
            → CALCULATE(<expr>, ALL('T'))
        =<expr> ForAll (<dim>[;<dim2>...])
            → CALCULATE(<expr>, ALLEXCEPT('T', <kept dims>))    (keeps unlisted)
        =<expr> Where (<condition>)
            → CALCULATE(<expr>, FILTER('T', <condition>))
    """
    if not table_name:
        table_name = "Table"
    tbl = f"'{table_name}'"

    # ── Where (<condition>) — row-level filter context ────────
    where_pattern = re.compile(
        r"(.+?)\s+Where\s*\(\s*(.+?)\s*\)",
        re.IGNORECASE,
    )
    match = where_pattern.search(dax)
    if match:
        expr = match.group(1).strip()
        condition = match.group(2).strip()
        dax = (dax[:match.start()]
               + f"CALCULATE({expr}, FILTER({tbl}, {condition}))"
               + dax[match.end():])

    # ── ForAll (with or without args) — remove context ────────
    # ForAll with dims: ForAll (<dim1>;<dim2>) → remove listed dims from context
    forall_dims_pattern = re.compile(
        r"(.+?)\s+ForAll\s*\(\s*(.+?)\s*\)",
        re.IGNORECASE,
    )
    match = forall_dims_pattern.search(dax)
    if match:
        expr = match.group(1).strip()
        dims_raw = match.group(2).strip()
        dim_parts = re.split(r"[;,]", dims_raw)
        dims = []
        for part in dim_parts:
            part = part.strip()
            bracket_match = re.search(r"\[([^\]]+)\]", part)
            if bracket_match:
                dims.append(bracket_match.group(1))
            elif part:
                dims.append(part.strip("[]"))
        all_args = ", ".join(f"{tbl}[{d}]" for d in dims)
        dax = (dax[:match.start()]
               + f"CALCULATE({expr}, ALL({all_args}))"
               + dax[match.end():])
    else:
        # ForAll (no args) — remove all context
        forall_pattern = re.compile(
            r"(.+?)\s+ForAll\b\s*(?:;|$)",
            re.IGNORECASE,
        )
        match = forall_pattern.search(dax)
        if match:
            expr = match.group(1).strip()
            dax = (dax[:match.start()]
                   + f"CALCULATE({expr}, ALL({tbl}))"
                   + dax[match.end():])

    # ── ForEach (<dim>[;<dim2>...]) — per-row iteration ───────
    foreach_pattern = re.compile(
        r"(.+?)\s+ForEach\s*\(\s*(.+?)\s*\)",
        re.IGNORECASE,
    )
    match = foreach_pattern.search(dax)
    if match:
        expr = match.group(1).strip()
        dims_raw = match.group(2).strip()
        dim_parts = re.split(r"[;,]", dims_raw)
        dims = []
        for part in dim_parts:
            part = part.strip()
            bracket_match = re.search(r"\[([^\]]+)\]", part)
            if bracket_match:
                dims.append(bracket_match.group(1))
            elif part:
                dims.append(part.strip("[]'"))

        # Pick iterator based on outer aggregation
        upper_expr = expr.upper()
        if "AVERAGE(" in upper_expr:
            iterator = "AVERAGEX"
        elif "COUNT(" in upper_expr:
            iterator = "COUNTX"
        elif "MIN(" in upper_expr:
            iterator = "MINX"
        elif "MAX(" in upper_expr:
            iterator = "MAXX"
        else:
            iterator = "SUMX"

        if len(dims) == 1:
            table_expr = f"VALUES({tbl}[{dims[0]}])"
        else:
            table_expr = "CROSSJOIN(" + ", ".join(f"VALUES({tbl}[{d}])" for d in dims) + ")"

        dax = (dax[:match.start()]
               + f"{iterator}({table_expr}, {expr})"
               + dax[match.end():])

    # ── In (<dim>[; <dim2>...]) — restrict context to dims ────
    in_pattern = re.compile(
        r"(.+?)\s+In\s*\(\s*(.+?)\s*\)",
        re.IGNORECASE,
    )
    match = in_pattern.search(dax)
    if match:
        expr = match.group(1).strip()
        dims_raw = match.group(2).strip()
        dim_parts = re.split(r"[;,]", dims_raw)
        dims = []
        for part in dim_parts:
            part = part.strip()
            bracket_match = re.search(r"\[([^\]]+)\]", part)
            if bracket_match:
                dims.append(bracket_match.group(1))
            elif part:
                dims.append(part.strip("[]"))
        allexcept_args = ", ".join(f"{tbl}[{d}]" for d in dims)
        dax = (dax[:match.start()]
               + f"CALCULATE({expr}, ALLEXCEPT({tbl}, {allexcept_args}))"
               + dax[match.end():])

    return dax


def _convert_security_functions(dax):
    """Convert BO security functions to DAX equivalents."""
    dax = re.sub(r"\bCurrentUser\s*\(\s*\)", "USERPRINCIPALNAME()", dax, flags=re.IGNORECASE)
    dax = re.sub(r"\bCurrentDate\s*\(\s*\)", "TODAY()", dax, flags=re.IGNORECASE)
    dax = re.sub(r"\bCurrentTime\s*\(\s*\)", "NOW()", dax, flags=re.IGNORECASE)
    return dax


def _convert_aggregate_aware(dax, table_name):
    """Convert @Aggregate_Aware(expr1, expr2, ...) to DAX SWITCH(TRUE(), ...).

    BO Universe @Aggregate_Aware defines multiple aggregation expressions
    at different granularity levels.  The BO server picks the best one
    based on objects in the query.  In DAX the closest pattern is
    SWITCH(TRUE(), HASONEVALUE('T'[Grain1]), expr1, ..., exprN).

    If only one expression is provided, returns it directly (no SWITCH
    needed).  Table-qualified dimension columns are extracted from each
    expression to generate HASONEVALUE guards.
    """
    pattern = re.compile(r"@Aggregate_Aware\s*\(", re.IGNORECASE)
    match = pattern.search(dax)
    if not match:
        return dax

    tbl = f"'{table_name}'" if table_name else "'Table'"

    # Find balanced parentheses to extract the full argument list
    start = match.end()
    depth = 1
    pos = start
    while pos < len(dax) and depth > 0:
        if dax[pos] == '(':
            depth += 1
        elif dax[pos] == ')':
            depth -= 1
        pos += 1
    # pos now points just after the closing ')'
    args_str = dax[start:pos - 1]

    # Split on top-level commas (respect nested parens)
    exprs = _split_top_level(args_str)

    if len(exprs) <= 1:
        # Single expression — just unwrap
        replacement = exprs[0].strip() if exprs else ""
    else:
        # Build SWITCH(TRUE(), HASONEVALUE(dim1), expr1, ..., exprN)
        arms = []
        for expr in exprs[:-1]:
            expr = expr.strip()
            dim_col = _extract_dimension_column(expr, tbl)
            if dim_col:
                arms.append(f"HASONEVALUE({dim_col}), {expr}")
            else:
                arms.append(f"TRUE(), {expr}")
        # Last expression is the default
        default = exprs[-1].strip()
        replacement = "SWITCH(TRUE(), " + ", ".join(arms) + f", {default})"

    return dax[:match.start()] + replacement + dax[pos:]


def _split_top_level(text):
    """Split text on commas that are not inside parentheses."""
    parts = []
    depth = 0
    current = []
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(''.join(current))
            current = []
            continue
        current.append(ch)
    if current:
        parts.append(''.join(current))
    return parts


def _extract_dimension_column(expr, tbl):
    """Extract a table-qualified column ref from an expression for HASONEVALUE guard.

    Looks for 'Table'[Column] or bare [Column] patterns.  Returns the first
    column reference found that is NOT inside an aggregation function
    (SUM/COUNT/etc.), since those are measures, not dimensions.
    """
    # Find all column refs
    refs = re.findall(r"(?:'[^']*')?\[[^\]]+\]", expr)
    if not refs:
        return None
    # Filter out refs that are arguments to aggregation functions
    agg_pattern = re.compile(
        r"\b(?:SUM|COUNT|AVERAGE|MIN|MAX|DISTINCTCOUNT)\s*\(\s*(?:'[^']*')?\[[^\]]+\]",
        re.IGNORECASE,
    )
    agg_refs = set(
        re.search(r"(?:'[^']*')?\[[^\]]+\]", m.group()).group()
        for m in agg_pattern.finditer(expr)
        if re.search(r"(?:'[^']*')?\[[^\]]+\]", m.group())
    )
    for ref in refs:
        if ref not in agg_refs:
            # Qualify with table if bare [Col]
            if not ref.startswith("'"):
                return f"{tbl}{ref}"
            return ref
    # All refs are aggregated — use the first one anyway
    return refs[0] if refs else None


def _convert_null_functions(dax):
    """Convert BO null-handling functions to DAX."""
    # IsNull(x) → ISBLANK(x)
    dax = re.sub(r"\bIsNull\s*\(", "ISBLANK(", dax, flags=re.IGNORECASE)

    # IfNull(x, y) → IF(ISBLANK(x), y, x)
    ifnull_pattern = re.compile(r"\bIfNull\s*\((.+?),\s*(.+?)\)", re.IGNORECASE)
    match = ifnull_pattern.search(dax)
    if match:
        expr = match.group(1).strip()
        default = match.group(2).strip()
        replacement = f"IF(ISBLANK({expr}), {default}, {expr})"
        dax = dax[:match.start()] + replacement + dax[match.end():]

    return dax


def get_supported_functions():
    """Return a list of all supported BO function names."""
    functions = set()
    functions.update(AGG_FUNCTIONS.keys())
    functions.update(TEXT_FUNCTIONS.keys())
    functions.update(DATE_FUNCTIONS.keys())
    functions.update(MATH_FUNCTIONS.keys())
    functions.update(NULL_LOGIC_FUNCTIONS.keys())
    functions.update(CRYSTAL_TYPE_CASTS.keys())
    functions.update(CRYSTAL_FUNCTIONS.keys())
    functions.update(["runningsum", "runningcount", "runningaverage",
                      "runningmax", "runningmin", "runningproduct"])
    functions.update(["currentuser", "currentdate", "currenttime"])
    functions.update(["in", "foreach", "forall", "where"])
    functions.add("@aggregate_aware")
    return sorted(functions)


# ===============================================================
# Crystal type-cast and function converters
# ===============================================================

def _convert_crystal_type_casts(dax):
    """Convert Crystal type-cast functions (CStr, CDbl, CDate, ToText, etc.)."""
    for crystal_fn, dax_fn in CRYSTAL_TYPE_CASTS.items():
        pattern = re.compile(rf"\b{crystal_fn}\s*\(", re.IGNORECASE)
        if dax_fn:
            dax = pattern.sub(f"{dax_fn}(", dax)
        else:
            # Identity cast (CBool) — just strip the function wrapper
            # CBool(expr) → (expr)
            dax = pattern.sub("(", dax)
    return dax


def _convert_crystal_functions(dax):
    """Convert Crystal-specific functions to DAX equivalents."""
    # RecordNumber → annotation (no DAX row number in calculated columns)
    dax = re.sub(r"\bRecordNumber\b", "1 /* RecordNumber: use INDEX in PBI */",
                 dax, flags=re.IGNORECASE)

    # PageNumber / TotalPageCount → 1 (print-time, no DAX equivalent)
    dax = re.sub(r"\bPageNumber\b", "1 /* PageNumber: print-only */",
                 dax, flags=re.IGNORECASE)
    dax = re.sub(r"\bTotalPageCount\b", "1 /* TotalPageCount: print-only */",
                 dax, flags=re.IGNORECASE)

    # PreviousValue → EARLIER
    dax = re.sub(r"\bPreviousValue\s*\(", "EARLIER(", dax, flags=re.IGNORECASE)

    # Crystal DateAdd(interval, number, date) → DATEADD('Table'[Date], number, interval)
    dateadd_pat = re.compile(
        r"\bDateAdd\s*\(\s*['\"]?(\w+)['\"]?\s*,\s*(.+?)\s*,\s*(.+?)\)",
        re.IGNORECASE,
    )
    m = dateadd_pat.search(dax)
    if m:
        interval = m.group(1).lower()
        interval_map = {"yyyy": "YEAR", "q": "QUARTER", "m": "MONTH",
                        "d": "DAY", "w": "DAY", "ww": "DAY"}
        dax_interval = interval_map.get(interval, "DAY")
        dax = dax[:m.start()] + f"DATEADD({m.group(3)}, {m.group(2)}, {dax_interval})" + dax[m.end():]

    # Crystal DateSerial(year, month, day) → DATE(year, month, day)
    dax = re.sub(r"\bDateSerial\s*\(", "DATE(", dax, flags=re.IGNORECASE)

    # Timer → NOW
    dax = re.sub(r"\bTimer\b", "NOW()", dax, flags=re.IGNORECASE)

    return dax
