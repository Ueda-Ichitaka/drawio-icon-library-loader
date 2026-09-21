"""Tests for drawio_libs.cli: command dispatch, exit codes and what the user is told."""

import io
import json
import os
import tempfile
import unittest

from drawio_libs.cli import main

APP = "com.jgraph.drawio.desktop"


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = os.path.join(self._tmp.name, "home")
        os.makedirs(self.home)
        self.libs = os.path.join(self.home, "libs")
        os.makedirs(self.libs)
        self.lib = os.path.join(self.libs, "A.xml")
        with open(self.lib, "w") as handle:
            handle.write("<mxlibrary>[]</mxlibrary>")
        self.settings_path = os.path.join(self.home, ".config", "drawio-library-loader", "settings.conf")
        self.executed = []
        self.notified = []
        self.synced = []

    def make_profile(self):
        config = os.path.join(self.home, ".var", "app", APP, "config", "draw.io", "config.json")
        os.makedirs(os.path.dirname(config))
        with open(config, "w") as handle:
            handle.write("{}")

    def write_settings(self, text):
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        with open(self.settings_path, "w") as handle:
            handle.write(text)

    def run_main(self, argv, env=None, runner=lambda cmd: (0, ""), sync_error=None):
        out, err = io.StringIO(), io.StringIO()

        def sync(app_id, mounts, add_ids, remove_ids):
            self.synced.append((app_id, add_ids, remove_ids))
            if sync_error:
                raise sync_error

        code = main(argv, env=env or {}, home=self.home,
                    execute=lambda program, cmd: self.executed.append((program, cmd)),
                    runner=runner, out=out, err=err, sync=sync,
                    notify=lambda summary, body: self.notified.append((summary, body)))
        return code, out.getvalue(), err.getvalue()


class LaunchCommandTest(CliTestCase):
    def test_launch_executes_the_planned_command_with_the_forwarded_arguments(self):
        self.write_settings("[libraries]\n")
        code, _, err = self.run_main(["launch", "@@u", "%U", "@@"])
        program, cmd = self.executed[0]
        self.assertEqual(program, "flatpak")
        self.assertEqual(cmd[-4:], [APP, "@@u", "%U", "@@"])
        self.assertEqual(err, "")
        self.assertEqual(self.notified, [])

    def test_arguments_that_look_like_options_pass_through_to_the_app(self):
        self.write_settings("[libraries]\n")
        self.run_main(["launch", "--new", "--flag=1"])
        self.assertEqual(self.executed[0][1][-2:], ["--new", "--flag=1"])

    def test_messages_go_to_stderr_and_to_a_desktop_notification_each(self):
        self.write_settings("[libraries]\n%s/gone.xml\n" % self.libs)
        _, _, err = self.run_main(["launch"])
        self.assertIn("gone.xml", err)
        self.assertEqual(len(self.notified), 1)
        self.assertIn("gone.xml", self.notified[0][1])
        self.assertEqual(len(self.executed), 1)

    def test_a_needed_sync_runs_before_the_app_starts_and_is_announced(self):
        self.write_settings("[libraries]\n%s\n" % self.lib)
        self.make_profile()
        _, _, err = self.run_main(["launch"])
        self.assertEqual(len(self.synced), 1)
        self.assertIn("registering", err)
        self.assertEqual(len(self.executed), 1)

    def test_broken_settings_still_start_the_app(self):
        self.write_settings("[bogus]\n")
        self.run_main(["launch"])
        self.assertEqual(len(self.executed), 1)
        self.assertEqual(len(self.notified), 1)

    def test_config_option_selects_another_settings_file(self):
        other = os.path.join(self.home, "other.conf")
        with open(other, "w") as handle:
            handle.write("[general]\napp_id = org.example.Draw\n")
        self.run_main(["--config", other, "launch"])
        self.assertIn("org.example.Draw", self.executed[0][1])

    def test_environment_variable_selects_the_settings_file(self):
        other = os.path.join(self.home, "other.conf")
        with open(other, "w") as handle:
            handle.write("[general]\napp_id = org.example.Draw\n")
        self.run_main(["launch"], env={"DRAWIO_LIBS_SETTINGS": other})
        self.assertIn("org.example.Draw", self.executed[0][1])


class SyncCommandTest(CliTestCase):
    def test_sync_registers_the_libraries_without_starting_the_app_for_the_user(self):
        self.write_settings("[libraries]\n%s\n" % self.lib)
        self.make_profile()
        code, out, _ = self.run_main(["sync"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.synced), 1)
        self.assertEqual(self.executed, [])
        self.assertIn("registered", out)

    def test_sync_runs_even_when_nothing_changed(self):
        self.write_settings("[libraries]\n%s\n" % self.lib)
        self.make_profile()
        self.run_main(["sync"])
        self.run_main(["sync"])
        self.assertEqual(len(self.synced), 2)

    def test_a_failed_sync_exits_non_zero_and_says_why(self):
        from drawio_libs.sync import SyncError
        self.write_settings("[libraries]\n%s\n" % self.lib)
        self.make_profile()
        code, _, err = self.run_main(["sync"], sync_error=SyncError("no window"))
        self.assertEqual(code, 1)
        self.assertIn("no window", err)

    def test_sync_while_the_app_runs_fails_and_says_to_close_it(self):
        self.write_settings("[libraries]\n%s\n" % self.lib)
        self.make_profile()
        code, _, err = self.run_main(["sync"], runner=lambda cmd: (0, APP + "\n"))
        self.assertEqual(code, 1)
        self.assertIn("close draw.io", err)


class ListCommandTest(CliTestCase):
    def test_lists_settings_app_and_resolved_libraries(self):
        self.write_settings("[libraries]\n%s\n" % self.libs)
        code, out, _ = self.run_main(["list"])
        self.assertEqual(code, 0)
        self.assertIn(self.settings_path, out)
        self.assertIn(APP, out)
        self.assertIn(self.lib, out)
        self.assertEqual(self.executed, [])

    def test_reports_missing_libraries(self):
        self.write_settings("[libraries]\n%s/gone.xml\n" % self.libs)
        code, out, _ = self.run_main(["list"])
        self.assertEqual(code, 0)
        self.assertIn("gone.xml", out)

    def test_reports_whether_the_libraries_are_registered(self):
        self.write_settings("[libraries]\n%s\n" % self.lib)
        self.make_profile()
        _, out, _ = self.run_main(["list"])
        self.assertIn("registered with draw.io: no", out)
        self.run_main(["sync"])
        _, out, _ = self.run_main(["list"])
        self.assertIn("registered with draw.io: yes", out)

    def test_reports_profile_and_running_state(self):
        self.write_settings("[libraries]\n")
        _, out, _ = self.run_main(["list"], runner=lambda cmd: (0, APP + "\n"))
        self.assertIn("running: yes", out)
        self.assertIn("profile: not created yet", out)

    def test_broken_settings_fail_with_the_reason(self):
        self.write_settings("[bogus]\n")
        code, _, err = self.run_main(["list"])
        self.assertEqual(code, 1)
        self.assertIn("bogus", err)


class OtherCommandsTest(CliTestCase):
    def test_no_command_prints_usage_and_fails(self):
        code, _, err = self.run_main([])
        self.assertEqual(code, 2)
        self.assertIn("usage", err.lower())

    def test_unknown_command_prints_usage_and_fails(self):
        code, _, err = self.run_main(["frobnicate"])
        self.assertEqual(code, 2)
        self.assertIn("frobnicate", err)

    def test_help_succeeds(self):
        code, out, _ = self.run_main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("install", out)

    def test_install_without_the_flatpak_reports_the_error(self):
        env = {"XDG_DATA_HOME": os.path.join(self.home, "share"), "XDG_DATA_DIRS": os.path.join(self.home, "none"),
               "FLATPAK_SYSTEM_DIR": os.path.join(self.home, "none"), "FLATPAK_USER_DIR": os.path.join(self.home, "none")}
        code, _, err = self.run_main(["install"], env=env)
        self.assertEqual(code, 1)
        self.assertIn(APP, err)

    def test_uninstall_reports_nothing_to_remove(self):
        env = {"XDG_DATA_HOME": os.path.join(self.home, "share")}
        code, out, _ = self.run_main(["uninstall"], env=env)
        self.assertEqual(code, 0)
        self.assertIn("nothing", out.lower())


if __name__ == "__main__":
    unittest.main()
