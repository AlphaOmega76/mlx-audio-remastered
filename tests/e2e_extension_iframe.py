"""End-to-end check that the extension reads a page whose text lives in an iframe (e-textbooks).

Run:  python3.14 tests/e2e_extension_iframe.py

Nothing is spoken: a stand-in server answers /v1/audio/speech with silence and records the text.
Headless, muted Chrome with a throwaway profile. Checks that pressing Read on a page whose only
header is in the top frame and whose chapter is in an iframe reads the chapter, and that the
highlight lands inside the iframe.
"""

import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from e2e_extension_native_host import Cdp, check, results, wait_for  # noqa: E402
from e2e_extension_pdf import silent_wav  # noqa: E402

PORT = int(os.environ.get("E2E_IFRAME_PORT", "8819"))
SPOKEN = []
SPEEDS = []

PARAS = "".join(
    f"<p>Sentence {w} of the chapter explains an idea in plain words. It carries on for a little while longer.</p>"
    for w in ("Alpha", "Bravo", "Charlie", "Delta")
)
PAGES = {
    "/": "<html><head><title>eTextbook Test</title></head><body><header>eTextbook: TEST</header>"
         "<iframe src='/chapter.html' style='width:900px;height:500px'></iframe>"
         "<iframe style='width:0;height:0'></iframe></body></html>",
    "/chapter.html": f"<html><body><h1>Chapter Four</h1><h2>Learning Objectives</h2>{PARAS}</body></html>",
}


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
        if self.path.startswith("/v1/models"):
            return self._send(200, b'{"data": []}', "application/json")
        if self.path in PAGES:
            return self._send(200, PAGES[self.path].encode(), "text/html")
        self._send(404, b"nf", "text/plain")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/v1/audio/speech":
            req = json.loads(body)
            SPOKEN.append(req["input"])
            SPEEDS.append(req.get("speed"))
            return self._send(200, silent_wav(20.0), "audio/wav")  # still playing when the speed changes
        self._send(404, b"nf", "text/plain")


def main():
    if not os.path.exists("/Applications/Google Chrome.app"):
        print("Google Chrome is not installed here; skipping.")
        return 0
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cdp = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ext = Path(tmp) / "ext"
            shutil.copytree(REPO / "browser-extension", ext)
            m = json.loads((ext / "manifest.json").read_text())
            m["host_permissions"] += [f"http://localhost:{PORT}/*", f"http://127.0.0.1:{PORT}/*"]
            (ext / "manifest.json").write_text(json.dumps(m))
            cdp = Cdp(Path(tmp) / "profile")
            time.sleep(2)
            ext_id = cdp.call("Extensions.loadUnpacked", {"path": str(ext)})["result"]["id"]
            page = cdp.page(f"chrome-extension://{ext_id}/options.html")
            time.sleep(1)
            cdp.js(page, f"chrome.storage.local.set({{serverUrl: 'http://localhost:{PORT}'}})")

            def tabs(p):
                return cdp.js(page, f"chrome.tabs.query({{}}).then(t => t.filter(x => (x.url||'').includes({json.dumps(p)})).map(x => x.id))") or []

            cdp.call("Target.createTarget", {"url": f"http://localhost:{PORT}/"})
            check("the page tab opened", wait_for(lambda: tabs(f"localhost:{PORT}/"), 15))
            time.sleep(2)
            tab = tabs(f"localhost:{PORT}/")[0]
            cdp.js(page, f'chrome.runtime.sendMessage({{target:"background", type:"start", tabId:{tab}}})', timeout=120)
            check("speech started", wait_for(lambda: len(SPOKEN) >= 1, 30))
            first = SPOKEN[0] if SPOKEN else ""
            check("it reads the chapter in the iframe", "Alpha" in first, first[:80])
            check("it does not read only the page header", first.strip() != "eTextbook: TEST", first[:80])
            frame_hl = cdp.js(page, f"""chrome.scripting.executeScript({{target:{{tabId:{tab},allFrames:true}},
                func:()=>{{const h=CSS.highlights.get('mlxa-current');return h?[...h][0].toString():null}}}})
                .then(r=>r.map(x=>({{f:x.frameId,t:x.result}})))""")
            check("a sentence is highlighted inside the iframe", any(x["f"] != 0 and x["t"] for x in (frame_hl or [])), str(frame_hl)[:160])
            check("nothing is highlighted in the top frame", not any(x["f"] == 0 and x["t"] for x in (frame_hl or [])), str(frame_hl)[:160])

            # ---- the popup's speed slider changes the part being read right away ----
            pop = cdp.page(f"chrome-extension://{ext_id}/popup.html?tabId={tab}")
            time.sleep(2)
            check("the popup shows a speed slider at the saved speed", cdp.js(pop, "document.getElementById('speedValue').textContent") == "1.0x")
            n = len(SPOKEN)
            cdp.js(pop, """(() => { const s = document.getElementById('speed'); s.value = '1.5';
                s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change')) })()""")
            check("the label follows the slider", cdp.js(pop, "document.getElementById('speedValue').textContent") == "1.5x")
            check("the part being read is requested again at once", wait_for(lambda: any(sp == 1.5 for sp in SPEEDS[n:]), 20), str(SPEEDS[n:]))
            again = next((t for t, sp in zip(SPOKEN[n:], SPEEDS[n:]) if sp == 1.5), "")
            # (the stand-in's one-second clips move on quickly, so "the part playing" is not always the first)
            check("and it is a part that was already made at the old speed (re-made, not the next)", again in SPOKEN[:n], again[:60])
            saved = cdp.js(page, "chrome.storage.local.get('speed').then(x => x.speed)")
            check("the speed is remembered", saved == 1.5, str(saved))
            cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"stop"})')
    finally:
        if cdp:
            cdp.quit()
        srv.shutdown()
        srv.server_close()
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
