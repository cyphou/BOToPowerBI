"""Tests for UNX diagnostics in the universe extractor."""

import io
import os
import tempfile
import unittest
import zipfile

from bo_export.universe_extractor import extract_universe


def _component(name, protected):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as nested:
        nested.writestr("Properties", b"\x03\x00\x00\x001.0")
        if protected:
            nested.writestr("Cipher", b"\x08\x00\x00\x00MDCipher")
        nested.writestr(name, b"\x04\x00\x00\x00opaque")
    return buffer.getvalue()


class TestProtectedUnxDiagnostics(unittest.TestCase):
    def _write(self, members):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = os.path.join(directory.name, "synthetic.unx")
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in members:
                archive.writestr(name, data)
        return path

    def test_cipher_protected_components_are_named_and_yield_no_objects(self):
        path = self._write([
            ("Properties", b"\x03\x00\x00\x001.0"),
            ("Sales.dfx", _component("Sales.dfx", True)),
            ("Sales.blx", _component("Sales.blx", True)),
            ("Sales.cns", _component("Sales.cns", False)),
        ])
        with self.assertLogs("bo_export.universe_extractor", level="WARNING") as logged:
            extracted = extract_universe(path)

        self.assertEqual(len(extracted), 15)
        self.assertTrue(all(items == [] for items in extracted.values()))
        message = " ".join(logged.output)
        self.assertIn("Sales.dfx", message)
        self.assertIn("Sales.blx", message)
        self.assertNotIn("Sales.cns", message)
        self.assertIn("no decryption is attempted", message)

    def test_unprotected_components_do_not_trigger_the_warning(self):
        path = self._write([("Sales.dfx", _component("Sales.dfx", False))])
        with self.assertNoLogs("bo_export.universe_extractor", level="WARNING"):
            extract_universe(path)


if __name__ == "__main__":
    unittest.main()
