"""Real local IPC and SQLite tests; no host services, privilege, or power actions."""

import contextlib
import errno
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock
import uuid
from types import SimpleNamespace

import burnbag_history
import burnbag_service as service


class Sampler:
    def sample(self):
        return {"batteries": {"test": {"percentage": 72.0, "energy_wh": 40.0}}, "errors": []}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".local" / "tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="service-test-", dir=root)
        self.path = Path(self.temporary.name) / "state" / "history.sqlite3"
        self.address = "\0burnbag.test." + uuid.uuid4().hex
        self.foreground_address = self.address + ".foreground"
        self.patches = [mock.patch.object(service, "SOCKET_ADDRESS", self.address),
                        mock.patch.object(service, "_foreground_address", return_value=self.foreground_address),
                        mock.patch.object(burnbag_history, "user_database_path", return_value=self.path),
                        mock.patch.object(burnbag_history, "PowerSampler", Sampler)]
        for patch in self.patches:
            patch.start()
        self.collectors = []
        self.recorders = []

    def tearDown(self):
        for recorder in self.recorders:
            recorder.close()
        for collector in self.collectors:
            collector.close()
        for patch in reversed(self.patches):
            patch.stop()
        self.temporary.cleanup()

    def collector(self, **kwargs):
        collector = service._Collector("user", on_warning=lambda _message: None, **kwargs)
        self.collectors.append(collector)
        collector.start()
        return collector

    def wait_for(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Timed out waiting for collector state")

    def records(self, kind):
        with contextlib.closing(sqlite3.connect(self.path)) as connection:
            return [json.loads(row[0]) for row in connection.execute("SELECT data FROM records WHERE kind=?", (kind,))]

    def test_absent_probe_is_read_only_and_warning_is_explicit(self):
        self.assertEqual(service.probe_service()["status"], "absent")
        self.assertFalse(self.path.exists())
        self.assertIn("NOT RUNNING", service.warning_for_service(service.probe_service()))

    def test_atomic_background_singleton_and_kernel_owned_lifetime(self):
        first = self.collector()
        second = service._Collector("user", on_warning=lambda _message: None)
        with self.assertRaises(OSError) as raised:
            second.start()
        self.assertEqual(raised.exception.errno, errno.EADDRINUSE)
        second.close()
        self.assertEqual(service.probe_service()["status"], "ready")
        first.close()
        self.assertEqual(service.probe_service()["status"], "absent")
        self.collector()
        self.assertEqual(service.probe_service()["status"], "ready")

    def test_real_sampling_snapshot_event_and_durable_flush(self):
        collector = self.collector()
        self.wait_for(lambda: service.connect_snapshot() is not None)
        snapshot = service.connect_snapshot()
        self.assertEqual(snapshot["data"]["batteries"]["test"]["percentage"], 72.0)
        self.assertGreater(snapshot["boottime"], 0)
        self.assertGreater(snapshot["captured_at"], 0)
        service._request("event", payload={"kind": "run_started", "data": {"mode": "run"}})
        self.assertTrue(service.flush_service())
        self.assertEqual(self.records("run_started")[0]["mode"], "run")
        self.assertTrue(self.records("sample"))
        self.assertTrue(collector.writer.status()["healthy"])

    def test_prudent_leases_overlap_without_undoing_another_caller(self):
        collector = self.collector()
        first, second = service.lease_prudent(), service.lease_prudent()
        try:
            self.assertTrue(collector.writer.status()["prudent"])
            self.assertEqual(collector.leases, 2)
            first.close()
            self.wait_for(lambda: collector.leases == 1)
            self.assertTrue(collector.writer.status()["prudent"])
            second.close()
            self.wait_for(lambda: collector.leases == 0)
            self.assertFalse(collector.writer.status()["prudent"])
        finally:
            first.close()
            second.close()

    def test_prudent_baseline_survives_client_disconnect(self):
        collector = self.collector(prudent=True)
        with service.lease_prudent():
            self.assertTrue(collector.writer.status()["prudent"])
        self.wait_for(lambda: collector.leases == 0)
        self.assertTrue(collector.writer.status()["prudent"])

    def test_lease_detects_daemon_exit(self):
        collector = self.collector()
        lease = service.lease_prudent()
        self.assertTrue(lease.alive())
        collector.close()
        self.wait_for(lambda: not lease.alive())
        lease.close()

    def test_foreign_status_redacts_private_paths_and_writer_details(self):
        collector = self.collector()
        foreign = collector.status(os.geteuid() + 10000)
        self.assertNotIn("database", foreign)
        self.assertEqual(set(foreign["health"]), {"healthy"})
        with mock.patch.object(service, "_request", return_value=dict(foreign, uid=os.geteuid() + 10000)):
            result = service.probe_service()
        self.assertEqual(result["status"], "foreign")
        self.assertIn("private", service.warning_for_service(result))

    def test_unknown_operations_and_forged_collector_samples_are_rejected(self):
        self.collector()
        with self.assertRaisesRegex(RuntimeError, "Unknown"):
            service._request("execute_sql")
        with self.assertRaisesRegex(RuntimeError, "Collector-owned"):
            service._request("event", payload={"kind": "sample", "data": {}})

    def test_background_observed_lid_events_are_not_duplicated_by_clients(self):
        self.collector()
        result = service._request("event", payload={"kind": "lid_closed", "data": {"closed": True}})
        self.assertTrue(result["ignored"])
        service.flush_service()
        self.assertEqual(self.records("lid_closed"), [])

    def test_mismatched_peer_identity_is_unhealthy_not_absent(self):
        self.collector()
        with mock.patch.object(service, "_credentials", return_value=(os.getpid() + 1, os.geteuid(), os.getegid())):
            status = service.probe_service()
        self.assertEqual(status["status"], "unhealthy")
        self.assertIn("verified", status["reason"])

    def test_stalled_sampling_marks_service_unhealthy(self):
        collector = self.collector()
        with mock.patch.object(service.time, "monotonic", return_value=collector.sampling_progress + 100):
            self.assertFalse(collector.status(os.geteuid())["health"]["healthy"])

    def test_foreground_fallback_shares_one_collector_and_records_early_event(self):
        first = service.ForegroundRecorder(on_warning=lambda _message: None).start()
        self.recorders.append(first)
        first.record_event("lid_closed", {"closed": True})
        second = service.ForegroundRecorder(prudent=True, on_warning=lambda _message: None).start()
        self.recorders.append(second)
        self.wait_for(lambda: first.latest_snapshot() is not None and second.latest_snapshot() is not None)
        self.assertEqual(sum(recorder.collector is not None for recorder in (first, second)), 1)
        self.assertTrue(first.flush())
        self.assertEqual(len(self.records("lid_closed")), 1)
        self.assertEqual(service.probe_service()["status"], "absent")

    def test_fallback_follower_takes_over_after_owner_exits(self):
        first = service.ForegroundRecorder(on_warning=lambda _message: None).start()
        self.recorders.append(first)
        self.wait_for(lambda: first.latest_snapshot() is not None)
        second = service.ForegroundRecorder(on_warning=lambda _message: None).start()
        self.recorders.append(second)
        self.wait_for(lambda: second.latest_snapshot() is not None)
        first.close()
        self.wait_for(lambda: second.collector is not None)
        self.assertTrue(second.flush())

    def test_manage_enable_does_not_start_or_pick_ambiguous_scope(self):
        states = {"LoadState": "loaded", "ActiveState": "inactive", "UnitFileState": "disabled"}
        with mock.patch.object(service, "_unit_state", return_value=states), \
             mock.patch.object(service.subprocess, "run") as run, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(service.manage_service("enable"), 2)
            run.assert_not_called()
            run.return_value.returncode = 0
            self.assertEqual(service.manage_service("enable", "user"), 0)
            command = run.call_args[0][0]
            self.assertIn("enable", command)
            self.assertNotIn("--now", command)
            self.assertIn("--user", command)

    def test_total_response_deadline_rejects_slow_drip_peer(self):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(self.address)
        listener.listen(1)

        def trickle():
            connection, _ = listener.accept()
            try:
                connection.recv(1024)
                for _ in range(50):
                    connection.sendall(b" ")
                    time.sleep(0.02)
            except OSError:
                pass
            finally:
                connection.close()

        thread = threading.Thread(target=trickle, daemon=True)
        thread.start()
        try:
            started = time.monotonic()
            self.assertEqual(service.probe_service(timeout=0.12)["status"], "unhealthy")
            self.assertLess(time.monotonic() - started, 0.35)
        finally:
            listener.close()
            thread.join(timeout=1)

    def test_foreground_handoff_to_service_and_back_preserves_events(self):
        recorder = service.ForegroundRecorder(prudent=True, on_warning=lambda _message: None).start()
        self.recorders.append(recorder)
        self.wait_for(lambda: recorder.latest_snapshot() is not None)
        foreground = recorder.collector
        collector = self.collector()
        self.wait_for(lambda: recorder.address == self.address and foreground.delegated)
        self.wait_for(lambda: collector.writer.status()["prudent"])
        recorder.record_event("run_started", {"handoff": True}, urgent=True)
        self.assertTrue(recorder.flush())
        collector.close()
        self.wait_for(lambda: recorder.address == self.foreground_address and not foreground.delegated)
        recorder.record_event("lid_opened", {"closed": False}, urgent=True)
        self.assertTrue(recorder.flush())
        self.assertEqual(len(self.records("run_started")), 1)
        self.assertEqual(len(self.records("lid_opened")), 1)

    def test_unaccepted_event_is_visible_at_close_after_cleanup(self):
        recorder = service.ForegroundRecorder(on_warning=lambda _message: None).start()
        self.recorders.append(recorder)
        self.wait_for(lambda: recorder.latest_snapshot() is not None)
        recorder.record_event("broken", {"not_json": object()})
        with self.assertRaisesRegex(RuntimeError, "not accepted"):
            recorder.close()
        self.assertTrue(recorder.closed)
        recorder.close()

    def test_dbus_lid_signal_records_one_original_event(self):
        collector = self.collector()
        observer = service._BusObserver(collector)
        observer.lid_state = False
        parameters = SimpleNamespace(unpack=lambda: ("org.freedesktop.UPower", {"LidIsClosed": True}, []))
        observer._signal(None, "org.freedesktop.UPower", "/org/freedesktop/UPower",
                         "org.freedesktop.DBus.Properties", "PropertiesChanged", parameters, None)
        collector.writer.flush()
        self.assertEqual(len(self.records("lid_closed")), 1)

    def test_prepare_sleep_releases_delay_even_when_record_submission_fails(self):
        collector = self.collector()
        observer = service._BusObserver(collector)
        parameters = SimpleNamespace(unpack=lambda: (True,))
        with mock.patch.object(collector.writer, "submit", side_effect=RuntimeError("disk failed")), \
             mock.patch.object(observer, "_release") as release:
            observer._signal(None, "org.freedesktop.login1", "/org/freedesktop/login1",
                             "org.freedesktop.login1.Manager", "PrepareForSleep", parameters, None)
        release.assert_called_once_with("sleep")

    def test_clock_verified_sleep_survives_classifier_failure(self):
        import burnbag
        from datetime import datetime, timezone, timedelta
        collector = self.collector()
        started = datetime.now(timezone.utc)
        interval = burnbag.SuspendInterval(started, started + timedelta(seconds=3), 2.0, 5.0)
        collector.monitor = SimpleNamespace(_lock=threading.Lock(), intervals=[interval], finish=lambda: None)
        collector.runtime = SimpleNamespace(classify_sleep_intervals=mock.Mock(side_effect=RuntimeError("journal unavailable")))
        collector._drain_sleep()
        collector.writer.flush()
        recorded = self.records("sleep_interval")
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["sleep_kind"], "unknown")
        self.assertEqual(recorded[0]["end_boottime"] - recorded[0]["start_boottime"], 3.0)

    def test_lid_baseline_duplicates_and_invalid_types_do_not_inflate_events(self):
        collector = self.collector()
        observer = service._BusObserver(collector)
        for value in (False, False, "closed", True, True, False, False):
            parameters = SimpleNamespace(unpack=lambda value=value: ("org.freedesktop.UPower", {"LidIsClosed": value}, []))
            observer._signal(None, "org.freedesktop.UPower", "/org/freedesktop/UPower",
                             "org.freedesktop.DBus.Properties", "PropertiesChanged", parameters, None)
        collector.writer.flush()
        self.assertEqual(len(self.records("lid_closed")), 1)
        self.assertEqual(len(self.records("lid_opened")), 1)
        self.assertTrue(self.records("observer_coverage"))

    def test_invalidated_lid_is_reread_before_recording_transition(self):
        collector = self.collector()
        observer = service._BusObserver(collector)
        observer.lid_state = False
        parameters = SimpleNamespace(unpack=lambda: ("org.freedesktop.UPower", {}, ["LidIsClosed"]))
        with mock.patch.object(observer, "_properties", return_value={"LidIsClosed": True}) as read:
            observer._signal(None, "org.freedesktop.UPower", "/org/freedesktop/UPower",
                             "org.freedesktop.DBus.Properties", "PropertiesChanged", parameters, None)
        read.assert_called_once()
        collector.writer.flush()
        self.assertEqual(len(self.records("lid_closed")), 1)

    def test_snapshot_wait_is_bounded_and_caller_cannot_mutate_shared_record(self):
        recorder = service.ForegroundRecorder(on_warning=lambda _message: None)
        started = time.monotonic()
        self.assertIsNone(recorder.latest_snapshot(timeout=0.06))
        self.assertLess(time.monotonic() - started, 0.18)
        recorder.start()
        self.recorders.append(recorder)
        snapshot = recorder.latest_snapshot(timeout=1.0)
        self.assertIsNotNone(snapshot)
        snapshot["data"]["batteries"]["test"]["percentage"] = 0
        self.assertEqual(recorder.latest_snapshot()["data"]["batteries"]["test"]["percentage"], 72.0)

    def test_snapshot_retains_newest_local_observation_after_coordinator_stops(self):
        recorder = service.ForegroundRecorder(on_warning=lambda _message: None).start()
        self.recorders.append(recorder)
        self.assertIsNotNone(recorder.latest_snapshot(timeout=1))
        recorder.stop.set()
        recorder.thread.join(timeout=1)
        collector = recorder.collector
        newest = {"captured_at": time.time(), "boottime": service._boottime() + 1,
                  "data": {"batteries": {"test": {"percentage": 71.0}}}}
        collector._publish_snapshot(newest)
        self.assertEqual(recorder.latest_snapshot()["data"]["batteries"]["test"]["percentage"], 71.0)
        recorder.close()
        self.assertEqual(recorder.latest_snapshot()["data"]["batteries"]["test"]["percentage"], 71.0)

    def test_flush_lookup_without_any_collector_creates_nothing(self):
        self.assertIsNone(service.flush_service(timeout=0.5))
        self.assertFalse(self.path.exists())

    def test_flush_lookup_uses_existing_same_user_foreground_collector(self):
        recorder = service.ForegroundRecorder(on_warning=lambda _message: None).start()
        self.recorders.append(recorder)
        self.assertIsNotNone(recorder.latest_snapshot(timeout=1))
        self.assertTrue(service.flush_service(timeout=1))
        self.assertTrue(self.records("sample"))

    def test_flush_lookup_prefers_ready_background(self):
        collector = self.collector()
        with mock.patch.object(collector.writer, "flush", wraps=collector.writer.flush) as flush:
            self.assertTrue(service.flush_service(timeout=1))
        flush.assert_called_once()

    def test_foreign_or_unhealthy_background_uses_private_foreground_flush(self):
        recorder = service.ForegroundRecorder(on_warning=lambda _message: None).start()
        self.recorders.append(recorder)
        self.assertIsNotNone(recorder.latest_snapshot(timeout=1))
        for state in ("foreign", "unhealthy"):
            with self.subTest(state=state), mock.patch.object(service, "probe_service", return_value={"status": state}):
                self.assertTrue(service.flush_service(timeout=1))

    def test_shared_foreground_observer_suppresses_both_clients_lid_copies(self):
        import burnbag
        with mock.patch.object(service._BusObserver, "start") as observer_start:
            first = service.ForegroundRecorder(runtime=burnbag, on_warning=lambda _message: None).start()
            self.recorders.append(first)
            self.assertIsNotNone(first.latest_snapshot(timeout=1))
            second = service.ForegroundRecorder(runtime=burnbag, on_warning=lambda _message: None).start()
            self.recorders.append(second)
            self.assertIsNotNone(second.latest_snapshot(timeout=1))
            observer_start.assert_called_once()
            observer = first.collector.observer
            observer.lid_state = False
            first.record_event("lid_closed", {"closed": True})
            second.record_event("lid_closed", {"closed": True})
            parameters = SimpleNamespace(unpack=lambda: ("org.freedesktop.UPower", {"LidIsClosed": True}, []))
            observer._signal(None, "org.freedesktop.UPower", "/org/freedesktop/UPower",
                             "org.freedesktop.DBus.Properties", "PropertiesChanged", parameters, None)
            self.assertTrue(first.flush())
            self.assertTrue(second.flush())
            self.assertEqual(len(self.records("lid_closed")), 1)
            second.close()
            first.close()

    def test_delegated_foreground_observer_does_not_duplicate_sleep_or_lid(self):
        import burnbag
        from datetime import datetime, timezone, timedelta
        with mock.patch.object(service._BusObserver, "start"):
            collector = self.collector(address=self.foreground_address, runtime=burnbag)
            collector.stop.set()
            collector._set_delegated(True)
            observer = collector.observer
            observer.lid_state = False
            parameters = SimpleNamespace(unpack=lambda: ("org.freedesktop.UPower", {"LidIsClosed": True}, []))
            observer._signal(None, "org.freedesktop.UPower", "/org/freedesktop/UPower",
                             "org.freedesktop.DBus.Properties", "PropertiesChanged", parameters, None)
            started = datetime.now(timezone.utc)
            with collector.monitor._lock:
                collector.monitor.intervals.append(burnbag.SuspendInterval(
                    started, started + timedelta(seconds=3), 2.0, 5.0))
            collector._drain_sleep()
            collector.writer.flush()
            self.assertEqual(self.records("lid_closed"), [])
            self.assertEqual(self.records("sleep_interval"), [])

    def test_kernel_critical_sample_commits_itself_and_preceding_buffer(self):
        reading_started = threading.Event()
        release_reading = threading.Event()

        class CriticalSampler:
            def sample(self):
                reading_started.set()
                if not release_reading.wait(2):
                    raise RuntimeError("Test did not release its sensor read")
                return {"batteries": {"test": {"percentage": 7.0, "capacity_level": "cRiTiCaL"}}, "errors": []}

        with mock.patch.object(burnbag_history, "PowerSampler", CriticalSampler):
            collector = self.collector()
        try:
            self.assertTrue(reading_started.wait(2))
            collector.writer.submit("buffered_observation", {"pending": True})
            self.assertEqual(self.records("buffered_observation"), [])
            release_reading.set()
            self.wait_for(lambda: bool(self.records("sample")), timeout=1)
            self.assertEqual(self.records("buffered_observation"), [{"pending": True}])
            self.assertEqual(self.records("sample")[0]["batteries"]["test"]["capacity_level"], "cRiTiCaL")
        finally:
            release_reading.set()

    def test_low_percentage_without_kernel_critical_flag_remains_batched(self):
        class LowSampler:
            def sample(self):
                return {"batteries": {"test": {"percentage": 0.0, "capacity_level": "Low"}}, "errors": []}

        with mock.patch.object(burnbag_history, "PowerSampler", LowSampler):
            collector = self.collector()
        self.wait_for(lambda: collector.snapshot is not None)
        self.wait_for(lambda: collector.writer.status()["pending_records"] > 0)
        self.assertEqual(self.records("sample"), [])


if __name__ == "__main__":
    unittest.main()
