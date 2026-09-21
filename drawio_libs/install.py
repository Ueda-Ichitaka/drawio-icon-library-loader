"""Puts the loader on a user's system and takes it off again, without needing root.

Installing copies the program to the user's data directory, links it into ~/.local/bin,
creates the settings file if there is none, and writes a desktop entry that shadows the
flatpak's own so the app menu and file associations start draw.io through the loader.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass, field

from drawio_libs.flatpak import is_loader_entry, loader_desktop_entry
from drawio_libs.settings import DEFAULT_APP_ID, SettingsError, load_settings

PROGRAM = "drawio-libs"
PACKAGE = "drawio_libs"
SETTINGS_EXAMPLE = "settings.example.conf"
_INSTALL_DIR_NAME = "drawio-library-loader"


class InstallError(Exception):
    """Installation cannot proceed; nothing has been changed."""


@dataclass
class Dirs:
    home: str
    data_home: str
    config_home: str
    data_dirs: list = field(default_factory=list)
    flatpak_user_dir: str = ""
    flatpak_system_dir: str = "/var/lib/flatpak"

    @classmethod
    def from_env(cls, env, home):
        data_home = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
        config_home = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        data_dirs = [d for d in (env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
        return cls(home, data_home, config_home, data_dirs,
                   flatpak_user_dir=env.get("FLATPAK_USER_DIR") or os.path.join(data_home, "flatpak"),
                   flatpak_system_dir=env.get("FLATPAK_SYSTEM_DIR") or "/var/lib/flatpak")

    @property
    def install_dir(self):
        return os.path.join(self.data_home, _INSTALL_DIR_NAME)

    @property
    def link(self):
        return os.path.join(self.home, ".local", "bin", PROGRAM)

    @property
    def settings_path(self):
        return os.path.join(self.config_home, _INSTALL_DIR_NAME, "settings.conf")

    @property
    def applications_dir(self):
        return os.path.join(self.data_home, "applications")

    def flatpak_export_dirs(self):
        return [os.path.join(self.flatpak_user_dir, "exports", "share"),
                os.path.join(self.flatpak_system_dir, "exports", "share"), *self.data_dirs]


def update_desktop_database(directory):
    """Refresh the desktop environment's cache of desktop entries; harmless if the tool is absent."""
    try:
        subprocess.run(["update-desktop-database", directory], capture_output=True)
    except OSError:
        pass


def _app_id(dirs):
    if not os.path.exists(dirs.settings_path):
        return DEFAULT_APP_ID
    try:
        return load_settings(dirs.settings_path).app_id
    except SettingsError as error:
        raise InstallError(str(error))


def _find_exported_entry(dirs, app_id):
    for share in dirs.flatpak_export_dirs():
        candidate = os.path.join(share, "applications", app_id + ".desktop")
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as handle:
                return handle.read()
    raise InstallError("flatpak app %s is not installed (no exported desktop entry found)" % app_id)


def _copy_program(source_dir, install_dir):
    if os.path.realpath(source_dir) == os.path.realpath(install_dir):
        return
    os.makedirs(install_dir, exist_ok=True)
    for name in (PROGRAM, SETTINGS_EXAMPLE):
        shutil.copy2(os.path.join(source_dir, name), os.path.join(install_dir, name))
    package = os.path.join(install_dir, PACKAGE)
    shutil.rmtree(package, ignore_errors=True)
    shutil.copytree(os.path.join(source_dir, PACKAGE), package,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _replace_link(link, target):
    os.makedirs(os.path.dirname(link), exist_ok=True)
    if os.path.lexists(link):
        if not os.path.islink(link) or os.path.realpath(link) != os.path.realpath(target):
            raise InstallError("%s already exists and is not the loader" % link)
        return
    os.symlink(target, link)


def install(source_dir, dirs, update_database=update_desktop_database):
    """Install the loader from source_dir; returns human-readable lines describing what was done."""
    app_id = _app_id(dirs)
    entry_text = _find_exported_entry(dirs, app_id)
    entry_path = os.path.join(dirs.applications_dir, app_id + ".desktop")
    if os.path.exists(entry_path):
        with open(entry_path, encoding="utf-8") as handle:
            if not is_loader_entry(handle.read()):
                raise InstallError("%s already exists and was not created by the loader; "
                                   "move it away first" % entry_path)
    installed = os.path.join(dirs.install_dir, PROGRAM)
    if os.path.lexists(dirs.link) and (not os.path.islink(dirs.link)
                                       or os.path.realpath(dirs.link) != os.path.realpath(installed)):
        raise InstallError("%s already exists and is not the loader" % dirs.link)

    done = []
    _copy_program(source_dir, dirs.install_dir)
    done.append("program: " + dirs.install_dir)
    _replace_link(dirs.link, installed)
    done.append("command: " + dirs.link)

    if not os.path.exists(dirs.settings_path):
        os.makedirs(os.path.dirname(dirs.settings_path), exist_ok=True)
        shutil.copyfile(os.path.join(source_dir, SETTINGS_EXAMPLE), dirs.settings_path)
        done.append("settings (edit this): " + dirs.settings_path)
    else:
        done.append("settings (kept): " + dirs.settings_path)

    os.makedirs(dirs.applications_dir, exist_ok=True)
    with open(entry_path, "w", encoding="utf-8") as handle:
        handle.write(loader_desktop_entry(entry_text, app_id, dirs.link))
    update_database(dirs.applications_dir)
    done.append("menu entry: " + entry_path)
    return done


def uninstall(dirs, update_database=update_desktop_database):
    """Remove what install created, except the settings file; returns lines describing what was removed."""
    removed = []
    if os.path.isdir(dirs.applications_dir):
        for name in sorted(os.listdir(dirs.applications_dir)):
            path = os.path.join(dirs.applications_dir, name)
            if name.endswith(".desktop") and os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as handle:
                    ours = is_loader_entry(handle.read())
                if ours:
                    os.remove(path)
                    removed.append("menu entry: " + path)
        update_database(dirs.applications_dir)
    installed = os.path.join(dirs.install_dir, PROGRAM)
    if os.path.islink(dirs.link) and os.path.realpath(dirs.link) == os.path.realpath(installed):
        os.remove(dirs.link)
        removed.append("command: " + dirs.link)
    if os.path.isdir(dirs.install_dir):
        shutil.rmtree(dirs.install_dir)
        removed.append("program: " + dirs.install_dir)
    return removed
