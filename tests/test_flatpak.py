"""Tests for drawio_libs.flatpak: app paths, running detection, launch command, mounts and the desktop entry."""

import os
import tempfile
import unittest

from drawio_libs.flatpak import (
    ENTRY_MARKER,
    app_paths,
    is_loader_entry,
    is_running,
    launch_command,
    loader_desktop_entry,
    sandbox_mounts,
)
from drawio_libs.libraries import Library

EXPORTED_ENTRY = """[Desktop Entry]
Name=drawio
Exec=/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=run.sh --file-forwarding com.jgraph.drawio.desktop @@u %U @@
Terminal=false
Type=Application
Icon=com.jgraph.drawio.desktop
MimeType=application/vnd.jgraph.mxfile;application/vnd.visio;
X-Flatpak=com.jgraph.drawio.desktop
"""


class AppPathsTest(unittest.TestCase):
    def test_paths_live_in_the_flatpak_app_data_directory(self):
        paths = app_paths("com.jgraph.drawio.desktop", "/home/u")
        self.assertEqual(paths.config_json,
                         "/home/u/.var/app/com.jgraph.drawio.desktop/config/draw.io/config.json")
        self.assertEqual(paths.state_dir,
                         "/home/u/.var/app/com.jgraph.drawio.desktop/data/drawio-library-loader")


class IsRunningTest(unittest.TestCase):
    def test_true_when_the_app_is_listed_by_flatpak_ps(self):
        runner = lambda cmd: (0, "org.mozilla.firefox\ncom.jgraph.drawio.desktop\n")
        self.assertTrue(is_running("com.jgraph.drawio.desktop", runner))

    def test_false_when_only_other_apps_run(self):
        runner = lambda cmd: (0, "org.mozilla.firefox\ncom.jgraph.drawio.desktop.Plugin\n")
        self.assertFalse(is_running("com.jgraph.drawio.desktop", runner))

    def test_false_when_flatpak_ps_fails(self):
        self.assertFalse(is_running("com.jgraph.drawio.desktop", lambda cmd: (1, "")))

    def test_asks_flatpak_for_the_application_column_only(self):
        seen = []
        is_running("x.y", lambda cmd: seen.append(cmd) or (0, ""))
        self.assertEqual(seen, [["flatpak", "ps", "--columns=application"]])


class SandboxMountsTest(unittest.TestCase):
    def mounts(self, *paths):
        return sandbox_mounts([Library(p) for p in paths], "/home/u")

    def test_libraries_under_home_need_no_mount(self):
        mounts, warnings = self.mounts("/home/u/libs/a.xml")
        self.assertEqual((mounts, warnings), ([], []))

    def test_libraries_elsewhere_get_a_read_only_mount_of_their_directory(self):
        mounts, _ = self.mounts("/data/icons/a.xml", "/data/icons/b.xml", "/mnt/x/c.xml")
        self.assertEqual(mounts, ["--filesystem=/data/icons:ro", "--filesystem=/mnt/x:ro"])

    def test_home_lookalike_prefix_is_not_home(self):
        mounts, _ = self.mounts("/home/u2/a.xml")
        self.assertEqual(mounts, ["--filesystem=/home/u2:ro"])

    def test_directories_flatpak_reserves_are_skipped_with_a_warning(self):
        mounts, warnings = self.mounts("/usr/share/icons/a.xml")
        self.assertEqual(mounts, [])
        self.assertIn("/usr/share/icons", warnings[0])

    def test_directory_with_a_colon_is_skipped_with_a_warning(self):
        mounts, warnings = self.mounts("/data/a:b/a.xml")
        self.assertEqual(mounts, [])
        self.assertIn("/data/a:b", warnings[0])


class LaunchCommandTest(unittest.TestCase):
    def test_runs_the_app_with_file_forwarding_and_passes_arguments_on(self):
        cmd = launch_command("com.jgraph.drawio.desktop", [], ["@@u", "%U", "@@"])
        self.assertEqual(cmd, ["flatpak", "run", "--file-forwarding", "com.jgraph.drawio.desktop",
                               "@@u", "%U", "@@"])

    def test_mounts_go_before_the_app_id(self):
        cmd = launch_command("a.b.C", ["--filesystem=/data:ro"], [])
        self.assertLess(cmd.index("--filesystem=/data:ro"), cmd.index("a.b.C"))


class DesktopEntryTest(unittest.TestCase):
    def entry(self, launcher="/home/u/.local/bin/drawio-libs"):
        return loader_desktop_entry(EXPORTED_ENTRY, "com.jgraph.drawio.desktop", launcher)

    def test_exec_starts_the_loader_and_keeps_the_file_arguments(self):
        self.assertIn('Exec="/home/u/.local/bin/drawio-libs" launch @@u %U @@\n', self.entry())

    def test_other_keys_are_kept(self):
        text = self.entry()
        for line in ("Name=drawio", "Icon=com.jgraph.drawio.desktop",
                     "MimeType=application/vnd.jgraph.mxfile;application/vnd.visio;"):
            self.assertIn(line + "\n", text)

    def test_entry_is_marked_as_the_loaders(self):
        self.assertTrue(is_loader_entry(self.entry()))
        self.assertFalse(is_loader_entry(EXPORTED_ENTRY))
        self.assertEqual(self.entry().count(ENTRY_MARKER), 1)

    def test_marker_sits_in_the_desktop_entry_group(self):
        lines = self.entry().splitlines()
        self.assertEqual(lines[0], "[Desktop Entry]")
        self.assertEqual(lines[1], ENTRY_MARKER)

    def test_launcher_path_with_spaces_and_specials_is_quoted(self):
        text = self.entry('/home/my user/$bin/drawio-libs')
        self.assertIn('Exec="/home/my user/\\\\$bin/drawio-libs" launch', text)

    def test_percent_in_the_launcher_path_is_doubled(self):
        text = self.entry("/opt/100%/drawio-libs")
        self.assertIn('Exec="/opt/100%%/drawio-libs" launch', text)

    def test_action_exec_lines_are_rewritten_too(self):
        source = EXPORTED_ENTRY + ("\n[Desktop Action new]\n"
                                   "Exec=/usr/bin/flatpak run --command=run.sh com.jgraph.drawio.desktop --new\n")
        text = loader_desktop_entry(source, "com.jgraph.drawio.desktop", "/bin/dl")
        self.assertIn('Exec="/bin/dl" launch --new\n', text)

    def test_exec_lines_that_do_not_start_the_app_are_left_alone(self):
        source = "[Desktop Entry]\nExec=/usr/bin/other thing\n"
        text = loader_desktop_entry(source, "com.jgraph.drawio.desktop", "/bin/dl")
        self.assertIn("Exec=/usr/bin/other thing\n", text)


if __name__ == "__main__":
    unittest.main()
