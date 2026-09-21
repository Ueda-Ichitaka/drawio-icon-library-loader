"""Writes JSON files the way the draw.io app does (tab indented), safely enough to survive a crash."""

import json
import os
import tempfile


def write_json_atomic(path, data, mode=None):
    """Write data as tab-indented JSON to path via a temp file and rename, creating parent directories."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=directory, prefix=".drawio-libs-")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(data, out, indent="\t", ensure_ascii=False)
        os.chmod(temp, mode if mode is not None else 0o644)
        os.replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.unlink(temp)
        raise
