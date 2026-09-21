"""Everything that touches the flatpak side: where the app keeps its data, whether it runs,
how to start it, and the desktop entry that routes menu and file-association launches
through the loader.
"""

import os
import re
import subprocess
from dataclasses import dataclass

# Written into desktop entries created by the loader so uninstall never deletes someone else's file.
ENTRY_MARKER = "X-DrawioLibraryLoader=true"

# Locations flatpak provides itself; it refuses to mount over them.
_RESERVED_DIRS = ("/app", "/usr", "/etc", "/lib", "/lib32", "/lib64", "/bin", "/sbin",
                  "/proc", "/dev", "/sys", "/run/host", "/run/flatpak")

_STATE_DIR_NAME = "drawio-library-loader"


@dataclass(frozen=True)
class AppPaths:
    config_json: str
    state_dir: str


def app_paths(app_id, home):
    """Locate the flatpak app's settings file and the directory where the loader keeps its state for it."""
    root = os.path.join(home, ".var", "app", app_id)
    return AppPaths(
        config_json=os.path.join(root, "config", "draw.io", "config.json"),
        state_dir=os.path.join(root, "data", _STATE_DIR_NAME),
    )


def run_command(cmd):
    """Run cmd and return (exit code, stdout); a missing program counts as a failure."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True)
    except OSError:
        return 127, ""
    return done.returncode, done.stdout


def is_running(app_id, runner=run_command):
    """Whether an instance of the flatpak app is running right now."""
    code, output = runner(["flatpak", "ps", "--columns=application"])
    return code == 0 and app_id in (line.strip() for line in output.splitlines())


def _is_within(path, directory):
    return path == directory or path.startswith(directory.rstrip(os.sep) + os.sep)


def sandbox_mounts(libraries, home):
    """Return (flatpak arguments, warnings) making library directories outside home visible read-only."""
    mounts, warnings, seen = [], [], set()
    for library in libraries:
        directory = os.path.dirname(library.path)
        if directory in seen or _is_within(directory, home):
            continue
        seen.add(directory)
        if ":" in directory:
            warnings.append("cannot mount a directory with ':' in its name into the sandbox: " + directory)
        elif any(_is_within(directory, reserved) for reserved in _RESERVED_DIRS):
            warnings.append("flatpak already controls this location, library may not be visible: " + directory)
        else:
            mounts.append("--filesystem=%s:ro" % directory)
    return mounts, warnings


def launch_command(app_id, mounts, args):
    """The command line that starts the app, with sandbox mounts and arguments for the app."""
    return ["flatpak", "run", *mounts, "--file-forwarding", app_id, *args]


def _quote_exec_argument(argument):
    """Quote one Exec argument per the Desktop Entry spec (quoting rule, then string escaping)."""
    quoted = re.sub(r'(["`$\\])', r"\\\1", argument)
    quoted = quoted.replace("\\", "\\\\").replace("%", "%%")
    return '"' + quoted + '"'


def loader_desktop_entry(source_text, app_id, launcher):
    """Rewrite flatpak's exported desktop entry so it starts launcher instead of the app directly."""
    exec_pattern = re.compile(r"^Exec=.*?\s" + re.escape(app_id) + r"(?=\s|$)(.*)$")
    replacement = "Exec=%s launch" % _quote_exec_argument(launcher)
    lines = []
    for line in source_text.split("\n"):
        match = exec_pattern.match(line)
        lines.append(replacement + match.group(1) if match else line)
        if line.strip() == "[Desktop Entry]":
            lines.append(ENTRY_MARKER)
    return "\n".join(lines)


def is_loader_entry(text):
    """Whether text is a desktop entry created by the loader."""
    return ENTRY_MARKER in (line.strip() for line in text.splitlines())
