"""End-to-end check of the Text to Speech page's PDF viewer in a REAL Chrome (not part of the
plain-assert suite).

Run:  python3.14 tests/e2e_web_pdf_viewer.py     (build the UI first: cd mlx_audio/ui && npm run build)

Nothing is spoken: a small stand-in server serves the built page, answers /v1/documents/extract-text
with the text of a PDF this script generates (plus one sentence that is NOT on any page) and
/v1/audio/speech with a few seconds of silence. Headless, muted Chrome with a throwaway profile.
Checks that dropping a PDF shows its real pages, that the spoken sentence is highlighted and the
highlight moves on, that clicking a sentence starts reading from it, and that a sentence that is not
on the pages is still read (just without a highlight).
"""

import http.server
import json
import mimetypes
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tests"))
from e2e_extension_native_host import Cdp, check, results, wait_for  # noqa: E402
from e2e_extension_pdf import make_pdf, wrap  # noqa: E402
from e2e_web_read_from_here import silent_wav  # noqa: E402

OUT = REPO / "mlx_audio" / "ui" / "out"
PORT = int(os.environ.get("E2E_WEB_PORT", "8821"))
REQUESTS = []

# One paragraph per page; the sentences are short so several share a spoken part.
P1 = ["Alpha sentence opens the first page.", "Bravo sentence follows it closely.", "Charlie sentence ends the page."]
P2 = ["Delta sentence starts the second page.", "Echo sentence is the one we will click.", "Foxtrot sentence comes after it."]
P3 = ["Golf sentence opens the last page.", "Hotel sentence closes the book."]
MISSING = "Zulu sentence is in the text but on no page at all."
TEXT = " ".join(P1) + "\n\n" + " ".join(P2) + "\n\n" + MISSING + " " + " ".join(P3)
# A long tail that is on no page, so generation takes many parts and is still running when we click.
TEXT += "\n\n" + " ".join(f"Filler sentence number {i} pads the text out." for i in range(60))
PDF = make_pdf([wrap(" ".join(P1)), wrap(" ".join(P2)), wrap(" ".join(P3))])
SENTENCES = P1 + P2 + [MISSING] + P3


class Stub(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        f = OUT / self.path.split("?")[0].lstrip("/")
        if f.is_dir():
            f = f / "index.html"
        if f.is_file():
            return self._send(200, f.read_bytes(), mimetypes.guess_type(str(f))[0] or "application/octet-stream")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/v1/audio/speech":
            REQUESTS.append(json.loads(body)["input"])
            time.sleep(2)  # like a real model: generation takes a while
            return self._send(200, silent_wav(6.0), "audio/wav")
        if self.path == "/v1/documents/extract-text":
            return self._send(200, json.dumps({"text": TEXT, "pages": 3}).encode(), "application/json")
        self._send(404, b"nf", "text/plain")


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
            pdf_path = Path(tmp) / "sample book.pdf"
            pdf_path.write_bytes(PDF)
            cdp = Cdp(Path(tmp) / "profile")
            time.sleep(2)
            page = cdp.page(f"http://localhost:{PORT}/text-to-speech/")
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1400, "height": 900, "deviceScaleFactor": 1, "mobile": False}, page)
            check("the page loaded", wait_for(lambda: cdp.js(page, "!!document.querySelector('textarea')"), 20))
            time.sleep(1)

            # ---- drop the PDF ----
            for kind in ("dragEnter", "dragOver", "drop"):
                cdp.call("Input.dispatchDragEvent", {"type": kind, "x": 400, "y": 300,
                         "data": {"items": [], "files": [str(pdf_path)], "dragOperationsMask": 1}}, page)
            check("the PDF viewer appears", wait_for(lambda: cdp.js(page, "!!document.querySelector('[data-testid=pdf-viewer]')"), 30))
            check("the text box is hidden while the pages show", cdp.js(page, "getComputedStyle(document.querySelector('textarea')).display") == "none")
            check("it shows the 3 pages", wait_for(lambda: cdp.js(page, "document.querySelectorAll('[data-page]').length") == 3, 20))
            ready = wait_for(lambda: "Click a sentence" in (cdp.js(page, "document.querySelector('[data-testid=pdf-status]').textContent") or ""), 40)
            check("the highlights get ready", ready, str(cdp.js(page, "document.querySelector('[data-testid=pdf-status]').textContent")))
            drawn = wait_for(lambda: cdp.js(page, """(() => { const c = document.querySelector('[data-page="0"] canvas')
                if (!c || !c.width) return false
                const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data
                for (let i = 0; i < d.length; i += 4) if (d[i] < 100) return true
                return false })()"""), 20)
            check("the first page is really drawn (dark text on it)", bool(drawn))

            # which sentences have a place on the pages
            # (boxes only exist for pages near the screen, so look at each page in turn)
            seen = set()
            for i in range(3):
                cdp.js(page, f"(() => {{ const v = document.querySelector('[data-testid=pdf-viewer]'); v.scrollTop = document.querySelector('[data-page=\"{i}\"]').offsetTop }})()")
                time.sleep(1.2)
                seen |= set(cdp.js(page, "[...document.querySelectorAll('[data-sentence]')].map(e => +e.dataset.sentence)") or [])
            have = sorted(seen)
            cdp.js(page, "document.querySelector('[data-testid=pdf-viewer]').scrollTop = 0")
            time.sleep(0.5)
            expected = [i for i, s in enumerate(SENTENCES) if s != MISSING]
            check("every sentence that is on a page has a clickable place", have == expected, str(have))
            check("the sentence that is not on any page has none", SENTENCES.index(MISSING) not in (have or []), str(have))

            # ---- click a sentence on page 2: reading starts there ----
            echo = SENTENCES.index("Echo sentence is the one we will click.")
            check("clicking the sentence works", cdp.js(page, f"(() => {{ const e = document.querySelector('[data-sentence=\"{echo}\"]'); if (!e) return false; e.click(); return true }})()") is True)
            check("speech was requested", wait_for(lambda: len(REQUESTS) >= 1, 30))
            first = REQUESTS[0] if REQUESTS else ""
            check("reading starts at the clicked sentence", first.startswith("Echo sentence"), first[:60])
            check("nothing before it is read", all("Alpha" not in r and "Delta" not in r for r in REQUESTS), str(REQUESTS)[:120])
            check("the clicked sentence is highlighted", wait_for(lambda: cdp.js(page, "!!document.querySelector('[data-active=\"1\"]')"), 20))
            act = cdp.js(page, "+document.querySelector('[data-active=\"1\"]').dataset.sentence")
            check("it is the clicked one", act == echo, f"{act} vs {echo}")
            check("the highlight moves on as it reads", wait_for(lambda: (cdp.js(page, "+(document.querySelector('[data-active=\"1\"]')||{dataset:{}}).dataset.sentence") or -1) > echo, 30))
            # ---- pause, then play again ----
            cdp.js(page, "document.querySelector('[data-testid=play-pause]').click()")
            check("pause stops the audio", wait_for(lambda: cdp.js(page, "document.querySelector('audio').paused") is True, 5))
            time.sleep(1)
            cdp.js(page, "document.querySelector('[data-testid=play-pause]').click()")
            check("play after pause resumes the audio", wait_for(lambda: cdp.js(page, "document.querySelector('audio').paused") is False, 5))

            # ---- click an EARLIER sentence while the rest is still being generated ----
            alpha = SENTENCES.index("Alpha sentence opens the first page.")
            n = len(REQUESTS)
            cdp.js(page, f"document.querySelector('[data-sentence=\"{alpha}\"]').click()")
            check("clicking an earlier sentence restarts reading there", wait_for(lambda: len(REQUESTS) > n and REQUESTS[n].startswith("Alpha"), 30), str(REQUESTS[n:])[:120])
            check("that sentence is highlighted", wait_for(lambda: cdp.js(page, "+(document.querySelector('[data-active=\"1\"]')||{dataset:{}}).dataset.sentence") == alpha, 20))
            cdp.js(page, "document.querySelector('[data-testid=play-pause]').click()")
            check("pause works after jumping", wait_for(lambda: cdp.js(page, "document.querySelector('audio').paused") is True, 5))
            cdp.js(page, "document.querySelector('[data-testid=play-pause]').click()")
            check("play works after jumping", wait_for(lambda: cdp.js(page, "document.querySelector('audio').paused") is False, 5))
            spoken = " ".join(REQUESTS)
            check("the sentence that is not on a page is still read", wait_for(lambda: "Zulu sentence" in " ".join(REQUESTS), 60), spoken[:120])
            cdp.js(page, "[...document.querySelectorAll('button')].find(x => x.textContent.trim() === 'Stop')?.click()")

            # ---- switching to the text and back ----
            cdp.js(page, "[...document.querySelectorAll('button')].find(x => x.textContent.trim() === 'Show text').click()")
            time.sleep(0.5)
            check("'Show text' brings back the text box with the PDF's text",
                  "Alpha sentence" in (cdp.js(page, "document.querySelector('textarea').value") or ""))
            cdp.js(page, "[...document.querySelectorAll('button')].find(x => x.textContent.trim() === 'Show PDF pages').click()")
            check("'Show PDF pages' brings the pages back", wait_for(lambda: cdp.js(page, "!!document.querySelector('[data-testid=pdf-viewer]')"), 10))
            cdp.js(page, "[...document.querySelectorAll('button')].find(x => x.textContent.trim() === 'Close PDF').click()")
            time.sleep(0.5)
            check("'Close PDF' keeps the text in the box and removes the pages",
                  cdp.js(page, "!document.querySelector('[data-testid=pdf-viewer]') && document.querySelector('textarea').value.includes('Alpha sentence')"))
    finally:
        if cdp:
            cdp.quit()
        srv.shutdown()
        srv.server_close()

    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
