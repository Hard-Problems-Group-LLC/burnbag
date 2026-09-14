"""Failure boundaries must preserve recovery, reporting, and durable outcomes."""

from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import burnbag


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FailingStream(io.StringIO):
    def __init__(self, fail_on_flush=False):
        super().__init__()
        self.fail_on_flush = fail_on_flush

    def write(self, text):
        if not self.fail_on_flush:
            raise BrokenPipeError("injected closed output consumer")
        return super().write(text)

    def flush(self):
        if self.fail_on_flush:
            raise OSError("injected buffered output failure")


class TimerBoundary:
    @staticmethod
    def timeout_add(*unused):
        return 42

    @staticmethod
    def source_remove(source_id):
        return True


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        local_tmp = PROJECT_ROOT / ".local" / "tmp"
        local_tmp.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="error-handling-test.", dir=local_tmp)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.log_path = self.root / "run.log"
        self.log = burnbag.RunningLog.open(self.log_path, "run", 0.0)
        self.log.start_session({})
        self.addCleanup(self.log.close)
        self.manager = burnbag.LidCloseManager(
            "run", None, False, True, do_not_touch_backlight=True,
            terminal_style=burnbag.TerminalStyle(False, False), running_log=self.log,
        )
        self.glib = mock.patch.object(burnbag, "GLib", TimerBoundary)
        self.glib.start()
        self.addCleanup(self.glib.stop)
        supply = self.root / "power_supply" / "BAT0"
        supply.mkdir(parents=True)
        for name, value in {"type": "Battery", "capacity": "80"}.items():
            (supply / name).write_text(value + "\n", encoding="ascii")
        self.manager.battery_monitor = burnbag.BatteryMonitor(supply.parent, self.manager.started_boottime)
        self.manager.start_battery_monitoring()
        self.descriptor = os.open(os.devnull, os.O_RDONLY)
        self.manager.inhibitor_fds.append(self.descriptor)
        self.addCleanup(self.close_descriptor_if_open)

    def close_descriptor_if_open(self):
        try:
            os.close(self.descriptor)
        except OSError:
            pass

    def final_record(self):
        rows = [json.loads(line) for line in self.log_path.read_text().splitlines()]
        self.assertEqual(rows[-1]["event"], "session_end")
        self.assertEqual(sum(row["event"] == "session_end" for row in rows), 1)
        final = rows[-1]["details"]
        self.assertEqual(final["exit_code"], 1)
        self.assertFalse(final["goal_achieved"])
        self.assertIsNone(self.log.file_descriptor)
        return final

    def assert_released(self):
        with self.assertRaises(OSError):
            os.fstat(self.descriptor)

    def test_each_cleanup_failure_leaves_remaining_actions_available(self):
        calls = []
        original_stop = self.manager.stop_battery_monitoring

        def sample_then_fail():
            original_stop()
            raise RuntimeError("injected observer failure after final sample")

        def restore_backlights():
            calls.append("backlight")
            raise RuntimeError("injected restoration failure")

        def restore_profile():
            calls.append("profile")
            raise RuntimeError("injected profile recovery failure")

        with mock.patch.object(self.manager, "stop_battery_monitoring", sample_then_fail), \
                mock.patch.object(self.manager, "restore_backlights", restore_backlights), \
                mock.patch.object(self.manager, "restore_power_profile", restore_profile), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.manager.teardown()
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assertEqual(calls, ["backlight", "profile"])
        self.assert_released()
        final = self.final_record()
        self.assertEqual(final["final_state"]["battery_sample_count"], 2)
        self.assertEqual(len(final["deviations"]), 3)

    def test_timer_cancellation_failure_does_not_skip_recovery(self):
        self.manager.backlight_timer_id = 24
        self.manager.suspend_timer_id = 25
        with mock.patch.object(TimerBoundary, "source_remove", side_effect=RuntimeError("timer backend failed")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assert_released()
        final = self.final_record()
        self.assertEqual(final["final_state"]["battery_sample_count"], 2)

    def test_broken_stdout_uses_stderr_and_records_failure(self):
        errors = io.StringIO()
        with contextlib.redirect_stdout(FailingStream()), contextlib.redirect_stderr(errors):
            self.manager._info("Trigger closed consumer")
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assert_released()
        self.assertIn("BATTERY DEPLETION", errors.getvalue())
        self.assertIn("BATTERY SUMMARY", errors.getvalue())
        self.assertNotIn("ACHIEVED SUCCESSFULLY", errors.getvalue())
        final = self.final_record()
        self.assertTrue(final["final_state"]["terminal_output_failed"])
        self.assertEqual(final["final_state"]["battery_sample_count"], 2)

    def test_both_output_streams_can_fail_without_skipping_recovery_or_log(self):
        with contextlib.redirect_stdout(FailingStream()), contextlib.redirect_stderr(FailingStream()):
            self.manager._warn("External service failed")
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assert_released()
        final = self.final_record()
        self.assertEqual(final["final_state"]["battery_sample_count"], 2)
        self.assertEqual(len(self.manager.failed_output_streams), 2)

    def test_flush_failure_is_observed_before_session_end(self):
        with contextlib.redirect_stdout(FailingStream(fail_on_flush=True)), \
                contextlib.redirect_stderr(io.StringIO()):
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assertTrue(self.final_record()["final_state"]["terminal_output_failed"])

    def test_narrative_failure_still_displays_graph_and_statistics(self):
        output = io.StringIO()
        with mock.patch.object(self.manager, "_render_shutdown_fields", side_effect=RuntimeError("narrative failed")), \
                contextlib.redirect_stdout(output):
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assertIn("BATTERY DEPLETION", output.getvalue())
        self.assertIn("BATTERY SUMMARY", output.getvalue())
        self.final_record()

    def test_chart_failure_still_displays_statistics(self):
        output = io.StringIO()
        with mock.patch.object(burnbag, "render_battery_depletion_chart", side_effect=RuntimeError("chart failed")), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assertIn("BATTERY SUMMARY", output.getvalue())
        self.final_record()

    def test_statistics_failure_still_displays_chart(self):
        output = io.StringIO()
        with mock.patch.object(burnbag, "render_battery_statistics", side_effect=RuntimeError("statistics failed")), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assertIn("BATTERY DEPLETION", output.getvalue())
        self.final_record()

    def test_unexpected_session_end_error_still_closes_log(self):
        with mock.patch.object(self.log, "end_session", side_effect=ValueError("invalid final data")), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assertIsNone(self.log.file_descriptor)
        self.assertEqual(self.manager.exit_code, 1)

    def test_bad_statistics_serialization_preserves_minimal_session_end(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.manager.teardown()
            with mock.patch.object(burnbag.BatteryStatistics, "to_log_details", side_effect=ValueError("bad derived field")):
                self.manager.print_shutdown_narrative()
        final = self.final_record()
        self.assertEqual(final["final_state"]["battery_statistics"], [])
        self.assertTrue(any("serialize battery statistics" in item for item in final["deviations"]))

    def test_fsync_and_both_terminal_failures_cannot_skip_recovery(self):
        with contextlib.redirect_stdout(FailingStream()), contextlib.redirect_stderr(FailingStream()):
            with mock.patch.object(burnbag.os, "fsync", side_effect=OSError("storage failed")):
                with self.assertRaises(burnbag.RunningLogError):
                    self.manager._info("Durability boundary")
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assert_released()
        self.assertIsNone(self.log.file_descriptor)
        self.assertEqual(len(self.manager.battery_monitor.samples), 2)
        self.assertEqual(self.manager.exit_code, 1)

    def test_lid_goal_cannot_overwrite_operational_failure_in_final_report(self):
        self.manager.exit_code = 1
        self.manager.goal_achieved = True
        self.manager.deviations.append("Earlier battery observation failed")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.manager.teardown()
            self.manager.print_shutdown_narrative()
        self.assertNotIn("ACHIEVED SUCCESSFULLY", output.getvalue())
        self.final_record()

    def test_invalid_timer_values_are_usage_errors_without_starting_session(self):
        for value in ("0", "-1", "invalid", "999999999999999999999999"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()):
                path = self.root / "rejected.log"
                with self.assertRaises(SystemExit) as exited:
                    burnbag.main(["run", "--suspend-after-minutes", value, "--log-file", str(path)])
                self.assertEqual(exited.exception.code, 2)
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
