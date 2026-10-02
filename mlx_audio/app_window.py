"""A native macOS window for MLX-Audio, so it behaves like a normal app instead of a browser tab.

Run it with ``python -m mlx_audio.app_window`` (needs the optional ``desktop`` extra:
``pip install "mlx-audio[desktop]"``). It:

* starts the API/UI server (``mlx_audio.server``) unless one is already answering on the port,
* opens a window on it (macOS's built-in web view via ``pywebview``), and
* stops the server it started when the window is closed, on Cmd+Q, or if this process dies.

A server that was already running is left alone: it is not ours to stop.

The friends-and-family installer wraps this in a proper ``MLX-Audio.app`` bundle so the Dock and
menu bar show the right name and icon (see ``packaging/friends-and-family/make_app.sh``).
"""

from __future__ import annotations

import argparse
import html
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Sequence

APP_NAME = "MLX-Audio"
DEFAULT_PORT = 8000
# The very first launch after installing can be slow: macOS checks every newly installed
# compiled library the first time it runs (measured at ~8 minutes once on a fresh VM).
STARTUP_TIMEOUT_S = 15 * 60

SUPPORT_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
DEFAULT_LOG_DIR = SUPPORT_DIR / "logs"
DEFAULT_LOG_FILE = Path.home() / "Library" / "Logs" / f"{APP_NAME}.log"

# Runs the server and kills it as soon as the process that owns the window (its parent pid,
# passed as $1) is gone, however that happens: Cmd+Q ends the process without giving Python a
# chance to clean up, and a crash or force-quit would otherwise leave the server running.
_WATCHDOG = (
    'parent=$1; shift; "$@" & child=$!; '
    '(while kill -0 "$parent" 2>/dev/null; do sleep 1; done; kill "$child" 2>/dev/null) & '
    'wait "$child"'
)

_PAGE_STYLE = (
    "body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;"
    "font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#2b2b3a;"
    "background:linear-gradient(160deg,#f4f3ff,#e6e4ff)}"
    ".card{text-align:center;max-width:520px;padding:32px}"
    "h1{font-size:22px;margin:0 0 12px}p{color:#5a5a70;line-height:1.5;margin:6px 0}"
    "code{background:#0001;padding:2px 6px;border-radius:4px}"
    ".dot{width:10px;height:10px;border-radius:50%;background:#6254f5;display:inline-block;"
    "margin:0 3px;animation:b 1s infinite ease-in-out}.dot:nth-child(2){animation-delay:.15s}"
    ".dot:nth-child(3){animation-delay:.3s}@keyframes b{0%,80%,100%{opacity:.25}40%{opacity:1}}"
)


def splash_html() -> str:
    return (
        f"<html><head><meta charset='utf-8'><style>{_PAGE_STYLE}</style></head><body><div class='card'>"
        "<h1>Starting MLX-Audio</h1><div><span class='dot'></span><span class='dot'></span>"
        "<span class='dot'></span></div>"
        "<p>The very first launch after installing can take several minutes while macOS checks "
        "the newly installed files. This only happens once.</p></div></body></html>"
    )


def error_html(reason: str, log_file: Path) -> str:
    return (
        f"<html><head><meta charset='utf-8'><style>{_PAGE_STYLE}</style></head><body><div class='card'>"
        f"<h1>MLX-Audio could not start</h1><p>{html.escape(reason)}</p>"
        f"<p>Details are in <code>{html.escape(str(log_file))}</code>.</p>"
        "<p>Close this window and open MLX-Audio again to retry.</p></div></body></html>"
    )


def server_url(port: int) -> str:
    return f"http://localhost:{port}"


def server_is_up(port: int, timeout: float = 1.0) -> bool:
    """True if something is answering HTTP on the port (any status counts)."""
    try:
        with urllib.request.urlopen(f"{server_url(port)}/v1/models", timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True  # it answered, just not with 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def default_server_cmd(port: int, log_dir: Path) -> list[str]:
    return [sys.executable, "-m", "mlx_audio.server", "--port", str(port), "--log-dir", str(log_dir)]


def start_server(
    port: int,
    log_dir: Path,
    log_file: Path,
    server_cmd: Optional[Sequence[str]] = None,
) -> subprocess.Popen:
    """Start the server in its own process group, with the watchdog described above."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = list(server_cmd) if server_cmd is not None else default_server_cmd(port, log_dir)
    log = open(log_file, "wb")
    try:
        return subprocess.Popen(
            ["/bin/sh", "-c", _WATCHDOG, "sh", str(os.getpid()), *cmd],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            # The server crashes with "Read-only file system: 'logs'" if started from a
            # read-only working directory (as happens when launched from some contexts).
            cwd=str(Path.home()),
            start_new_session=True,
        )
    finally:
        log.close()  # the child keeps its own copy of the descriptor


def stop_server(proc: Optional[subprocess.Popen], grace_s: float = 8.0) -> None:
    """Stop the whole process group started by start_server(). Safe to call more than once."""
    if proc is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.time() + grace_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def wait_for_server(
    port: int,
    proc: Optional[subprocess.Popen],
    timeout_s: float = STARTUP_TIMEOUT_S,
    poll_s: float = 0.5,
) -> str:
    """Wait until the server answers. Returns "up", "exited" (our child died) or "timeout"."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if server_is_up(port):
            return "up"
        if proc is not None and proc.poll() is not None:
            return "exited"
        time.sleep(poll_s)
    return "timeout"


def _brand_app(name: str) -> None:
    """Make the menu bar, About and Quit items say the app name instead of "Python"."""
    try:
        from Foundation import NSBundle, NSProcessInfo

        info = NSBundle.mainBundle().infoDictionary()
        info["CFBundleName"] = name
        info["CFBundleDisplayName"] = name
        NSProcessInfo.processInfo().setProcessName_(name)
    except Exception:  # cosmetic only
        pass


def _allow_microphone() -> None:
    """Let pages in the window use the microphone (for live transcription).

    pywebview does not do this itself, and inside an app bundle the web view then hides
    ``navigator.mediaDevices`` completely ("undefined is not an object"). Call before the window
    is created. macOS still shows its own "allow microphone" prompt the first time.
    """
    try:
        import objc
        from webview.platforms import cocoa

        def grant(self, web_view, origin, frame, media_type, decision_handler):
            decision_handler(1)  # WKPermissionDecisionGrant

        selector = objc.selector(
            grant,
            selector=b"webView:requestMediaCapturePermissionForOrigin:initiatedByFrame:type:decisionHandler:",
            signature=b"v@:@@@q@?",
        )
        objc.classAddMethods(cocoa.BrowserView.BrowserDelegate, [selector])
    except Exception as exc:  # the app still works without it, only the microphone does not
        print(f"Could not enable the microphone: {exc}", file=sys.stderr)


def _enable_media_devices() -> None:
    """Turn on the web view's media-devices preference (needs the window to exist)."""
    try:
        from PyObjCTools import AppHelper
        from webview.platforms import cocoa

        def apply():
            for view in list(cocoa.BrowserView.instances.values()):
                view.webview.configuration().preferences().setValue_forKey_(True, "mediaDevicesEnabled")

        AppHelper.callAfter(apply)
    except Exception as exc:
        print(f"Could not enable the microphone: {exc}", file=sys.stderr)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="mlx_audio.app_window", description=__doc__.split("\n\n")[0])
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR, help="the server's own log folder")
    p.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE, help="server output, for troubleshooting")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=860)
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if sys.platform != "darwin":
        print("The MLX-Audio window app only supports macOS.", file=sys.stderr)
        return 1
    try:
        import webview
    except ImportError:
        print('The window needs pywebview: pip install "mlx-audio[desktop]"', file=sys.stderr)
        return 1

    _brand_app(APP_NAME)
    url = server_url(args.port)
    # A server that was already running is not ours to stop.
    proc = None if server_is_up(args.port) else start_server(args.port, args.log_dir, args.log_file)
    stopped = threading.Event()

    def shutdown(*_):
        if not stopped.is_set():
            stopped.set()
            stop_server(proc)

    # No Python signal handlers on purpose: macOS's event loop holds the main thread, so a Python
    # handler never gets to run (SIGTERM left the app and its server running in testing). The
    # default action ends the process at once and the watchdog then stops the server.

    _allow_microphone()
    webview.settings["ALLOW_DOWNLOADS"] = True  # the "Download" buttons save through a native Save panel
    window = webview.create_window(
        APP_NAME,
        html=splash_html(),
        width=args.width,
        height=args.height,
        min_size=(900, 600),
        text_select=True,
        zoomable=True,
    )
    # Both closing the window and Cmd+Q pass through "closing".
    window.events.closing += shutdown

    def boot():
        _enable_media_devices()
        time.sleep(0.5)  # let the preference land before the page loads
        state = "up" if proc is None else wait_for_server(args.port, proc)
        if state == "up":
            window.load_url(url)
        elif state == "exited":
            window.load_html(error_html("The server stopped while starting.", args.log_file))
        else:
            window.load_html(error_html("The server did not start in time.", args.log_file))

    try:
        SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        # persistent storage so the app remembers its settings between launches
        webview.start(boot, private_mode=False, storage_path=str(SUPPORT_DIR / "webview"))
    finally:
        shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
