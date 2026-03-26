"""Tests for the DAX converter (BO formula → DAX)."""

import unittest

from bo_export.dax_converter import convert_bo_formula_to_dax, get_supported_functions


class TestAggregationFunctions(unittest.TestCase):
    """Test aggregation function conversion."""

    def test_sum(self):
        result = convert_bo_formula_to_dax("=Sum([Revenue])", table_name="Sales")
        self.assertIn("SUM", result)

    def test_count(self):
        result = convert_bo_formula_to_dax("=Count([OrderID])", table_name="Sales")
        self.assertIn("COUNT", result)

    def test_average(self):
        result = convert_bo_formula_to_dax("=Average([Price])", table_name="Sales")
        self.assertIn("AVERAGE", result)

    def test_min(self):
        result = convert_bo_formula_to_dax("=Min([Price])", table_name="Sales")
        self.assertIn("MIN", result)

    def test_max(self):
        result = convert_bo_formula_to_dax("=Max([Price])", table_name="Sales")
        self.assertIn("MAX", result)

    def test_distinctcount(self):
        result = convert_bo_formula_to_dax("=DistinctCount([Customer])", table_name="Sales")
        self.assertIn("DISTINCTCOUNT", result)


class TestTextFunctions(unittest.TestCase):
    """Test text function conversion."""

    def test_substr(self):
        result = convert_bo_formula_to_dax("=Substr([Name],1,3)", table_name="Customers")
        self.assertIn("MID", result)

    def test_length(self):
        result = convert_bo_formula_to_dax("=Length([Name])", table_name="Customers")
        self.assertIn("LEN", result)

    def test_upper(self):
        result = convert_bo_formula_to_dax("=Upper([Name])", table_name="Customers")
        self.assertIn("UPPER", result)

    def test_lower(self):
        result = convert_bo_formula_to_dax("=Lower([Name])", table_name="Customers")
        self.assertIn("LOWER", result)

    def test_trim(self):
        result = convert_bo_formula_to_dax("=Trim([Name])", table_name="Customers")
        self.assertIn("TRIM", result)

    def test_pos(self):
        result = convert_bo_formula_to_dax("=Pos([Name],\"A\")", table_name="Customers")
        self.assertIn("SEARCH", result)

    def test_replace(self):
        result = convert_bo_formula_to_dax("=Replace([Name],\"old\",\"new\")", table_name="Customers")
        self.assertIn("SUBSTITUTE", result)


class TestDateFunctions(unittest.TestCase):
    """Test date function conversion."""

    def test_year(self):
        result = convert_bo_formula_to_dax("=Year([OrderDate])", table_name="Orders")
        self.assertIn("YEAR", result)

    def test_month(self):
        result = convert_bo_formula_to_dax("=Month([OrderDate])", table_name="Orders")
        self.assertIn("MONTH", result)

    def test_day(self):
        result = convert_bo_formula_to_dax("=Day([OrderDate])", table_name="Orders")
        self.assertIn("DAY", result)

    def test_daysbetween(self):
        result = convert_bo_formula_to_dax("=DaysBetween([Start],[End])", table_name="Orders")
        self.assertIn("DATEDIFF", result)

    def test_currentdate(self):
        result = convert_bo_formula_to_dax("=CurrentDate()")
        self.assertIn("TODAY", result)

    def test_now(self):
        result = convert_bo_formula_to_dax("=Now()")
        self.assertIn("NOW", result)


class TestLogicFunctions(unittest.TestCase):
    """Test logic/conditional conversion."""

    def test_if_then_else(self):
        result = convert_bo_formula_to_dax(
            "=If [Revenue]>1000 Then \"High\" Else \"Low\"",
            table_name="Sales",
        )
        self.assertIn("IF", result)

    def test_if_elseif_to_switch(self):
        result = convert_bo_formula_to_dax(
            '=If [Score]>=90 Then "A" ElseIf [Score]>=80 Then "B" Else "C"',
            table_name="T",
        )
        self.assertIn("SWITCH", result)
        self.assertIn("TRUE()", result)

    def test_and_operator(self):
        result = convert_bo_formula_to_dax("=[X]>0 And [Y]>0", table_name="T")
        self.assertIn("&&", result)

    def test_or_operator(self):
        result = convert_bo_formula_to_dax("=[X]>0 Or [Y]>0", table_name="T")
        self.assertIn("||", result)


class TestNullFunctions(unittest.TestCase):
    """Test null handling function conversion."""

    def test_isnull(self):
        result = convert_bo_formula_to_dax("=IsNull([Revenue])", table_name="Sales")
        self.assertIn("ISBLANK", result)

    def test_ifnull(self):
        result = convert_bo_formula_to_dax("=IfNull([Revenue],0)", table_name="Sales")
        self.assertIn("ISBLANK", result)
        self.assertIn("IF", result)


class TestMathFunctions(unittest.TestCase):
    """Test math function conversion."""

    def test_abs(self):
        result = convert_bo_formula_to_dax("=Abs([Value])", table_name="T")
        self.assertIn("ABS", result)

    def test_round(self):
        result = convert_bo_formula_to_dax("=Round([Value],2)", table_name="T")
        self.assertIn("ROUND", result)

    def test_truncate(self):
        result = convert_bo_formula_to_dax("=Truncate([Value],2)", table_name="T")
        self.assertIn("TRUNC", result)

    def test_power(self):
        result = convert_bo_formula_to_dax("=Power([Value],2)", table_name="T")
        self.assertIn("POWER", result)

    def test_sqrt(self):
        result = convert_bo_formula_to_dax("=Sqrt([Value])", table_name="T")
        self.assertIn("SQRT", result)


class TestCrystalSyntax(unittest.TestCase):
    """Test Crystal Reports formula syntax conversion."""

    def test_crystal_field_ref(self):
        result = convert_bo_formula_to_dax("{Orders.Revenue}")
        self.assertIn("'Orders'[Revenue]", result)

    def test_crystal_formula_ref(self):
        result = convert_bo_formula_to_dax("{@TotalRevenue}")
        self.assertIn("[TotalRevenue]", result)

    def test_crystal_param_ref(self):
        result = convert_bo_formula_to_dax("{?Country}")
        self.assertIn("[Country]", result)

    def test_crystal_multiword_field(self):
        result = convert_bo_formula_to_dax("{Customer Name.First Name}")
        self.assertIn("'Customer Name'[First Name]", result)

    def test_while_printing_stripped(self):
        result = convert_bo_formula_to_dax("WhilePrintingRecords; {Orders.Total}")
        self.assertNotIn("WhilePrintingRecords", result)
        self.assertIn("'Orders'[Total]", result)

    def test_while_reading_stripped(self):
        result = convert_bo_formula_to_dax("WhileReadingRecords; Sum({Orders.Amount})")
        self.assertNotIn("WhileReadingRecords", result)
        self.assertIn("SUM", result)

    def test_formula_cross_ref_resolved(self):
        fmap = {"TotalRevenue": "SUM('Sales'[Revenue])"}
        result = convert_bo_formula_to_dax("{@TotalRevenue} * 1.1", formula_map=fmap)
        self.assertIn("SUM('Sales'[Revenue])", result)
        self.assertNotIn("@", result)

    def test_crystal_cstr(self):
        result = convert_bo_formula_to_dax("CStr({Orders.ID})")
        self.assertIn("FORMAT", result)

    def test_crystal_cdbl(self):
        result = convert_bo_formula_to_dax("CDbl({Orders.Quantity})")
        self.assertIn("VALUE", result)

    def test_crystal_dateserial(self):
        result = convert_bo_formula_to_dax("DateSerial(2024, 1, 15)")
        self.assertIn("DATE(", result)

    def test_crystal_record_number(self):
        result = convert_bo_formula_to_dax("RecordNumber")
        self.assertIn("RecordNumber", result)  # Annotation preserved


class TestSecurityFunctions(unittest.TestCase):
    """Test security function conversion."""

    def test_currentuser(self):
        result = convert_bo_formula_to_dax("=CurrentUser()")
        self.assertIn("USERPRINCIPALNAME", result)


class TestRunningFunctions(unittest.TestCase):
    """Test running calculation conversion."""

    def test_running_sum(self):
        result = convert_bo_formula_to_dax("=RunningSum([Revenue])", table_name="Sales")
        self.assertIn("CALCULATE", result)
        self.assertIn("SUM", result)
        self.assertIn("ALLSELECTED", result)

    def test_running_count(self):
        result = convert_bo_formula_to_dax("=RunningCount([OrderID])", table_name="Orders")
        self.assertIn("CALCULATE", result)
        self.assertIn("COUNT", result)

    def test_running_average(self):
        result = convert_bo_formula_to_dax("=RunningAverage([Price])", table_name="Sales")
        self.assertIn("CALCULATE", result)
        self.assertIn("AVERAGE", result)

    def test_running_max(self):
        result = convert_bo_formula_to_dax("=RunningMax([Score])", table_name="T")
        self.assertIn("MAX", result)
        self.assertIn("ALLSELECTED", result)

    def test_running_min(self):
        result = convert_bo_formula_to_dax("=RunningMin([Score])", table_name="T")
        self.assertIn("MIN", result)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and special scenarios."""

    def test_empty_formula(self):
        result = convert_bo_formula_to_dax("")
        self.assertEqual(result, "")

    def test_strip_leading_equals(self):
        result = convert_bo_formula_to_dax("=Sum([X])", table_name="T")
        self.assertNotIn("=SUM", result)
        self.assertIn("SUM", result)

    def test_supported_functions_list(self):
        functions = get_supported_functions()
        self.assertGreater(len(functions), 50)
        self.assertIn("sum", functions)
        self.assertIn("isnull", functions)
        self.assertIn("currentuser", functions)


class TestContextOperators(unittest.TestCase):
    """Test BO context operator conversion (In, ForEach, ForAll)."""

    def test_in_single_dimension(self):
        result = convert_bo_formula_to_dax(
            "=Sum([Revenue]) In ([Country])", table_name="Sales")
        self.assertIn("CALCULATE", result)
        self.assertIn("ALLEXCEPT", result)
        self.assertIn("'Sales'[Country]", result)
        self.assertIn("SUM", result)

    def test_in_multiple_dimensions(self):
        result = convert_bo_formula_to_dax(
            "=Sum([Revenue]) In ([Country]; [Year])", table_name="Sales")
        self.assertIn("ALLEXCEPT", result)
        self.assertIn("'Sales'[Country]", result)
        self.assertIn("'Sales'[Year]", result)

    def test_foreach_sumx(self):
        result = convert_bo_formula_to_dax(
            "=Sum([Revenue]) ForEach ([Product])", table_name="Sales")
        self.assertIn("SUMX", result)
        self.assertIn("VALUES('Sales'[Product])", result)
        self.assertIn("SUM", result)

    def test_foreach_averagex(self):
        result = convert_bo_formula_to_dax(
            "=Average([Price]) ForEach ([Category])", table_name="Sales")
        self.assertIn("AVERAGEX", result)
        self.assertIn("VALUES('Sales'[Category])", result)

    def test_foreach_countx(self):
        result = convert_bo_formula_to_dax(
            "=Count([OrderID]) ForEach ([Region])", table_name="Sales")
        self.assertIn("COUNTX", result)
        self.assertIn("VALUES('Sales'[Region])", result)

    def test_forall(self):
        result = convert_bo_formula_to_dax(
            "=Sum([Revenue]) ForAll;", table_name="Sales")
        self.assertIn("CALCULATE", result)
        self.assertIn("ALL('Sales')", result)
        self.assertIn("SUM", result)


if __name__ == "__main__":
    unittest.main()
