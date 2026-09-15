"""Controller/recorder adapters with real local history and no host power calls."""

import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

import burnbag
import burnbag_history
import burnbag_service


class MemoryLog:
    failed_reason = None

    def __init__(self):
        self.records = []

    def append(self, event, level, message, details=None):
        self.records.append((event, level, message, details))


class FixtureSampler:
    def sample(self):
        return {"batteries": {"BAT0": {"percentage": 81.5, "status": "Discharging", "present": True}}, "errors": []}


class RecorderIntegrationTests(unittest.TestCase):
    def setUp(self):
        base = Path(__file__).resolve().parents[1] / ".local" / "tmp"
        base.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="recorder-integration-", dir=base)
        self.path = Path(self.temporary.name) / "user" / "history.sqlite3"
        self.address = "\0burnbag.integration." + uuid.uuid4().hex
        self.stack = contextlib.ExitStack()
        self.stack.enter_context(mock.patch.object(burnbag_service, "SOCKET_ADDRESS", self.address))
        self.stack.enter_context(mock.patch.object(burnbag_service, "_foreground_address", return_value=self.address + ".user"))
        self.stack.enter_context(mock.patch.object(burnbag_history, "user_database_path", return_value=self.path))
        self.stack.enter_context(mock.patch.object(burnbag_history, "PowerSampler", FixtureSampler))
        self.recorders = []

    def tearDown(self):
        for recorder in self.recorders:
            recorder.close()
        self.stack.close()
        self.temporary.cleanup()

    def manager(self, recorder, mode="run", log=None):
        manager = burnbag.LidCloseManager(
            mode=mode, suspend_after_minutes=None, no_inhibit_auto_suspend=False,
            ignore_lid=True, do_not_touch_backlight=True,
            terminal_style=burnbag.TerminalStyle(False, False), telemetry_recorder=recorder,
            running_log=log)
        manager.battery_monitor.devices = [burnbag.BatteryDevice("BAT0", Path("fixture-capacity"))]
        return manager

    def real_recorder(self):
        recorder = burnbag_service.ForegroundRecorder(on_warning=lambda _message: None)
        self.recorders.append(recorder)
        return recorder

    def test_initial_real_snapshot_is_ingested_without_controller_hardware_poll(self):
        recorder = self.real_recorder()
        log = MemoryLog()
        manager = self.manager(recorder, log=log)
        recorder.start()
        with mock.patch.object(manager.battery_monitor, "sample", side_effect=AssertionError("duplicate hardware poll")):
            sample = manager._take_battery_sample("initial")
            self.assertIsNotNone(sample)
            self.assertEqual(sample.percentages, {"BAT0": 82})
            self.assertIsNone(manager._take_battery_sample("periodic"))
        self.assertEqual(len(manager.battery_monitor.samples), 1)
        self.assertFalse(any(record[0] == "battery_sample" for record in log.records))
        self.assertTrue(recorder.flush())
        with contextlib.closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM records WHERE kind='sample'").fetchone()[0], 1)

    def test_snapshot_from_before_this_run_is_not_relabelled_as_current(self):
        recorder = SimpleNamespace(latest_snapshot=mock.Mock())
        manager = self.manager(recorder)
        recorder.latest_snapshot.return_value = {"captured_at": time.time() - 5,
            "boottime": manager.started_boottime - 5, "data": FixtureSampler().sample()}
        self.assertIsNone(manager._take_battery_sample("initial"))
        self.assertEqual(manager.battery_monitor.samples, [])
        recorder.latest_snapshot.return_value = {"captured_at": time.time(),
            "boottime": manager.started_boottime + 1, "data": FixtureSampler().sample()}
        self.assertIsNotNone(manager._take_battery_sample("periodic"))
        self.assertEqual(manager.battery_monitor.samples[0].elapsed_seconds, 1)

    def test_sample_arriving_during_close_is_included_in_final_graph_and_statistics(self):
        class DelayedRecorder:
            closed = False

            def latest_snapshot(self, timeout=0):
                return snapshot if self.closed else None

            def close(self):
                self.closed = True

        recorder = DelayedRecorder()
        manager = self.manager(recorder)
        snapshot = {"captured_at": time.time(), "boottime": manager.started_boottime + 0.1,
                    "data": FixtureSampler().sample()}
        manager.stop_battery_monitoring()
        self.assertEqual(manager.battery_statistics[0].valid_readings, 0)
        manager.goal_achieved = True
        manager.shutdown_reason = "Requested stop"
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            manager.print_shutdown_narrative()
        self.assertEqual(manager.battery_statistics[0].valid_readings, 1)
        self.assertIn("82%", output.getvalue())
        self.assertTrue(manager.telemetry_closed)

    def test_pre_sleep_flush_failure_prevents_the_power_call(self):
        recorder = SimpleNamespace(record_event=mock.Mock(), flush=mock.Mock(return_value=False))
        manager = self.manager(recorder, mode="suspend", log=MemoryLog())
        proxy = SimpleNamespace(call_sync=mock.Mock(return_value=SimpleNamespace(unpack=lambda: ("yes",))))
        manager.logind_proxy = proxy
        gio = SimpleNamespace(DBusCallFlags=SimpleNamespace(NONE=0))
        glib = SimpleNamespace(Variant=lambda *args: args)
        with mock.patch.object(burnbag, "Gio", gio), mock.patch.object(burnbag, "GLib", glib), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(burnbag.ShutdownRequested):
                manager.execute_immediate_action()
        self.assertEqual([call.args[0] for call in proxy.call_sync.call_args_list], ["CanSuspend"])
        self.assertEqual(manager.exit_code, 1)
        self.assertTrue(manager.stop_requested)

    def test_pre_sleep_intent_reaches_real_database_before_adapter_returns(self):
        recorder = self.real_recorder()
        manager = self.manager(recorder, log=MemoryLog())
        recorder.start()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            manager._append_running_log("suspend_request_intent", "INFO", "Preparing to suspend", {"source": "test"})
        self.assertEqual(manager.exit_code, 0)
        with contextlib.closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute("SELECT data FROM records WHERE kind='suspend_request_intent'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0][0])["source"], "test")

    def test_recorder_close_failure_changes_reported_mission_status(self):
        recorder = SimpleNamespace(latest_snapshot=lambda timeout=0: None,
                                   close=mock.Mock(side_effect=RuntimeError("disk synchronization failed")))
        manager = self.manager(recorder)
        manager.goal_achieved = True
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            manager.print_shutdown_narrative()
        self.assertFalse(manager.goal_achieved)
        self.assertEqual(manager.exit_code, 1)
        self.assertTrue(any("disk synchronization failed" in deviation for deviation in manager.deviations))

    def test_worker_diagnostic_is_synchronized_only_when_main_thread_drains(self):
        log_path = Path(self.temporary.name) / "operational.log"
        log = burnbag.RunningLog.open(log_path, "run", time.monotonic())
        try:
            log.start_session({})
            manager = self.manager(None, log=log)
            diagnostics = burnbag.TelemetryDiagnostics()
            manager.telemetry_diagnostics = diagnostics
            worker = threading.Thread(target=diagnostics.put, args=("Collector storage is degraded",))
            worker.start()
            worker.join(timeout=1)
            self.assertNotIn("Collector storage is degraded", log_path.read_text())
            synchronized_on = []
            original_fsync = os.fsync

            def fsync(descriptor):
                synchronized_on.append(threading.get_ident())
                return original_fsync(descriptor)

            with mock.patch.object(burnbag.os, "fsync", side_effect=fsync), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                manager.check_shutdown_requested()
            records = [json.loads(line) for line in log_path.read_text().splitlines()]
            self.assertTrue(any(record.get("message") == "Collector storage is degraded" for record in records))
            self.assertEqual(synchronized_on, [threading.get_ident()])
        finally:
            log.close()


if __name__ == "__main__":
    unittest.main()
