# MLX-Audio Remastered

**Text-to-speech on your Mac that feels like a real app.** MLX-Audio Remastered is a fork of
[MLX-Audio](https://github.com/Blaizzy/mlx-audio) by Prince Canuma: the same fast, local,
Apple-Silicon speech engine, plus a native window, a one-double-click installer, a Chrome extension
that reads web pages aloud, and long-text narration that sounds like one continuous reading.

Everything runs on your own Mac. Nothing you type or read is sent anywhere.

> **Credit where it's due.** The speech models, the server, and the vast majority of the code come
> from the original [MLX-Audio](https://github.com/Blaizzy/mlx-audio) (MIT license). This fork adds
> the pieces below on top. The original README is kept as [UPSTREAM-README.md](UPSTREAM-README.md).

## What's new in this fork

- **A native Mac app.** Open *MLX-Audio* from Applications and it appears in its own window with its
  own icon and name in the Dock and menu bar, instead of a browser tab. Closing the window (or Cmd+Q)
  quits it and shuts the server down.
- **A friendly installer.** Unzip, double-click `install.command`, done. It sets up a private Python
  environment (nothing else on your Mac is touched), creates the app, and comes with an uninstaller.
- **A Chrome extension, *MLX-Audio Reader*.** Reads the page you're looking at aloud, highlights each
  sentence as it's spoken, and **starts and stops the speech server by itself**, so there's nothing to
  open first.
- **Long text that sounds like one reading.** Text is split at paragraph boundaries and each piece is
  levelled for volume, matched for pace and joined with consistent pauses. Broken pieces (too slow or
  too fast, so garbled) are detected and regenerated automatically.
- **Kokoro as the default voice**, chosen because it sounded more natural and more consistent in
  practice; Qwen3-TTS is still available from the model menu.
- **One address for everything.** The web interface is served by the same server that does the speech,
  with PDF drag-and-drop, chunk-by-chunk playback and WAV download.

## Install (the easy way)

You need an Apple Silicon Mac (M1 or later) running a recent version of macOS (tested on macOS 15).

1. Download **MLX-Audio-Installer** from the [Releases](../../releases) page and unzip it.
2. Double-click `install.command`. macOS will warn that it's from an unidentified developer the first
   time: right-click it, choose **Open**, then **Open** again. Let it finish (a few minutes).
3. Open **MLX-Audio** from your Applications folder. The very first launch can take several minutes
   while macOS checks the newly installed files; after that it starts quickly.
4. *(Optional)* For the Chrome extension, download **MLX-Audio-Reader-Extension** from the same page and
   follow the steps in the included `EXTENSION - READ ME FIRST.txt`.

To remove everything later, use *Uninstall MLX-Audio* (the installer puts it on your Desktop).

Full details, including how the installer works and how it was tested: 
[`packaging/friends-and-family/README.md`](packaging/friends-and-family/README.md).

## Install (for developers)

```bash
git clone https://github.com/AlphaOmega76/mlx-audio-remastered.git
cd mlx-audio-remastered
python3 -m pip install -e ".[all,server,desktop]"

mlx_audio.server                      # API + web interface on http://localhost:8000
python -m mlx_audio.app_window        # the native window (starts the server for you)
python -m mlx_audio.native_host --register   # lets the Chrome extension start the server
```

The web interface is a static Next.js export; rebuild it after changing it:
`cd mlx_audio/ui && npm install && npm run build`.

Tests are plain-assert files under `tests/` (for example `tests/test_audio_polish.py`,
`tests/test_app_window.py`, `tests/test_native_host.py`).

## Good to know

- This is a personal project, tested on macOS in fresh virtual machines and on one real Mac. The
  window app's file pickers, PDF drop and microphone (Realtime speech-to-text) haven't been exercised
  by an automated check, so try those yourself.
- The Chrome extension is installed manually ("Load unpacked"); it isn't on the Chrome Web Store.
- With Kokoro, macOS may log a harmless warning about `libespeak-ng` failing to load; unusual words
  are skipped by the phonemizer's fallback. It comes from the Kokoro voice library, not this fork.
- The app saves WAV audio. Other formats (MP3, FLAC, and so on) need [ffmpeg](https://ffmpeg.org) installed; see
  [UPSTREAM-README.md](UPSTREAM-README.md#installing-ffmpeg).
- Models are downloaded from Hugging Face the first time you use them and are cached on your Mac.

## Credits and licenses

- **MLX-Audio** by Prince Canuma and contributors: [Blaizzy/mlx-audio](https://github.com/Blaizzy/mlx-audio),
  MIT license. This fork keeps that license ([LICENSE](LICENSE)) and all of its notices.
- The speech models belong to their authors and have their own licenses (see
  [CONTRIBUTIONS.md](CONTRIBUTIONS.md) and each model's page).
- The Chrome extension bundles Mozilla's [Readability](https://github.com/mozilla/readability)
  (Apache-2.0, license included in `browser-extension/vendor/`).
- The native window uses [pywebview](https://pywebview.flowrl.com) (BSD-3-Clause).
