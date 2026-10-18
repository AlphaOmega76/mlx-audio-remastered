# MLX-Audio Reader (browser extension)

Reads the web page you are looking at aloud, using your own local MLX-Audio server, and
highlights each sentence on the page as it is spoken. Page text never leaves your computer:
it goes only to `http://localhost:8000`.

Works in Chrome and other Chromium-based browsers (Brave, Edge, Arc).

## Install

1. Optional: run the MLX-Audio installer (`packaging/friends-and-family`) or
   `python -m mlx_audio.native_host --register` once. That lets the extension start the server
   by itself (see "Starting the server" below). Without it, start MLX-Audio yourself first.
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

## Reading PDFs

Chrome's built-in PDF viewer does not let extensions inject scripts or highlight text, so PDFs
work through the extension's own **PDF reader** page:

1. Open a PDF in Chrome and click the toolbar icon (the button says **Open PDF reader**), or use
   the right-click menu. A new tab opens, downloads the PDF, has the MLX-Audio server extract its
   text (`/v1/documents/extract-text`, text layer only: scanned PDFs have no text and say so) and
   shows it split into pages and paragraphs.
2. **Click any sentence** to start reading from there. **Read from the start** begins at the top,
   and **Jump to page** scrolls to a page. The **Speed** slider (0.5x to 2x, the same setting as on
   the options page) applies from the next part on: parts already prepared are made again at the
   new speed, and the part playing finishes as it is. The sentence being spoken is highlighted, and the
   popup's controls (and the same controls on the reader page) work as on any web page.
3. PDFs saved on your Mac (`file://`): the extension does not declare `file:///*` (the Chrome Web
   Store reviews that permission strictly), so the reader page asks you to **Choose the PDF file…**
   (or drop the file on the page) once per PDF. The same button is the fallback if a web PDF
   fails to download. The download happens on the reader *page* because Chrome does not let the
   background worker read files.

Some PDFs draw every line of text two or three times at the same spot (an outline copy under a
filled copy), which made the speech repeat every sentence. The server (`mlx_audio/pdf_text.py`)
removes those repeats before extracting. Found on a 373-page rulebook: 2,471 repeated text blocks
on 51 pages; the whole book extracts in about 13 s.

PDF text has hard line breaks and no real paragraphs, so `pdftext.js` rebuilds them from line
lengths (a short line ending a sentence ends a paragraph), joins words hyphenated across lines,
turns ligatures into letters, and drops page numbers, running headers/footers, junk characters
and dot leaders. It is a
heuristic: two-column layouts may read in an odd order, and a paragraph that ends on a nearly
full line is merged with the next one. The reader shows extracted text, not the PDF's layout.

Tests: `tests/test_pdf_reader_text.py` (needs Node) and `python3 tests/e2e_extension_pdf.py`
(real headless Chrome; speech is replaced by silence, so nothing is spoken).

## Starting the server

A Chrome extension cannot start programs, so the extension talks to a small helper through
Chrome's *native messaging* (`mlx_audio/native_host.py`, registered per browser by
`--register` in `NativeMessagingHosts/com.mlxaudio.host.json`).

- The first time you press Read (or use the right-click menu) and the server is not running,
  the extension asks the helper to start it. The popup says so; the very first start after
  installing can take several minutes.
- The helper stays connected for as long as the extension runs. When Chrome quits, or the
  extension is disabled, removed or reloaded, Chrome closes the connection and the helper stops
  the server. If the helper is force-killed, the server's own watchdog stops it within a second.
- A server that was already running (the MLX-Audio window app, or one you started) is reused
  and **never stopped** by the helper.
- The helper only accepts this extension. That is why `manifest.json` carries a `key`: it pins
  the extension's ID (`oanafgbookdcphadfbjnohnmibkemgmf`), which the registration file lists in
  `allowed_origins`. Changing the key means changing `EXTENSION_ID` in `mlx_audio/native_host.py`
  (a test checks they agree). An extension loaded before the key was added has a different ID:
  remove it in `chrome://extensions` and load it again.
- The connection also keeps the extension's background worker alive (checked in real Chrome past
  its 30 s idle timeout, so long narrations are not cut off).
- Only used when the server address is on this computer (`localhost` / `127.0.0.1`).
- Works in Chrome, Chromium, Edge, Brave and Arc; `--register` covers whichever are installed.
- Automated check in a real headless Chrome: `python3 tests/e2e_extension_native_host.py`
  (set `E2E_READ=1` to also press Read; that makes Kokoro speak).

## How it works

- `reader.html` / `reader.js` / `pdftext.js`: the PDF reader page (above). It downloads the PDF,
  asks the server for its text and loads `content.js`
  itself, which finds the sentences in its `<main>` and highlights them; clicking a sentence tells
  `content.js` where (`window.__mlxaFrom`) so the coordinator starts from that sentence.
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

- The MLX-Audio server must be running, or the helper must be registered so the extension can
  start it; otherwise the popup says it cannot reach the server.
- Chrome does not let extensions read its own pages (`chrome://…`), the Web Store, or the PDF viewer.
- Speech is generated at about real-time speed, so a moment of "Generating the next part…" can
  happen on very fast reading speeds or slow machines.
- Highlight timing inside a chunk is estimated from sentence length, so it can drift by a beat.
- The voice model still varies a little in tone from chunk to chunk; the server evens out
  volume, pace and the gaps between chunks, but cannot make the delivery identical.
- If you change the server to another address, allow it under the extension's site access.
