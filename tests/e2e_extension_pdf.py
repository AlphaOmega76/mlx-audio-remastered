"""End-to-end check of the extension's PDF reader in a REAL Chrome (not part of the plain-assert suite).

Run:  python3.14 tests/e2e_extension_pdf.py

Nothing is spoken: a small stand-in server answers /v1/audio/speech with a second of silence (and
records the text it was asked to say), while PDF text extraction goes to the real MLX-Audio server
(started on a spare port; it loads no speech model). Headless, muted Chrome with a throwaway
profile; your own Chrome is not touched. Checks that:

  * pressing Read on a PDF tab opens the reader page (and does not start speaking),
  * the reader shows the PDF's pages and paragraphs, rebuilt from the PDF's line-broken text,
  * clicking a sentence starts reading from that sentence (the first text sent for speech begins
    there, and the highlight lands on it),
  * "Read from the start" begins at the top,
  * the toolbar popup labels its button correctly on a PDF tab and on the reader tab,
  * a PDF with no text gives a clear message and opens no reader.
"""

import http.server
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from e2e_extension_native_host import Cdp, check, results, wait_for  # noqa: E402
from mlx_audio import native_host as nh  # noqa: E402

STUB_PORT = int(os.environ.get("E2E_PDF_PORT", "8817"))
REAL_PORT = STUB_PORT - 1  # the real server, used only for text extraction

SPEECH_REQUESTS = []


def silent_wav(seconds=1.0, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(rate * seconds))
    return buf.getvalue()


def make_pdf(pages):
    """pages: a list of pages, each a list of text lines. Returns PDF bytes (with a text layer)."""
    objs = {}
    n_pages = len(pages)
    kids = []
    next_id = 3 + 1  # 1 catalog, 2 pages, 3 font
    page_ids = []
    for lines in pages:
        content_id, page_id = next_id, next_id + 1
        next_id += 2
        ops = ["BT /F1 11 Tf 14 TL 50 740 Td"]
        for line in lines:
            ops.append("(%s) '" % line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))
        ops.append("ET")
        stream = "\n".join(ops).encode()
        objs[content_id] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        objs[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 3 0 R >> >> >>" % content_id
        )
        page_ids.append(page_id)
        kids.append(b"%d 0 R" % page_id)
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count %d >>" % n_pages
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Roman >>"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = {}
    for i in sorted(objs):
        offsets[i] = out.tell()
        out.write(b"%d 0 obj\n" % i + objs[i] + b"\nendobj\n")
    xref = out.tell()
    size = max(objs) + 1
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % size)
    for i in range(1, size):
        out.write(b"%010d 00000 n \n" % offsets[i])
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref))
    return out.getvalue()


def wrap(text, width=68):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


PAGES = [
    ["Chapter One"],
    [],
    [],
]
P1A = ("Alpha sentence opens the first paragraph of the book. It goes on to say a few more words "
       "about the harbour and the grey morning light. Another sentence follows right behind it.")
P1B = ("Bravo paragraph begins here and talks about the fishing boats. They rocked gently at their "
       "moorings while the gulls wheeled overhead and cried.")
P2A = ("Charlie paragraph is on the second page of the book. It describes the long walk up the hill "
       "to the lighthouse. Delta sentence is the second sentence of that paragraph and it is the one "
       "we will click on in the test. Echo ends it.")
P2B = ("Foxtrot paragraph closes the second page with a short thought about the evening that was "
       "coming in over the water.")
P3A = ("Golf paragraph is the whole of the third page. Hotel sentence follows it and ends the book.")


def build_pdf():
    def para(lines, text):
        return lines + wrap(text) + [""]

    # a running header on every page, as many real PDFs have
    head = ["The Lighthouse Book", ""]
    p1 = head + ["Chapter One", ""]
    p1 = para(p1, P1A)
    p1 = para(p1, P1B) + ["1"]
    p2 = para(head, P2A)
    p2 = para(p2, P2B) + ["2"]
    p3 = para(head, P3A) + ["3"]
    return make_pdf([p1, p2, p3])


class Stub(http.server.BaseHTTPRequestHandler):
    pdfs = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/v1/models"):
            return self._send(200, b'{"data": []}')
        if self.path in self.pdfs:
            return self._send(200, self.pdfs[self.path], "application/pdf")
        self._send(404, b"not found")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/v1/audio/speech":
            SPEECH_REQUESTS.append(json.loads(body)["input"])
            return self._send(200, silent_wav(), "audio/wav")
        if self.path == "/v1/documents/extract-text":  # forwarded to the real server
            req = urllib.request.Request(
                f"http://localhost:{REAL_PORT}{self.path}", data=body,
                headers={"Content-Type": self.headers["Content-Type"]},
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return self._send(r.status, r.read())
            except urllib.error.HTTPError as e:
                return self._send(e.code, e.read())
        self._send(404, b"not found")


def main():
    if not os.path.exists("/Applications/Google Chrome.app"):
        print("Google Chrome is not installed here; skipping.")
        return 0
    from pypdf import PdfWriter

    blank = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.write(blank)
    Stub.pdfs = {"/book.pdf": build_pdf(), "/blank.pdf": blank.getvalue()}

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", STUB_PORT), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    real = subprocess.Popen(
        [sys.executable, "-m", "mlx_audio.server", "--port", str(REAL_PORT), "--log-dir", tempfile.mkdtemp()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=tempfile.mkdtemp(),
        env={**os.environ, "PYTHONPATH": str(REPO)},
    )
    cdp = None
    try:
        def real_up():
            try:
                urllib.request.urlopen(f"http://localhost:{REAL_PORT}/v1/models", timeout=1)
                return True
            except Exception:
                return False

        check("the real server (for text extraction) started", wait_for(real_up, 90))

        with tempfile.TemporaryDirectory() as tmp:
            # Automation cannot grant "activeTab", so use a copy of the extension that may use the stand-in server.
            ext = Path(tmp) / "ext"
            shutil.copytree(REPO / "browser-extension", ext)
            manifest = json.loads((ext / "manifest.json").read_text())
            manifest["host_permissions"] += [f"http://localhost:{STUB_PORT}/*"]
            (ext / "manifest.json").write_text(json.dumps(manifest))

            cdp = Cdp(Path(tmp) / "profile")
            time.sleep(2)
            ext_id = cdp.call("Extensions.loadUnpacked", {"path": str(ext)})["result"]["id"]
            page = cdp.page(f"chrome-extension://{ext_id}/options.html")
            time.sleep(1)
            cdp.js(page, f"chrome.storage.local.set({{serverUrl: 'http://localhost:{STUB_PORT}'}})")

            def tabs(pattern):
                return cdp.js(page, f"chrome.tabs.query({{}}).then(t => t.filter(x => (x.url||'').includes({json.dumps(pattern)})).map(x => x.id))") or []

            # ---- a PDF with text ----
            cdp.call("Target.createTarget", {"url": f"http://localhost:{STUB_PORT}/book.pdf"})
            check("the PDF tab opened", wait_for(lambda: tabs("/book.pdf"), 15))
            time.sleep(3)  # let Chrome's PDF viewer load
            pdf_tab = tabs("/book.pdf")[0]
            probe = cdp.js(page, f"chrome.scripting.executeScript({{target:{{tabId:{pdf_tab}}}, func:()=>document.contentType}}).then(r=>r[0].result)")
            check("Chrome shows it in its PDF viewer", probe == "application/pdf", str(probe))

            state = cdp.js(page, f'chrome.runtime.sendMessage({{target:"background", type:"start", tabId:{pdf_tab}}})', timeout=120)
            check("pressing Read on a PDF does not fail", state and state.get("status") in ("idle", None), str(state)[:200])
            check("the reader page opened", wait_for(lambda: tabs("reader.html"), 20))
            check("nothing was spoken yet", SPEECH_REQUESTS == [], str(SPEECH_REQUESTS)[:100])

            reader_tab = tabs("reader.html")[0]
            targets = cdp.call("Target.getTargets")["result"]["targetInfos"]
            tid = next(t["targetId"] for t in targets if "reader.html" in t["url"])
            rd = cdp.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["result"]["sessionId"]
            time.sleep(2)

            info = cdp.js(rd, """JSON.stringify({
                pages: document.querySelectorAll('.page').length,
                paras: [...document.querySelectorAll('.page')].map(p => p.querySelectorAll('p').length),
                text: document.getElementById('doc').innerText,
                title: document.getElementById('title').textContent })""")
            info = json.loads(info) if isinstance(info, str) else {}
            check("the reader shows 3 pages", info.get("pages") == 3, str(info.get("pages")))
            # page 1: heading + 2 paragraphs; page 2: 2 paragraphs; page 3: 1 paragraph
            check("paragraphs were rebuilt from the line-broken PDF text", info.get("paras") == [3, 2, 1], str(info.get("paras")))
            check("the running header was dropped", "Lighthouse Book" not in info.get("text", ""), "")
            check("page numbers in the PDF were dropped", "\n1\n" not in "\n" + info.get("text", "") + "\n", "")
            check("the title shows", bool(info.get("title")), info.get("title", ""))

            # ---- the toolbar popup knows what it is looking at ----
            def popup_label(tab_id):
                pop = cdp.page(f"chrome-extension://{ext_id}/popup.html?tabId={tab_id}")
                time.sleep(2)
                return cdp.js(pop, "document.getElementById('read').textContent")

            label = popup_label(pdf_tab)
            check("the popup offers to open the PDF reader on a PDF tab", label == "Open PDF reader", str(label))
            label = popup_label(reader_tab)
            check("and offers to read from the start on the reader tab", label == "Read from the start", str(label))

            # ---- click a sentence: reading begins there ----
            pos = cdp.js(rd, """(() => {
                const walker = document.createTreeWalker(document.getElementById('doc'), NodeFilter.SHOW_TEXT)
                let n
                while ((n = walker.nextNode())) {
                  const i = n.nodeValue.indexOf('Delta')
                  if (i >= 0) {
                    const r = document.createRange(); r.setStart(n, i + 2); r.setEnd(n, i + 3)
                    r.startContainer.parentElement.scrollIntoView({block: 'center'})
                    const b = r.getBoundingClientRect()
                    return JSON.stringify({x: b.x + b.width / 2, y: b.y + b.height / 2})
                  }
                }
                return null })()""")
            if not pos:
                # "Delta" may wrap onto a line of its own text node; fall back to searching the page text
                check("found the sentence to click", False, "Delta not found in a single text node")
            else:
                pos = json.loads(pos)
                time.sleep(0.5)
                for typ in ("mousePressed", "mouseReleased"):
                    cdp.call("Input.dispatchMouseEvent", {"type": typ, "x": pos["x"], "y": pos["y"], "button": "left", "clickCount": 1}, rd)
                got = wait_for(lambda: len(SPEECH_REQUESTS) >= 1, 30)
                check("clicking a sentence started speech", got)
                first = SPEECH_REQUESTS[0] if SPEECH_REQUESTS else ""
                check("it starts at the clicked sentence", first.startswith("Delta sentence"), first[:80])
                check("it does not include earlier text", "Alpha" not in first and "Charlie" not in first, first[:80])
                wait_for(lambda: len(SPEECH_REQUESTS) >= 2, 20)
                spoken = " ".join(SPEECH_REQUESTS)
                check("later text follows", "Hotel" in spoken or "Foxtrot" in spoken, spoken[-80:])
                hl = cdp.js(rd, "(() => { const h = CSS.highlights.get('mlxa-current'); return h ? [...h][0].toString() : null })()")
                check("a sentence is highlighted on the reader page", bool(hl), str(hl)[:80])

                # ---- start from the top ----
                cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"stop"})')
                SPEECH_REQUESTS.clear()
                cdp.js(rd, "document.getElementById('top').click()")
                wait_for(lambda: len(SPEECH_REQUESTS) >= 1, 30)
                first = SPEECH_REQUESTS[0] if SPEECH_REQUESTS else ""
                check("'Read from the start' begins at the top", first.startswith("Chapter One"), first[:80])
                cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"stop"})')

            # ---- a PDF with no text ----
            cdp.call("Target.createTarget", {"url": f"http://localhost:{STUB_PORT}/blank.pdf"})
            wait_for(lambda: tabs("/blank.pdf"), 15)
            time.sleep(3)
            blank_tab = tabs("/blank.pdf")[0]
            before = len(tabs("reader.html"))
            state = cdp.js(page, f'chrome.runtime.sendMessage({{target:"background", type:"start", tabId:{blank_tab}}})', timeout=120)
            check("a PDF with no text gives a clear message", state and state.get("status") == "error" and "No text" in (state.get("error") or ""), str(state)[:200])
            check("and opens no reader", len(tabs("reader.html")) == before)
    finally:
        if cdp:
            cdp.quit()
        srv.shutdown()
        srv.server_close()
        real.terminate()
        try:
            real.wait(timeout=10)
        except subprocess.TimeoutExpired:
            real.kill()

    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
