"""Real subprocess signals and GLib lifecycle, with external D-Bus substituted."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
import burnbag


def run_child(root: Path, scenario: str, ready_fd: int) -> int:
    """Exercise owned wiring and native GLib without touching host power state."""
    burnbag.load_pygobject(burnbag.TerminalStyle(False, False))
    glib, gio = burnbag.GLib, burnbag.Gio
    burnbag.BATTERY_SYSFS_ROOT = root / "power_supply"
    original_handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    descriptors = []

    def ready(stage: str) -> None:
        os.write(ready_fd, (stage + "\n").encode("ascii"))

    class FDList:
        def get(self, index):
            descriptor = os.open(os.devnull, os.O_RDONLY)
            descriptors.append(descriptor)
            return descriptor

    class Proxy:
        """Minimal system-service boundary with real Variants and descriptors."""

        def __init__(self, interface):
            self.interface = interface
            self.active_profile = "balanced"

        def call_sync(self, method, arguments, *unused):
            if method in {"Get", "org.freedesktop.DBus.Properties.Get"}:
                interface, name = arguments.unpack()
                if name == "Profiles":
                    return glib.Variant("(v)", (glib.Variant("aa{sv}", [
                        {"Profile": glib.Variant("s", profile)}
                        for profile in ("balanced", "power-saver", "performance")
                    ]),))
                value = ({"LidIsClosed": False, "LidIsPresent": True}.get(name, self.active_profile))
                return glib.Variant("(v)", (glib.Variant("b" if isinstance(value, bool) else "s", value),))
            if method == "Set":
                self.active_profile = arguments.unpack()[2]
                if self.active_profile == "balanced" and scenario == "repeated":
                    ready("cleanup")
                    sys.stdin.readline()
                return None
            if method == "Suspend":
                return None
            if method in {"CanSuspend", "CanHibernate"}:
                return glib.Variant("(s)", ("yes",))
            raise AssertionError(f"Unexpected external call: {method}")

        def call_with_unix_fd_list_sync(self, *unused):
            return glib.Variant("(h)", (0,)), FDList()

        def connect(self, name, callback):
            if scenario == "callback_failure":
                def invalid_signal():
                    callback(self, None, [])
                    return False
                glib.idle_add(invalid_signal)
            if scenario == "lid":
                def lid_cycle():
                    for closed in (True, False):
                        callback(self, glib.Variant("a{sv}", {"LidIsClosed": glib.Variant("b", closed)}), [])
                    return False
                glib.idle_add(lid_cycle)
            return 1

    def connect_bus(*unused):
        if scenario in {"setup", "setup_one_shot"}:
            ready("setup")
            sys.stdin.readline()
        if scenario == "failure":
            raise RuntimeError("injected system bus failure")
        return object()

    def new_proxy(*arguments):
        return Proxy(arguments[5])

    def loop_ready():
        ready("loop")
        return False

    if scenario in {"loop", "repeated", "no_plot", "broken_output"}:
        glib.idle_add(loop_ready)

    # Observe the narrow race between the final setup checkpoint and loop entry
    # using the real GLib loop after actual OS signal delivery.
    original_run = glib.MainLoop.run

    def signal_before_run(loop):
        os.kill(os.getpid(), signal.SIGTERM)
        original_run(loop)

    args = ["suspend" if scenario == "setup_one_shot" else "run-cool",
            "--do-not-touch-backlight", "--no-color", "--log-file", str(root / "run.log")]
    if scenario != "lid":
        args.append("--ignore-lid")
    if scenario == "no_plot":
        args.append("--no-plot")

    with mock.patch.object(gio, "bus_get_sync", side_effect=connect_bus), \
            mock.patch.object(gio.DBusProxy, "new_sync", side_effect=new_proxy):
        if scenario == "race":
            with mock.patch.object(glib.MainLoop, "run", signal_before_run):
                result = burnbag.main(args)
        else:
            try:
                result = burnbag.main(args)
            except SystemExit as exc:
                result = int(exc.code)

    for signum, original in original_handlers.items():
        assert signal.getsignal(signum) == original, "process signal handler leaked"
    for descriptor in descriptors:
        try:
            os.fstat(descriptor)
        except OSError as exc:
            assert exc.errno == errno.EBADF
        else:
            raise AssertionError("inhibitor descriptor leaked")
    return result


class ShutdownSubprocessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        probe = subprocess.run(
            [sys.executable, "-c", "from gi.repository import GLib, Gio"],
            capture_output=True, text=True,
        )
        if probe.returncode:
            raise unittest.SkipTest("native PyGObject unavailable to this interpreter")

    def wait_ready(self, descriptor, expected):
        deadline = time.monotonic() + 8
        data = b""
        while not data.endswith(b"\n"):
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, "subprocess did not reach signal boundary")
            readable, _, _ = select.select([descriptor], [], [], remaining)
            self.assertTrue(readable, "subprocess did not reach signal boundary")
            chunk = os.read(descriptor, 1)
            self.assertTrue(chunk, "subprocess exited before signal boundary")
            data += chunk
        self.assertEqual(data.decode().strip(), expected)

    def run_scenario(self, scenario, signum=signal.SIGINT):
        local_tmp = PROJECT_ROOT / ".local" / "tmp"
        local_tmp.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="shutdown-test.", dir=local_tmp) as directory:
            root = Path(directory)
            battery = root / "power_supply" / "BAT0"
            battery.mkdir(parents=True)
            for name, value in {"type": "Battery", "capacity": "80", "status": "Discharging"}.items():
                (battery / name).write_text(value + "\n", encoding="ascii")
            reader, writer = os.pipe()
            child = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--child", str(root), scenario, str(writer)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, pass_fds=(writer,),
            )
            os.close(writer)
            try:
                if scenario in {"loop", "repeated", "no_plot", "setup", "setup_one_shot", "broken_output"}:
                    setup = scenario.startswith("setup")
                    self.wait_ready(reader, "setup" if setup else "loop")
                    if scenario == "broken_output":
                        child.stdout.close()
                        child.stdout = None
                    child.send_signal(signum)
                    if setup:
                        child.stdin.write("continue\n")
                        child.stdin.flush()
                    if scenario == "repeated":
                        self.wait_ready(reader, "cleanup")
                        child.send_signal(signal.SIGINT)
                        child.send_signal(signal.SIGTERM)
                        child.stdin.write("continue\n")
                        child.stdin.flush()
                output, errors = child.communicate(timeout=8)
                if scenario == "broken_output":
                    output = errors
            finally:
                os.close(reader)
                if child.poll() is None:
                    child.kill()
                    child.communicate()
            records = [json.loads(line) for line in (root / "run.log").read_text().splitlines()]

        self.assertNotIn("Traceback", errors)
        self.assertEqual(output.count("BURNBAG — SHUTDOWN & TEARDOWN"), 1)
        self.assertEqual(output.count("BATTERY SUMMARY"), 1)
        self.assertEqual(output.count("BATTERY DEPLETION - 15-second samples"), 0 if scenario == "no_plot" else 1)
        self.assertEqual(sum(row["event"] == "session_end" for row in records), 1)
        self.assertEqual(records[-1]["event"], "session_end")
        final = records[-1]["details"]
        self.assertTrue(final["final_state"]["teardown_complete"])
        self.assertEqual(final["final_state"]["inhibitor_count"], 0)
        self.assertEqual(final["final_state"]["battery_sample_count"], 2)
        self.assertEqual(child.returncode, final["exit_code"])
        self.assertEqual(child.returncode, 1 if scenario in {"failure", "callback_failure", "broken_output"} else 0, errors)
        if scenario in {"setup", "setup_one_shot"}:
            self.assertNotIn("inhibitor_acquired", [row["event"] for row in records])
            self.assertNotIn("suspend_request_intent", [row["event"] for row in records])
        if scenario not in {"failure", "lid", "callback_failure", "broken_output"}:
            self.assertEqual(sum(row["event"] == "signal_received" for row in records), 1)
            self.assertIn("User termination signal", final["shutdown_reason"])

    def test_ignore_lid_sigint_reports_chart_and_summary(self):
        self.run_scenario("loop")

    def test_sigterm_reports_chart_and_summary(self):
        self.run_scenario("loop", signal.SIGTERM)

    def test_terminal_hangup_reports_chart_and_summary(self):
        self.run_scenario("loop", signal.SIGHUP)

    def test_callback_exception_exits_glib_with_nonzero_and_final_report(self):
        self.run_scenario("callback_failure")

    def test_broken_output_pipe_uses_stderr_and_closes_log(self):
        self.run_scenario("broken_output")

    def test_sigterm_during_setup_finalizes_before_next_mutation(self):
        self.run_scenario("setup", signal.SIGTERM)

    def test_signal_also_protects_one_shot_setup(self):
        self.run_scenario("setup_one_shot", signal.SIGTERM)

    def test_repeated_signals_cannot_interrupt_cleanup(self):
        self.run_scenario("repeated")

    def test_signal_immediately_before_loop_run_is_not_lost(self):
        self.run_scenario("race")

    def test_setup_failure_after_initial_sample_reports_once(self):
        self.run_scenario("failure")

    def test_lid_cycle_uses_same_final_report(self):
        self.run_scenario("lid")

    def test_no_plot_still_reports_summary_on_signal(self):
        self.run_scenario("no_plot")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        sys.exit(run_child(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])))
    unittest.main()
