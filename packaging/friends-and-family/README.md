# Sharing MLX-Audio with friends and family

This is the "cheap and cheerful" distribution path: no Apple Developer account, no Chrome
Web Store — two zip files you build yourself and send directly (AirDrop, Dropbox, email).
Requires an Apple Silicon Mac on the receiving end.

## What you get

Two independent zips:

1. **The app** (server + web UI) — `build_release.sh` produces
   `~/Desktop/MLX-Audio-Installer-<version>.zip`. Your friend unzips it and double-clicks
   `install.command`.
2. **The Chrome extension** — `package_extension.sh` produces
   `~/Desktop/MLX-Audio-Reader-Extension.zip`. Your friend unzips it and follows
   "EXTENSION - READ ME FIRST.txt" (Chrome's manual "Load unpacked" flow — a few clicks,
   including turning on Developer Mode, since this isn't published on the Web Store).

They're independent: the extension just talks to `http://localhost:8000`, so it works with
whichever copy of the app is running there.

## To cut a release

```
cd packaging/friends-and-family
./build_release.sh          # app: builds the UI, stages source, zips to ~/Desktop
./package_extension.sh      # extension: zips browser-extension/ to ~/Desktop
```

Send both zips to your friend, or just the app zip if they don't want the extension.

## How the app installer works (so you can debug it)

`install.command`:
1. Checks the Mac is Apple Silicon (mlx doesn't run on Intel Macs).
2. Finds a Python 3.10+ (checks Homebrew, python.org framework installs, then whatever
   `python3` is on `PATH`). If none is found, it opens the python.org download page and
   asks them to re-run after installing.
3. Copies the bundled source to `~/Library/Application Support/MLX-Audio/app`.
4. Creates a private virtual environment at `~/Library/Application Support/MLX-Audio/venv`
   (does not touch any other Python installation on their Mac).
5. `pip install`s the app into that venv with the `[all,server,desktop]` extras (`desktop`
   adds `pywebview`, which provides the native window).
6. Runs `make_app.sh`, which builds a real app bundle, `MLX-Audio.app`, in `/Applications`
   with its own name and icon (`MLX-Audio.icns`, drawn by `make_icon.py`). Opening it runs
   `python -m mlx_audio.app_window` from the private environment: a native window on the
   server. **Closing the window or pressing Cmd+Q quits the app and stops the server** (there is
   no separate Stop icon any more). A server that was already running on the port is left alone.
7. Copies `uninstall.command` to their Desktop so it's always around later, even if they
   delete the original zip/download.

If `/Applications` isn't writable (a standard, non-admin Mac account), the app goes in
`~/Applications` instead; this is checked up front so it can't fail after the long download.
The uninstaller stops only the process *listening* on the port
(`lsof -ti tcp:PORT -sTCP:LISTEN`), never other processes merely connected to it, like a
browser tab. It leaves downloaded voice models in `~/.cache/huggingface` (they are shared
with other tools) and tells the user so.

For same-machine testing, override locations with `MLXA_APP_SUPPORT`, `MLXA_APPS_DIR`,
`MLXA_PORT`, `MLXA_DESKTOP` and `MLXA_LOG_FILE` (see the top of `install.command`).

**How the window app works (`mlx_audio/app_window.py`).**
- The server is started as a child in its own process group, wrapped in a tiny shell
  watchdog that kills it within about a second if the window app disappears for *any* reason.
  This matters because Cmd+Q ends the process without giving Python a chance to clean up.
  `tests/test_app_window.py` force-kills a stand-in owner and checks the server dies.
- The server needs `--log-dir` and a home-folder working directory: from a read-only
  working directory it crashes with `Read-only file system: 'logs'`.
- Downloads (the WAV and text "Download" buttons) go through a native Save panel
  (`webview.settings["ALLOW_DOWNLOADS"]`); links that open new tabs go to the default browser.
- The menu bar, About and Quit items are renamed from code (`_brand_app`), because they take
  the name of the process's main bundle ("Python") rather than of `MLX-Audio.app`. The Dock
  icon and window title come from the app bundle itself.
- The Chrome extension talks to the same server, so it **only works while the MLX-Audio window
  is open** (it can be minimized).

**Why the older design was replaced.** It was two AppleScript apps (Start, Stop) that opened
a browser tab. Starting the server from the AppleScript app as a child made that app never
quit (it ignored `quit`, `tell me to quit`, SIGTERM and a stay-open `on reopen` handler), so
"Stop, then start again" did nothing, and it was worked around with `launchctl submit`.
Making the window app itself own the server removes all of that.

**Testing notes:** the whole install → start → stop flow was tested twice:

1. On this Mac, using a sandboxed port and fake install/`Applications` directories
   (`MLXA_APP_SUPPORT`, `MLXA_APPS_DIR`, `MLXA_PORT`, `MLXA_DESKTOP` env vars — see the top
   of `install.command`), so it never touched the real port 8000 or `/Applications` during
   development.
2. **In a real, disposable macOS VM** (via [Tart](https://tart.run), which uses Apple's own
   Virtualization framework — `brew install cirruslabs/cli/tart`), with the real default
   paths (no overrides), on a genuinely separate machine identity with its own fresh
   `$HOME`. This caught two bugs the same-machine testing above couldn't have, because it
   only ever used no-space sandbox paths and an already-"warmed up" Mac:

   - **A quoting bug:** the venv's Python path (`.../Application Support/...` — note the
     space) wasn't quoted in the generated shell command, so `nohup` tried to run
     `Application` as the command and treated the rest as arguments. Fixed by
     single-quoting the substituted paths in `make_app.sh`.
   - **A timeout that was much too short:** the very first time the freshly installed
     Python actually runs the server, macOS checks all the newly installed compiled
     libraries (scipy, mlx, numpy, etc.) for the first time, which took about **8 minutes**
     on the test VM — every run after that was instant. The launcher's retry window was
     90 seconds, so a perfectly good install looked like a failure. Raised to 10 minutes,
     and the messaging in `make_app.sh` and "READ ME FIRST.txt" now sets that
     expectation instead of looking frozen or broken.

   The VM test image (Cirrus Labs' `macos-sequoia-base`, used for CI, not a stand-in for a
   consumer Mac) already has Xcode Command Line Tools and Homebrew Python pre-installed, so
   it validated the happy path well but did **not** exercise the "no Python found" fallback
   or a from-scratch compile of `webrtcvad` without a compiler present. It also could not
   demonstrate the actual Gatekeeper "unidentified developer" click-through, since the
   install was driven over SSH/`tart exec` rather than by physically double-clicking in
   Finder — that part is still worth checking with your own eyes once on a real Mac before
   sending zips out.

## Extras installed

`pip install "...[all,server,desktop]"` — `all` covers TTS/STT/STS, `server` adds the FastAPI/
uvicorn/pypdf bits the web UI's PDF-drop feature needs, and `desktop` adds `pywebview` for the window. (The `all` extra alone is missing
`pypdf`, which looks like a small gap in the upstream project's own extras, not something
specific to this installer.)

## If you want to go further later

- **Web Store (even "Unlisted")** would make the extension a true one-click "Add to
  Chrome" with no Developer Mode banner — costs a one-time $5 Google developer fee plus a
  review. Revisit if manual installs prove annoying for people.
- **Signed & notarized app** would remove the Gatekeeper warning on the installer and the
  launcher apps entirely — needs an Apple Developer Program membership ($99/year).
- Both are meaningful, real costs (money and/or process), which is why this simpler path
  was chosen first.
