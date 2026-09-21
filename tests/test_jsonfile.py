"""Tests for drawio_libs.jsonfile: crash-safe JSON files in the tab-indented style the app itself writes."""

import json
import os
import tempfile
import unittest

from drawio_libs.jsonfile import write_json_atomic


class WriteJsonAtomicTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "sub", "data.json")

    def test_writes_tab_indented_json_and_creates_parent_directories(self):
        write_json_atomic(self.path, {"a": [1]})
        with open(self.path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(json.loads(text), {"a": [1]})
        self.assertIn('\n\t"a"', text)

    def test_keeps_non_ascii_text_readable(self):
        write_json_atomic(self.path, {"name": "café"})
        with open(self.path, encoding="utf-8") as handle:
            self.assertIn("café", handle.read())

    def test_applies_the_requested_file_mode(self):
        write_json_atomic(self.path, {}, mode=0o600)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_replaces_existing_content_and_leaves_no_temporary_files(self):
        write_json_atomic(self.path, {"a": 1})
        write_json_atomic(self.path, {"b": 2})
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"b": 2})
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["data.json"])


if __name__ == "__main__":
    unittest.main()
