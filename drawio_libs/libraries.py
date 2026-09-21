"""Finds the library files named in the settings and turns them into the ids draw.io understands.

A settings entry is either a library file or a directory. A directory contributes every
library file directly inside it, loading a library that exists in several formats
(Foo.xml, Foo.drawio, Foo.drawio.xml) only once, in the most preferred format.
"""

import os
from dataclasses import dataclass, field
from urllib.parse import quote

# The desktop app itself saves libraries as .drawiolib or .xml; .drawio files carry the same content.
DEFAULT_PREFER = [".drawiolib", ".xml", ".drawio"]

# Characters JavaScript's encodeURIComponent leaves alone; draw.io builds library ids with it.
_URI_COMPONENT_SAFE = "-_.!~*'()"

# Service prefix draw.io uses for libraries stored as local files on the desktop.
_DESKTOP_SERVICE = "S"


def library_id(path):
    """Return the id draw.io uses for the desktop library stored at path."""
    return _DESKTOP_SERVICE + quote(path, safe=_URI_COMPONENT_SAFE)


def library_stem(name, extensions):
    """Return name without its trailing library extensions, or None if name is not a library file."""
    lowered = [ext.lower() for ext in extensions]
    stem = name
    stripped = False
    while True:
        ext = next((e for e in lowered if stem.lower().endswith(e) and len(stem) > len(e)), None)
        if ext is None:
            break
        stem = stem[: -len(ext)]
        stripped = True
    return stem if stripped else None


@dataclass(frozen=True)
class Library:
    path: str

    @property
    def id(self):
        return library_id(self.path)


@dataclass
class Discovery:
    libraries: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def _rank(name, prefer):
    lowered = name.lower()
    for index, ext in enumerate(prefer):
        if lowered.endswith(ext.lower()):
            return index
    return len(prefer)


def _scan_directory(directory, prefer):
    """Return the preferred file of each library in directory, sorted by name."""
    best = {}
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if name.startswith(".") or not os.path.isfile(path):
            continue
        stem = library_stem(name, prefer)
        if stem is None:
            continue
        key = (_rank(name, prefer), name)
        if stem not in best or key < best[stem][0]:
            best[stem] = (key, path)
    winners = sorted(best.items(), key=lambda item: (item[0].casefold(), item[0]))
    return [path for _, (_, path) in winners]


def discover(entries, prefer):
    """Resolve settings entries to a Discovery of libraries and warnings, keeping entry order."""
    result = Discovery()
    seen = set()
    for entry in entries:
        entry = os.path.abspath(entry)
        if os.path.isdir(entry):
            paths = _scan_directory(entry, prefer)
        elif os.path.isfile(entry):
            paths = [entry]
        else:
            result.warnings.append("library not found, skipped: " + entry)
            continue
        for path in paths:
            if path not in seen:
                seen.add(path)
                result.libraries.append(Library(path))
    return result
