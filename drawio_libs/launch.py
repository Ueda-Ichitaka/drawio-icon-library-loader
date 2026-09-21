"""Prepares the draw.io profile for the configured libraries and builds the command that starts the app.

Preparation authorises the library files in the app's config and, when the configured set changed,
registers them with the app (see sync). Starting the app always wins over loading libraries: a
broken settings file or profile downgrades the launch to a plain start and is reported as a message,
never as a failure.
"""

from dataclasses import dataclass, field

from drawio_libs import flatpak
from drawio_libs.libraries import discover
from drawio_libs.profile import ProfileError, seed_blessed_paths
from drawio_libs.settings import DEFAULT_APP_ID, SettingsError, load_settings
from drawio_libs.sync import SyncError, read_state, sync_flatpak, sync_needed, write_state


@dataclass
class Preparation:
    app_id: str
    mounts: list
    ok: bool
    messages: list = field(default_factory=list)


@dataclass
class LaunchPlan:
    command: list
    messages: list = field(default_factory=list)


def _remember(state_dir, state, say):
    try:
        write_state(state_dir, state)
    except OSError as error:
        say("cannot save sync state in %s: %s" % (state_dir, error.strerror or error))


def prepare(settings_path, home, runner, sync, report, force=False):
    """Authorise and register the configured libraries; report each message as it arises.

    Unless force is set, an app that is already running is left alone and libraries are only
    registered when the configured set changed since the last successful sync.
    """
    messages = []

    def say(message):
        messages.append(message)
        report(message)

    try:
        settings = load_settings(settings_path)
    except SettingsError as error:
        say("libraries not loaded: %s" % error)
        return Preparation(DEFAULT_APP_ID, [], False, messages)

    paths = flatpak.app_paths(settings.app_id, home)
    found = discover(settings.libraries, settings.prefer)
    for warning in found.warnings:
        say(warning)
    mounts, mount_warnings = flatpak.sandbox_mounts(found.libraries, home)
    for warning in mount_warnings:
        say(warning)
    result = Preparation(settings.app_id, mounts, True, messages)

    if flatpak.is_running(settings.app_id, runner):
        if force:
            say("close draw.io before syncing libraries")
            result.ok = False
        return result

    try:
        outcome = seed_blessed_paths(paths.config_json, [lib.path for lib in found.libraries])
    except (ProfileError, OSError) as error:
        say("libraries may not load, cannot authorise them: %s" % error)
        result.ok = False
        return result
    if outcome == "no-profile":
        if found.libraries:
            say("draw.io has no profile yet; the libraries are set up on the next start")
        result.ok = False
        return result

    ids = [library.id for library in found.libraries]
    state = read_state(paths.state_dir)
    removed = [i for i in state.get("ids", []) if i not in ids]
    if (force or sync_needed(ids, state)) and (ids or removed):
        say("registering the libraries with draw.io, it opens in a few seconds")
        try:
            sync(settings.app_id, mounts, ids, removed)
        except SyncError as error:
            _remember(paths.state_dir, {"ids": state.get("ids", []), "failed": ids}, say)
            say("libraries could not be registered (%s); run `drawio-libs sync` to retry" % error)
            result.ok = False
            return result
        _remember(paths.state_dir, {"ids": ids}, say)
    return result


def plan_launch(settings_path, home, args, runner=flatpak.run_command, sync=sync_flatpak, report=lambda message: None):
    """Prepare the libraries and return the command that starts the app, plus what the user was told."""
    prepared = prepare(settings_path, home, runner, sync, report)
    return LaunchPlan(flatpak.launch_command(prepared.app_id, prepared.mounts, args), prepared.messages)
