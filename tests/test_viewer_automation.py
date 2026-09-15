"""Bounded opt-in Unix automation transport tests without a GTK display."""
import json
from pathlib import Path
import socket
import stat
import tempfile
import threading
import unittest

from burnbag_viewer import AutomationServer

ROOT = Path(__file__).resolve().parents[1]


class _GLib:
    @staticmethod
    def idle_add(callback, *args):
        callback(*args)
        return 1


class _Viewer:
    GLib = _GLib()

    def automation_request(self, request):
        if request.get("op") == "fail":
            raise ValueError("expected test failure")
        return {"accepted": request.get("op")}


class AutomationServerTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".local/tmp").mkdir(parents=True, exist_ok=True)
        self.workspace = tempfile.TemporaryDirectory(prefix="viewer-socket-", dir=ROOT / ".local/tmp")
        self.directory = Path(self.workspace.name)
        self.path = self.directory / "control.sock"
        self.server = AutomationServer(_Viewer(), str(self.path))
        self.server.start()
        self.addCleanup(self.stop)

    def tearDown(self):
        self.workspace.cleanup()

    def stop(self):
        if self.server:
            self.server.stop()
            self.server = None

    def send(self, payload):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(self.path))
            connection.sendall((json.dumps(payload) + "\n").encode())
            data = bytearray()
            while b"\n" not in data:
                data.extend(connection.recv(4096))
        return json.loads(bytes(data).split(b"\n", 1)[0])

    def test_explicit_socket_is_private_and_correlates_responses(self):
        info = self.path.lstat()
        self.assertTrue(stat.S_ISSOCK(info.st_mode))
        self.assertEqual(0o600, stat.S_IMODE(info.st_mode))
        response = self.send({"id": "request-1", "op": "status"})
        self.assertEqual({"id": "request-1", "ok": True,
                          "result": {"accepted": "status"}}, response)

    def test_structured_dispatch_errors_return_correlated_failure(self):
        response = self.send({"id": 42, "op": "fail"})
        self.assertEqual(42, response["id"])
        self.assertFalse(response["ok"])
        self.assertEqual("expected test failure", response["error"])

    def test_oversized_request_is_rejected_within_bound(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(3)
            connection.connect(str(self.path))
            connection.sendall(b"x" * (AutomationServer.MAX_REQUEST + 1) + b"\n")
            response = json.loads(connection.recv(4096).split(b"\n", 1)[0])
        self.assertFalse(response["ok"])
        self.assertIn("exceeds its limit", response["error"])

    def test_shutdown_only_removes_the_socket_created_by_this_instance(self):
        self.path.unlink()
        self.path.write_text("replacement")
        self.stop()
        self.assertEqual("replacement", self.path.read_text())

    def test_non_private_or_ambiguous_socket_paths_are_rejected(self):
        broad = self.directory / "broad"
        broad.mkdir()
        broad.chmod(0o777)
        with self.assertRaises(ValueError):
            AutomationServer(_Viewer(), str(broad / "socket"))
        with self.assertRaises(ValueError):
            AutomationServer(_Viewer(), str(self.directory / ".." / "socket"))


if __name__ == "__main__":
    unittest.main()
