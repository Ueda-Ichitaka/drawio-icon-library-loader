"""Tests for drawio_libs.settings: parsing the settings file into app id, format preference and library paths."""

import os
import tempfile
import unittest
from unittest import mock

from drawio_libs.libraries import DEFAULT_PREFER
from drawio_libs.settings import DEFAULT_APP_ID, SettingsError, load_settings, parse_settings

BASE = "/etc/base"


def parse(text, base=BASE):
    return parse_settings(text, base, source="settings.conf")


class ParseSettingsTest(unittest.TestCase):
    def test_empty_file_yields_defaults(self):
        settings = parse("")
        self.assertEqual(settings.app_id, DEFAULT_APP_ID)
        self.assertEqual(settings.prefer, DEFAULT_PREFER)
        self.assertEqual(settings.libraries, [])

    def test_general_section_sets_app_id_and_prefer(self):
        settings = parse("[general]\napp_id = org.example.Draw\nprefer = drawio, .XML\n")
        self.assertEqual(settings.app_id, "org.example.Draw")
        self.assertEqual(settings.prefer, [".drawio", ".xml"])

    def test_libraries_section_lists_one_path_per_line(self):
        settings = parse("[libraries]\n/a/one.xml\n/b/two dir/Two Lib.drawio\n")
        self.assertEqual(settings.libraries, ["/a/one.xml", "/b/two dir/Two Lib.drawio"])

    def test_comments_and_blank_lines_are_ignored(self):
        settings = parse("# top\n\n[libraries]\n# note\n/a/one.xml\n\n   \n")
        self.assertEqual(settings.libraries, ["/a/one.xml"])

    def test_hash_inside_a_path_is_kept(self):
        settings = parse("[libraries]\n/a/c#.xml\n")
        self.assertEqual(settings.libraries, ["/a/c#.xml"])

    def test_surrounding_whitespace_is_trimmed(self):
        settings = parse("[libraries]\n   /a/one.xml   \n")
        self.assertEqual(settings.libraries, ["/a/one.xml"])

    def test_relative_paths_resolve_against_the_settings_directory(self):
        settings = parse("[libraries]\nlibs/one.xml\n../up.xml\n")
        self.assertEqual(settings.libraries, ["/etc/base/libs/one.xml", "/etc/up.xml"])

    def test_tilde_and_environment_variables_are_expanded(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/tester", "LIBS": "/data/libs"}):
            settings = parse("[libraries]\n~/mine.xml\n$LIBS/x.xml\n${LIBS}/y.xml\n")
        self.assertEqual(settings.libraries,
                         ["/home/tester/mine.xml", "/data/libs/x.xml", "/data/libs/y.xml"])

    def test_sections_may_repeat_and_come_in_any_order(self):
        settings = parse("[libraries]\n/a.xml\n[general]\nprefer = .xml\n[libraries]\n/b.xml\n")
        self.assertEqual(settings.libraries, ["/a.xml", "/b.xml"])
        self.assertEqual(settings.prefer, [".xml"])

    def assertRejected(self, text, *fragments):
        with self.assertRaises(SettingsError) as caught:
            parse(text)
        for fragment in fragments:
            self.assertIn(fragment, str(caught.exception))

    def test_unknown_section_is_rejected_with_its_line(self):
        self.assertRejected("[libraries]\n/a.xml\n[other]\n", "settings.conf:3", "other")

    def test_unknown_general_key_is_rejected(self):
        self.assertRejected("[general]\ncolour = red\n", "settings.conf:2", "colour")

    def test_content_before_any_section_is_rejected(self):
        self.assertRejected("/a.xml\n", "settings.conf:1")

    def test_general_line_without_equals_is_rejected(self):
        self.assertRejected("[general]\napp_id\n", "settings.conf:2")

    def test_app_id_with_unsafe_characters_is_rejected(self):
        self.assertRejected("[general]\napp_id = ../../etc\n", "app_id")
        self.assertRejected("[general]\napp_id = a b\n", "app_id")

    def test_empty_prefer_is_rejected(self):
        self.assertRejected("[general]\nprefer =\n", "prefer")


class LoadSettingsTest(unittest.TestCase):
    def test_reads_a_file_and_resolves_relative_paths_against_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.conf")
            with open(path, "w") as handle:
                handle.write("[libraries]\nlibs/one.xml\n")
            settings = load_settings(path)
        self.assertEqual(settings.libraries, [os.path.join(tmp, "libs", "one.xml")])

    def test_missing_file_raises_a_settings_error_naming_it(self):
        with self.assertRaises(SettingsError) as caught:
            load_settings("/nonexistent/settings.conf")
        self.assertIn("/nonexistent/settings.conf", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
