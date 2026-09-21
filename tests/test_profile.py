"""Tests for drawio_libs.profile: authorising library paths in the app's config.json."""

import json
import os
import tempfile
import unittest

from drawio_libs.profile import ProfileError, seed_blessed_paths


class ProfileTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def write(self, name, text):
        with open(self.path(name), "w", encoding="utf-8") as handle:
            handle.write(text)
        return self.path(name)

    def read_json(self, name):
        with open(self.path(name), encoding="utf-8") as handle:
            return json.load(handle)


class SeedBlessedPathsTest(ProfileTestCase):
    def test_adds_library_paths_and_keeps_every_other_setting(self):
        config = self.write("config.json", json.dumps(
            {"lastWinSize": "1,2,3,4,false,false", "blessedPaths": ["/x/diagram.drawio"]}))
        outcome = seed_blessed_paths(config, ["/libs/a.xml", "/libs/b.xml"])
        self.assertEqual(outcome, "updated")
        data = self.read_json("config.json")
        self.assertEqual(data["lastWinSize"], "1,2,3,4,false,false")
        self.assertEqual(data["blessedPaths"], ["/x/diagram.drawio", "/libs/a.xml", "/libs/b.xml"])

    def test_creates_the_list_when_the_config_has_none(self):
        config = self.write("config.json", "{}")
        seed_blessed_paths(config, ["/libs/a.xml"])
        self.assertEqual(self.read_json("config.json")["blessedPaths"], ["/libs/a.xml"])

    def test_authorises_the_symlink_target_as_well(self):
        target = self.write("real.xml", "<mxlibrary>[]</mxlibrary>")
        link = self.path("link.xml")
        os.symlink(target, link)
        config = self.write("config.json", "{}")
        seed_blessed_paths(config, [link])
        self.assertEqual(self.read_json("config.json")["blessedPaths"], [link, os.path.realpath(target)])

    def test_second_run_changes_nothing(self):
        config = self.write("config.json", "{}")
        seed_blessed_paths(config, ["/libs/a.xml"])
        before = os.stat(config).st_mtime_ns
        self.assertEqual(seed_blessed_paths(config, ["/libs/a.xml"]), "unchanged")
        self.assertEqual(os.stat(config).st_mtime_ns, before)

    def test_only_missing_paths_are_appended(self):
        config = self.write("config.json", json.dumps({"blessedPaths": ["/libs/a.xml", "/x/d.drawio"]}))
        seed_blessed_paths(config, ["/libs/a.xml", "/libs/b.xml"])
        self.assertEqual(self.read_json("config.json")["blessedPaths"],
                         ["/libs/a.xml", "/x/d.drawio", "/libs/b.xml"])

    def test_missing_config_means_no_profile_and_creates_nothing(self):
        config = self.path("config.json")
        self.assertEqual(seed_blessed_paths(config, ["/libs/a.xml"]), "no-profile")
        self.assertFalse(os.path.exists(config))

    def test_invalid_json_is_refused_and_left_untouched(self):
        config = self.write("config.json", "{not json")
        with self.assertRaises(ProfileError) as caught:
            seed_blessed_paths(config, ["/libs/a.xml"])
        self.assertIn(config, str(caught.exception))
        with open(config) as handle:
            self.assertEqual(handle.read(), "{not json")

    def test_unexpected_shapes_are_refused(self):
        for text in ("[]", '{"blessedPaths": "nope"}'):
            config = self.write("config.json", text)
            with self.assertRaises(ProfileError, msg=text):
                seed_blessed_paths(config, ["/libs/a.xml"])

    def test_no_libraries_changes_nothing(self):
        config = self.write("config.json", "{}")
        self.assertEqual(seed_blessed_paths(config, []), "unchanged")

    def test_written_file_uses_tab_indentation_like_the_app(self):
        config = self.write("config.json", "{}")
        seed_blessed_paths(config, ["/libs/a.xml"])
        with open(config, encoding="utf-8") as handle:
            self.assertIn('\n\t"blessedPaths"', handle.read())

    def test_keeps_the_file_mode(self):
        config = self.write("config.json", "{}")
        os.chmod(config, 0o600)
        seed_blessed_paths(config, ["/libs/a.xml"])
        self.assertEqual(os.stat(config).st_mode & 0o777, 0o600)

    def test_leaves_no_temporary_files_behind(self):
        config = self.write("config.json", "{}")
        seed_blessed_paths(config, ["/libs/a.xml"])
        self.assertEqual(os.listdir(self.dir), ["config.json"])


if __name__ == "__main__":
    unittest.main()
