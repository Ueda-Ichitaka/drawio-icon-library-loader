"""Command line front end: launch, sync, list, install and uninstall.

`launch` is what the desktop menu entry runs; the other commands are for the user.
"""

import os
import subprocess
import sys

from drawio_libs import flatpak
from drawio_libs.install import Dirs, InstallError, install, uninstall
from drawio_libs.launch import plan_launch, prepare
from drawio_libs.libraries import discover
from drawio_libs.settings import SettingsError, load_settings
from drawio_libs.sync import read_state, sync_flatpak, sync_needed

SETTINGS_ENV = "DRAWIO_LIBS_SETTINGS"

USAGE = """usage: drawio-libs [--config FILE] COMMAND [ARGS...]

Starts the draw.io flatpak with your local icon libraries loaded.

commands:
  launch [ARGS...]  start draw.io (ARGS go to draw.io, e.g. files to open); libraries
                    are registered first when the settings changed
  sync              register the libraries with draw.io now (draw.io must be closed)
  list              show the settings file and the libraries it resolves to
  install           set up the menu entry and the drawio-libs command
  uninstall         remove what install set up (the settings file is kept)

The settings file defaults to ~/.config/drawio-library-loader/settings.conf;
--config or $DRAWIO_LIBS_SETTINGS pick another one.
"""


def notify_user(summary, body):
    """Show a desktop notification; launching from a menu has no terminal to print to."""
    try:
        subprocess.run(["notify-send", "--app-name=drawio-libs", "--icon=dialog-warning", summary, body],
                       capture_output=True)
    except OSError:
        pass


def _exec(program, command):
    os.execvp(program, command)


def _list(settings_path, home, runner, out, err):
    try:
        settings = load_settings(settings_path)
    except SettingsError as error:
        print("drawio-libs: %s" % error, file=err)
        return 1
    paths = flatpak.app_paths(settings.app_id, home)
    found = discover(settings.libraries, settings.prefer)
    print("settings: " + settings_path, file=out)
    print("app: " + settings.app_id, file=out)
    print("running: " + ("yes" if flatpak.is_running(settings.app_id, runner) else "no"), file=out)
    print("profile: " + ("found" if os.path.exists(paths.config_json) else "not created yet"), file=out)
    ids = [library.id for library in found.libraries]
    state = read_state(paths.state_dir)
    if state.get("failed") is not None and set(state["failed"]) == set(ids):
        registered = "failed (run `drawio-libs sync`)"
    else:
        registered = "no" if sync_needed(ids, state) else "yes"
    print("registered with draw.io: " + registered, file=out)
    print("libraries (%d):" % len(found.libraries), file=out)
    for library in found.libraries:
        print("  " + library.path, file=out)
    for warning in found.warnings:
        print("warning: " + warning, file=out)
    return 0


def _sync_command(settings_path, home, runner, sync, out, err):
    def report(message):
        print("drawio-libs: " + message, file=err)

    result = prepare(settings_path, home, runner, sync, report, force=True)
    if not result.ok:
        return 1
    print("libraries are registered with draw.io", file=out)
    return 0


def _install_command(dirs, source_dir, out, err):
    try:
        lines = install(source_dir, dirs)
    except InstallError as error:
        print("drawio-libs: %s" % error, file=err)
        return 1
    for line in lines:
        print(line, file=out)
    print("Edit the settings file, then start draw.io from the menu or with `drawio-libs launch`.", file=out)
    return 0


def _uninstall_command(dirs, out):
    lines = uninstall(dirs)
    for line in lines:
        print("removed " + line, file=out)
    if not lines:
        print("nothing to remove", file=out)
    return 0


def main(argv, env=None, home=None, execute=None, runner=None, out=None, err=None,
         notify=None, source_dir=None, sync=None):
    """Run the command in argv and return the process exit code."""
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    execute = execute or _exec
    runner = runner or flatpak.run_command
    out = out or sys.stdout
    err = err or sys.stderr
    notify = notify or notify_user
    sync = sync or sync_flatpak
    source_dir = source_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs = Dirs.from_env(env, home)

    args = list(argv)
    settings_path = env.get(SETTINGS_ENV) or dirs.settings_path
    while args and (args[0] == "--config" or args[0].startswith("--config=")):
        if args[0] == "--config":
            if len(args) < 2:
                print("drawio-libs: --config needs a file", file=err)
                return 2
            settings_path = args[1]
            args = args[2:]
        else:
            settings_path = args[0].split("=", 1)[1]
            args = args[1:]

    if not args:
        print(USAGE, file=err)
        return 2
    command, rest = args[0], args[1:]
    if command in ("-h", "--help", "help"):
        print(USAGE, file=out)
        return 0
    if command == "launch":
        def report(message):
            print("drawio-libs: " + message, file=err)
            notify("draw.io libraries", message)

        plan = plan_launch(settings_path, home, rest, runner, sync, report)
        try:
            execute(plan.command[0], plan.command)
        except OSError as error:
            print("drawio-libs: cannot start %s: %s" % (plan.command[0], error.strerror or error), file=err)
            return 127
        return 0
    if command == "sync":
        return _sync_command(settings_path, home, runner, sync, out, err)
    if command == "list":
        return _list(settings_path, home, runner, out, err)
    if command == "install":
        return _install_command(dirs, source_dir, out, err)
    if command == "uninstall":
        return _uninstall_command(dirs, out)
    print("drawio-libs: unknown command '%s'\n\n%s" % (command, USAGE), file=err)
    return 2
