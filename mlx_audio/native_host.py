"""Chrome "native messaging" helper for the MLX-Audio Reader extension.

A Chrome extension cannot start programs on its own. Chrome can, however, launch a registered
helper when the extension connects to it, and it closes the helper's input when the extension
goes away (Chrome quits, or the extension is disabled, removed or reloaded). This module is that
helper:

* the extension sends ``{"cmd": "start", "port": 8000}`` and the helper starts the MLX-Audio
  server (or reuses one that is already answering) and reports ``starting`` / ``up`` / ``error``;
* when Chrome closes the connection, the helper stops the server it started, and exits.

A server that was already running (the MLX-Audio window app, or one started by hand) is never
stopped: it is not ours. If the helper itself is force-killed, the server's watchdog (see
``app_window.start_server``) still stops the server within about a second.

Setup, done by the installer (or by hand)::

    python -m mlx_audio.native_host --register        # tells Chrome/Brave/Edge about the helper
    python -m mlx_audio.native_host --unregister

The helper only accepts connections from the extension whose ID is ``EXTENSION_ID`` (the ID is
pinned by the ``key`` in ``browser-extension/manifest.json``); Chrome enforces that through the
``allowed_origins`` entry in the registration file.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import stat
import struct
import sys
import threading
from pathlib import Path
from typing import BinaryIO, Callable, Optional, Sequence

from mlx_audio.app_window import (
    DEFAULT_LOG_DIR,
    DEFAULT_LOG_FILE,
    STARTUP_TIMEOUT_S,
    SUPPORT_DIR,
    server_is_up,
    start_server,
    stop_server,
    wait_for_server,
)

HOST_NAME = "com.mlxaudio.host"
# Derived from the public key in browser-extension/manifest.json; a test keeps the two in sync.
EXTENSION_ID = "oanafgbookdcphadfbjnohnmibkemgmf"
ALLOWED_ORIGIN = f"chrome-extension://{EXTENSION_ID}/"
MAX_MESSAGE_BYTES = 64 * 1024  # Chrome allows far more; this helper needs a few dozen bytes

# Chromium-family browsers and where each keeps per-user native messaging registrations,
# relative to ~/Library/Application Support.
BROWSER_DIRS = {
    "Google Chrome": "Google/Chrome",
    "Chromium": "Chromium",
    "Brave": "BraveSoftware/Brave-Browser",
    "Microsoft Edge": "Microsoft Edge",
    "Arc": "Arc/User Data",
}
DEFAULT_BROWSERS_ROOT = Path.home() / "Library" / "Application Support"
LAUNCHER_NAME = "native-host.sh"


# ---- the message protocol: a 4-byte length (native byte order) followed by that many bytes of JSON


def read_message(stream: BinaryIO) -> Optional[dict]:
    """The next message as a dict, {} for one that is oversized/malformed (ignored), or None at EOF."""
    raw = stream.read(4)
    if len(raw) < 4:
        return None
    (size,) = struct.unpack("=I", raw)
    if size > MAX_MESSAGE_BYTES:
        remaining = size  # skip it in chunks so the stream stays in sync
        while remaining > 0:
            chunk = stream.read(min(remaining, 65536))
            if not chunk:
                return None
            remaining -= len(chunk)
        return {}
    body = stream.read(size)
    if len(body) < size:
        return None
    try:
        obj = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def write_message(stream: BinaryIO, obj: dict, lock: Optional[threading.Lock] = None) -> None:
    data = json.dumps(obj, separators=(",", ":")).encode()
    frame = struct.pack("=I", len(data)) + data
    if lock is None:
        stream.write(frame)
        stream.flush()
        return
    with lock:
        stream.write(frame)
        stream.flush()


def valid_port(value) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and 1024 <= value <= 65535 else None


# ---- the helper


class Host:
    def __init__(
        self,
        out: BinaryIO,
        *,
        log_dir: Path = DEFAULT_LOG_DIR,
        log_file: Path = DEFAULT_LOG_FILE,
        server_cmd: Optional[Sequence[str]] = None,
        startup_timeout_s: float = STARTUP_TIMEOUT_S,
    ):
        self.out = out
        self.lock = threading.Lock()
        self.log_dir, self.log_file, self.server_cmd = log_dir, log_file, server_cmd
        self.startup_timeout_s = startup_timeout_s
        self.proc = None  # the server we started (None if we did not, or have not)
        self.port: Optional[int] = None
        self._waiter: Optional[threading.Thread] = None

    def send(self, obj: dict) -> None:
        try:
            write_message(self.out, obj, self.lock)
        except (BrokenPipeError, ValueError, OSError):
            pass  # Chrome went away; the read loop will see EOF and clean up

    def handle(self, msg: dict) -> None:
        cmd = msg.get("cmd")
        if cmd == "ping":
            self.send({"type": "pong"})
        elif cmd in ("start", "status"):
            port = valid_port(msg.get("port"))
            if port is None:
                self.send({"type": "status", "state": "error", "detail": "invalid port"})
            elif cmd == "status":
                self.send(self._status(port))
            else:
                self.start(port)
        # anything else is ignored

    def _status(self, port: int) -> dict:
        if server_is_up(port):
            return {"type": "status", "state": "up", "owned": self.proc is not None}
        if self.proc is not None and self.proc.poll() is None:
            return {"type": "status", "state": "starting", "owned": True}
        return {"type": "status", "state": "down", "owned": False}

    def start(self, port: int) -> None:
        if self.proc is not None and self.port != port and self.proc.poll() is None:
            self.send({"type": "status", "state": "error", "detail": "already serving another port"})
            return
        current = self._status(port)
        if current["state"] == "up":
            self.send(current)  # includes owned=False for someone else's server: never ours to stop
            return
        if current["state"] == "down":
            self.port = port
            self.proc = start_server(port, self.log_dir, self.log_file, server_cmd=self.server_cmd)
        self.send({"type": "status", "state": "starting", "owned": True})
        if self._waiter is None or not self._waiter.is_alive():
            self._waiter = threading.Thread(target=self._wait_and_report, args=(port,), daemon=True)
            self._waiter.start()

    def _wait_and_report(self, port: int) -> None:
        outcome = wait_for_server(port, self.proc, self.startup_timeout_s)
        if outcome == "up":
            self.send({"type": "status", "state": "up", "owned": True})
        else:
            detail = "the server stopped while starting" if outcome == "exited" else "the server did not start in time"
            self.send({"type": "status", "state": "error", "detail": detail, "owned": True})

    def close(self) -> None:
        stop_server(self.proc)


def serve(stdin: BinaryIO, host: Host) -> None:
    """Handle messages until Chrome closes the connection, then stop the server we started."""
    try:
        while True:
            msg = read_message(stdin)
            if msg is None:
                break
            host.handle(msg)
    finally:
        host.close()


# ---- registration with the browsers


def manifest_dict(launcher: Path) -> dict:
    return {
        "name": HOST_NAME,
        "description": "Starts and stops the MLX-Audio server for the MLX-Audio Reader extension",
        "path": str(launcher),
        "type": "stdio",
        "allowed_origins": [ALLOWED_ORIGIN],
    }


def write_launcher(python: str, support_dir: Path) -> Path:
    support_dir.mkdir(parents=True, exist_ok=True)
    launcher = support_dir / LAUNCHER_NAME
    launcher.write_text(f'#!/bin/sh\nexec {shlex.quote(python)} -m mlx_audio.native_host "$@"\n')
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return launcher


def register(
    python: str,
    support_dir: Path = SUPPORT_DIR,
    browsers_root: Path = DEFAULT_BROWSERS_ROOT,
) -> list[Path]:
    """Register the helper with every installed Chromium-family browser. Returns the files written."""
    launcher = write_launcher(python, support_dir)
    written = []
    for rel in BROWSER_DIRS.values():
        browser_dir = browsers_root / rel
        if not browser_dir.is_dir():
            continue  # that browser is not installed for this user
        target = browser_dir / "NativeMessagingHosts"
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{HOST_NAME}.json"
        path.write_text(json.dumps(manifest_dict(launcher), indent=2) + "\n")
        written.append(path)
    return written


def unregister(support_dir: Path = SUPPORT_DIR, browsers_root: Path = DEFAULT_BROWSERS_ROOT) -> list[Path]:
    removed = []
    for rel in BROWSER_DIRS.values():
        path = browsers_root / rel / "NativeMessagingHosts" / f"{HOST_NAME}.json"
        if path.exists():
            path.unlink()
            removed.append(path)
    launcher = support_dir / LAUNCHER_NAME
    if launcher.exists():
        launcher.unlink()
        removed.append(launcher)
    return removed


def parse_args(argv: Optional[Sequence[str]] = None):
    p = argparse.ArgumentParser(prog="mlx_audio.native_host", description=__doc__.split("\n\n")[0])
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--register", action="store_true", help="register the helper with installed browsers")
    mode.add_argument("--unregister", action="store_true", help="remove the registration")
    p.add_argument("--python", default=sys.executable, help="python to run the helper with (for --register)")
    p.add_argument("--support-dir", type=Path, default=SUPPORT_DIR)
    p.add_argument("--browsers-root", type=Path, default=DEFAULT_BROWSERS_ROOT)
    # Chrome appends the calling extension's origin (and sometimes a window handle)
    return p.parse_known_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args, extra = parse_args(argv)
    if args.register:
        for path in register(args.python, args.support_dir, args.browsers_root):
            print("registered:", path)
        return 0
    if args.unregister:
        for path in unregister(args.support_dir, args.browsers_root):
            print("removed:", path)
        return 0

    origin = next((a for a in extra if a.startswith("chrome-extension://")), None)
    if origin is not None and origin != ALLOWED_ORIGIN:
        print(f"refusing connection from {origin}", file=sys.stderr)
        return 1

    # stdout carries the protocol; make sure stray prints cannot corrupt it
    out = sys.stdout.buffer
    sys.stdout = sys.stderr
    serve(sys.stdin.buffer, Host(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
