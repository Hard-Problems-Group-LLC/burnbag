"""Durability, security, concurrency, and lifecycle tests for the running log."""

from __future__ import annotations

import contextlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

import burnbag


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_TMP = PROJECT_ROOT / ".local" / "tmp"


def concurrent_log_writer(path_text: str, worker: int, count: int) -> None:
    """Process entry point that appends one complete session to a shared file."""
    running_log = burnbag.RunningLog.open(
        Path(path_text),
        mode="run-cool",
        started_monotonic=time.monotonic(),
    )
    running_log.start_session({"worker": worker})
    for index in range(count):
        running_log.append(
            "worker_event",
            "INFO",
            f"Worker {worker} record {index}.",
            {"worker": worker, "index": index},
        )
    running_log.end_session(
        exit_code=0,
        goal_achieved=True,
        shutdown_reason="Concurrent test complete.",
        deviations=[],
        final_state={"worker": worker},
    )
    running_log.close()


class RunningLogTests(unittest.TestCase):
    def setUp(self) -> None:
        LOCAL_TMP.mkdir(parents=True, exist_ok=True)
        self.run_root = Path(
            tempfile.mkdtemp(prefix="burnbag-running-log-test.", dir=LOCAL_TMP)
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.run_root)

    @staticmethod
    def read_records(path: Path) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def open_log(self, name: str = "burnbag.log") -> burnbag.RunningLog:
        return burnbag.RunningLog.open(
            self.run_root / name,
            mode="run-cool",
            started_monotonic=time.monotonic(),
        )

    def test_real_file_records_secure_ordered_session(self) -> None:
        path = self.run_root / "state" / "burnbag" / "burnbag.log"
        running_log = burnbag.RunningLog.open(
            path,
            mode="run-cool",
            started_monotonic=time.monotonic(),
            managed_directory=True,
        )
        session_id = running_log.session_id

        running_log.start_session({"manage_backlight": True})
        running_log.append(
            "lid_closed", "EVENT", "Lid closure detected.", {"closed": True}
        )
        running_log.end_session(
            exit_code=0,
            goal_achieved=True,
            shutdown_reason="Lid cycle completed.",
            deviations=[],
            final_state={"teardown_complete": True},
        )
        running_log.close()

        records = self.read_records(path)
        self.assertEqual([record["sequence"] for record in records], [1, 2, 3])
        self.assertEqual(
            [record["event"] for record in records],
            ["session_start", "lid_closed", "session_end"],
        )
        self.assertEqual({record["session_id"] for record in records}, {session_id})
        self.assertTrue(all(record["schema_version"] == 1 for record in records))
        self.assertTrue(all(str(record["timestamp"]).endswith("Z") for record in records))
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_path_selection_respects_xdg_and_requires_absolute_values(self) -> None:
        state_home = self.run_root / "xdg-state"
        with mock.patch.dict(
            os.environ,
            {"HOME": str(self.run_root), "XDG_STATE_HOME": str(state_home)},
            clear=True,
        ):
            selected, managed = burnbag.RunningLog.select_path(None)

        self.assertTrue(managed)
        self.assertEqual(selected, state_home / "burnbag" / "burnbag.log")

        with self.assertRaisesRegex(burnbag.RunningLogError, "absolute path"):
            burnbag.RunningLog.select_path("relative.log")

        with mock.patch.dict(
            os.environ,
            {"HOME": str(self.run_root), "XDG_STATE_HOME": "relative-state"},
            clear=True,
        ):
            with self.assertRaisesRegex(burnbag.RunningLogError, "must be absolute"):
                burnbag.RunningLog.select_path(None)

    def test_symlink_log_target_is_rejected_without_touching_target(self) -> None:
        target = self.run_root / "unrelated.txt"
        target.write_text("preserve me\n", encoding="utf-8")
        link = self.run_root / "burnbag.log"
        link.symlink_to(target)

        with self.assertRaisesRegex(burnbag.RunningLogError, "Could not open"):
            self.open_log()

        self.assertEqual(target.read_text(encoding="utf-8"), "preserve me\n")

    def test_hard_link_and_unsafe_parent_are_rejected(self) -> None:
        original = self.run_root / "original.log"
        original.write_bytes(b"")
        linked = self.run_root / "linked.log"
        os.link(original, linked)

        with self.assertRaisesRegex(burnbag.RunningLogError, "one hard link"):
            burnbag.RunningLog.open(
                linked, mode="run-cool", started_monotonic=time.monotonic()
            )

        unsafe_parent = self.run_root / "unsafe"
        unsafe_parent.mkdir()
        unsafe_parent.chmod(0o777)
        with self.assertRaisesRegex(
            burnbag.RunningLogError, "group/world writable"
        ):
            burnbag.RunningLog.open(
                unsafe_parent / "burnbag.log",
                mode="run-cool",
                started_monotonic=time.monotonic(),
            )

    def test_partial_tail_is_preserved_and_terminated_before_new_session(self) -> None:
        path = self.run_root / "burnbag.log"
        path.write_bytes(b'{"interrupted":')

        running_log = self.open_log()
        running_log.start_session({"manage_backlight": True})
        running_log.close()

        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], '{"interrupted":')
        start_record = json.loads(lines[1])
        self.assertEqual(start_record["event"], "session_start")
        self.assertTrue(start_record["details"]["partial_tail_detected"])

    def test_each_append_calls_fsync_before_advancing_sequence(self) -> None:
        running_log = self.open_log()
        real_fsync = os.fsync

        with mock.patch.object(burnbag.os, "fsync", wraps=real_fsync) as fsync:
            running_log.append("runtime_status", "INFO", "Durable record.")

        fsync.assert_called_once_with(running_log.file_descriptor)
        self.assertEqual(running_log.sequence, 1)
        running_log.close()

    def test_fsync_failure_marks_log_failed_and_refuses_later_records(self) -> None:
        running_log = self.open_log()
        with mock.patch.object(
            burnbag.os, "fsync", side_effect=OSError("injected fsync failure")
        ):
            with self.assertRaisesRegex(
                burnbag.RunningLogError, "injected fsync failure"
            ):
                running_log.append("runtime_status", "INFO", "Will not commit.")

        self.assertEqual(running_log.sequence, 0)
        self.assertIsNotNone(running_log.failed_reason)
        with self.assertRaisesRegex(burnbag.RunningLogError, "injected fsync failure"):
            running_log.append("runtime_status", "INFO", "Must be refused.")
        running_log.close()

    def test_write_failure_and_oversized_record_fail_before_success(self) -> None:
        write_failure_log = self.open_log("write-failure.log")
        with mock.patch.object(
            burnbag.os, "write", side_effect=OSError("injected write failure")
        ):
            with self.assertRaisesRegex(
                burnbag.RunningLogError, "injected write failure"
            ):
                write_failure_log.append(
                    "runtime_status", "INFO", "Write must fail."
                )
        self.assertEqual(write_failure_log.sequence, 0)
        write_failure_log.close()

        oversized_path = self.run_root / "oversized.log"
        oversized_log = self.open_log("oversized.log")
        with self.assertRaisesRegex(burnbag.RunningLogError, "maximum"):
            oversized_log.append(
                "runtime_status",
                "INFO",
                "x" * burnbag.RunningLog.MAX_RECORD_BYTES,
            )
        self.assertEqual(oversized_path.stat().st_size, 0)
        oversized_log.close()

    def test_logging_failure_aborts_work_but_teardown_helpers_still_run(self) -> None:
        running_log = self.open_log()
        manager = burnbag.LidCloseManager(
            mode="run-cool",
            suspend_after_minutes=None,
            no_inhibit_auto_suspend=False,
            ignore_lid=False,
            running_log=running_log,
            terminal_style=burnbag.TerminalStyle(False, False),
        )
        manager.restore_backlights = mock.Mock(return_value=True)
        manager.release_inhibitor_fds = mock.Mock()
        manager.restore_power_profile = mock.Mock()

        with mock.patch.object(
            burnbag.os, "fsync", side_effect=OSError("injected media failure")
        ):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(burnbag.RunningLogError):
                    manager._info("This event must be durable.")

        manager.teardown()

        self.assertEqual(manager.exit_code, 1)
        self.assertTrue(manager.teardown_complete)
        manager.restore_backlights.assert_called_once_with()
        manager.release_inhibitor_fds.assert_called_once_with()
        manager.restore_power_profile.assert_called_once_with()
        running_log.close()

    def test_manager_final_record_follows_teardown(self) -> None:
        path = self.run_root / "burnbag.log"
        running_log = self.open_log()
        running_log.start_session({"manage_backlight": False})
        manager = burnbag.LidCloseManager(
            mode="normal",
            suspend_after_minutes=None,
            no_inhibit_auto_suspend=False,
            ignore_lid=False,
            running_log=running_log,
            terminal_style=burnbag.TerminalStyle(False, False),
        )
        manager.goal_achieved = True
        manager.shutdown_reason = "Test completed."
        manager.teardown()

        with contextlib.redirect_stdout(io.StringIO()):
            manager.print_shutdown_narrative()

        records = self.read_records(path)
        self.assertEqual(records[-1]["event"], "session_end")
        details = records[-1]["details"]
        self.assertIsInstance(details, dict)
        self.assertTrue(details["final_state"]["teardown_complete"])
        self.assertIsNone(running_log.file_descriptor)

    def test_mutation_intents_are_durable_before_owned_boundaries(self) -> None:
        path = self.run_root / "mutation-order.log"
        running_log = self.open_log("mutation-order.log")
        running_log.start_session({"manage_backlight": True})
        boundaries: list[tuple[str, str]] = []

        def latest_event() -> str:
            return str(self.read_records(path)[-1]["event"])

        class FakeVariant:
            def __init__(self, _signature: str, values: object) -> None:
                self.values = values

        class FakeResult:
            def __init__(self, value: tuple[object, ...]) -> None:
                self.value = value

            def unpack(self) -> tuple[object, ...]:
                return self.value

        class FakePowerProxy:
            active_profile = "balanced"

            def call_sync(self, method: str, parameters: FakeVariant, *_arguments: object) -> FakeResult | None:
                if method == "Get":
                    if parameters.values[1] == "Profiles":
                        return FakeResult(([{"Profile": "balanced"}, {"Profile": "power-saver"}],))
                    return FakeResult((self.active_profile,))
                boundaries.append(("power", latest_event()))
                self.active_profile = parameters.values[2].values
                return None

        inhibitor_read_fd, inhibitor_write_fd = os.pipe()
        os.close(inhibitor_write_fd)

        class FakeFDList:
            @staticmethod
            def get(_index: int) -> int:
                return inhibitor_read_fd

        class FakeInhibitorProxy:
            @staticmethod
            def call_with_unix_fd_list_sync(
                *_arguments: object,
            ) -> tuple[FakeResult, FakeFDList]:
                boundaries.append(("inhibitor", latest_event()))
                return FakeResult((0,)), FakeFDList()

        class FakeCallFlags:
            NONE = 0

        class FakeGio:
            DBusCallFlags = FakeCallFlags

        class FakeGLib:
            Variant = FakeVariant

        original_gio = burnbag.Gio
        original_glib = burnbag.GLib
        burnbag.Gio = FakeGio
        burnbag.GLib = FakeGLib
        try:
            manager = burnbag.LidCloseManager(
                mode="run-cool",
                suspend_after_minutes=None,
                no_inhibit_auto_suspend=False,
                ignore_lid=False,
                running_log=running_log,
                terminal_style=burnbag.TerminalStyle(False, False),
            )
            manager.power_proxy = FakePowerProxy()
            manager.logind_proxy = FakeInhibitorProxy()

            device_root = self.run_root / "panel0"
            device_root.mkdir()
            brightness_path = device_root / "brightness"
            actual_path = device_root / "actual_brightness"
            brightness_path.write_text("40\n", encoding="ascii")
            actual_path.write_text("40\n", encoding="ascii")
            manager.backlight_devices = [
                burnbag.BacklightDeviceState(
                    name="panel0",
                    brightness_path=brightness_path,
                    verification_path=actual_path,
                    original_brightness=40,
                    original_actual_brightness=40,
                    maximum_brightness=100,
                )
            ]

            def set_backlight(
                _device: burnbag.BacklightDeviceState, brightness: int
            ) -> None:
                boundaries.append(("backlight", latest_event()))
                brightness_path.write_text(f"{brightness}\n", encoding="ascii")
                actual_path.write_text(f"{brightness}\n", encoding="ascii")

            manager._set_backlight_brightness = set_backlight
            manager.save_and_set_power_profile("power-saver")
            manager.acquire_inhibitor_locks()
            manager._on_backlight_power_down()
            manager.goal_achieved = True
            manager.shutdown_reason = "Mutation-order test complete."
            manager.teardown()
            with contextlib.redirect_stdout(io.StringIO()):
                manager.print_shutdown_narrative()
        finally:
            burnbag.Gio = original_gio
            burnbag.GLib = original_glib
            try:
                os.close(inhibitor_read_fd)
            except OSError:
                pass

        self.assertIn(("power", "power_profile_change_intent"), boundaries)
        self.assertIn(("inhibitor", "inhibitor_acquire_intent"), boundaries)
        self.assertIn(("backlight", "backlight_power_down_intent"), boundaries)
        self.assertIn(("backlight", "backlight_restore_intent"), boundaries)
        self.assertIn(("power", "power_profile_restore_intent"), boundaries)

    def test_concurrent_processes_append_only_complete_records(self) -> None:
        path = self.run_root / "concurrent.log"
        worker_count = 4
        records_per_worker = 8
        context = multiprocessing.get_context("fork")
        processes = [
            context.Process(
                target=concurrent_log_writer,
                args=(str(path), worker, records_per_worker),
            )
            for worker in range(worker_count)
        ]

        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=15)
            self.assertEqual(process.exitcode, 0)

        records = self.read_records(path)
        self.assertEqual(
            len(records), worker_count * (records_per_worker + 2)
        )
        session_ids = {str(record["session_id"]) for record in records}
        self.assertEqual(len(session_ids), worker_count)
        for session_id in session_ids:
            sequences = [
                int(record["sequence"])
                for record in records
                if record["session_id"] == session_id
            ]
            self.assertEqual(sequences, list(range(1, records_per_worker + 3)))

    def test_help_does_not_create_an_operational_log(self) -> None:
        path = self.run_root / "help.log"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                burnbag.main(["--log-file", str(path), "--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertFalse(path.exists())
        self.assertIn("--log-file", stdout.getvalue())

    def test_pre_manager_failure_still_writes_handled_session_end(self) -> None:
        path = self.run_root / "initialization-failure.log"
        with mock.patch.object(
            burnbag, "load_pygobject", side_effect=SystemExit(1)
        ):
            with self.assertRaises(SystemExit) as raised:
                burnbag.main(["normal", "--log-file", str(path)])

        self.assertEqual(raised.exception.code, 1)
        records = self.read_records(path)
        self.assertEqual(
            [record["event"] for record in records],
            ["session_start", "session_end"],
        )
        self.assertFalse(records[-1]["details"]["goal_achieved"])


if __name__ == "__main__":
    unittest.main()
