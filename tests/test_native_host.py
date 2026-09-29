import base64
import hashlib
import io
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

from mlx_audio import native_host as nh

REPO = Path(__file__).resolve().parent.parent


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def fake_server_cmd(port):
    # anything answering HTTP counts as "up"
    return [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"]


def frame(obj):
    data = json.dumps(obj).encode()
    return struct.pack("=I", len(data)) + data


def messages(buf):
    stream = io.BytesIO(buf.getvalue())
    out = []
    while True:
        m = nh.read_message(stream)
        if m is None:
            return out
        out.append(m)


def wait_for(cond, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def make_host(d, out, port):
    return nh.Host(out, log_dir=Path(d) / "logs", log_file=Path(d) / "s.log", server_cmd=fake_server_cmd(port), startup_timeout_s=20)


def test_protocol_roundtrip_and_bad_input():
    buf = io.BytesIO()
    nh.write_message(buf, {"a": 1})
    buf.seek(0)
    assert nh.read_message(buf) == {"a": 1}
    assert nh.read_message(buf) is None  # EOF
    assert nh.read_message(io.BytesIO(struct.pack("=I", 5) + b"notjs")) == {}  # malformed
    assert nh.read_message(io.BytesIO(frame([1, 2]))) == {}  # not an object
    big = struct.pack("=I", nh.MAX_MESSAGE_BYTES + 1) + b"x" * (nh.MAX_MESSAGE_BYTES + 1) + frame({"ok": 1})
    stream = io.BytesIO(big)
    assert nh.read_message(stream) == {}  # oversized is skipped...
    assert nh.read_message(stream) == {"ok": 1}  # ...and the stream stays in sync


def test_start_reports_starting_then_up_and_close_stops_the_server():
    port = free_port()
    with tempfile.TemporaryDirectory() as d:
        out = io.BytesIO()
        host = make_host(d, out, port)
        host.handle({"cmd": "start", "port": port})
        assert wait_for(lambda: any(m.get("state") == "up" for m in messages(out)))
        states = [m["state"] for m in messages(out)]
        assert states[0] == "starting" and states[-1] == "up", states
        assert [m for m in messages(out) if m["state"] == "up"][-1]["owned"] is True
        host.close()
        assert wait_for(lambda: not nh.server_is_up(port), 10), "server still running after close()"


def test_a_server_that_was_already_running_is_never_stopped():
    port = free_port()
    import http.server

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as d:
            out = io.BytesIO()
            host = make_host(d, out, port)
            host.handle({"cmd": "start", "port": port})
            assert messages(out) == [{"type": "status", "state": "up", "owned": False}]
            host.close()
            assert nh.server_is_up(port), "stopped a server that was not ours"
    finally:
        srv.shutdown()
        srv.server_close()


def test_serve_stops_the_server_when_chrome_closes_the_connection():
    port = free_port()
    with tempfile.TemporaryDirectory() as d:
        out = io.BytesIO()
        host = make_host(d, out, port)
        r, w = os.pipe()
        t = threading.Thread(target=nh.serve, args=(os.fdopen(r, "rb"), host))
        t.start()
        os.write(w, frame({"cmd": "start", "port": port}))
        assert wait_for(lambda: nh.server_is_up(port))
        os.close(w)  # what Chrome does when the extension goes away
        t.join(timeout=15)
        assert not t.is_alive()
        assert wait_for(lambda: not nh.server_is_up(port), 10), "server survived the disconnect"


def test_bad_ports_and_unknown_commands_are_handled():
    for bad in (None, 0, 80, 70000, "8000", True, 8000.5):
        assert nh.valid_port(bad) is None, bad
    assert nh.valid_port(8000) == 8000
    out = io.BytesIO()
    host = nh.Host(out)
    host.handle({"cmd": "start", "port": 22})
    host.handle({"cmd": "rm -rf /"})
    host.handle({"cmd": "ping"})
    got = messages(out)
    assert got[0]["state"] == "error" and got[1] == {"type": "pong"} and len(got) == 2, got
    assert host.proc is None  # nothing was started


def test_register_and_unregister_use_only_installed_browsers():
    with tempfile.TemporaryDirectory() as d:
        root, support = Path(d) / "root", Path(d) / "support"
        (root / "Google/Chrome").mkdir(parents=True)  # only Chrome is "installed"
        written = nh.register("/opt/my python/bin/python3", support, root)
        assert [p.parent.parent.name for p in written] == ["Chrome"]
        m = json.loads(written[0].read_text())
        assert m["name"] == nh.HOST_NAME and m["type"] == "stdio"
        assert m["allowed_origins"] == [f"chrome-extension://{nh.EXTENSION_ID}/"]
        launcher = Path(m["path"])
        assert launcher.parent == support and os.access(launcher, os.X_OK)
        assert "'/opt/my python/bin/python3'" in launcher.read_text()  # path with a space is quoted
        assert not (root / "BraveSoftware").exists()
        removed = nh.unregister(support, root)
        assert len(removed) == 2 and not launcher.exists() and not written[0].exists()
        assert nh.unregister(support, root) == []  # repeatable


def test_extension_id_matches_the_key_pinned_in_the_extension_manifest():
    key = json.loads((REPO / "browser-extension" / "manifest.json").read_text())["key"]
    digest = hashlib.sha256(base64.b64decode(key)).hexdigest()[:32]
    derived = "".join(chr(ord("a") + int(c, 16)) for c in digest)
    assert derived == nh.EXTENSION_ID, (derived, nh.EXTENSION_ID)


def test_connection_from_another_extension_is_refused():
    assert nh.main(["chrome-extension://someotherextensionidxxxxxxxxxxxx/"]) == 1
