"""Tests for drawio_libs.sync: deciding when to register libraries with the app and doing it over DevTools."""

import json
import os
import subprocess
import tempfile
import unittest

from drawio_libs.cdp import CdpError
from drawio_libs.sync import SyncError, build_script, read_state, run_sync, sync_needed, write_state

A, B, C = "S%2Fa.xml", "S%2Fb.xml", "S%2Fc.xml"


class StateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = os.path.join(self._tmp.name, "state")

    def test_missing_state_reads_as_empty(self):
        self.assertEqual(read_state(self.dir), {})

    def test_state_round_trips(self):
        write_state(self.dir, {"ids": [A]})
        self.assertEqual(read_state(self.dir), {"ids": [A]})

    def test_corrupt_state_reads_as_empty(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "state.json"), "w") as handle:
            handle.write("{nope")
        self.assertEqual(read_state(self.dir), {})

    def test_state_of_the_wrong_shape_reads_as_empty(self):
        os.makedirs(self.dir)
        with open(os.path.join(self.dir, "state.json"), "w") as handle:
            handle.write("[1]")
        self.assertEqual(read_state(self.dir), {})


class SyncNeededTest(unittest.TestCase):
    def test_needed_when_libraries_were_never_applied(self):
        self.assertTrue(sync_needed([A], {}))

    def test_not_needed_when_nothing_is_configured_and_nothing_was_applied(self):
        self.assertFalse(sync_needed([], {}))

    def test_not_needed_when_the_same_set_was_applied_in_any_order(self):
        self.assertFalse(sync_needed([A, B], {"ids": [B, A]}))

    def test_needed_when_a_library_was_added(self):
        self.assertTrue(sync_needed([A, B], {"ids": [A]}))

    def test_needed_when_a_library_was_removed(self):
        self.assertTrue(sync_needed([A], {"ids": [A, B]}))

    def test_needed_to_remove_everything_that_was_applied(self):
        self.assertTrue(sync_needed([], {"ids": [A]}))

    def test_not_retried_for_a_set_that_already_failed(self):
        self.assertFalse(sync_needed([A, B], {"ids": [], "failed": [B, A]}))

    def test_retried_when_the_configuration_changed_since_the_failure(self):
        self.assertTrue(sync_needed([A, B, C], {"ids": [], "failed": [A, B]}))


class BuildScriptTest(unittest.TestCase):
    def test_script_adds_and_removes_the_given_ids_through_the_apps_settings(self):
        script = build_script([A, B], [C])
        self.assertIn("mxSettings.addCustomLibrary", script)
        self.assertIn("mxSettings.removeCustomLibrary", script)
        self.assertIn(json.dumps([A, B]), script)
        self.assertIn(json.dumps([C]), script)

    def test_late_loads_from_the_apps_startup_cannot_re_register_removed_libraries(self):
        script = build_script([A], [C])
        guard = script.index("mxSettings.addCustomLibrary = ")
        self.assertLess(guard, script.index("remove.forEach"))
        self.assertIn("remove.indexOf(id) >= 0", script)

    def test_ids_cannot_break_out_of_the_script(self):
        script = build_script(['x"]);alert(1);//'], [])
        self.assertIn(json.dumps(['x"]);alert(1);//']), script)


class FakeProcess:
    def __init__(self, exits_after=0):
        self.exits_after = exits_after
        self.calls = []

    def wait(self, timeout=None):
        self.calls.append(("wait", timeout))
        if self.exits_after > 0:
            self.exits_after -= 1
            raise subprocess.TimeoutExpired("flatpak", timeout)
        return 0

    def terminate(self):
        self.calls.append(("terminate",))

    def kill(self):
        self.calls.append(("kill",))


class FakeDevTools:
    def __init__(self, ready_after=0, libraries=None, page_error=None):
        self.ready_after = ready_after
        self.libraries = libraries
        self.page_error = page_error
        self.evaluated = []
        self.closed = []

    def find_free_port(self):
        return 9555

    def find_page(self, port, timeout, **kwargs):
        if self.page_error:
            raise self.page_error
        return {"webSocketDebuggerUrl": "ws://127.0.0.1:%d/devtools/page/p" % port}

    def evaluate(self, ws_url, expression, timeout=30, **kwargs):
        self.evaluated.append(expression)
        if "typeof mxSettings" in expression:
            self.ready_after -= 1
            return self.ready_after < 0
        return json.dumps(self.libraries)

    def close_browser(self, port, **kwargs):
        self.closed.append(port)


class RunSyncTest(unittest.TestCase):
    def run_it(self, devtools, process=None, add=(A, B), remove=(C,), mounts=()):
        started = []
        process = process or FakeProcess()

        def start(port):
            started.append(port)
            return process

        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        run_sync(add, remove, start, devtools=devtools, sleep=sleep, clock=lambda: clock[0])
        return started, process

    def test_registers_the_libraries_and_closes_the_app(self):
        devtools = FakeDevTools(libraries=[A, B])
        started, process = self.run_it(devtools)
        self.assertEqual(started, [9555])
        self.assertEqual(devtools.closed, [9555])
        self.assertEqual(process.calls, [("wait", 30)])
        self.assertIn(json.dumps([A, B]), devtools.evaluated[-1])

    def test_waits_until_the_apps_settings_are_available(self):
        devtools = FakeDevTools(ready_after=3, libraries=[A, B])
        self.run_it(devtools)
        probes = [e for e in devtools.evaluated if "typeof mxSettings" in e]
        self.assertEqual(len(probes), 4)

    def test_fails_when_a_library_is_missing_from_the_result_and_still_closes_the_app(self):
        devtools = FakeDevTools(libraries=[A])
        with self.assertRaises(SyncError) as caught:
            self.run_it(devtools)
        self.assertIn(B, str(caught.exception))
        self.assertEqual(devtools.closed, [9555])

    def test_fails_when_a_removed_library_is_still_registered_and_still_closes_the_app(self):
        devtools = FakeDevTools(libraries=[A, B, C])
        with self.assertRaises(SyncError) as caught:
            self.run_it(devtools)
        self.assertIn(C, str(caught.exception))
        self.assertEqual(devtools.closed, [9555])

    def test_fails_with_the_devtools_message_when_the_window_never_opens(self):
        devtools = FakeDevTools(page_error=CdpError("no window"))
        process = FakeProcess()
        with self.assertRaises(SyncError) as caught:
            self.run_it(devtools, process)
        self.assertIn("no window", str(caught.exception))
        self.assertEqual(devtools.closed, [9555])

    def test_an_app_that_ignores_the_close_request_is_terminated_then_killed(self):
        devtools = FakeDevTools(libraries=[A, B])
        process = FakeProcess(exits_after=2)
        self.run_it(devtools, process)
        self.assertEqual(process.calls, [("wait", 30), ("terminate",), ("wait", 10), ("kill",)])

    def test_gives_up_waiting_for_the_settings_after_the_deadline(self):
        devtools = FakeDevTools(ready_after=10 ** 6, libraries=[A, B])
        with self.assertRaises(SyncError):
            self.run_it(devtools)


if __name__ == "__main__":
    unittest.main()
