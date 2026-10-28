"""
Utility functions for classifying and converting BO calculated columns.

Determines which calculations should be materialised as physical columns
in the Lakehouse (loaded by Dataflows or Notebooks) versus kept as
DAX measures in the Semantic Model.

Architecture:
    Calculated columns → physical columns in Lakehouse Delta tables
    Measures           → DAX expressions in Semantic Model
"""

import re
import json
import ast

from .fabric_constants import AGG_PATTERN as _AGG_PATTERN, SPARK_TYPE_MAP

_CALC_SPARK_TYPE = {k: v for k, v in SPARK_TYPE_MAP.items()
                    if k in ('string', 'integer', 'int64', 'real',
                             'double', 'number', 'boolean', 'date', 'datetime')}


def classify_calculations(calculations):
    """Split BO calculations into *calculated columns* vs *measures*.

    Calculated columns are row-level expressions without aggregation and
    are materialised in the Lakehouse.  Measures use aggregation functions
    and remain as DAX in the Semantic Model.

    Returns:
        ``(calc_columns, measures)`` — two lists.
        Each ``calc_column`` dict carries an extra ``spark_type`` key.
    """
    calc_columns = []
    measures = []

    for calc in calculations:
        formula = calc.get('formula', '').strip()
        if not formula:
            continue

        role = calc.get('role', 'measure')
        datatype = calc.get('datatype', 'string')

        is_literal = '[' not in formula
        has_aggregation = bool(_AGG_PATTERN.search(formula)) or bool(re.search(
            r'\b(?:RunningSum|RunningCount|RunningAverage|RunningMin|RunningMax|RunningProduct)\s*\(',
            formula, re.IGNORECASE,
        ))

        is_calc_col = (not is_literal) and (
            role == 'dimension' or not has_aggregation
        )

        if is_calc_col:
            cc = dict(calc)
            cc['spark_type'] = _CALC_SPARK_TYPE.get(datatype, 'STRING')
            calc_columns.append(cc)
        else:
            measures.append(calc)

    return calc_columns, measures


def sanitize_calc_col_name(name):
    """Sanitize a calculated-column name for Delta Lake / Spark."""
    name = name.replace('[', '').replace(']', '')
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    name = re.sub(r'^[0-9]+', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return name.lower() or 'calc_col'


def bo_formula_to_m(formula):
    """Best-effort conversion of a BO formula to a Power Query M
    row expression (for use inside ``each …``).
    """
    m = formula.strip().removeprefix('=').lstrip()
    if re.search(r'\bPrevious\s*\(', m, re.IGNORECASE):
        return 'error "BO Previous requires explicit source ordering; materialization is unsupported"'

    # Pre-process ELSEIF → else if (before keyword lowering)
    m = re.sub(r'\bELSEIF\b', 'ELSE IF', m, flags=re.IGNORECASE)

    m = re.sub(r'\bIF\b', 'if', m, flags=re.IGNORECASE)
    m = re.sub(r'\bTHEN\b', 'then', m, flags=re.IGNORECASE)
    m = re.sub(r'\bELSE\b', 'else', m, flags=re.IGNORECASE)
    m = re.sub(r'\bEND\b', '', m, flags=re.IGNORECASE)

    # Ensure every M 'if...then' has a matching 'else' (Power Query M requires it).
    # Count if/then/else outside string literals.
    stripped = re.sub(r'"([^"]|"")*"', '""', m)
    if_count = len(re.findall(r'\bif\b', stripped))
    else_count = len(re.findall(r'\belse\b', stripped))
    if if_count > else_count:
        m = m.rstrip() + ' else null' * (if_count - else_count)

    m = re.sub(r'\bAND\b', 'and', m, flags=re.IGNORECASE)
    m = re.sub(r'\bOR\b', 'or', m, flags=re.IGNORECASE)
    m = re.sub(r'\bNOT\b', 'not', m, flags=re.IGNORECASE)

    m = re.sub(r'\bLEFT\s*\(', 'Text.Start(', m, flags=re.IGNORECASE)
    m = re.sub(r'\bRIGHT\s*\(', 'Text.End(', m, flags=re.IGNORECASE)
    m = re.sub(r'\bUPPER\s*\(', 'Text.Upper(', m, flags=re.IGNORECASE)
    m = re.sub(r'\bLOWER\s*\(', 'Text.Lower(', m, flags=re.IGNORECASE)
    m = re.sub(r'\bLEN\s*\(', 'Text.Length(', m, flags=re.IGNORECASE)
    m = re.sub(r'\bTRIM\s*\(', 'Text.Trim(', m, flags=re.IGNORECASE)
    m = re.sub(r'\bROUND\s*\(', 'Number.Round(', m, flags=re.IGNORECASE)
    m = re.sub(r'\bABS\s*\(', 'Number.Abs(', m, flags=re.IGNORECASE)
    m = re.sub(r'\bINT\s*\(', 'Number.IntegerDivide(', m, flags=re.IGNORECASE)

    return m.strip()


# Characters invalid in M generalized identifiers (must use [#"name"] quoting).
_M_SPECIAL = set('/()\'"+@#$%^&*!~`<>?;:{}|\\,-')


def _quote_m_ids(m_expr):
    """Quote [field] refs containing chars invalid in M generalized identifiers."""
    if not m_expr:
        return m_expr
    def _repl(match):
        name = match.group(1)
        if name.startswith('#"') or '=' in name:
            return match.group(0)
        if any(ch in _M_SPECIAL for ch in name):
            return f'[#"{name}"]'
        return match.group(0)
    return re.sub(r'\[([^\]]+)\]', _repl, m_expr)


def make_m_add_column_step(formula, col_name, prev_step):
    """Return a Power Query M ``Table.AddColumn`` step string.

    Returns:
        ``(m_line, step_name)`` tuple.
    """
    safe_col = col_name.replace('"', '""')
    m_expr = _quote_m_ids(bo_formula_to_m(formula))
    step_name = f'CalcCol_{sanitize_calc_col_name(col_name)}'
    line = f'    {step_name} = Table.AddColumn({prev_step}, "{safe_col}", each {m_expr})'
    return line, step_name


def bo_formula_to_pyspark(formula, col_name):
    """Best-effort conversion of a BO formula to PySpark
    ``.withColumn()`` code.
    """
    formula = formula.strip().removeprefix('=').lstrip()
    if re.search(r'\b(?:Previous|RunningSum|RunningCount|RunningAverage|RunningMin|RunningMax|RunningProduct)\s*\(', formula, re.IGNORECASE):
        return 'raise NotImplementedError("BO Previous requires explicit source ordering; materialization is unsupported")'
    quoted_name = json.dumps(col_name, ensure_ascii=False)

    def _col_ref(m):
        return f'F.col({json.dumps(m.group(1), ensure_ascii=False)})'

    if_match = re.match(
        r'^\s*IF\s+(.+?)\s+THEN\s+(.+?)\s+ELSE\s+(.+?)(?:\s+END)?\s*$',
        formula, re.IGNORECASE | re.DOTALL,
    )
    if if_match:
        cond = re.sub(r'\[([^\]]+)\]', _col_ref, if_match.group(1).strip())
        comparison = re.fullmatch(r'(F\.col\("(?:[^"\\]|\\.)*"\))\s*<>\s*([-+]?\d+(?:\.\d+)?)', cond)
        if comparison:
            cond = comparison.group(1) + ' != ' + comparison.group(2)
        then_v = re.sub(r'\[([^\]]+)\]', _col_ref, if_match.group(2).strip())
        else_v = re.sub(r'\[([^\]]+)\]', _col_ref, if_match.group(3).strip())
        pyspark_expr = f'F.when({cond}, {then_v}).otherwise({else_v})'
    elif re.match(r'^\[[^\]]+\]$', formula.strip()):
        inner = formula.strip().strip('[]')
        pyspark_expr = f'F.col({json.dumps(inner, ensure_ascii=False)})'
    else:
        pyspark_expr = re.sub(r'\[([^\]]+)\]', _col_ref, formula)
    try:
        expression_tree = ast.parse(pyspark_expr, mode='eval')
    except SyntaxError:
        return 'raise NotImplementedError("Unsupported BO row-expression syntax; manual materialization is required")'
    if any(isinstance(node, ast.Name) and node.id != 'F' for node in ast.walk(expression_tree)):
        return 'raise NotImplementedError("Unsupported BO row-expression function; manual materialization is required")'
    return f'df = df.withColumn({quoted_name}, {pyspark_expr})'
