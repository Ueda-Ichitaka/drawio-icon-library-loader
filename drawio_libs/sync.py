"""Registers the configured libraries in draw.io's own settings so the app loads them natively.

draw.io keeps its list of open libraries in its settings and restores it on every start, but the
list can only be edited from inside the running app. A sync therefore starts the app for a few
seconds with a DevTools port, calls the app's own settings functions, and shuts it down again;
normal use never has a debug port open. A state file remembers which libraries were applied so a
sync only happens when the configured set changes.
"""

import json
import os
import subprocess
import time

from drawio_libs import cdp, flatpak
from drawio_libs.jsonfile import write_json_atomic

_STATE_FILE = "state.json"
_PAGE_TIMEOUT = 90
_READY_TIMEOUT = 60
_CLOSE_WAIT = 30
_TERMINATE_WAIT = 10

_READY_SCRIPT = 'typeof mxSettings === "object" && mxSettings.settings != null'


class SyncError(Exception):
    """The libraries could not be registered with the app."""


def read_state(state_dir):
    """Return the saved sync state, or an empty state if there is none or it is unreadable."""
    try:
        with open(os.path.join(state_dir, _STATE_FILE), encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def write_state(state_dir, state):
    write_json_atomic(os.path.join(state_dir, _STATE_FILE), state)


def sync_needed(desired_ids, state):
    """Whether the configured libraries differ from what was last applied (and did not already fail)."""
    desired = set(desired_ids)
    if state.get("failed") is not None and set(state["failed"]) == desired:
        return False
    return desired != set(state.get("ids", []))


def build_script(add_ids, remove_ids):
    """JavaScript that edits the app's saved library list and returns the resulting list as JSON.

    The app registers each library in its saved list once it finished loading at startup, which
    can happen after this script ran. Registration of the ids being removed is switched off first
    so a late load cannot bring them back; the app is closed again right after the sync.
    """
    return ("(function(add, remove) {"
            " mxSettings.load();"
            " var register = mxSettings.addCustomLibrary;"
            " mxSettings.addCustomLibrary = function(id) {"
            " if (remove.indexOf(id) >= 0) { return; }"
            " return register.apply(mxSettings, arguments); };"
            " remove.forEach(function(id) { mxSettings.removeCustomLibrary(id); });"
            " add.forEach(function(id) { mxSettings.addCustomLibrary(id); });"
            " return JSON.stringify(mxSettings.getCustomLibraries()); })(%s, %s)"
            % (json.dumps(list(add_ids)), json.dumps(list(remove_ids))))


def _stop(process):
    try:
        process.wait(_CLOSE_WAIT)
        return
    except subprocess.TimeoutExpired:
        process.terminate()
    try:
        process.wait(_TERMINATE_WAIT)
    except subprocess.TimeoutExpired:
        process.kill()


def run_sync(add_ids, remove_ids, start, devtools=cdp, sleep=time.sleep, clock=time.monotonic):
    """Start the app via start(port), apply the library changes and shut the app down again."""
    port = devtools.find_free_port()
    process = start(port)
    try:
        try:
            ws_url = devtools.find_page(port, timeout=_PAGE_TIMEOUT)["webSocketDebuggerUrl"]
            deadline = clock() + _READY_TIMEOUT
            while devtools.evaluate(ws_url, _READY_SCRIPT) is not True:
                if clock() > deadline:
                    raise SyncError("draw.io's settings did not become available")
                sleep(0.5)
            applied = json.loads(devtools.evaluate(ws_url, build_script(add_ids, remove_ids)))
        except cdp.CdpError as error:
            raise SyncError(str(error))
        missing = [i for i in add_ids if i not in applied]
        if missing:
            raise SyncError("draw.io did not register: " + ", ".join(missing))
        lingering = [i for i in remove_ids if i in applied]
        if lingering:
            raise SyncError("draw.io did not unregister: " + ", ".join(lingering))
    finally:
        devtools.close_browser(port)
        _stop(process)


def sync_flatpak(app_id, mounts, add_ids, remove_ids):
    """Register and unregister libraries in the flatpak app, starting it briefly with a DevTools port."""
    def start(port):
        command = flatpak.launch_command(app_id, mounts, ["--remote-debugging-port=%d" % port])
        return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    run_sync(add_ids, remove_ids, start)
