"""Tests for drawio_libs.install: putting the loader on a user's system and taking it off again."""

import os
import tempfile
import unittest
from dataclasses import replace

from drawio_libs.flatpak import is_loader_entry
from drawio_libs.install import Dirs, InstallError, install, uninstall

SOURCE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = "com.jgraph.drawio.desktop"
EXPORTED_ENTRY = ("[Desktop Entry]\nName=drawio\n"
                  "Exec=/usr/bin/flatpak run --command=run.sh --file-forwarding %s @@u %%U @@\n"
                  "Icon=%s\n" % (APP, APP))


class InstallTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = os.path.join(self._tmp.name, "home")
        data_home = os.path.join(self.home, ".local", "share")
        self.dirs = Dirs(home=self.home, data_home=data_home, config_home=os.path.join(self.home, ".config"),
                         data_dirs=[], flatpak_user_dir=os.path.join(data_home, "flatpak"),
                         flatpak_system_dir=os.path.join(self._tmp.name, "no-system-flatpak"))
        exports = os.path.join(self.dirs.data_home, "flatpak", "exports", "share", "applications")
        os.makedirs(exports)
        with open(os.path.join(exports, APP + ".desktop"), "w") as handle:
            handle.write(EXPORTED_ENTRY)
        self.entry_path = os.path.join(self.dirs.data_home, "applications", APP + ".desktop")
        self.settings_path = os.path.join(self.dirs.config_home, "drawio-library-loader", "settings.conf")
        self.link = os.path.join(self.home, ".local", "bin", "drawio-libs")

    def install(self):
        return install(SOURCE_DIR, self.dirs, update_database=lambda directory: None)

    def read(self, path):
        with open(path) as handle:
            return handle.read()


class DirsFromEnvTest(unittest.TestCase):
    def test_defaults_follow_the_xdg_and_flatpak_conventions(self):
        dirs = Dirs.from_env({}, "/home/u")
        self.assertEqual(dirs.data_home, "/home/u/.local/share")
        self.assertEqual(dirs.config_home, "/home/u/.config")
        self.assertEqual(dirs.data_dirs, ["/usr/local/share", "/usr/share"])
        self.assertEqual(dirs.flatpak_export_dirs()[:2],
                         ["/home/u/.local/share/flatpak/exports/share", "/var/lib/flatpak/exports/share"])

    def test_environment_overrides_are_honoured(self):
        dirs = Dirs.from_env({"XDG_DATA_HOME": "/d", "XDG_CONFIG_HOME": "/c", "XDG_DATA_DIRS": "/x:/y",
                              "FLATPAK_USER_DIR": "/fu", "FLATPAK_SYSTEM_DIR": "/fs"}, "/home/u")
        self.assertEqual((dirs.data_home, dirs.config_home, dirs.data_dirs), ("/d", "/c", ["/x", "/y"]))
        self.assertEqual(dirs.flatpak_export_dirs()[:2], ["/fu/exports/share", "/fs/exports/share"])


class InstallTest(InstallTestCase):
    def test_program_is_copied_and_linked_into_local_bin(self):
        self.install()
        installed = os.path.join(self.dirs.data_home, "drawio-library-loader", "drawio-libs")
        self.assertTrue(os.access(installed, os.X_OK))
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(installed), "drawio_libs", "cli.py")))
        self.assertEqual(os.path.realpath(self.link), os.path.realpath(installed))

    def test_program_copy_leaves_out_bytecode_caches(self):
        self.install()
        package = os.path.join(self.dirs.data_home, "drawio-library-loader", "drawio_libs")
        self.assertNotIn("__pycache__", os.listdir(package))

    def test_settings_file_is_created_from_the_example(self):
        self.install()
        self.assertEqual(self.read(self.settings_path), self.read(os.path.join(SOURCE_DIR, "settings.example.conf")))

    def test_existing_settings_are_never_overwritten(self):
        os.makedirs(os.path.dirname(self.settings_path))
        with open(self.settings_path, "w") as handle:
            handle.write("[libraries]\n/mine.xml\n")
        self.install()
        self.assertEqual(self.read(self.settings_path), "[libraries]\n/mine.xml\n")

    def test_desktop_entry_overrides_the_flatpaks_and_starts_the_loader(self):
        self.install()
        text = self.read(self.entry_path)
        self.assertTrue(is_loader_entry(text))
        self.assertIn('Exec="%s" launch @@u %%U @@' % self.link, text)
        self.assertIn("Icon=" + APP, text)

    def test_reinstall_is_idempotent(self):
        self.install()
        first = self.read(self.entry_path)
        self.install()
        self.assertEqual(self.read(self.entry_path), first)

    def test_uses_the_app_id_from_the_settings(self):
        other = "org.example.Draw"
        exports = os.path.join(self.dirs.data_home, "flatpak", "exports", "share", "applications")
        with open(os.path.join(exports, other + ".desktop"), "w") as handle:
            handle.write(EXPORTED_ENTRY.replace(APP, other))
        os.makedirs(os.path.dirname(self.settings_path))
        with open(self.settings_path, "w") as handle:
            handle.write("[general]\napp_id = %s\n" % other)
        self.install()
        self.assertTrue(os.path.exists(os.path.join(self.dirs.data_home, "applications", other + ".desktop")))

    def test_finds_the_system_wide_flatpak_entry_through_the_data_dirs(self):
        exports = os.path.join(self.dirs.data_home, "flatpak", "exports", "share", "applications")
        system = os.path.join(self._tmp.name, "system-share")
        os.makedirs(os.path.join(system, "applications"))
        os.rename(os.path.join(exports, APP + ".desktop"), os.path.join(system, "applications", APP + ".desktop"))
        self.dirs = replace(self.dirs, data_dirs=[system])
        self.install()
        self.assertTrue(os.path.exists(self.entry_path))

    def test_missing_flatpak_app_is_an_error_and_changes_nothing(self):
        os.remove(os.path.join(self.dirs.data_home, "flatpak", "exports", "share", "applications", APP + ".desktop"))
        with self.assertRaises(InstallError) as caught:
            self.install()
        self.assertIn(APP, str(caught.exception))
        self.assertFalse(os.path.exists(self.link))
        self.assertFalse(os.path.exists(self.settings_path))

    def test_a_foreign_desktop_entry_is_never_overwritten(self):
        os.makedirs(os.path.dirname(self.entry_path))
        with open(self.entry_path, "w") as handle:
            handle.write("[Desktop Entry]\nName=mine\n")
        with self.assertRaises(InstallError) as caught:
            self.install()
        self.assertIn(self.entry_path, str(caught.exception))
        self.assertEqual(self.read(self.entry_path), "[Desktop Entry]\nName=mine\n")

    def test_desktop_database_is_refreshed(self):
        seen = []
        install(SOURCE_DIR, self.dirs, update_database=seen.append)
        self.assertEqual(seen, [os.path.dirname(self.entry_path)])


class UninstallTest(InstallTestCase):
    def test_removes_entry_link_and_program_but_keeps_the_settings(self):
        self.install()
        uninstall(self.dirs, update_database=lambda directory: None)
        self.assertFalse(os.path.lexists(self.entry_path))
        self.assertFalse(os.path.lexists(self.link))
        self.assertFalse(os.path.exists(os.path.join(self.dirs.data_home, "drawio-library-loader")))
        self.assertTrue(os.path.exists(self.settings_path))

    def test_a_foreign_desktop_entry_is_left_alone(self):
        os.makedirs(os.path.dirname(self.entry_path))
        with open(self.entry_path, "w") as handle:
            handle.write("[Desktop Entry]\nName=mine\n")
        uninstall(self.dirs, update_database=lambda directory: None)
        self.assertTrue(os.path.exists(self.entry_path))

    def test_a_foreign_bin_file_is_left_alone(self):
        os.makedirs(os.path.dirname(self.link))
        with open(self.link, "w") as handle:
            handle.write("#!/bin/sh\n")
        uninstall(self.dirs, update_database=lambda directory: None)
        self.assertTrue(os.path.exists(self.link))

    def test_uninstall_without_install_is_harmless(self):
        uninstall(self.dirs, update_database=lambda directory: None)


if __name__ == "__main__":
    unittest.main()
