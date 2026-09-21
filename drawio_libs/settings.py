"""Reads the user's settings file: which draw.io flatpak to start and which libraries to load into it.

The file has two sections. [general] holds key = value lines (app_id, prefer); [libraries]
holds one path per line. Lines starting with # are comments. Paths may use ~ and
environment variables; relative paths are relative to the settings file.
"""

import os
import re
from dataclasses import dataclass, field

from drawio_libs.libraries import DEFAULT_PREFER

DEFAULT_APP_ID = "com.jgraph.drawio.desktop"

# The app id ends up in filesystem paths and flatpak arguments, so it is kept to safe characters.
_APP_ID_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")

_GENERAL_KEYS = ("app_id", "prefer")


class SettingsError(Exception):
    """The settings file is missing or malformed."""


@dataclass
class Settings:
    app_id: str = DEFAULT_APP_ID
    prefer: list = field(default_factory=lambda: list(DEFAULT_PREFER))
    libraries: list = field(default_factory=list)


def _expand(entry, base_dir):
    expanded = os.path.expandvars(os.path.expanduser(entry))
    return os.path.normpath(os.path.join(base_dir, expanded))


def _parse_prefer(value, where):
    extensions = []
    for part in value.split(","):
        part = part.strip().lower()
        if part:
            extensions.append(part if part.startswith(".") else "." + part)
    if not extensions:
        raise SettingsError(where + "prefer needs at least one file extension")
    return extensions


def _parse_general(settings, line, where):
    if "=" not in line:
        raise SettingsError(where + "expected 'key = value', got: " + line)
    key, value = (part.strip() for part in line.split("=", 1))
    if key not in _GENERAL_KEYS:
        raise SettingsError(where + "unknown key '%s' (known: %s)" % (key, ", ".join(_GENERAL_KEYS)))
    if key == "app_id":
        if not _APP_ID_PATTERN.match(value):
            raise SettingsError(where + "app_id must be a flatpak application id, got: " + value)
        settings.app_id = value
    else:
        settings.prefer = _parse_prefer(value, where)


def parse_settings(text, base_dir, source="settings"):
    """Parse settings text; relative library paths resolve against base_dir."""
    settings = Settings()
    section = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = "%s:%d: " % (source, number)
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower()
            if section not in ("general", "libraries"):
                raise SettingsError(where + "unknown section [%s]" % section)
        elif section == "general":
            _parse_general(settings, line, where)
        elif section == "libraries":
            settings.libraries.append(_expand(line, base_dir))
        else:
            raise SettingsError(where + "expected a [general] or [libraries] section first")
    return settings


def load_settings(path):
    """Read and parse the settings file at path."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as error:
        raise SettingsError("cannot read settings file %s: %s" % (path, error.strerror or error))
    return parse_settings(text, os.path.dirname(os.path.abspath(path)), source=path)
