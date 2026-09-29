# MLX-Audio Reader (browser extension)

Reads the web page you are looking at aloud, using your own local MLX-Audio server, and
highlights each sentence on the page as it is spoken. Page text never leaves your computer:
it goes only to `http://localhost:8000`.

Works in Chrome and other Chromium-based browsers (Brave, Edge, Arc).

## Install

1. Start MLX-Audio so the server is running on port 8000.
2. Open `chrome://extensions` and turn on **Developer mode** (top right).
3. Click **Load unpacked** and choose this `browser-extension` folder.
4. Optional: pin the extension from the puzzle-piece menu so the icon is always visible.

## Use

- **Toolbar icon:** open any article and click the icon, then **Read this page**. If you have
  text highlighted, the button says **Read selection** and reads just that.
- **Right-click:** on a page or on selected text, choose **Read aloud with MLX-Audio**.
- **Controls** (in the popup): pause/resume, previous/next paragraph, stop. Narration keeps
  playing if you close the popup or switch tabs. It stops when the tab closes or navigates away.
- **Settings** (popup → Settings): server address, voice model, voice, speaking style, speed.
  The default is Kokoro (voice `af_heart`); Qwen3-TTS is also selectable, with its own voices
  and a speaking-style instruction (default "calm, measured narrator tone").

## How it works

- `content.js` (with Mozilla's [Readability](https://github.com/mozilla/readability) in `vendor/`)
  finds the selection or main article, drops menus, ads and footers, and splits the text into
  sentences. It highlights the current sentence with the CSS Custom Highlight API, so the page
  itself is never modified.
- `background.js` groups sentences into chunks, tracks which sentence is being spoken, and
  drives the highlight. Chunks end at paragraph boundaries where possible, and start small
  and grow so audio begins quickly.
- `offscreen.js` is a hidden page that requests speech from `/v1/audio/speech` a few chunks
  ahead of the playback position and plays it, so long articles are not synthesized all at once.
  Each request asks the server to trim silence, cap long pauses, level the volume and match the
  pace of the narration's first chunk (see "Narrating long text in chunks" in
  `docs/guides/web-ui-api-server.md`), so the chunks sound like one continuous reading.
- Chrome closes that hidden page after 30 seconds without sound (for example a long pause).
  The extension notices and rebuilds it from the saved position when you press Play.

## Limits

- The MLX-Audio server must be running, or the popup says so.
- Chrome does not let extensions read its own pages (`chrome://…`), the Web Store, or the PDF viewer.
- Speech is generated at about real-time speed, so a moment of "Generating the next part…" can
  happen on very fast reading speeds or slow machines.
- Highlight timing inside a chunk is estimated from sentence length, so it can drift by a beat.
- The voice model still varies a little in tone from chunk to chunk; the server evens out
  volume, pace and the gaps between chunks, but cannot make the delivery identical.
- If you change the server to another address, allow it under the extension's site access.
