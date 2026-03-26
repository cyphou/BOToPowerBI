#!/usr/bin/env python3
"""Generate realistic SAP BusinessObjects sample files for migration testing.

Produces synthetic .wid, .rpt, .unx, .unv, .lumx, and .biar artifacts
that exercise the full extraction -> generation -> validation pipeline.

Usage:
    python examples/generate_samples.py
"""

import io
import json
import os
import xml.etree.ElementTree as ET
import zipfile

EXAMPLES_DIR = os.path.dirname(os.path.abspath(__file__))


# ══════════════════════════════════════════════════════════════════════════════
# XML builder helpers (proper escaping via ElementTree)
# ══════════════════════════════════════════════════════════════════════════════

def _build_webi_xml(name, queries, variables, prompts, charts, filters,
                    tables, datasource, custom_sql=None):
    """Build a WebI document XML string using ElementTree (safe escaping)."""
    root = ET.Element("Document")

    # Datasource
    ET.SubElement(root, "DataSource",
                  name=datasource["name"], type=datasource["type"],
                  server=datasource.get("server", ""),
                  database=datasource.get("database", ""),
                  universe=datasource.get("universe", ""))

    # Queries / data providers
    for q in queries:
        dp = ET.SubElement(root, "DataProvider",
                           name=q["name"], type=q.get("type", "universe"),
                           universe=q.get("universe", ""))
        for obj in q.get("objects", []):
            ET.SubElement(dp, "ResultObject",
                          name=obj["name"],
                          qualification=obj.get("qualification", "dimension"),
                          path=obj.get("path", ""))
        if q.get("sql"):
            sql_el = ET.SubElement(dp, "SQL")
            sql_el.text = q["sql"]

    # Tables
    for t in tables:
        ET.SubElement(root, "Table",
                      name=t["name"], schema=t.get("schema", "dbo"),
                      type=t.get("type", "table"))

    # Variables (formulas)
    for v in variables:
        ET.SubElement(root, "Variable",
                      name=v["name"], formula=v["formula"],
                      qualification=v.get("qualification", "measure"),
                      dataType=v.get("data_type", "number"),
                      description=v.get("description", ""))

    # Prompts
    for p in prompts:
        pr = ET.SubElement(root, "Prompt",
                           name=p["name"], type=p.get("type", "text"),
                           required=str(p.get("required", True)).lower(),
                           multiValue=str(p.get("multi_value", False)).lower(),
                           dimension=p.get("associated_dimension", ""),
                           operator=p.get("operator", "Equal To"))
        for val in p.get("default_values", []):
            v_el = ET.SubElement(pr, "Value")
            v_el.text = str(val)

    # Filters
    for f in filters:
        qf = ET.SubElement(root, "QueryFilter",
                           name=f.get("name", ""),
                           operator=f.get("operator", "Equal To"),
                           object=f.get("object", ""))
        for val in f.get("values", []):
            v_el = ET.SubElement(qf, "Value")
            v_el.text = str(val)

    # Report tabs
    report = ET.SubElement(root, "Report", name=name)
    ET.SubElement(report, "Section", name="Header", type="header")
    ET.SubElement(report, "Section", name="Body", type="body")
    ET.SubElement(report, "Section", name="Footer", type="footer")

    # Charts
    for c in charts:
        ch = ET.SubElement(root, "Chart",
                           name=c["name"], type=c["type"],
                           title=c.get("title", ""), report=name)
        for dim in c.get("dimensions", []):
            ET.SubElement(ch, "CategoryAxis", name=dim)
        for meas in c.get("measures", []):
            ET.SubElement(ch, "ValueSeries", name=meas)

    # Breaks / groups
    ET.SubElement(root, "Break", name="YearBreak", object="Year",
                  sortOrder="ascending")

    # Sorts
    ET.SubElement(root, "Sort", object="Revenue", order="descending",
                  type="value")

    # Alerters
    ET.SubElement(root, "Alerter", name="HighRevenue",
                  condition="Revenue > 100000",
                  format="background-color:#FF0000")

    # Custom SQL
    for sql in (custom_sql or []):
        fs = ET.SubElement(root, "FreehandSQL",
                           name=sql["name"],
                           datasource=sql.get("datasource", ""))
        fs.text = sql["sql"]

    # Document links
    ET.SubElement(root, "DocumentLink", name="DrillToDetail",
                  target="Detail_Report")

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode")


def _create_wid(filename, xml_content):
    """Create a .wid file (ZIP containing document.xml)."""
    path = os.path.join(EXAMPLES_DIR, filename)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("document.xml", xml_content)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    print(f"  Created {filename} ({os.path.getsize(path):,} bytes)")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# 1. WebI samples (.wid)
# ══════════════════════════════════════════════════════════════════════════════

def generate_webi_sales():
    """Enterprise Sales -- full-featured WebI document."""
    xml = _build_webi_xml(
        name="Sales Dashboard",
        queries=[
            {
                "name": "Sales_Query",
                "type": "universe",
                "universe": "eFashion",
                "objects": [
                    {"name": "Year", "qualification": "dimension", "path": "Time/Year"},
                    {"name": "Quarter", "qualification": "dimension", "path": "Time/Quarter"},
                    {"name": "Month", "qualification": "dimension", "path": "Time/Month"},
                    {"name": "Product Line", "qualification": "dimension", "path": "Product/Line"},
                    {"name": "Product Category", "qualification": "dimension", "path": "Product/Category"},
                    {"name": "Store Region", "qualification": "dimension", "path": "Store/Region"},
                    {"name": "Store Country", "qualification": "dimension", "path": "Store/Country"},
                    {"name": "Store City", "qualification": "dimension", "path": "Store/City"},
                    {"name": "Revenue", "qualification": "measure", "path": "Measures/Revenue"},
                    {"name": "Quantity Sold", "qualification": "measure", "path": "Measures/Quantity Sold"},
                    {"name": "Margin", "qualification": "measure", "path": "Measures/Margin"},
                    {"name": "Discount", "qualification": "measure", "path": "Measures/Discount"},
                ],
                "sql": ("SELECT T.YEAR, T.QUARTER, P.PRODUCT_LINE, S.REGION, "
                        "SUM(F.REVENUE), SUM(F.QUANTITY) "
                        "FROM FACT_SALES F "
                        "JOIN DIM_TIME T ON F.TIME_ID = T.ID "
                        "JOIN DIM_PRODUCT P ON F.PRODUCT_ID = P.ID "
                        "JOIN DIM_STORE S ON F.STORE_ID = S.ID "
                        "GROUP BY T.YEAR, T.QUARTER, P.PRODUCT_LINE, S.REGION"),
            },
        ],
        variables=[
            {"name": "Revenue Growth %",
             "formula": "=(([Revenue] - Previous([Revenue])) / Previous([Revenue])) * 100",
             "qualification": "measure", "data_type": "number",
             "description": "Year-over-year revenue growth percentage"},
            {"name": "Margin %",
             "formula": "=([Margin] / [Revenue]) * 100",
             "qualification": "measure", "data_type": "number"},
            {"name": "High Revenue Flag",
             "formula": '=If [Revenue] > 100000 Then "High" Else "Normal"',
             "qualification": "dimension", "data_type": "string"},
            {"name": "Running Revenue",
             "formula": "=RunningSum([Revenue])",
             "qualification": "measure", "data_type": "number"},
            {"name": "Revenue by Region",
             "formula": "=Sum([Revenue]) In ([Store Region])",
             "qualification": "measure", "data_type": "number"},
            {"name": "Total Revenue",
             "formula": "=Sum([Revenue]) ForAll",
             "qualification": "measure", "data_type": "number"},
            {"name": "Revenue per Product",
             "formula": "=Sum([Revenue]) ForEach ([Product Line])",
             "qualification": "measure", "data_type": "number"},
        ],
        prompts=[
            {"name": "Select Year", "type": "number", "required": True,
             "default_values": ["2023", "2024"], "multi_value": True,
             "associated_dimension": "Year", "operator": "In List"},
            {"name": "Select Region", "type": "text", "required": False,
             "default_values": ["EMEA"], "associated_dimension": "Store Region"},
        ],
        charts=[
            {"name": "Revenue Trend", "type": "line", "title": "Revenue Over Time",
             "dimensions": ["Year", "Quarter"], "measures": ["Revenue", "Margin"]},
            {"name": "Regional Breakdown", "type": "bar", "title": "Revenue by Region",
             "dimensions": ["Store Region"], "measures": ["Revenue"]},
            {"name": "Product Mix", "type": "pie", "title": "Revenue by Product Line",
             "dimensions": ["Product Line"], "measures": ["Revenue"]},
            {"name": "Margin Scatter", "type": "scatter", "title": "Revenue vs Margin",
             "dimensions": ["Product Category"], "measures": ["Revenue", "Margin %"]},
        ],
        filters=[
            {"name": "Year Filter", "operator": "In List", "object": "Year",
             "values": ["2023", "2024"]},
            {"name": "Active Products", "operator": "Equal To", "object": "Product Status",
             "values": ["Active"]},
        ],
        tables=[
            {"name": "FACT_SALES", "schema": "dbo", "type": "table"},
            {"name": "DIM_TIME", "schema": "dbo", "type": "table"},
            {"name": "DIM_PRODUCT", "schema": "dbo", "type": "table"},
            {"name": "DIM_STORE", "schema": "dbo", "type": "table"},
        ],
        datasource={
            "name": "eFashion Universe", "type": "universe",
            "server": "bo-server.corp.com", "database": "eFashion",
            "universe": "eFashion",
        },
    )
    return _create_wid("Enterprise_Sales.wid", xml)


def generate_webi_hr():
    """HR Analytics -- WebI with formulas, context operators, prompts."""
    xml = _build_webi_xml(
        name="HR Analytics",
        queries=[
            {
                "name": "HR_Query",
                "type": "universe",
                "universe": "HR_Universe",
                "objects": [
                    {"name": "Department", "qualification": "dimension"},
                    {"name": "Employee Name", "qualification": "dimension"},
                    {"name": "Hire Date", "qualification": "dimension"},
                    {"name": "Job Title", "qualification": "dimension"},
                    {"name": "Salary", "qualification": "measure"},
                    {"name": "Headcount", "qualification": "measure"},
                    {"name": "Turnover Rate", "qualification": "measure"},
                ],
            },
        ],
        variables=[
            {"name": "Avg Salary", "formula": "=Average([Salary])",
             "qualification": "measure", "data_type": "number"},
            {"name": "Tenure Years",
             "formula": "=DaysBetween([Hire Date]; CurrentDate()) / 365",
             "qualification": "measure", "data_type": "number"},
            {"name": "Salary Band",
             "formula": '=If [Salary] > 100000 Then "Senior" ElseIf [Salary] > 60000 Then "Mid" Else "Junior"',
             "qualification": "dimension", "data_type": "string"},
            {"name": "Dept Avg Salary",
             "formula": "=Average([Salary]) In ([Department])",
             "qualification": "measure", "data_type": "number"},
            {"name": "Salary Where Active",
             "formula": '=Sum([Salary]) Where ([Status] = "Active")',
             "qualification": "measure", "data_type": "number"},
        ],
        prompts=[
            {"name": "Department", "type": "text", "required": True,
             "default_values": ["Engineering", "Sales"]},
            {"name": "Min Salary", "type": "number", "required": False,
             "default_values": ["50000"]},
        ],
        charts=[
            {"name": "Salary Distribution", "type": "histogram",
             "dimensions": ["Salary Band"], "measures": ["Headcount"]},
            {"name": "Turnover Trend", "type": "line",
             "dimensions": ["Hire Date"], "measures": ["Turnover Rate"]},
        ],
        filters=[
            {"name": "Active Only", "operator": "Equal To", "object": "Status",
             "values": ["Active"]},
        ],
        tables=[
            {"name": "DIM_EMPLOYEE", "schema": "hr"},
            {"name": "DIM_DEPARTMENT", "schema": "hr"},
            {"name": "FACT_SALARY", "schema": "hr"},
        ],
        datasource={
            "name": "HR Database", "type": "sqlserver",
            "server": "hr-db.corp.com", "database": "HumanResources",
        },
    )
    return _create_wid("HR_Analytics.wid", xml)


def generate_webi_finance():
    """Financial Report -- WebI with custom SQL, running totals."""
    xml = _build_webi_xml(
        name="Financial Report",
        queries=[
            {
                "name": "Finance_Query",
                "type": "direct",
                "objects": [
                    {"name": "Account", "qualification": "dimension"},
                    {"name": "Cost Center", "qualification": "dimension"},
                    {"name": "Fiscal Year", "qualification": "dimension"},
                    {"name": "Fiscal Period", "qualification": "dimension"},
                    {"name": "Amount", "qualification": "measure"},
                    {"name": "Budget", "qualification": "measure"},
                ],
                "sql": ("SELECT A.ACCOUNT_NAME, C.COST_CENTER, T.FISCAL_YEAR, "
                        "T.FISCAL_PERIOD, SUM(F.AMOUNT), SUM(F.BUDGET) "
                        "FROM GL_FACT F "
                        "JOIN GL_ACCOUNT A ON F.ACCOUNT_ID = A.ID "
                        "JOIN GL_COST_CENTER C ON F.CC_ID = C.ID "
                        "JOIN GL_TIME T ON F.TIME_ID = T.ID "
                        "WHERE T.FISCAL_YEAR >= 2022 "
                        "GROUP BY A.ACCOUNT_NAME, C.COST_CENTER, "
                        "T.FISCAL_YEAR, T.FISCAL_PERIOD"),
            },
        ],
        variables=[
            {"name": "Variance", "formula": "=([Amount] - [Budget])",
             "qualification": "measure", "data_type": "number"},
            {"name": "Variance %",
             "formula": "=If [Budget] <> 0 Then (([Amount] - [Budget]) / [Budget]) * 100 Else 0",
             "qualification": "measure", "data_type": "number"},
            {"name": "Running Balance", "formula": "=RunningSum([Amount])",
             "qualification": "measure", "data_type": "number"},
            {"name": "YTD Amount",
             "formula": "=RunningSum([Amount]) In ([Fiscal Year])",
             "qualification": "measure", "data_type": "number"},
            {"name": "Grand Total", "formula": "=Sum([Amount]) ForAll",
             "qualification": "measure", "data_type": "number"},
            {"name": "Amount by CC",
             "formula": "=Sum([Amount]) ForEach ([Cost Center]; [Account])",
             "qualification": "measure", "data_type": "number"},
        ],
        prompts=[
            {"name": "Fiscal Year", "type": "number", "required": True,
             "default_values": ["2024"]},
            {"name": "Cost Center", "type": "text", "required": False,
             "multi_value": True},
        ],
        charts=[
            {"name": "Budget vs Actual", "type": "bar",
             "dimensions": ["Fiscal Period"], "measures": ["Amount", "Budget"]},
            {"name": "Variance Waterfall", "type": "waterfall",
             "dimensions": ["Account"], "measures": ["Variance"]},
        ],
        filters=[],
        tables=[
            {"name": "GL_FACT", "schema": "fin"},
            {"name": "GL_ACCOUNT", "schema": "fin"},
            {"name": "GL_COST_CENTER", "schema": "fin"},
            {"name": "GL_TIME", "schema": "fin"},
        ],
        datasource={
            "name": "Finance DB", "type": "oracle",
            "server": "fin-db.corp.com:1521", "database": "FINPROD",
        },
        custom_sql=[
            {"name": "GL_Summary",
             "sql": "SELECT FISCAL_YEAR, SUM(AMOUNT) AS TOTAL FROM GL_FACT GROUP BY FISCAL_YEAR",
             "datasource": "Finance DB"},
        ],
    )
    return _create_wid("Financial_Report.wid", xml)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Crystal Reports samples (.rpt) -- binary with embedded text markers
# ══════════════════════════════════════════════════════════════════════════════

def _build_rpt_binary(text_segments):
    """Build a .rpt-like binary file with embedded text markers."""
    buf = bytearray()
    # RPT binary header (simulated)
    buf.extend(b"\x00\x00\x01\x00")
    buf.extend(b"Crystal Reports\x00\x00")
    buf.extend(b"\x00" * 64)

    for segment in text_segments:
        buf.extend(b"\x00" * 8)
        buf.extend(segment.encode("ascii", errors="replace"))
        buf.extend(b"\x00" * 4)

    buf.extend(b"\x00" * 128)
    return bytes(buf)


def _create_rpt(filename, binary_content):
    """Create a .rpt file."""
    path = os.path.join(EXAMPLES_DIR, filename)
    with open(path, "wb") as f:
        f.write(binary_content)
    print(f"  Created {filename} ({os.path.getsize(path):,} bytes)")
    return path


def generate_crystal_invoice():
    """Invoice Report -- Crystal with formulas, groups, subreports, parameters."""
    segments = [
        # Database fields
        "{Orders.OrderID}",
        "{Orders.OrderDate}",
        "{Orders.CustomerID}",
        "{Orders.ShipDate}",
        "{Customers.CompanyName}",
        "{Customers.ContactName}",
        "{Customers.Country}",
        "{Customers.City}",
        "{OrderDetails.ProductID}",
        "{OrderDetails.UnitPrice}",
        "{OrderDetails.Quantity}",
        "{OrderDetails.Discount}",
        "{Products.ProductName}",
        "{Products.CategoryName}",
        # Formulas
        "{@LineTotal}",
        "{@SubTotal}",
        "{@TaxAmount}",
        "{@GrandTotal}",
        "{@DiscountPct}",
        "{@ShipDays}",
        "{@FormattedDate}",
        # Parameters
        "{?StartDate}",
        "{?EndDate}",
        "{?CustomerCountry}",
        "{?MinOrderAmount}",
        # Groups
        "Group #1 on {Customers.CompanyName}",
        "Group #2 on {Orders.OrderDate}",
        "Group #3 on {Products.CategoryName}",
        # Sorts
        "Sort on {Customers.CompanyName} Ascending",
        "Sort on {Orders.OrderDate} Descending",
        "Sort on {OrderDetails.UnitPrice} Descending",
        # Charts
        "Chart SalesByCategory - Bar",
        "Chart MonthlyTrend - Line",
        "Chart TopCustomers - Pie",
        # Subreports
        "Subreport CustomerDetails",
        "Subreport OrderHistory",
        # Running totals
        "Running Total PageTotal on {OrderDetails.UnitPrice}",
        "Running Total RunningBalance on {OrderDetails.Quantity}",
        # Conditional formatting
        "Condition Formula Rule: DiscountHighlight",
        "Condition Formula Rule: GrandTotalHighlight",
        # SQL
        ("SELECT O.OrderID, O.OrderDate, C.CompanyName, "
         "OD.UnitPrice, OD.Quantity, OD.Discount, P.ProductName "
         "FROM Orders O "
         "JOIN Customers C ON O.CustomerID = C.CustomerID "
         "JOIN OrderDetails OD ON O.OrderID = OD.OrderID "
         "JOIN Products P ON OD.ProductID = P.ProductID"),
    ]
    return _create_rpt("Invoice_Report.rpt", _build_rpt_binary(segments))


def generate_crystal_inventory():
    """Inventory Report -- Crystal with cross-tabs, running totals, alerts."""
    segments = [
        # Tables
        "{Inventory.ProductID}",
        "{Inventory.WarehouseID}",
        "{Inventory.StockQty}",
        "{Inventory.ReorderLevel}",
        "{Inventory.UnitCost}",
        "{Warehouses.WarehouseName}",
        "{Warehouses.Location}",
        "{Products.ProductName}",
        "{Products.Category}",
        "{Products.Supplier}",
        # Formulas
        "{@StockValue}",
        "{@ReorderFlag}",
        "{@DaysOfStock}",
        "{@TotalInventoryValue}",
        # Parameters
        "{?Warehouse}",
        "{?Category}",
        # Groups
        "Group #1 on {Warehouses.WarehouseName}",
        "Group #2 on {Products.Category}",
        # Sorts
        "Sort on {Products.ProductName} Ascending",
        # Charts
        "Chart StockByWarehouse - Bar",
        "Chart CategoryBreakdown - Pie",
        # Cross-tab
        "CrossTab Inventory Matrix",
        # Running totals
        "Running Total CumulativeStock on {Inventory.StockQty}",
        # Conditional formatting
        "Condition Formula Rule: ReorderAlert",
        "Condition Formula Rule: HighValueHighlight",
        # Subreports
        "Subreport SupplierInfo",
        # SQL
        ("SELECT I.ProductID, I.StockQty, I.ReorderLevel, I.UnitCost, "
         "W.WarehouseName, P.ProductName, P.Category "
         "FROM Inventory I "
         "JOIN Warehouses W ON I.WarehouseID = W.ID "
         "JOIN Products P ON I.ProductID = P.ID"),
    ]
    return _create_rpt("Inventory_Report.rpt", _build_rpt_binary(segments))


# ══════════════════════════════════════════════════════════════════════════════
# 3. Universe samples (.unx) -- ZIP with business layer + data foundation XML
# ══════════════════════════════════════════════════════════════════════════════

def _create_unx(filename, bl_xml, df_xml, conn_xml):
    """Create a .unx file (ZIP with XML entries)."""
    path = os.path.join(EXAMPLES_DIR, filename)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("businesslayer.blx", bl_xml)
        zf.writestr("datafoundation.dfx", df_xml)
        zf.writestr("connection.xml", conn_xml)
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    print(f"  Created {filename} ({os.path.getsize(path):,} bytes)")
    return path


def _build_bl_xml(name, dimensions, measures, details=None, lovs=None,
                  filters=None):
    """Build business layer XML using ElementTree."""
    root = ET.Element("BusinessLayer", name=name)
    for d in dimensions:
        ET.SubElement(root, "Dimension", **{k: str(v) for k, v in d.items()})
    for m in measures:
        ET.SubElement(root, "Measure", **{k: str(v) for k, v in m.items()})
    for det in (details or []):
        ET.SubElement(root, "Detail", **{k: str(v) for k, v in det.items()})
    for lov in (lovs or []):
        el = ET.SubElement(root, "ListOfValues",
                           name=lov["name"], dimension=lov["dimension"])
        if "sql" in lov:
            el.set("sql", lov["sql"])
    for f in (filters or []):
        ET.SubElement(root, "Filter", **{k: str(v) for k, v in f.items()})
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode")


def _build_df_xml(name, connection, tables, joins, contexts=None,
                  derived_tables=None):
    """Build data foundation XML using ElementTree."""
    root = ET.Element("DataFoundation", name=name)
    ET.SubElement(root, "Connection", **{k: str(v) for k, v in connection.items()})
    for t in tables:
        ET.SubElement(root, "Table", **{k: str(v) for k, v in t.items()})
    for dt in (derived_tables or []):
        ET.SubElement(root, "DerivedTable", **{k: str(v) for k, v in dt.items()})
    for j in joins:
        ET.SubElement(root, "Join", **{k: str(v) for k, v in j.items()})
    for ctx in (contexts or []):
        c_el = ET.SubElement(root, "Context", name=ctx["name"])
        for ref in ctx.get("joins", []):
            ET.SubElement(c_el, "JoinRef", ref=ref)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode")


def _build_conn_xml(connections):
    """Build connections XML."""
    root = ET.Element("Connections")
    for c in connections:
        ET.SubElement(root, "Connection", **{k: str(v) for k, v in c.items()})
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(
        root, encoding="unicode")


def generate_universe_efashion():
    """eFashion Universe -- full data model with joins, contexts, derived tables."""
    bl = _build_bl_xml(
        "eFashion",
        dimensions=[
            {"name": "Year", "path": "Time/Year", "table": "DIM_TIME",
             "select": "DIM_TIME.FISCAL_YEAR", "qualification": "dimension"},
            {"name": "Quarter", "path": "Time/Quarter", "table": "DIM_TIME",
             "select": "DIM_TIME.FISCAL_QUARTER", "qualification": "dimension"},
            {"name": "Month", "path": "Time/Month", "table": "DIM_TIME",
             "select": "DIM_TIME.MONTH_NAME", "qualification": "dimension"},
            {"name": "Product Line", "path": "Product/Line", "table": "DIM_PRODUCT",
             "select": "DIM_PRODUCT.PRODUCT_LINE", "qualification": "dimension"},
            {"name": "Category", "path": "Product/Category", "table": "DIM_PRODUCT",
             "select": "DIM_PRODUCT.CATEGORY", "qualification": "dimension"},
            {"name": "Color", "path": "Product/Color", "table": "DIM_PRODUCT",
             "select": "DIM_PRODUCT.COLOR", "qualification": "dimension"},
            {"name": "Store Region", "path": "Store/Region", "table": "DIM_STORE",
             "select": "DIM_STORE.REGION", "qualification": "dimension"},
            {"name": "Store Country", "path": "Store/Country", "table": "DIM_STORE",
             "select": "DIM_STORE.COUNTRY", "qualification": "dimension"},
            {"name": "Store City", "path": "Store/City", "table": "DIM_STORE",
             "select": "DIM_STORE.CITY", "qualification": "dimension"},
        ],
        measures=[
            {"name": "Revenue", "path": "Measures/Revenue", "table": "FACT_SALES",
             "select": "SUM(FACT_SALES.REVENUE)", "qualification": "measure"},
            {"name": "Quantity Sold", "path": "Measures/Quantity", "table": "FACT_SALES",
             "select": "SUM(FACT_SALES.QUANTITY)", "qualification": "measure"},
            {"name": "Margin", "path": "Measures/Margin", "table": "FACT_SALES",
             "select": "SUM(FACT_SALES.MARGIN)", "qualification": "measure"},
            {"name": "Discount", "path": "Measures/Discount", "table": "FACT_SALES",
             "select": "SUM(FACT_SALES.DISCOUNT_AMOUNT)", "qualification": "measure"},
            {"name": "Sales Count", "path": "Measures/Count", "table": "FACT_SALES",
             "select": "COUNT(FACT_SALES.SALE_ID)", "qualification": "measure"},
            {"name": "Agg Revenue", "path": "Measures/AggRevenue",
             "table": "AGG_SALES_MONTHLY",
             "select": "@Aggregate_Aware(SUM(FACT_SALES.REVENUE), SUM(AGG_SALES_MONTHLY.REVENUE), SUM(AGG_SALES_YEARLY.REVENUE))",
             "qualification": "measure"},
        ],
        details=[
            {"name": "Product SKU", "path": "Product/SKU", "table": "DIM_PRODUCT",
             "select": "DIM_PRODUCT.SKU", "qualification": "detail"},
        ],
        lovs=[
            {"name": "YearLOV", "dimension": "Year",
             "sql": "SELECT DISTINCT FISCAL_YEAR FROM DIM_TIME ORDER BY 1"},
            {"name": "RegionLOV", "dimension": "Store Region",
             "sql": "SELECT DISTINCT REGION FROM DIM_STORE ORDER BY 1"},
        ],
        filters=[
            {"name": "Current Year", "expression": "DIM_TIME.FISCAL_YEAR = 2024",
             "level": "universe"},
            {"name": "Active Products", "expression": "DIM_PRODUCT.IS_ACTIVE = 1",
             "level": "universe"},
        ],
    )

    df = _build_df_xml(
        "eFashion Data Foundation",
        connection={"name": "eFashion DW", "type": "sqlserver",
                    "server": "dw-server.corp.com", "database": "eFashion_DW"},
        tables=[
            {"name": "FACT_SALES", "schema": "dbo", "type": "table"},
            {"name": "DIM_TIME", "schema": "dbo", "type": "table"},
            {"name": "DIM_PRODUCT", "schema": "dbo", "type": "table"},
            {"name": "DIM_STORE", "schema": "dbo", "type": "table"},
            {"name": "DIM_CUSTOMER", "schema": "dbo", "type": "table"},
            {"name": "AGG_SALES_MONTHLY", "schema": "dbo", "type": "table"},
            {"name": "AGG_SALES_YEARLY", "schema": "dbo", "type": "table"},
        ],
        joins=[
            {"leftTable": "FACT_SALES", "rightTable": "DIM_TIME",
             "leftColumn": "TIME_ID", "rightColumn": "ID",
             "type": "inner", "cardinality": "many-to-one"},
            {"leftTable": "FACT_SALES", "rightTable": "DIM_PRODUCT",
             "leftColumn": "PRODUCT_ID", "rightColumn": "ID",
             "type": "inner", "cardinality": "many-to-one"},
            {"leftTable": "FACT_SALES", "rightTable": "DIM_STORE",
             "leftColumn": "STORE_ID", "rightColumn": "ID",
             "type": "inner", "cardinality": "many-to-one"},
            {"leftTable": "FACT_SALES", "rightTable": "DIM_CUSTOMER",
             "leftColumn": "CUSTOMER_ID", "rightColumn": "ID",
             "type": "left", "cardinality": "many-to-one"},
            {"leftTable": "AGG_SALES_MONTHLY", "rightTable": "DIM_TIME",
             "leftColumn": "MONTH_ID", "rightColumn": "ID",
             "type": "inner", "cardinality": "many-to-one"},
            {"leftTable": "AGG_SALES_YEARLY", "rightTable": "DIM_TIME",
             "leftColumn": "YEAR_ID", "rightColumn": "ID",
             "type": "inner", "cardinality": "many-to-one"},
        ],
        contexts=[
            {"name": "Sales", "joins": [
                "FACT_SALES_DIM_TIME", "FACT_SALES_DIM_PRODUCT",
                "FACT_SALES_DIM_STORE"]},
            {"name": "Monthly Aggregate", "joins": ["AGG_SALES_MONTHLY_DIM_TIME"]},
        ],
        derived_tables=[
            {"name": "SALES_SUMMARY", "type": "derived",
             "sql": ("SELECT T.FISCAL_YEAR, P.PRODUCT_LINE, S.REGION, "
                     "SUM(F.REVENUE) AS TOTAL_REV "
                     "FROM FACT_SALES F "
                     "JOIN DIM_TIME T ON F.TIME_ID=T.ID "
                     "JOIN DIM_PRODUCT P ON F.PRODUCT_ID=P.ID "
                     "JOIN DIM_STORE S ON F.STORE_ID=S.ID "
                     "GROUP BY T.FISCAL_YEAR, P.PRODUCT_LINE, S.REGION")},
        ],
    )

    conn = _build_conn_xml([
        {"name": "eFashion DW", "type": "sqlserver",
         "server": "dw-server.corp.com", "database": "eFashion_DW",
         "connectionString": "Server=dw-server.corp.com;Database=eFashion_DW;Trusted_Connection=Yes;"},
    ])

    return _create_unx("eFashion_Universe.unx", bl, df, conn)


def generate_universe_hr():
    """HR Universe -- smaller, with SAP HANA connection."""
    bl = _build_bl_xml(
        "HR_Universe",
        dimensions=[
            {"name": "Department", "path": "Org/Department", "select": "DEPT.NAME"},
            {"name": "Job Title", "path": "Org/Title", "select": "EMP.JOB_TITLE"},
            {"name": "Employee Name", "path": "Employee/Name", "select": "EMP.FULL_NAME"},
            {"name": "Hire Date", "path": "Employee/HireDate", "select": "EMP.HIRE_DATE",
             "qualification": "dimension"},
        ],
        measures=[
            {"name": "Salary", "path": "Compensation/Salary",
             "select": "SUM(COMP.SALARY)", "qualification": "measure"},
            {"name": "Headcount", "path": "Metrics/Headcount",
             "select": "COUNT(EMP.ID)", "qualification": "measure"},
            {"name": "Avg Tenure", "path": "Metrics/AvgTenure",
             "select": "AVG(DATEDIFF(DAY, EMP.HIRE_DATE, GETDATE()))/365",
             "qualification": "measure"},
        ],
    )

    df = _build_df_xml(
        "HR Data Foundation",
        connection={"name": "HR HANA", "type": "saphana",
                    "server": "hana-hr.corp.com:30015", "database": "HR_PROD"},
        tables=[
            {"name": "EMP", "schema": "HR", "type": "table"},
            {"name": "DEPT", "schema": "HR", "type": "table"},
            {"name": "COMP", "schema": "HR", "type": "table"},
        ],
        joins=[
            {"leftTable": "EMP", "rightTable": "DEPT",
             "leftColumn": "DEPT_ID", "rightColumn": "ID",
             "type": "inner", "cardinality": "many-to-one"},
            {"leftTable": "EMP", "rightTable": "COMP",
             "leftColumn": "ID", "rightColumn": "EMP_ID",
             "type": "inner", "cardinality": "one-to-many"},
        ],
    )

    conn = _build_conn_xml([
        {"name": "HR HANA", "type": "saphana",
         "server": "hana-hr.corp.com:30015", "database": "HR_PROD"},
    ])

    return _create_unx("HR_Universe.unx", bl, df, conn)


# ══════════════════════════════════════════════════════════════════════════════
# 4. Legacy Universe (.unv) -- binary with embedded XML
# ══════════════════════════════════════════════════════════════════════════════

def generate_legacy_universe():
    """Legacy .unv file -- Designer format with embedded XML."""
    bl_root = ET.Element("BusinessLayer", name="Legacy_Sales")
    ET.SubElement(bl_root, "Dimension", name="Region", path="Geography/Region")
    ET.SubElement(bl_root, "Dimension", name="Product", path="Product/Name")
    ET.SubElement(bl_root, "Dimension", name="Year", path="Time/Year")
    ET.SubElement(bl_root, "Measure", name="Sales Amount", path="Measures/Sales",
                  select="SUM(SALES.AMOUNT)", qualification="measure")
    ET.SubElement(bl_root, "Measure", name="Cost", path="Measures/Cost",
                  select="SUM(SALES.COST)", qualification="measure")

    xml_block = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 + ET.tostring(bl_root, encoding="unicode"))

    buf = bytearray()
    buf.extend(b"\x00" * 128)
    buf.extend(b"SAP BusinessObjects Designer Universe\x00")
    buf.extend(b"\x00" * 64)
    buf.extend(xml_block.encode("utf-8"))
    buf.extend(b"\x00" * 128)

    path = os.path.join(EXAMPLES_DIR, "Legacy_Sales.unv")
    with open(path, "wb") as f:
        f.write(bytes(buf))
    print(f"  Created Legacy_Sales.unv ({os.path.getsize(path):,} bytes)")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# 5. Lumira samples (.lumx) -- ZIP with JSON metadata
# ══════════════════════════════════════════════════════════════════════════════

def generate_lumira_discovery():
    """Lumira Discovery -- data exploration document."""
    metadata = {
        "name": "Sales Exploration",
        "type": "discovery",
        "datasources": [
            {"name": "SalesDB", "type": "hana",
             "connection": "hana://analytics-server:30015/SALES_DB"},
        ],
        "datasets": [
            {"name": "Sales", "source": "SalesDB"},
        ],
        "dimensions": [
            {"name": "Year", "type": "date", "table": "Sales"},
            {"name": "Quarter", "type": "date", "table": "Sales"},
            {"name": "Region", "type": "string", "table": "Sales"},
            {"name": "Product", "type": "string", "table": "Sales"},
            {"name": "Customer Segment", "type": "string", "table": "Sales"},
        ],
        "measures": [
            {"name": "Revenue", "type": "decimal", "table": "Sales"},
            {"name": "Profit", "type": "decimal", "table": "Sales"},
            {"name": "Quantity", "type": "integer", "table": "Sales"},
            {"name": "Discount", "type": "decimal", "table": "Sales"},
        ],
        "columns": [
            {"name": "Order ID", "type": "string", "table": "Sales"},
        ],
        "visualizations": [
            {"name": "Revenue by Region", "type": "bar", "title": "Regional Revenue"},
            {"name": "Profit Trend", "type": "line", "title": "Profit Over Time"},
            {"name": "Product Treemap", "type": "treemap", "title": "Product Revenue"},
            {"name": "KPI Card", "type": "kpi", "title": "Total Revenue"},
        ],
        "pages": [
            {"name": "Overview", "title": "Sales Overview"},
            {"name": "Detail", "title": "Detailed Analysis"},
        ],
        "calculatedFields": [
            {"name": "Profit Margin", "formula": "(Revenue - Cost) / Revenue * 100"},
            {"name": "Revenue Growth", "formula": "CALCULATE(Revenue) - LAG(Revenue)"},
        ],
        "filters": [
            {"name": "Year Filter", "dimension": "Year", "values": ["2023", "2024"]},
            {"name": "Region Filter", "dimension": "Region",
             "values": ["EMEA", "North America", "APAC"]},
        ],
    }

    path = os.path.join(EXAMPLES_DIR, "Sales_Exploration.lumx")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", json.dumps(metadata, indent=2))
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    print(f"  Created Sales_Exploration.lumx ({os.path.getsize(path):,} bytes)")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# 6. BIAR archive (.biar) -- ZIP with manifest + embedded artifacts
# ══════════════════════════════════════════════════════════════════════════════

def generate_biar_archive():
    """BIAR archive -- batch export containing multiple BO artifacts."""
    # Build manifest XML
    manifest_root = ET.Element("Manifest")
    ET.SubElement(manifest_root, "Item",
                  path="Reports/Sales_Dashboard.wid", type="webi",
                  folder="Reports", cuid="FKx100001",
                  description="Enterprise Sales Dashboard")
    ET.SubElement(manifest_root, "Item",
                  path="Reports/Inventory_Check.rpt", type="crystal",
                  folder="Reports", cuid="FKx100002",
                  description="Inventory Status Report")
    ET.SubElement(manifest_root, "Item",
                  path="Universes/eFashion.unx", type="universe",
                  folder="Universes", cuid="FKx100003",
                  description="eFashion Data Universe")
    manifest = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                + ET.tostring(manifest_root, encoding="unicode"))

    # Build inner .wid
    inner_wid_xml = _build_webi_xml(
        name="BIAR Sales Dashboard",
        queries=[{
            "name": "SalesDP", "type": "universe", "universe": "eFashion",
            "objects": [
                {"name": "Year", "qualification": "dimension"},
                {"name": "Region", "qualification": "dimension"},
                {"name": "Revenue", "qualification": "measure"},
            ],
        }],
        variables=[
            {"name": "Rev Growth",
             "formula": "=([Revenue] - Previous([Revenue])) / Previous([Revenue]) * 100",
             "qualification": "measure", "data_type": "number"},
        ],
        prompts=[{"name": "Year", "type": "number", "default_values": ["2024"]}],
        charts=[{"name": "Revenue Chart", "type": "bar",
                 "dimensions": ["Year"], "measures": ["Revenue"]}],
        filters=[],
        tables=[{"name": "FACT_SALES"}, {"name": "DIM_TIME"}],
        datasource={"name": "eFashion", "type": "universe", "universe": "eFashion"},
    )

    inner_wid_buf = io.BytesIO()
    with zipfile.ZipFile(inner_wid_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("document.xml", inner_wid_xml)
    inner_wid_bytes = inner_wid_buf.getvalue()

    # Build inner .rpt
    inner_rpt = _build_rpt_binary([
        "{Sales.Region}", "{Sales.Revenue}", "{Sales.Year}",
        "{@TotalRevenue}",
        "{?Year}",
        "Group #1 on {Sales.Region}",
        "Sort on {Sales.Revenue} Descending",
        "Chart RegionChart - Bar",
    ])

    # Build inner .unx
    inner_bl = _build_bl_xml(
        "BIAR_eFashion",
        dimensions=[
            {"name": "Year", "path": "Time/Year"},
            {"name": "Region", "path": "Store/Region"},
        ],
        measures=[
            {"name": "Revenue", "path": "Measures/Revenue",
             "select": "SUM(SALES.REVENUE)", "qualification": "measure"},
        ],
    )
    inner_df = _build_df_xml(
        "BIAR Data Foundation",
        connection={"name": "DW", "type": "sqlserver",
                    "server": "dw.corp.com", "database": "DW"},
        tables=[
            {"name": "SALES", "schema": "dbo", "type": "table"},
            {"name": "TIME", "schema": "dbo", "type": "table"},
        ],
        joins=[
            {"leftTable": "SALES", "rightTable": "TIME",
             "leftColumn": "TIME_ID", "rightColumn": "ID",
             "type": "inner", "cardinality": "many-to-one"},
        ],
    )
    inner_conn = _build_conn_xml([
        {"name": "DW", "type": "sqlserver",
         "server": "dw.corp.com", "database": "DW"},
    ])

    inner_unx_buf = io.BytesIO()
    with zipfile.ZipFile(inner_unx_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("businesslayer.blx", inner_bl)
        zf.writestr("datafoundation.dfx", inner_df)
        zf.writestr("connection.xml", inner_conn)
    inner_unx_bytes = inner_unx_buf.getvalue()

    # Build BIAR archive
    path = os.path.join(EXAMPLES_DIR, "Enterprise_Export.biar")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.xml", manifest)
        zf.writestr("Reports/Sales_Dashboard.wid", inner_wid_bytes)
        zf.writestr("Reports/Inventory_Check.rpt", inner_rpt)
        zf.writestr("Universes/eFashion.unx", inner_unx_bytes)

    print(f"  Created Enterprise_Export.biar ({os.path.getsize(path):,} bytes)")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# 7. Multi-tenant config
# ══════════════════════════════════════════════════════════════════════════════

def generate_multi_tenant_config():
    """Sample multi-tenant config JSON."""
    config = {
        "_comment": "Multi-tenant deployment configuration for BOToPowerBI",
        "tenants": [
            {
                "name": "EMEA",
                "workspace_id": "00000000-0000-0000-0000-000000000001",
                "overrides": {
                    "${TENANT_SERVER}": "sql-emea.database.windows.net",
                    "${TENANT_DATABASE}": "Sales_EMEA",
                    "${TENANT_REGION}": "EMEA",
                },
            },
            {
                "name": "APAC",
                "workspace_id": "00000000-0000-0000-0000-000000000002",
                "overrides": {
                    "${TENANT_SERVER}": "sql-apac.database.windows.net",
                    "${TENANT_DATABASE}": "Sales_APAC",
                    "${TENANT_REGION}": "APAC",
                },
            },
            {
                "name": "Americas",
                "workspace_id": "00000000-0000-0000-0000-000000000003",
                "overrides": {
                    "${TENANT_SERVER}": "sql-americas.database.windows.net",
                    "${TENANT_DATABASE}": "Sales_Americas",
                    "${TENANT_REGION}": "Americas",
                },
            },
        ],
    }

    path = os.path.join(EXAMPLES_DIR, "multi_tenant_config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print(f"  Created multi_tenant_config.json ({os.path.getsize(path):,} bytes)")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Generating SAP BusinessObjects sample files")
    print("=" * 60)
    print()

    os.makedirs(EXAMPLES_DIR, exist_ok=True)

    print("[WebI Documents (.wid)]")
    generate_webi_sales()
    generate_webi_hr()
    generate_webi_finance()
    print()

    print("[Crystal Reports (.rpt)]")
    generate_crystal_invoice()
    generate_crystal_inventory()
    print()

    print("[Universes (.unx)]")
    generate_universe_efashion()
    generate_universe_hr()
    print()

    print("[Legacy Universe (.unv)]")
    generate_legacy_universe()
    print()

    print("[Lumira Discovery (.lumx)]")
    generate_lumira_discovery()
    print()

    print("[BIAR Archive (.biar)]")
    generate_biar_archive()
    print()

    print("[Configuration]")
    generate_multi_tenant_config()
    print()

    print("=" * 60)
    print("Done! All samples written to:", EXAMPLES_DIR)
    print()
    print("Quick test commands:")
    print("  python migrate.py examples/Enterprise_Sales.wid")
    print("  python migrate.py examples/Invoice_Report.rpt")
    print("  python migrate.py examples/eFashion_Universe.unx")
    print("  python migrate.py examples/Sales_Exploration.lumx")
    print("  python migrate.py --biar examples/Enterprise_Export.biar")
    print("  python migrate.py examples/Enterprise_Sales.wid --assess")
    print("  python migrate.py examples/Enterprise_Sales.wid --output-format fabric")
    print("  python migrate.py examples/Enterprise_Sales.wid --dry-run")


if __name__ == "__main__":
    main()
