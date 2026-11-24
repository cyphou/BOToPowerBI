import json
import os
import tempfile
import unittest
import zipfile

from powerbi_import.geo_passthrough import (
    GeoExtractor,
    _classify_format,
    _extract_geojson_properties,
    geojson_to_shape_map_resource,
)


class GeoPassthroughTests(unittest.TestCase):
    def test_non_archive_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            extractor = GeoExtractor(os.path.join(directory, "Sales.wid"), directory)
            self.assertEqual(extractor.extract(), [])

    def test_extract_supported_formats_and_zip_errors(self):
        geojson = {"type": "FeatureCollection", "features": [{"properties": {"Region": "EMEA", "Code": "EU"}}]}
        with tempfile.TemporaryDirectory() as directory:
            archive = os.path.join(directory, "Map.twbx")
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("Maps/regions.geojson", json.dumps(geojson))
                z.writestr("Maps/bounds.topojson", '{"type":"Topology"}')
                z.writestr("Maps/ignored.txt", "ignore")
                z.writestr("Maps/regions.shp", b"shapefile")
                z.writestr("Maps/folder/", b"")
            extractor = GeoExtractor(archive, os.path.join(directory, "output"))
            files = extractor.extract()
            self.assertEqual(len(files), 3)
            formats = {item["filename"]: item["format"] for item in files}
            self.assertEqual(formats["regions.geojson"], "geojson")
            self.assertEqual(formats["bounds.topojson"], "topojson")
            self.assertEqual(formats["regions.shp"], "shapefile")
            for item in files:
                self.assertGreater(item["size_bytes"], 0)
                self.assertTrue(os.path.isfile(item["output_path"]))

            bad = os.path.join(directory, "bad.tdsx")
            with open(bad, "wb") as handle:
                handle.write(b"not a zip")
            self.assertEqual(GeoExtractor(bad, directory).extract(), [])

    def test_extract_os_error_is_reported_as_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = os.path.join(directory, "missing.twbx")
            self.assertEqual(GeoExtractor(missing, directory).extract(), [])

    def test_classify_format_branches(self):
        self.assertEqual(_classify_format(".geojson", "map.GEOJSON"), "geojson")
        self.assertEqual(_classify_format(".json", "geo_regions.json"), "geojson")
        self.assertEqual(_classify_format(".topojson", "map.topojson"), "topojson")
        self.assertEqual(_classify_format(".json", "topology.json"), "topojson")
        self.assertEqual(_classify_format(".json", "topo_regions.json"), "topojson")
        self.assertEqual(_classify_format(".shp", "regions.shp"), "shapefile")
        self.assertEqual(_classify_format(".json", "ordinary.json"), "geojson")
        self.assertEqual(_classify_format(".png", "map.png"), "unknown")

    def test_extract_properties_and_malformed_geojson(self):
        with tempfile.TemporaryDirectory() as directory:
            geo = os.path.join(directory, "regions.geojson")
            with open(geo, "w", encoding="utf-8") as handle:
                json.dump({"features": [{"properties": {"Region": "EMEA", "Code": "EU"}}]}, handle)
            self.assertEqual(_extract_geojson_properties(geo), ["Region", "Code"])

            malformed = os.path.join(directory, "malformed.geojson")
            with open(malformed, "w", encoding="utf-8") as handle:
                handle.write("not json")
            self.assertEqual(_extract_geojson_properties(malformed), [])
            self.assertEqual(_extract_geojson_properties(os.path.join(directory, "missing")), [])

    def test_shape_map_prefers_geojson_and_uses_key_override(self):
        with tempfile.TemporaryDirectory() as directory:
            geo = os.path.join(directory, "regions.geojson")
            with open(geo, "w", encoding="utf-8") as handle:
                json.dump({"features": [{"properties": {"Region": "EMEA"}}]}, handle)
            files = [
                {"filename": "regions.shp", "format": "shapefile", "output_path": os.path.join(directory, "regions.shp")},
                {"filename": "regions.geojson", "format": "geojson", "output_path": geo},
            ]
            extractor = GeoExtractor("Synthetic.twbx", directory)
            config = extractor.build_shape_map_config(files, key_column="Region")
            self.assertEqual(config["visualType"], "shapeMap")
            self.assertEqual(config["shapeMapConfig"]["keyProperty"], "Region")
            self.assertEqual(config["shapeMapConfig"]["availableProperties"], ["Region"])
            self.assertEqual(config["registeredResource"]["name"], "regions.geojson")

    def test_shape_map_shapefile_fallback_empty_and_defaults(self):
        extractor = GeoExtractor("Synthetic.twbx", ".")
        shapefile = {"filename": "regions.shp", "format": "shapefile", "output_path": "missing.shp"}
        config = extractor.build_shape_map_config([shapefile])
        self.assertEqual(config["shapeMapConfig"]["keyProperty"], "name")
        self.assertEqual(config["shapeMapConfig"]["customMapUrl"], "RegisteredResources/regions.shp")
        self.assertEqual(extractor.build_shape_map_config([]), {})

    def test_copy_registered_resources_and_standalone_resource(self):
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "source.geojson")
            with open(source, "w", encoding="utf-8") as handle:
                json.dump({"features": [{"properties": {"Name": "Sample"}}]}, handle)
            extractor = GeoExtractor("Synthetic.twbx", directory)
            copied = extractor.copy_to_registered_resources(
                [{"filename": "sample.geojson", "output_path": source},
                 {"filename": "missing.geojson", "output_path": os.path.join(directory, "missing")}],
                os.path.join(directory, "pbip"),
            )
            self.assertEqual(len(copied), 1)
            self.assertTrue(os.path.isfile(copied[0]))

            resource = geojson_to_shape_map_resource(source)
            self.assertEqual(resource["name"], "source.geojson")
            self.assertEqual(resource["format"], "geojson")
            self.assertEqual(resource["properties"], ["Name"])
            self.assertGreater(resource["size_bytes"], 0)

            named = geojson_to_shape_map_resource(source, "Custom.geojson")
            self.assertEqual(named["name"], "Custom.geojson")
            missing = geojson_to_shape_map_resource(os.path.join(directory, "missing.geojson"))
            self.assertEqual(missing["size_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
