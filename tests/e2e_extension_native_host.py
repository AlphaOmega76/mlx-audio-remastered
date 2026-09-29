"""End-to-end check of the extension + native helper in a REAL Chrome (not part of the plain-assert suite).

Run:  python3.14 tests/e2e_extension_native_host.py

It launches a separate, headless, muted Chrome with a throwaway profile (your own Chrome is not
touched), loads browser-extension/, points it at a spare port (default 8815) and checks that:

  * the extension gets the pinned ID the helper is registered for,
  * with the helper registered, the extension can start the real MLX-Audio server on demand,
  * the connection keeps the extension's service worker (and so the server) alive past Chrome's
    ~30 s idle timeout,
  * removing the extension stops the server, and so does quitting Chrome,
  * without the helper registered, the extension reports that it cannot start the server.

Branded Chrome ignores --load-extension, so the extension is loaded over the DevTools pipe with
Extensions.loadUnpacked (fd 3 = commands in, fd 4 = replies out, NUL-terminated JSON).
"""

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from mlx_audio import native_host as nh  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = int(os.environ.get("E2E_PORT", "8815"))
KEEPALIVE_WAIT_S = int(os.environ.get("E2E_KEEPALIVE_S", "75"))
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""), flush=True)


def up():
    try:
        urllib.request.urlopen(f"http://localhost:{PORT}/v1/models", timeout=1)
        return True
    except Exception:
        return False


def wait_for(cond, timeout, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


class Cdp:
    def __init__(self, udd):
        c2b_r, c2b_w = os.pipe()
        b2c_r, b2c_w = os.pipe()

        def child():
            os.dup2(c2b_r, 3)
            os.dup2(b2c_w, 4)

        self.proc = subprocess.Popen(
            [CHROME, "--headless", f"--user-data-dir={udd}", "--remote-debugging-pipe",
             "--enable-unsafe-extension-debugging", "--mute-audio", "--autoplay-policy=no-user-gesture-required", "--no-first-run",
             "--no-default-browser-check", "about:blank"],
            preexec_fn=child, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            pass_fds=(3, 4),  # keep the descriptors preexec_fn duplicates onto 3 and 4 (closed otherwise)
        )
        os.close(c2b_r)
        os.close(b2c_w)
        self.w = os.fdopen(c2b_w, "wb", buffering=0)
        self.r = os.fdopen(b2c_r, "rb", buffering=0)
        self.n = 0
        self.replies = {}
        self.events = []  # DevTools events, for debugging
        self.cv = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        buf = b""
        while True:
            chunk = self.r.read(65536)
            if not chunk:
                return
            buf += chunk
            while b"\0" in buf:
                raw, buf = buf.split(b"\0", 1)
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if "method" in msg:
                    self.events.append(msg)
                if "id" in msg:
                    with self.cv:
                        self.replies[msg["id"]] = msg
                        self.cv.notify_all()

    def call(self, method, params=None, session=None, timeout=60):
        self.n += 1
        i = self.n
        msg = {"id": i, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        self.w.write(json.dumps(msg).encode() + b"\0")
        end = time.time() + timeout
        with self.cv:
            while i not in self.replies:
                left = end - time.time()
                if left <= 0:
                    raise TimeoutError(method)
                self.cv.wait(left)
            return self.replies.pop(i)

    def page(self, url):
        tid = self.call("Target.createTarget", {"url": url})["result"]["targetId"]
        return self.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["result"]["sessionId"]

    def js(self, session, expr, timeout=60):
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True}, session, timeout)
        if "exceptionDetails" in r.get("result", {}):
            return {"__error__": r["result"]["exceptionDetails"].get("text")}
        return r["result"]["result"].get("value")

    def quit(self):
        try:
            self.call("Browser.close", timeout=10)
        except Exception:
            pass
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def launch(udd, with_host, ext_path=None):
    hosts = Path(udd) / "NativeMessagingHosts"
    hosts.mkdir(parents=True, exist_ok=True)
    if with_host:
        launcher = nh.write_launcher(sys.executable, Path(udd) / "support")
        (hosts / f"{nh.HOST_NAME}.json").write_text(json.dumps(nh.manifest_dict(launcher)))
    cdp = Cdp(udd)
    time.sleep(2)
    loaded = cdp.call("Extensions.loadUnpacked", {"path": str(ext_path or REPO / "browser-extension")})
    ext_id = loaded.get("result", {}).get("id")
    page = cdp.page(f"chrome-extension://{ext_id}/options.html")
    time.sleep(1)
    cdp.js(page, f"chrome.storage.local.set({{serverUrl: 'http://localhost:{PORT}'}})")
    return cdp, ext_id, page


def helper_pids():
    out = subprocess.run(["pgrep", "-f", "mlx_audio.native_host"], capture_output=True, text=True).stdout.split()
    return [p for p in out if p != str(os.getpid())]


def main():
    if not Path(CHROME).exists():
        print("Google Chrome not found; skipping")
        return 0
    assert not up(), f"something is already listening on {PORT}; set E2E_PORT to a free port"

    print(f"== with the helper registered (port {PORT}) ==")
    with tempfile.TemporaryDirectory() as udd:
        cdp, ext_id, page = launch(udd, with_host=True)
        try:
            check("extension loads with the pinned ID", ext_id == nh.EXTENSION_ID, f"got {ext_id}")
            st = cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"serverStatus"})')
            check("popup can tell the server is down but startable", st == {"up": False, "canStart": True}, str(st))
            check("no server yet (nothing starts before first use)", not up())

            t = time.time()
            res = cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"ensureServer"})', timeout=240)
            check("ensureServer starts the real server", res == {"ok": True} and up(), f"{res} after {time.time()-t:.0f}s")

            print(f"   ...idling {KEEPALIVE_WAIT_S}s to see whether the connection keeps the worker (and server) alive")
            time.sleep(KEEPALIVE_WAIT_S)
            check("server still up after the worker's idle timeout", up())
            st = cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"serverStatus"})')
            check("extension still sees it running", st and st.get("up") is True, str(st))

            cdp.call("Extensions.uninstall", {"id": ext_id})
            gone = wait_for(lambda: not up(), 20)
            check("removing the extension stops the server", gone)
            check("helper exited too", wait_for(lambda: not helper_pids(), 10))
        finally:
            cdp.quit()

    print("== quitting Chrome ==")
    with tempfile.TemporaryDirectory() as udd:
        cdp, ext_id, page = launch(udd, with_host=True)
        try:
            res = cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"ensureServer"})', timeout=240)
            check("server started again", res == {"ok": True} and up(), str(res))
        finally:
            cdp.quit()
        check("quitting Chrome stops the server", wait_for(lambda: not up(), 20))
        check("helper exited too", wait_for(lambda: not helper_pids(), 10))

    print("== without the helper registered ==")
    with tempfile.TemporaryDirectory() as udd:
        cdp, ext_id, page = launch(udd, with_host=False)
        try:
            st = cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"serverStatus"})')
            check("reports it cannot start the server", st == {"up": False, "canStart": False}, str(st))
            res = cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"ensureServer"})')
            check("ensureServer fails with a helpful message", res and res.get("ok") is False and "Open the MLX-Audio app" in res.get("error", ""), str(res))
            check("nothing was started", not up() and not helper_pids())
        finally:
            cdp.quit()

    if not os.environ.get("E2E_READ"):
        print("(skipping the real Read flow: it makes Kokoro speak, which on some Macs triggers a macOS library-load warning; set E2E_READ=1 to include it)")
    else:
        read_flow()

    print(f"\n{sum(results)} passed, {len(results) - sum(results)} failed")
    return 0 if all(results) else 1


def read_flow():
    page_port = PORT + 1
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "site"
        site.mkdir()
        para = ("The old lighthouse stood at the edge of the rocky point, and every night its slow beam "
                "crossed the water without fail, a habit the town had come to depend on. ")
        (site / "index.html").write_text(
            "<html><head><title>Lighthouse</title></head><body><article><h1>The lighthouse</h1>"
            + "".join(f"<p>{para * 3}</p>" for _ in range(4)) + "</article></body></html>")

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=str(site), **k)

            def log_message(self, *a):
                pass

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", page_port), Quiet)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        # Automation cannot grant "activeTab", so use a copy of the extension that may read the test page.
        ext_copy = Path(tmp) / "ext"
        shutil.copytree(REPO / "browser-extension", ext_copy)
        manifest = json.loads((ext_copy / "manifest.json").read_text())
        manifest["host_permissions"] += [f"http://localhost:{page_port}/*"]
        (ext_copy / "manifest.json").write_text(json.dumps(manifest))
        udd = Path(tmp) / "profile"
        cdp, ext_id, page = launch(udd, with_host=True, ext_path=ext_copy)
        try:
            check("copy keeps the pinned ID", ext_id == nh.EXTENSION_ID, ext_id)
            cdp.call("Target.createTarget", {"url": f"http://localhost:{page_port}/"})
            time.sleep(2)
            tab = cdp.js(page, f'chrome.tabs.query({{url: "http://localhost:{page_port}/*"}}).then(t => t[0] && t[0].id)')
            check("found the test page tab", isinstance(tab, int), str(tab))
            check("server is down before pressing Read", not up())
            state = cdp.js(page, f'chrome.runtime.sendMessage({{target:"background", type:"start", tabId:{tab}}})', timeout=300)
            check("start returned without an error", state and state.get("status") != "error", str(state)[:200])
            check("the server was started for it", up())
            seen = None
            for _ in range(90):  # up to ~3 minutes for the first chunk
                seen = cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"getState"})')
                if seen and (seen.get("status") == "error" or seen.get("generated", 0) >= 1):
                    break
                time.sleep(2)
            check("audio was generated through the auto-started server",
                  bool(seen) and seen.get("status") in ("playing", "buffering", "done") and seen.get("generated", 0) >= 1,
                  str({k: seen.get(k) for k in ("status", "generated", "chunkCount", "error")}) if seen else "no state")
            cdp.js(page, 'chrome.runtime.sendMessage({target:"background", type:"stop"})')
        finally:
            cdp.quit()
            srv.shutdown()
            srv.server_close()
        check("quitting Chrome stops that server too", wait_for(lambda: not up(), 20))


if __name__ == "__main__":
    raise SystemExit(main())
