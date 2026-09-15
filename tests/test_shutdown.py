"""Real subprocess signals and GLib lifecycle, with external D-Bus substituted."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
import errno
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
import burnbag


HIBERNATE_SCENARIOS = {"hibernates", "hibernates_no_plot"}
SLEEP_SCENARIOS = {"suspends", "suspends_no_plot", "suspends_ordinary"} | HIBERNATE_SCENARIOS


def run_child(root: Path, scenario: str, ready_fd: int) -> int:
    """Exercise owned wiring and native GLib without touching host power state."""
    burnbag.load_pygobject(burnbag.TerminalStyle(False, False))
    glib, gio = burnbag.GLib, burnbag.Gio
    burnbag.BATTERY_SYSFS_ROOT = root / "power_supply"
    original_handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    descriptors = []
    suspend_scenario = scenario in SLEEP_SCENARIOS

    def ready(stage: str) -> None:
        os.write(ready_fd, (stage + "\n").encode("ascii"))

    class KernelClocks:
        """External clock boundary; real worker and GLib code consume its reads."""

        def __init__(self):
            self.lock = threading.Lock()
            self.sleep_offset = 0.0
            self.awake_offset = 0.0
            self.worker_reads = 0
            self.stage = 0
            self.final_sleep_pending = False
            self.final_sleep_read = False
            self.last_read = None
            self.sleep_windows = []

        def read(self):
            with self.lock:
                worker = threading.current_thread() is not threading.main_thread()
                if worker:
                    self.worker_reads += 1
                elif self.final_sleep_pending:
                    # The final clock read must detect this period even though
                    # the GLib loop and worker have already stopped.
                    self.sleep_offset += 3.0
                    self.final_sleep_pending = False
                    self.final_sleep_read = True
                monotonic = time.monotonic() + self.awake_offset
                sample = burnbag.SuspendClockSample(
                    datetime.now().astimezone() + timedelta(seconds=self.awake_offset + self.sleep_offset),
                    monotonic + self.sleep_offset, monotonic,
                )
                if self.last_read is not None and sample.offset > self.last_read.offset:
                    self.sleep_windows.append((self.last_read.monotonic, sample.monotonic))
                self.last_read = sample
                return sample

        def journal(self, boot_id):
            """External records for real classification of the observed windows."""
            if scenario not in HIBERNATE_SCENARIOS:
                return []
            assert len(self.sleep_windows) == 3, "journal queried before final sleep reconciliation"
            records = []
            for index, ((start, end), kind) in enumerate(zip(
                    self.sleep_windows, ("hibernate", "suspend", "hibernate"))):
                opening = int((start + (end - start) / 4) * 1000000)
                closing = int((start + 3 * (end - start) / 4) * 1000000)
                assert start <= opening / 1000000 < closing / 1000000 <= end
                common = {
                    "_BOOT_ID": boot_id, "_UID": "0", "_COMM": "systemd-sleep",
                    "_PID": str(1000 + index), "_SYSTEMD_UNIT": f"systemd-{kind}.service",
                    "_SYSTEMD_INVOCATION_ID": f"{index + 1:032x}", "SLEEP": kind, "PRIORITY": "6",
                }
                records.extend((
                    dict(common, MESSAGE_ID="6bbd95ee977941e497c48be27c254128",
                         MESSAGE=f"Performing sleep operation '{kind}'...",
                         __MONOTONIC_TIMESTAMP=str(opening)),
                    dict(common, MESSAGE_ID="8811e6df2a8e40f58a94cea26f8ebf14",
                         MESSAGE=f"System returned from sleep operation '{kind}'.",
                         __MONOTONIC_TIMESTAMP=str(closing)),
                ))
            return records

        def boottime(self):
            with self.lock:
                return time.monotonic() + self.awake_offset + self.sleep_offset

        def restored(self):
            with self.lock:
                self.final_sleep_pending = True

        def advance(self):
            """Inject separate periods only after the worker consumed each one."""
            with self.lock:
                if self.stage and self.worker_reads < 2:
                    return True
                # The second read proves the previous read completed the real
                # monitor's observation before the next offset change occurs.
                self.worker_reads = 0
                if self.stage == 0:
                    self.sleep_offset += 5.0
                elif self.stage == 1:
                    self.awake_offset += 3.0
                elif self.stage == 2:
                    self.sleep_offset += 7.0
                else:
                    ready("loop")
                    return False
                self.stage += 1
                return True

    clocks = KernelClocks() if suspend_scenario else None

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
                if self.active_profile == "balanced" and clocks is not None:
                    clocks.restored()
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
            if scenario in {"lid", "lid_events", "lid_events_no_plot"}:
                def lid_cycle():
                    states = (True, False) if scenario == "lid" else (True, True, False, False, True, False)
                    for closed in states:
                        callback(self, glib.Variant("a{sv}", {"LidIsClosed": glib.Variant("b", closed)}), [])
                    if scenario != "lid":
                        ready("loop")
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
    if clocks is not None:
        glib.timeout_add(5, clocks.advance)

    # Observe the narrow race between the final setup checkpoint and loop entry
    # using the real GLib loop after actual OS signal delivery.
    original_run = glib.MainLoop.run

    def signal_before_run(loop):
        os.kill(os.getpid(), signal.SIGTERM)
        original_run(loop)

    args = ["suspend" if scenario == "setup_one_shot" else "run-cool",
            "--do-not-touch-backlight", "--no-color", "--log-file", str(root / "run.log")]
    if scenario not in {"lid", "suspends_ordinary"}:
        args.append("--ignore-lid")
    if scenario in {"no_plot", "lid_events_no_plot", "suspends_no_plot", "hibernates_no_plot"}:
        args.append("--no-plot")

    with contextlib.ExitStack() as boundaries, \
            mock.patch.object(gio, "bus_get_sync", side_effect=connect_bus), \
            mock.patch.object(gio.DBusProxy, "new_sync", side_effect=new_proxy):
        if clocks is not None:
            boundaries.enter_context(mock.patch.object(burnbag, "read_suspend_clocks", clocks.read))
            boundaries.enter_context(mock.patch.object(burnbag, "linux_boottime", clocks.boottime))
            boundaries.enter_context(mock.patch.object(burnbag, "read_sleep_journal", clocks.journal))
            boundaries.enter_context(mock.patch.object(burnbag.SuspendMonitor, "SAMPLE_SECONDS", 0.01))
        if scenario == "race":
            with mock.patch.object(glib.MainLoop, "run", signal_before_run):
                result = burnbag.main(args)
        else:
            try:
                result = burnbag.main(args)
            except SystemExit as exc:
                result = int(exc.code)

    if clocks is not None:
        assert clocks.final_sleep_read, "final suspend reconciliation was skipped"
    assert not any(thread.name == "burnbag-suspend-monitor" for thread in threading.enumerate()), \
        "suspend worker leaked beyond main()"
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
                if scenario in {"loop", "repeated", "no_plot", "setup", "setup_one_shot", "broken_output", "lid_events", "lid_events_no_plot"} | SLEEP_SCENARIOS:
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
        no_plot = scenario in {"no_plot", "lid_events_no_plot", "suspends_no_plot", "hibernates_no_plot"}
        self.assertEqual(output.count("BATTERY DEPLETION - 15-second samples"), 0 if no_plot else 1)
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
        if scenario in {"lid_events", "lid_events_no_plot"}:
            self.assertIn("close=2/open=2", output)
            self.assertEqual(final["final_state"]["lid_close_count"], 2)
            self.assertEqual(final["final_state"]["lid_open_count"], 2)
            transitions = [row for row in records if row["event"] in {"lid_closed", "lid_opened"}]
            self.assertEqual([row["details"]["closed"] for row in transitions], [True, False, True, False])
            self.assertTrue(all(row["details"]["timebase"] == "CLOCK_BOOTTIME" for row in transitions))
            battery_times = [row["details"]["elapsed_seconds"] for row in records if row["event"] == "battery_sample"]
            event_times = [row["details"]["elapsed_seconds"] for row in transitions]
            self.assertEqual(event_times, sorted(event_times))
            self.assertGreaterEqual(event_times[0], battery_times[0])
            self.assertLessEqual(event_times[-1], battery_times[-1])
            if no_plot:
                self.assertNotIn("Lid: C/|=close", output)
            else:
                self.assertIn("Lid: C/|=close", output)
                self.assertIn("O/:=open", output)
        if scenario in SLEEP_SCENARIOS:
            self.assertIn("Suspended Time", output)
            self.assertIn("3 observed interval(s), 15.000s total", output)
            self.assertNotIn("COVERAGE INCOMPLETE", output)
            intervals = [row["details"] for row in records if row["event"] == "suspend_interval"]
            summaries = [row["details"] for row in records if row["event"] == "suspend_monitor_summary"]
            self.assertEqual(len(intervals), 3)
            self.assertEqual(len(summaries), 1)
            summary = summaries[0]
            self.assertEqual(summary, final["final_state"]["suspend_monitor"])
            self.assertEqual(summary["interval_count"], 3)
            self.assertAlmostEqual(summary["total_suspended_seconds"], 15.0)
            self.assertTrue(summary["coverage_complete"])
            self.assertEqual(summary["errors"], [])
            for interval, duration in zip(intervals, (5.0, 7.0, 3.0)):
                self.assertAlmostEqual(interval["suspended_seconds"], duration)
                self.assertEqual(interval["timebase"], "CLOCK_BOOTTIME")
            self.assertLess(intervals[0]["end_elapsed_seconds"], intervals[1]["start_elapsed_seconds"])
            self.assertLess(intervals[1]["end_elapsed_seconds"], intervals[2]["start_elapsed_seconds"])
            battery_times = [row["details"]["elapsed_seconds"] for row in records if row["event"] == "battery_sample"]
            self.assertGreater(intervals[-1]["end_elapsed_seconds"], battery_times[-1])
            self.assertGreaterEqual(summary["coverage_end_elapsed_seconds"], intervals[-1]["end_elapsed_seconds"])
            self.assertLessEqual(summary["coverage_start_elapsed_seconds"], battery_times[0])
            self.assertEqual("Lid Events Detected" in output, scenario != "suspends_ordinary")
            if scenario in HIBERNATE_SCENARIOS:
                self.assertEqual(summary["sleep_kind_counts"], {"hibernate": 2, "suspend": 1, "unknown": 0})
                self.assertEqual(summary["type_classification"]["source"], "systemd-journal")
                self.assertEqual(summary["type_classification"]["classified_intervals"], 3)
                self.assertEqual([interval["sleep_kind"] for interval in intervals],
                                 ["hibernate", "suspend", "hibernate"])
                self.assertTrue(all(interval["classification_source"] == "systemd-journal" for interval in intervals))
                self.assertIn("suspend=1/hibernate=2/unverified=0", output)
            else:
                self.assertEqual(summary["sleep_kind_counts"], {"hibernate": 0, "suspend": 0, "unknown": 3})
            if no_plot:
                self.assertNotIn("Suspend: S=", output)
                self.assertNotIn("Hibernate: H=", output)
            else:
                self.assertIn("Suspend: S=suspended (full-height block)", output)
                rows = [row.split("|", 1)[1] for row in output.splitlines() if " |" in row]
                self.assertEqual(len(rows), 25)
                if scenario in HIBERNATE_SCENARIOS:
                    self.assertIn("Hibernate: H=hibernated (full-height block)", output)
                    start = summary["coverage_start_elapsed_seconds"]
                    span = summary["coverage_end_elapsed_seconds"] - start
                    masks = [0] * len(rows[0])
                    for interval in intervals:
                        left = round((interval["start_elapsed_seconds"] - start) / span * (len(masks) - 1))
                        right = round((interval["end_elapsed_seconds"] - start) / span * (len(masks) - 1))
                        for column in range(left, right + 1):
                            masks[column] |= 2 if interval["sleep_kind"] == "hibernate" else 1
                    self.assertIn(1, masks)
                    self.assertIn(2, masks)
                    for index, row in enumerate(rows):
                        for column, mask in enumerate(masks):
                            if mask:
                                expected = "H" if mask == 2 or (mask == 3 and index % 2 == 0) else "S"
                                self.assertEqual(row[column], expected)
                        self.assertEqual(row[-1], "H")
                else:
                    suspend_columns = [{i for i, cell in enumerate(row) if cell == "S"} for row in rows]
                    self.assertTrue(suspend_columns[0])
                    self.assertTrue(all(columns == suspend_columns[0] for columns in suspend_columns))

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

    def test_ignore_lid_transitions_reach_counts_graph_and_durable_log(self):
        self.run_scenario("lid_events")

    def test_ignore_lid_counts_survive_no_plot(self):
        self.run_scenario("lid_events_no_plot")

    def test_multiple_suspends_and_final_read_reach_graph_and_log_on_sigint(self):
        self.run_scenario("suspends")

    def test_suspend_summary_and_final_read_survive_no_plot(self):
        self.run_scenario("suspends_no_plot")

    def test_suspend_blocks_also_appear_with_ordinary_lid_policy(self):
        self.run_scenario("suspends_ordinary")

    def test_hibernate_and_suspend_evidence_reaches_graph_and_final_log_on_sigint(self):
        self.run_scenario("hibernates")

    def test_hibernate_classification_and_final_read_survive_no_plot(self):
        self.run_scenario("hibernates_no_plot")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        sys.exit(run_child(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])))
    unittest.main()
