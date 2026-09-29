import http.server
import os
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

from mlx_audio import app_window as aw


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def serve(port):
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_defaults_and_overrides():
    a = aw.parse_args([])
    assert a.port == 8000 and a.log_dir == aw.DEFAULT_LOG_DIR and a.log_file == aw.DEFAULT_LOG_FILE
    b = aw.parse_args(["--port", "8123", "--log-file", "/tmp/x.log"])
    assert b.port == 8123 and str(b.log_file) == "/tmp/x.log"


def test_server_is_up_detects_a_listener_and_its_absence():
    port = free_port()
    assert not aw.server_is_up(port)
    srv = serve(port)
    try:
        assert aw.server_is_up(port)
    finally:
        srv.shutdown()
        srv.server_close()


def test_wait_for_server_reports_up_exited_and_timeout():
    port = free_port()
    srv = serve(port)
    try:
        assert aw.wait_for_server(port, None, timeout_s=3) == "up"
    finally:
        srv.shutdown()
        srv.server_close()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    assert aw.wait_for_server(free_port(), dead, timeout_s=3, poll_s=0.05) == "exited"
    assert aw.wait_for_server(free_port(), None, timeout_s=0.3, poll_s=0.05) == "timeout"


def test_error_page_escapes_its_text():
    page = aw.error_html("<script>x</script>", Path("/tmp/a&b.log"))
    assert "<script>" not in page and "&lt;script&gt;" in page and "a&amp;b.log" in page


def test_stop_server_kills_the_whole_group_and_is_repeatable():
    with tempfile.TemporaryDirectory() as d:
        proc = aw.start_server(1, Path(d) / "logs", Path(d) / "s.log", server_cmd=["/bin/sleep", "300"])
        time.sleep(0.4)
        assert proc.poll() is None
        aw.stop_server(proc, grace_s=5)
        assert proc.poll() is not None
        aw.stop_server(proc)  # second call must not raise
        aw.stop_server(None)


def test_server_dies_when_its_owner_is_killed_without_cleanup():
    # A stand-in for the window app: starts the server, then is SIGKILLed (no chance to clean up),
    # like Cmd+Q ending the process or a crash. The watchdog must still stop the server.
    with tempfile.TemporaryDirectory() as d:
        pidfile = Path(d) / "server.pid"
        owner_code = textwrap.dedent(
            f"""
            import sys, time
            from pathlib import Path
            from mlx_audio import app_window as aw
            cmd = [sys.executable, "-c", "import os,time; open({str(pidfile)!r},'w').write(str(os.getpid())); time.sleep(300)"]
            aw.start_server(1, Path({d!r})/"logs", Path({d!r})/"s.log", server_cmd=cmd)
            time.sleep(300)
            """
        )
        owner = subprocess.Popen([sys.executable, "-c", owner_code])
        try:
            for _ in range(100):
                if pidfile.exists() and pidfile.read_text():
                    break
                time.sleep(0.1)
            server_pid = int(pidfile.read_text())
            assert pid_alive(server_pid)
            owner.send_signal(signal.SIGKILL)
            owner.wait()
            for _ in range(60):  # the watchdog checks once a second
                if not pid_alive(server_pid):
                    break
                time.sleep(0.1)
            assert not pid_alive(server_pid), "server kept running after its owner was killed"
        finally:
            if owner.poll() is None:
                owner.kill()
            try:
                os.killpg(int(pidfile.read_text()), signal.SIGKILL)
            except Exception:
                pass
