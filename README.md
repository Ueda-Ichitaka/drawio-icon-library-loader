# drawio-icon-library-loader

Loads your local draw.io icon libraries into the **draw.io flatpak** (`com.jgraph.drawio.desktop`)
on every start. You list the libraries in one settings file; the loader takes care of the rest.

Works on any Linux with flatpak (Ubuntu, Arch, ...). Needs only Python 3 (developed on 3.12) and no
extra packages. It does not need root and does not modify the flatpak itself.

## Quick start

```sh
git clone --recurse-submodules <this repo> && cd drawio-icon-library-loader
./drawio-libs install                       # once
$EDITOR ~/.config/drawio-library-loader/settings.conf
```

Then start draw.io from the app menu (or run `drawio-libs launch`). If draw.io has never been
started on this machine, start it once first: the libraries are set up on the next start.

## Settings

`~/.config/drawio-library-loader/settings.conf` (created by `install` from
[settings.example.conf](settings.example.conf)):

```ini
[general]
app_id = com.jgraph.drawio.desktop
prefer = .drawiolib, .xml, .drawio

[libraries]
~/workspace/drawio-icon-library-loader/drawio-symbol-libraries
~/icons/My Special Icons.xml
```

- `[libraries]` takes one path per line. A **file** is loaded as is. A **directory** loads every
  library file directly inside it (no subdirectories, no hidden files).
- When a directory holds the same library in several formats (`Cybersecurity.xml` and
  `Cybersecurity.drawio`, or `Labs.drawio.xml`), only the first format in `prefer` is loaded.
  Files listed explicitly are never de-duplicated.
- `~` and `$VARIABLES` are expanded; relative paths are relative to the settings file.
- Libraries appear in the sidebar's library list like ones opened with File > Open Library.

## Commands

| Command | What it does |
|---|---|
| `drawio-libs install` | Copies the program to `~/.local/share/drawio-library-loader`, links `~/.local/bin/drawio-libs`, creates the settings file, and adds a menu entry that shadows the flatpak's own so menu and file-association launches go through the loader. Safe to re-run. |
| `drawio-libs launch [ARGS]` | Starts draw.io (what the menu entry runs). |
| `drawio-libs sync` | Registers the libraries with draw.io now, or retries after a failure. draw.io must be closed. |
| `drawio-libs list` | Shows the settings file, the libraries it resolves to, and whether they are registered. |
| `drawio-libs uninstall` | Removes what `install` created. Your settings file is kept. |

`--config FILE` or `$DRAWIO_LIBS_SETTINGS` select another settings file. Problems found while
launching are printed to stderr and shown as a desktop notification, and never stop draw.io from
starting.

## How it works

draw.io remembers its open libraries in its own settings and restores them on every start, but the
list can only be edited from inside the running app, and the app only reads files it has authorised.
On each launch, while draw.io is not running, the loader:

1. adds the library paths to `blessedPaths` in the app's `config.json` (the app's list of authorised files);
2. **only if the library set in your settings changed**, starts draw.io for a few seconds with a
   local DevTools port, registers and unregisters the libraries through the app's own settings
   functions, and shuts it down again (you see the window open and close once);
3. starts draw.io normally. There is no debug port during normal use.

Consequences worth knowing:

- Editing the settings file takes effect at the next launch and costs a few seconds once.
- The loader only removes libraries it added itself. Libraries you opened by hand stay untouched, so
  a library you already opened manually can appear twice if you also list it in the settings.
- A library you close in the sidebar comes back only when the configured set changes (or on
  `drawio-libs sync`).
- Libraries outside `$HOME` are mounted read-only into the sandbox for each launch, so draw.io can
  read but not save them. Keep libraries you edit inside `$HOME`.
- After a flatpak update that changes the app's menu entry, run `drawio-libs install` again to
  refresh the copy.
- A failed sync is remembered and not retried on every start; fix the cause and run
  `drawio-libs sync`.

The loader relies on internals of the draw.io desktop app (the `blessedPaths` entry in `config.json`
and the `mxSettings` functions). It was verified against draw.io 31.4.5.

## Development

```sh
python3 -m unittest discover -s . -t .
```

The unit tests need no display and no flatpak. Layout:

| File | Role |
|---|---|
| `drawio-libs` | Entry point. |
| `drawio_libs/settings.py` | Parses the settings file. |
| `drawio_libs/libraries.py` | Finds library files, de-duplicates formats, builds draw.io library ids. |
| `drawio_libs/profile.py` | Authorises library paths in the app's `config.json`. |
| `drawio_libs/sync.py` | Registers libraries in the app's settings over DevTools when the set changed. |
| `drawio_libs/cdp.py` | Minimal stdlib DevTools websocket client. |
| `drawio_libs/flatpak.py` | Flatpak paths, running check, launch command, desktop entry. |
| `drawio_libs/launch.py` | Preparation and launch planning. |
| `drawio_libs/install.py` | `install` and `uninstall`. |
| `drawio_libs/cli.py` | Command line. |
