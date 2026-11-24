import sys
import types
import unittest
from unittest.mock import patch

from powerbi_import.plugins import (
    PluginBase,
    PluginManager,
    get_plugin_manager,
    reset_plugin_manager,
)


class TransformPlugin:
    name = "transform"

    def transform_dax(self, value):
        return value.replace("OLD", "NEW")

    def transform_m_query(self, value):
        return value + " | transformed"

    def custom_visual_mapping(self, chart_type):
        return "waterfall" if chart_type == "cascade" else None


class HookPlugin:
    name = "hook"

    def post_extraction(self, extracted_data):
        extracted_data["added"] = True
        return extracted_data

    def pre_generation(self, converted_objects):
        return None

    def on_merge_complete(self, assessment, merged, model_name):
        pass


class BrokenPlugin:
    name = "broken"

    def pre_extraction(self, **kwargs):
        raise RuntimeError("synthetic failure")


class PluginsTests(unittest.TestCase):
    def test_plugin_base_defaults(self):
        plugin = PluginBase()
        self.assertIsNone(plugin.post_extraction({}))
        self.assertIsNone(plugin.pre_generation({}))
        self.assertEqual(plugin.transform_dax("SUM([X])"), "SUM([X])")
        self.assertEqual(plugin.transform_m_query("let x=1"), "let x=1")
        self.assertIsNone(plugin.custom_visual_mapping("bar"))
        self.assertIsNone(plugin.on_merge_conflict("measure", "Revenue", {}))
        self.assertEqual(plugin.transform_merged_dax("Revenue", "SUM(X)", "A"), "SUM(X)")

    def test_register_transform_chain_and_properties(self):
        manager = PluginManager()
        self.assertFalse(manager.has_plugins())
        manager.register(TransformPlugin())
        self.assertTrue(manager.has_plugins())
        self.assertEqual(len(manager.plugins), 1)
        self.assertEqual(manager.apply_transform("transform_dax", "OLD_VALUE"), "NEW_VALUE")
        self.assertEqual(manager.apply_transform("transform_m_query", "source"), "source | transformed")

    def test_apply_transform_skips_non_callable_none_and_errors(self):
        class ReturnsNone:
            def transform_dax(self, value):
                return None

        class Broken:
            def transform_dax(self, value):
                raise ValueError("bad")

        manager = PluginManager()
        manager.register(ReturnsNone())
        manager.register(Broken())
        self.assertEqual(manager.apply_transform("transform_dax", "unchanged"), "unchanged")

    def test_call_hook_last_non_none_and_missing_hook(self):
        manager = PluginManager()
        manager.register(HookPlugin())
        data = {}
        result = manager.call_hook("post_extraction", extracted_data=data)
        self.assertIs(result, data)
        self.assertTrue(result["added"])
        self.assertIsNone(manager.call_hook("pre_generation", converted_objects={}))
        self.assertIsNone(manager.call_hook("not_a_real_hook", value=1))

    def test_hook_error_is_logged_and_other_values_continue(self):
        manager = PluginManager()
        manager.register(BrokenPlugin())
        manager.register(TransformPlugin())
        with self.assertLogs("bo_to_powerbi.plugins", level="ERROR"):
            result = manager.call_hook("pre_extraction", bo_file="Sales.wid")
        self.assertIsNone(result)

    def test_load_from_config_class_module_plugin_and_missing_plugin(self):
        module = types.ModuleType("synthetic_plugin")
        class Plugin(PluginBase):
            name = "synthetic"
        module.Plugin = Plugin

        manager = PluginManager()
        with patch("powerbi_import.plugins.importlib.import_module", return_value=module):
            manager.load_from_config(["synthetic_plugin", "synthetic_plugin.Plugin"])
        self.assertEqual(len(manager.plugins), 2)

        with patch("powerbi_import.plugins.importlib.import_module", return_value=types.ModuleType("empty")):
            manager.load_from_config(["empty_module"])
        self.assertEqual(len(manager.plugins), 2)

    def test_load_from_config_invalid_and_exception_paths(self):
        manager = PluginManager()
        manager.load_from_config(None)
        manager.load_from_config([])
        manager.load_from_config(["synthetic.no_such_plugin"])

        with patch("powerbi_import.plugins.importlib.import_module", side_effect=ImportError("missing")):
            with self.assertLogs("bo_to_powerbi.plugins", level="ERROR"):
                manager.load_from_config(["Synthetic.Plugin"])
        self.assertFalse(manager.has_plugins())

    def test_global_manager_reset(self):
        first = get_plugin_manager()
        reset = reset_plugin_manager()
        self.assertIsNot(first, reset)
        self.assertIs(reset, get_plugin_manager())


if __name__ == "__main__":
    unittest.main()
