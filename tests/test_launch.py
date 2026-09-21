"""Tests for drawio_libs.launch: preparing the app profile and libraries, and building the start command."""

import json
import os
import tempfile
import unittest

from drawio_libs.launch import plan_launch, prepare
from drawio_libs.libraries import library_id
from drawio_libs.sync import SyncError, read_state, write_state

APP = "com.jgraph.drawio.desktop"


def idle(cmd):
    return 0, ""


def running(cmd):
    return 0, APP + "\n"


class FakeSync:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def __call__(self, app_id, mounts, add_ids, remove_ids):
        self.calls.append((app_id, list(mounts), list(add_ids), list(remove_ids)))
        if self.error:
            raise self.error


class LaunchTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = os.path.join(self._tmp.name, "home")
        self.libs = os.path.join(self.home, "libs")
        os.makedirs(self.libs)
        self.settings_path = os.path.join(self._tmp.name, "settings.conf")
        self.app_root = os.path.join(self.home, ".var", "app", APP)
        self.config_json = os.path.join(self.app_root, "config", "draw.io", "config.json")
        self.state_dir = os.path.join(self.app_root, "data", "drawio-library-loader")
        self.sync = FakeSync()
        self.reported = []

    def write_settings(self, text):
        with open(self.settings_path, "w") as handle:
            handle.write(text)

    def make_library(self, name):
        path = os.path.join(self.libs, name)
        with open(path, "w") as handle:
            handle.write("<mxlibrary>[]</mxlibrary>")
        return path

    def make_profile(self, data=None):
        os.makedirs(os.path.dirname(self.config_json), exist_ok=True)
        with open(self.config_json, "w") as handle:
            json.dump({} if data is None else data, handle)

    def blessed(self):
        with open(self.config_json) as handle:
            return json.load(handle).get("blessedPaths", [])

    def plan(self, args=(), runner=idle):
        return plan_launch(self.settings_path, self.home, list(args), runner, self.sync, self.reported.append)

    def prepare(self, runner=idle, force=False):
        return prepare(self.settings_path, self.home, runner, self.sync, self.reported.append, force=force)


class NormalLaunchTest(LaunchTestCase):
    def test_libraries_are_authorised_registered_once_and_the_app_started_plainly(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.make_profile()
        plan = self.plan(["@@u", "%U", "@@"])
        self.assertEqual(self.blessed(), [lib])
        self.assertEqual(self.sync.calls, [(APP, [], [library_id(lib)], [])])
        self.assertEqual(read_state(self.state_dir), {"ids": [library_id(lib)]})
        self.assertEqual(plan.command, ["flatpak", "run", "--file-forwarding", APP, "@@u", "%U", "@@"])

    def test_the_user_hears_about_the_sync_before_it_starts(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.make_profile()
        order = []
        sync = lambda *args: order.append("sync")
        plan_launch(self.settings_path, self.home, [], idle, sync, lambda message: order.append("report"))
        self.assertEqual(order, ["report", "sync"])

    def test_directory_entries_load_each_library_once(self):
        self.make_library("A.xml")
        self.make_library("A.drawio")
        self.make_library("B.drawio")
        self.write_settings("[libraries]\n%s\n" % self.libs)
        self.make_profile()
        self.plan()
        self.assertEqual([os.path.basename(p) for p in self.blessed()], ["A.xml", "B.drawio"])
        self.assertEqual(len(self.sync.calls[0][2]), 2)

    def test_a_synced_configuration_starts_the_app_without_another_sync(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.make_profile()
        write_state(self.state_dir, {"ids": [library_id(lib)]})
        self.plan()
        self.assertEqual(self.sync.calls, [])
        self.assertEqual(self.reported, [])

    def test_removed_libraries_are_unregistered_but_only_those_the_loader_added(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.make_profile()
        write_state(self.state_dir, {"ids": [library_id(lib), "S%2Fold.xml"]})
        self.plan()
        self.assertEqual(self.sync.calls[0][2:], ([library_id(lib)], ["S%2Fold.xml"]))

    def test_the_configured_app_id_selects_the_profile_and_command(self):
        self.write_settings("[general]\napp_id = org.example.Draw\n[libraries]\n")
        plan = self.plan()
        self.assertIn("org.example.Draw", plan.command)

    def test_libraries_outside_home_are_mounted_for_the_start_and_the_sync(self):
        outside = os.path.join(self._tmp.name, "shared")
        os.makedirs(outside)
        with open(os.path.join(outside, "S.xml"), "w"):
            pass
        self.write_settings("[libraries]\n%s\n" % outside)
        self.make_profile()
        plan = self.plan()
        mount = "--filesystem=%s:ro" % outside
        self.assertIn(mount, plan.command)
        self.assertEqual(self.sync.calls[0][1], [mount])


class RunningAppTest(LaunchTestCase):
    def test_a_running_app_is_left_alone_because_it_would_overwrite_changes(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.make_profile({"blessedPaths": ["/x/d.drawio"]})
        plan = self.plan(runner=running)
        self.assertEqual(self.blessed(), ["/x/d.drawio"])
        self.assertEqual(self.sync.calls, [])
        self.assertEqual(plan.command[:2], ["flatpak", "run"])

    def test_an_explicit_sync_asks_to_close_a_running_app(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.make_profile()
        result = self.prepare(runner=running, force=True)
        self.assertFalse(result.ok)
        self.assertIn("close draw.io", result.messages[0])


class DegradedLaunchTest(LaunchTestCase):
    def test_missing_settings_still_start_the_app_plainly_and_say_why(self):
        plan = self.plan(["x.drawio"])
        self.assertEqual(plan.command, ["flatpak", "run", "--file-forwarding", APP, "x.drawio"])
        self.assertIn(self.settings_path, plan.messages[0])
        self.assertEqual(self.sync.calls, [])

    def test_malformed_settings_start_the_app_plainly_and_say_why(self):
        self.write_settings("[nope]\n")
        plan = self.plan()
        self.assertIn("nope", plan.messages[0])
        self.assertEqual(self.sync.calls, [])

    def test_missing_libraries_are_reported_but_the_rest_still_load(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n%s/gone.xml\n" % (lib, self.libs))
        self.make_profile()
        plan = self.plan()
        self.assertEqual(self.blessed(), [lib])
        self.assertEqual(self.sync.calls[0][2], [library_id(lib)])
        self.assertTrue(any("gone.xml" in m for m in plan.messages))

    def test_fresh_profile_is_left_alone_with_a_hint(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        plan = self.plan()
        self.assertFalse(os.path.exists(self.config_json))
        self.assertIn("next start", plan.messages[0])
        self.assertEqual(self.sync.calls, [])

    def test_unreadable_app_config_is_reported_left_untouched_and_blocks_the_sync(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        os.makedirs(os.path.dirname(self.config_json))
        with open(self.config_json, "w") as handle:
            handle.write("{broken")
        plan = self.plan()
        with open(self.config_json) as handle:
            self.assertEqual(handle.read(), "{broken")
        self.assertIn(self.config_json, plan.messages[0])
        self.assertEqual(self.sync.calls, [])
        self.assertEqual(plan.command[:2], ["flatpak", "run"])

    def test_a_failed_sync_is_reported_remembered_and_not_retried_every_start(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.make_profile()
        self.sync.error = SyncError("no window")
        plan = self.plan()
        self.assertEqual(plan.command[:2], ["flatpak", "run"])
        self.assertTrue(any("no window" in m for m in plan.messages))
        self.assertTrue(any("drawio-libs sync" in m for m in plan.messages))
        self.assertEqual(read_state(self.state_dir).get("failed"), [library_id(lib)])
        self.plan()
        self.assertEqual(len(self.sync.calls), 1)

    def test_an_unwritable_state_directory_is_reported_but_does_not_stop_the_start(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.make_profile()
        os.makedirs(os.path.dirname(self.state_dir), exist_ok=True)
        with open(self.state_dir, "w") as handle:
            handle.write("a file where the directory should be")
        plan = self.plan()
        self.assertEqual(plan.command[:2], ["flatpak", "run"])
        self.assertTrue(any(self.state_dir in m for m in plan.messages))

    def test_nothing_configured_and_nothing_applied_touches_nothing(self):
        self.write_settings("[libraries]\n")
        self.make_profile()
        self.plan()
        self.assertEqual(self.sync.calls, [])


class ForcedSyncTest(LaunchTestCase):
    def test_force_syncs_even_when_the_state_says_it_is_done_and_clears_a_failure(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.make_profile()
        write_state(self.state_dir, {"ids": [library_id(lib)], "failed": [library_id(lib)]})
        result = self.prepare(force=True)
        self.assertTrue(result.ok)
        self.assertEqual(len(self.sync.calls), 1)
        self.assertEqual(read_state(self.state_dir), {"ids": [library_id(lib)]})

    def test_a_failed_forced_sync_is_not_ok(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.make_profile()
        self.sync.error = SyncError("boom")
        self.assertFalse(self.prepare(force=True).ok)

    def test_a_fresh_profile_is_not_ok_for_a_forced_sync(self):
        lib = self.make_library("A.xml")
        self.write_settings("[libraries]\n%s\n" % lib)
        self.assertFalse(self.prepare(force=True).ok)


if __name__ == "__main__":
    unittest.main()
