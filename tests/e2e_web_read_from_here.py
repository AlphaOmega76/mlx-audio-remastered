"""End-to-end check of the Text to Speech page's "Read from here" button in a REAL Chrome (not part of
the plain-assert suite).

Run:  python3.14 tests/e2e_web_read_from_here.py     (build the UI first: cd mlx_audio/ui && npm run build)

Nothing is spoken: a small stand-in server serves the built page and answers /v1/audio/speech with a
second of silence, recording the text it was asked to say. Headless, muted Chrome with a throwaway
profile; your own Chrome is not touched. Checks that:

  * with the cursor in the middle of a sentence, "Read from here" reads from the start of THAT sentence
    to the end of the text (nothing before it is sent),
  * with a passage selected the button says "Read selection" and reads only that passage,
  * "Generate" still reads everything.
"""

import http.server
import io
import json
import mimetypes
import os
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
from e2e_extension_native_host import Cdp, check, results, wait_for  # noqa: E402

OUT = REPO / "mlx_audio" / "ui" / "out"
PORT = int(os.environ.get("E2E_WEB_PORT", "8818"))
REQUESTS = []


def silent_wav(seconds=1.0, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(rate * seconds))
    return buf.getvalue()


class Stub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        f = OUT / path.lstrip("/")
        if f.is_dir():
            f = f / "index.html"
        if f.is_file():
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(f))[0] or "application/octet-stream")
        else:
            body = b"not found"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/v1/audio/speech":
            REQUESTS.append(json.loads(body)["input"])
            wav = silent_wav()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav)))
            self.end_headers()
            self.wfile.write(wav)
        else:
            self.send_response(404)
            self.end_headers()


# Four paragraphs with a marker word each; long enough to be split into several parts.
FILLER = "The tide came in over the flat grey sand and the gulls complained about it. "
TEXT = (
    "Alpha sentence opens the book and sets the scene by the sea. " + FILLER * 6 + "\n\n"
    "Bravo sentence starts the second paragraph. " + FILLER * 6 + "\n\n"
    "Charlie sentence begins the third paragraph and is the one the cursor will sit in. "
    "Delta sentence follows it closely. " + FILLER * 6 + "\n\n"
    "Echo sentence ends the whole book on a calm note by the harbour wall."
)

JS_SET_TEXT = """(() => {
  const ta = document.querySelector('textarea')
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(ta, %s)
  ta.dispatchEvent(new Event('input', { bubbles: true }))
})()"""

JS_SELECT = """(() => {
  const ta = document.querySelector('textarea')
  ta.focus()
  const a = ta.value.indexOf(%s)
  ta.setSelectionRange(a + %d, a + %d + %d)
})()"""


def select(cdp, page, needle, offset=0, length=0):
    """Select `length` characters (0 = just a cursor) starting `offset` characters into `needle`."""
    cdp.js(page, JS_SELECT % (json.dumps(needle), offset, offset, length))
    # what the user's mouse release does after dragging a selection
    cdp.js(page, "document.querySelector('textarea').dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))")

JS_CLICK = """(() => {
  const b = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === %s)
  if (!b) return false
  b.click(); return true
})()"""

JS_LABELS = "[...document.querySelectorAll('button')].map(b => b.textContent.trim()).filter(t => /^(Read|Generate|Stop)/.test(t)).join('|')"


def main():
    if not os.path.exists("/Applications/Google Chrome.app"):
        print("Google Chrome is not installed here; skipping.")
        return 0
    if not (OUT / "text-to-speech" / "index.html").exists():
        print("The UI is not built: run  cd mlx_audio/ui && npm run build")
        return 1

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cdp = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cdp = Cdp(Path(tmp) / "profile")
            time.sleep(2)
            page = cdp.page(f"http://localhost:{PORT}/text-to-speech/")
            check("the page loaded", wait_for(lambda: cdp.js(page, "!!document.querySelector('textarea')"), 20))
            time.sleep(1)
            cdp.js(page, JS_SET_TEXT % json.dumps(TEXT))
            time.sleep(0.5)

            def idle():
                labels = cdp.js(page, JS_LABELS) or ""
                return "Generate" in labels and "Stop" not in labels

            # ---- cursor in the middle of the "Charlie" sentence ----
            select(cdp, page, "the one the cursor", 8)  # a cursor in the middle of that sentence
            time.sleep(0.5)
            labels = cdp.js(page, JS_LABELS)
            check("with only a cursor the button says 'Read from here'", "Read from here" in labels, labels)
            check("the button is clickable", cdp.js(page, JS_CLICK % json.dumps("Read from here")) is True)
            check("speech was requested", wait_for(lambda: len(REQUESTS) >= 1, 30))
            first = REQUESTS[0] if REQUESTS else ""
            check("it starts at the beginning of the cursor's sentence", first.startswith("Charlie sentence begins"), first[:70])
            check("nothing before that sentence is read", all("Alpha" not in r and "Bravo" not in r for r in REQUESTS), str(len(REQUESTS)))
            wait_for(idle, 60)
            spoken = " ".join(REQUESTS)
            check("it reads on to the end of the text", "Echo sentence ends the whole book" in spoken, spoken[-60:])
            msg = cdp.js(page, "document.body.innerText")
            check("the page says where it started", "Charlie sentence" in msg and "Reading from" in msg, "")

            # ---- a selected passage ----
            REQUESTS.clear()
            passage = "Bravo sentence starts the second paragraph."
            select(cdp, page, passage, 0, len(passage))
            time.sleep(0.5)
            labels = cdp.js(page, JS_LABELS)
            check("with a selection the button says 'Read selection'", "Read selection" in labels, labels)
            cdp.js(page, JS_CLICK % json.dumps("Read selection"))
            wait_for(lambda: len(REQUESTS) >= 1, 30)
            wait_for(idle, 60)
            check("only the selected passage is read", REQUESTS == [passage], str(REQUESTS)[:160])

            # ---- Generate reads everything ----
            REQUESTS.clear()
            cdp.js(page, JS_CLICK % json.dumps("Generate"))
            wait_for(lambda: len(REQUESTS) >= 1, 30)
            check("Generate still starts from the top", bool(REQUESTS) and REQUESTS[0].startswith("Alpha sentence"), (REQUESTS or [""])[0][:60])
            cdp.js(page, JS_CLICK % json.dumps("Stop"))
    finally:
        if cdp:
            cdp.quit()
        srv.shutdown()
        srv.server_close()

    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
