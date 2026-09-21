"""Authorises the configured library files in the draw.io desktop profile.

The app only reads files it has authorised, listed as blessedPaths in its config.json. The app
keeps that list in memory and rewrites the whole file, so it must only be changed while the app
is not running.
"""

import json
import os

from drawio_libs.jsonfile import write_json_atomic

_BLESSED_KEY = "blessedPaths"


class ProfileError(Exception):
    """The app's config file cannot be safely edited."""


def _authorised_forms(path):
    """The app authorises both the path as given and its symlink-resolved form."""
    forms = [path]
    real = os.path.realpath(path)
    if real != path:
        forms.append(real)
    return forms


def seed_blessed_paths(config_path, library_paths):
    """Authorise library_paths in the app's config file.

    Returns "updated", "unchanged", or "no-profile" when the app has not created its config
    yet (a fresh install is left alone so the app's first-run detection is not disturbed).
    """
    if not os.path.exists(config_path):
        return "no-profile"
    try:
        with open(config_path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise ProfileError("cannot read %s: %s" % (config_path, error))
    if not isinstance(data, dict):
        raise ProfileError("%s does not hold a JSON object" % config_path)
    blessed = data.get(_BLESSED_KEY, [])
    if not isinstance(blessed, list):
        raise ProfileError("%s: %s is not a list" % (config_path, _BLESSED_KEY))

    known = set(blessed)
    added = []
    for library in library_paths:
        for form in _authorised_forms(library):
            if form not in known:
                known.add(form)
                added.append(form)
    if not added:
        return "unchanged"

    data[_BLESSED_KEY] = blessed + added
    write_json_atomic(config_path, data, mode=os.stat(config_path).st_mode & 0o777)
    return "updated"
