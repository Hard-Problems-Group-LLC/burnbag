"""Actual suspended time, placement uncertainty, and safe monitor ownership."""

import contextlib
from datetime import datetime, timedelta, timezone
import io
import math
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import burnbag


class SuspendMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.wall = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)

    def clock(self, elapsed, awake=None, wall_offset=0, uncertainty=0.000001):
        return burnbag.SuspendClockSample(
            self.wall + timedelta(seconds=elapsed + wall_offset),
            1000.0 + elapsed, 100.0 + (elapsed if awake is None else awake),
            uncertainty,
        )

    def monitor(self, **kwargs):
        return burnbag.SuspendMonitor(1000.0, self.clock(0), **kwargs)

    def test_awake_delays_and_wall_clock_changes_do_not_become_suspend(self):
        monitor = self.monitor()
        for elapsed, offset in ((1, 0), (100, 7200), (5000, -3600)):
            monitor.observe(self.clock(elapsed, wall_offset=offset))
        self.assertEqual(monitor.intervals, [])
        self.assertEqual(monitor.to_log_details()["total_suspended_seconds"], 0)

    def test_multiple_sleeps_have_measured_duration_and_bounded_placement(self):
        monitor = self.monitor()
        monitor.observe(self.clock(1))
        monitor.observe(self.clock(62, awake=2))
        monitor.observe(self.clock(63, awake=3))
        monitor.observe(self.clock(84, awake=4))
        self.assertEqual(len(monitor.intervals), 2)
        first, second = monitor.intervals
        self.assertAlmostEqual(first.start_elapsed_seconds, 1.5)
        self.assertAlmostEqual(first.end_elapsed_seconds, 61.5)
        self.assertAlmostEqual(second.start_elapsed_seconds, 63.5)
        self.assertAlmostEqual(second.end_elapsed_seconds, 83.5)
        self.assertAlmostEqual(first.boundary_uncertainty_seconds, 0.500002)
        self.assertEqual(first.started_at, self.wall + timedelta(seconds=1.5))
        self.assertEqual(monitor.to_log_details()["total_suspended_seconds"], 80)
        self.assertEqual(first.to_log_details()["timebase"], "CLOCK_BOOTTIME")

    def test_delayed_sampling_expands_boundary_uncertainty_not_sleep_duration(self):
        monitor = self.monitor()
        monitor.observe(self.clock(160, awake=100))
        interval = monitor.intervals[0]
        self.assertEqual(interval.end_elapsed_seconds - interval.start_elapsed_seconds, 60)
        self.assertAlmostEqual(interval.boundary_uncertainty_seconds, 50.000002)
        self.assertEqual(interval.observed_start_elapsed_seconds, 0)
        self.assertEqual(interval.observed_end_elapsed_seconds, 160)

    def test_subthreshold_sleeps_accumulate_and_offset_jitter_is_not_double_counted(self):
        monitor = self.monitor()
        monitor.observe(self.clock(1, awake=0.9994))
        self.assertEqual(monitor.intervals, [])
        monitor.observe(self.clock(2, awake=1.9988))
        self.assertEqual(len(monitor.intervals), 1)
        self.assertAlmostEqual(monitor.to_log_details()["total_suspended_seconds"], 0.0012)
        monitor.observe(self.clock(3.000001, awake=2.9988))
        monitor.observe(self.clock(4, awake=3.9988))
        self.assertEqual(len(monitor.intervals), 1)
        self.assertAlmostEqual(monitor.to_log_details()["total_suspended_seconds"], 0.0012)

    def test_read_uncertainty_prevents_false_suspend(self):
        monitor = self.monitor()
        monitor.observe(self.clock(1.004, awake=1, uncertainty=0.01))
        monitor.observe(self.clock(2, awake=2))
        self.assertEqual(monitor.intervals, [])

    def test_final_read_covers_setup_and_post_teardown_sleep_without_loop(self):
        monitor = self.monitor(reader=lambda: self.clock(65, awake=5))
        monitor.finish()
        monitor.finish()
        self.assertEqual(len(monitor.intervals), 1)
        self.assertEqual(monitor.to_log_details()["total_suspended_seconds"], 60)
        self.assertTrue(monitor.to_log_details()["coverage_complete"])
        self.assertEqual(monitor.to_log_details()["coverage_end_elapsed_seconds"], 65)

    def test_read_failure_retains_evidence_and_marks_coverage_incomplete(self):
        calls = iter((self.clock(31, awake=1), OSError("clock unavailable"), self.clock(52, awake=2)))

        def reader():
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value

        monitor = self.monitor(reader=reader)
        self.assertTrue(monitor.sample())
        self.assertFalse(monitor.sample())
        monitor.finish()
        self.assertEqual(len(monitor.intervals), 2)
        self.assertEqual(monitor.to_log_details()["total_suspended_seconds"], 50)
        self.assertFalse(monitor.to_log_details()["coverage_complete"])
        self.assertIn("clock unavailable", monitor.errors[0])

    def test_backwards_and_nonfinite_clocks_cannot_create_regions(self):
        for observation in (self.clock(-1), self.clock(1, awake=3),
                            burnbag.SuspendClockSample(self.wall, math.nan, 100)):
            with self.subTest(observation=observation):
                monitor = self.monitor(reader=lambda: observation)
                monitor.finish()
                self.assertEqual(monitor.intervals, [])
                self.assertFalse(monitor.to_log_details()["coverage_complete"])

    def test_missing_clock_is_explicitly_unavailable(self):
        with mock.patch.object(burnbag.time, "CLOCK_BOOTTIME", None):
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                burnbag.read_suspend_clocks()

    def test_clock_capture_brackets_wall_time_and_chooses_tight_pair(self):
        clock_values = iter((1000, 1100, 1100, 1100.000002, 1101, 1101.001))
        with mock.patch.object(burnbag.time, "clock_gettime", side_effect=lambda _: next(clock_values)), \
                mock.patch.object(burnbag.time, "monotonic", side_effect=(100, 100.000001, 101)):
            sample = burnbag.read_suspend_clocks()
        self.assertAlmostEqual(sample.boottime, 1100.000001)
        self.assertAlmostEqual(sample.uncertainty_seconds, 0.000001)

    def test_worker_runs_independently_and_is_joined_before_final_read(self):
        observed_by_worker = threading.Event()
        reads = []

        def reader():
            is_worker = threading.current_thread().name == "burnbag-suspend-monitor"
            reads.append(is_worker)
            if is_worker:
                observed_by_worker.set()
            return self.clock(32, awake=2)

        monitor = self.monitor(reader=reader)
        monitor.SAMPLE_SECONDS = 0.001
        try:
            monitor.start()
            self.assertTrue(observed_by_worker.wait(2))
        finally:
            monitor.finish()
        self.assertFalse(monitor._thread.is_alive())
        self.assertFalse(reads[-1])
        self.assertEqual(len(monitor.intervals), 1)
        self.assertEqual(monitor.to_log_details()["total_suspended_seconds"], 30)

    def test_shutdown_reports_missing_coverage_without_claiming_no_suspend(self):
        manager = burnbag.LidCloseManager("run", None, False, True, do_not_touch_backlight=True)
        manager.suspend_monitor = self.monitor(reader=lambda: (_ for _ in ()).throw(OSError("clock failed")))
        manager.suspend_monitor.started = True
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            manager.print_shutdown_narrative()
        self.assertIn("COVERAGE INCOMPLETE", output.getvalue())
        self.assertIn("Unknown; no intervals verified", output.getvalue())
        self.assertNotIn("None detected", output.getvalue())
        self.assertIn("1 deviation(s) recorded", output.getvalue())
        self.assertIn("Suspend detection coverage is incomplete", manager.deviations[0])

    def test_timed_out_worker_cannot_change_report_after_finalization(self):
        worker_entered = threading.Event()
        release_worker = threading.Event()

        def reader():
            if threading.current_thread().name == "burnbag-suspend-monitor":
                worker_entered.set()
                if not release_worker.wait(2):
                    raise RuntimeError("test did not release worker")
                return self.clock(65, awake=5)
            return self.clock(1)

        monitor = self.monitor(reader=reader)
        monitor.SAMPLE_SECONDS = 0.001
        monitor.WORKER_JOIN_SECONDS = 0.001
        try:
            monitor.start()
            self.assertTrue(worker_entered.wait(2))
            monitor.finish()
            final = monitor.to_log_details()
            self.assertFalse(final["coverage_complete"])
        finally:
            release_worker.set()
            monitor.finish()
            monitor._thread.join(timeout=2)
        self.assertFalse(monitor._thread.is_alive())
        self.assertEqual(monitor.to_log_details(), final)
        self.assertEqual(monitor.intervals, [])

    def test_log_sync_failure_keeps_detected_region_and_shutdown_report(self):
        temporary_root = Path(__file__).resolve().parents[1] / ".local" / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="suspend-log-failure.", dir=temporary_root) as directory:
            log = burnbag.RunningLog.open(
                Path(directory) / "run.log", mode="run", started_monotonic=time.monotonic(),
            )
            log.start_session({})
            self.addCleanup(log.close)
            manager = burnbag.LidCloseManager(
                "run", None, False, True, do_not_touch_backlight=True, running_log=log,
                started_boottime=1000, terminal_style=burnbag.TerminalStyle(False, False),
            )
            manager.suspend_monitor = self.monitor(reader=lambda: self.clock(31, awake=1))
            manager.suspend_monitor.started = True
            manager.battery_monitor.devices = [burnbag.BatteryDevice("BAT0", Path("/unused"))]
            manager.battery_monitor.samples = [burnbag.BatterySample(self.wall, 0, {"BAT0": 80})]
            with contextlib.redirect_stdout(io.StringIO()) as output, \
                    contextlib.redirect_stderr(io.StringIO()), \
                    mock.patch.object(burnbag.os, "fsync", side_effect=OSError("injected fsync failure")):
                manager.print_shutdown_narrative()
            self.assertEqual(manager.exit_code, 1)
            self.assertEqual(len(manager.suspend_monitor.intervals), 1)
            self.assertIn("1 observed interval(s), 30.000s total", output.getvalue())
            self.assertIn("Suspend: S=suspended", output.getvalue())
            self.assertEqual(output.getvalue().count("BURNBAG — SHUTDOWN & TEARDOWN"), 1)
            self.assertIsNone(log.file_descriptor)


if __name__ == "__main__":
    unittest.main()
