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
5. `pip install`s the app into that venv with the `[all,server]` extras.
6. Runs `make_launchers.sh`, which compiles two tiny AppleScript apps with `osacompile`
   (a standard macOS tool) into `/Applications`: **MLX-Audio** (starts the server, opens
   the browser once it's ready) and **Stop MLX-Audio** (kills whatever's on the port).
7. Copies `uninstall.command` to their Desktop so it's always around later, even if they
   delete the original zip/download.

If `/Applications` isn't writable (a standard, non-admin Mac account), the icons go in
`~/Applications` instead; this is checked up front so it can't fail after the long download.
The Stop app and the uninstaller stop only the process *listening* on the port
(`lsof -ti tcp:PORT -sTCP:LISTEN`), never other processes merely connected to it, like a
browser tab. The uninstaller leaves downloaded voice models in `~/.cache/huggingface` (they
are shared with other tools) and tells the user so.

For same-machine testing, override locations with `MLXA_APP_SUPPORT`, `MLXA_APPS_DIR`,
`MLXA_PORT`, `MLXA_DESKTOP` and `MLXA_LOG_FILE` (see the top of `install.command`).

**Why two separate app icons instead of one that starts and stops on quit** (like your own
Automator launcher): reliably detecting "the user quit the app" from a script running via
`do shell script` isn't something I could verify without testing on a real second Mac, so
this trades a second icon for something that's simple enough to actually test — and it was
tested end-to-end (start, reaches the server, stop, confirmed the port is freed).

**Known real bug this caught and fixed:** the server writes a small `logs/` folder
relative to its working directory unless told otherwise. Launched via `do shell script`,
the working directory isn't writable, so the server would crash on startup with
`OSError: [Errno 30] Read-only file system: 'logs'`. Fixed by passing `--log-dir` pointing
at a folder inside Application Support, and by `cd`-ing to the user's home folder first
for good measure. If you ever edit `make_launchers.sh`, keep that flag.

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
     single-quoting the substituted paths in `make_launchers.sh`.
   - **A timeout that was much too short:** the very first time the freshly installed
     Python actually runs the server, macOS checks all the newly installed compiled
     libraries (scipy, mlx, numpy, etc.) for the first time, which took about **8 minutes**
     on the test VM — every run after that was instant. The launcher's retry window was
     90 seconds, so a perfectly good install looked like a failure. Raised to 10 minutes,
     and the messaging in `make_launchers.sh` and "READ ME FIRST.txt" now sets that
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

`pip install "...[all,server]"` — `all` covers TTS/STT/STS, `server` adds the FastAPI/
uvicorn/pypdf bits the web UI's PDF-drop feature needs. (The `all` extra alone is missing
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
