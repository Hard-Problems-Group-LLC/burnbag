"""Sleep types need successful journal evidence within clock-confirmed windows."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import burnbag


BOOT_ID = "a" * 32


def interval(lower=100, upper=110, elapsed=10):
    wall = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    return burnbag.SuspendInterval(
        wall, wall + timedelta(seconds=60), elapsed, elapsed + 60,
        boundary_uncertainty_seconds=5,
        observed_start_monotonic_seconds=lower,
        observed_end_monotonic_seconds=upper,
    )


def records(kind="hibernate", start=102, stop=108, pid="123", overall=None, old=False):
    overall = overall or kind
    shared = {
        "_BOOT_ID": BOOT_ID, "_UID": "0", "_COMM": "systemd-sleep", "_PID": pid,
        "_SYSTEMD_UNIT": "systemd-" + overall + ".service",
        "_SYSTEMD_INVOCATION_ID": "b" * 32, "PRIORITY": "6", "SLEEP": overall,
    }
    message = f"Entering sleep state '{kind}'..." if old else f"Performing sleep operation '{kind}'..."
    return [
        dict(shared, MESSAGE_ID=burnbag.SLEEP_JOURNAL_START_ID,
             MESSAGE=message, __MONOTONIC_TIMESTAMP=str(int(start * 1000000))),
        dict(shared, MESSAGE_ID=burnbag.SLEEP_JOURNAL_STOP_ID,
             MESSAGE=f"System returned from sleep operation '{overall}'.",
             __MONOTONIC_TIMESTAMP=str(int(stop * 1000000))),
    ]


class SleepClassificationTests(unittest.TestCase):
    def classify(self, evidence, intervals=None):
        return burnbag.classify_sleep_records(intervals or [interval()], evidence, BOOT_ID)

    def test_successful_hibernate_and_suspend_preserve_measured_geometry(self):
        inputs = [interval(), interval(120, 130, elapsed=90)]
        evidence = records() + records("suspend", 121, 129, pid="456")
        result, summary = self.classify(evidence, inputs)
        self.assertEqual([part.sleep_kind for part in result], ["hibernate", "suspend"])
        self.assertEqual(summary["classified_intervals"], 2)
        self.assertEqual(summary["unclassified_intervals"], 0)
        for old, new in zip(inputs, result):
            self.assertEqual(new.classification_source, "systemd-journal")
            self.assertEqual(replace(new, sleep_kind="unknown", classification_source="clock-only"), old)
            self.assertEqual(old.sleep_kind, "unknown")

    def test_failed_cancelled_or_incomplete_attempts_never_establish_hibernation(self):
        failed = records()
        failed[1].update(PRIORITY="3", ERRNO="16")
        for evidence in (failed, records()[:1], records()[1:], []):
            with self.subTest(evidence=evidence):
                result, summary = self.classify(evidence)
                self.assertEqual(result[0].sleep_kind, "unknown")
                self.assertEqual(summary["unclassified_intervals"], 1)

    def test_missing_or_malformed_success_status_stays_unknown(self):
        for change in ({"PRIORITY": "3"}, {"PRIORITY": None}, {"ERRNO": "0"},
                       {"SLEEP": "suspend"}, {"_SYSTEMD_INVOCATION_ID": "c" * 32},
                       {"_SYSTEMD_INVOCATION_ID": None}):
            evidence = records()
            evidence[1].update(change)
            with self.subTest(change=change):
                self.assertEqual(self.classify(evidence)[0][0].sleep_kind, "unknown")

    def test_same_pid_new_invocation_cannot_complete_old_request(self):
        evidence = records()
        evidence[1]["_SYSTEMD_INVOCATION_ID"] = "c" * 32
        self.assertEqual(self.classify(evidence)[0][0].sleep_kind, "unknown")

    def test_contradictory_plain_operation_and_stop_description_stay_unknown(self):
        contradictory_start = records("hibernate", overall="suspend")
        contradictory_stop = records()
        contradictory_stop[1]["MESSAGE"] = "System returned from sleep operation 'suspend'."
        for evidence in (contradictory_start, contradictory_stop):
            self.assertEqual(self.classify(evidence)[0][0].sleep_kind, "unknown")

    def test_failure_text_without_error_metadata_cannot_claim_success(self):
        evidence = records()
        evidence[1]["MESSAGE"] = "Failed to put system to sleep. System resumed again: Device busy"
        self.assertEqual(self.classify(evidence)[0][0].sleep_kind, "unknown")

    def test_compound_request_uses_actual_suboperation_not_overall_sleep(self):
        for kind in ("suspend", "hibernate"):
            evidence = records(kind, overall="suspend-then-hibernate")
            with self.subTest(kind=kind):
                self.assertEqual(self.classify(evidence)[0][0].sleep_kind, kind)

    def test_hybrid_does_not_claim_disk_restoration_and_fallback_is_suspend(self):
        self.assertEqual(self.classify(records("hybrid-sleep"))[0][0].sleep_kind, "unknown")
        evidence = records("suspend", overall="hybrid-sleep")
        self.assertEqual(self.classify(evidence)[0][0].sleep_kind, "suspend")

    def test_mixed_or_repeated_attempts_in_one_window_remain_unclassified(self):
        for second_kind in ("hibernate", "suspend"):
            for failed in (False, True):
                first = records("suspend", 101, 104, overall="suspend-then-hibernate")
                second = records(second_kind, 105, 109, overall="suspend-then-hibernate")
                if failed:
                    first[1].update(PRIORITY="3", ERRNO="5")
                with self.subTest(second=second_kind, failed=failed):
                    self.assertEqual(self.classify(first + second)[0][0].sleep_kind, "unknown")

    def test_old_formats_and_absent_invocation_fields_still_work(self):
        for kind in ("hibernate", "suspend"):
            for generic in (False, True):
                evidence = records(kind, old=True)
                for record in evidence:
                    record.pop("_SYSTEMD_INVOCATION_ID")
                if generic:
                    evidence[0]["MESSAGE"] = "Suspending system..."
                evidence[1]["MESSAGE"] = "System resumed." if generic else "System returned from sleep state."
                with self.subTest(kind=kind, generic=generic):
                    self.assertEqual(self.classify(evidence)[0][0].sleep_kind, kind)
        evidence = records("hibernate", overall="suspend-then-hibernate")
        evidence[0]["MESSAGE"] = "Suspending system..."
        self.assertEqual(self.classify(evidence)[0][0].sleep_kind, "unknown")

    def test_unrecognized_start_message_does_not_assume_overall_operation(self):
        evidence = records()
        evidence[0]["MESSAGE"] = "Future ambiguous operation description"
        self.assertEqual(self.classify(evidence)[0][0].sleep_kind, "unknown")

    def test_wrong_boot_user_process_and_unit_cannot_supply_evidence(self):
        for field, value in (("_BOOT_ID", "c" * 32), ("_UID", "1000"),
                             ("_COMM", "logger"), ("_SYSTEMD_UNIT", "other.service"),
                             ("_SYSTEMD_UNIT", ["systemd-hibernate.service"])):
            evidence = records()
            for record in evidence:
                record[field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(self.classify(evidence)[0][0].sleep_kind, "unknown")

    def test_timestamp_matching_does_not_use_real_time_or_guess_outside_window(self):
        for start, stop in ((80, 90), (111, 119), (99, 108), (102, 111), (102, 102)):
            with self.subTest(start=start, stop=stop):
                self.assertEqual(self.classify(records(start=start, stop=stop))[0][0].sleep_kind, "unknown")
        evidence = records()
        evidence[0]["__REALTIME_TIMESTAMP"] = "999999999999999999"
        evidence[1]["__REALTIME_TIMESTAMP"] = "1"
        self.assertEqual(self.classify(evidence)[0][0].sleep_kind, "hibernate")

    def test_invalid_observation_bounds_cannot_classify(self):
        for lower, upper in ((None, None), (math.nan, 110), (100, math.inf), (-1, 110), (110, 100)):
            with self.subTest(lower=lower, upper=upper):
                self.assertEqual(self.classify(records(), [interval(lower, upper)])[0][0].sleep_kind, "unknown")

    def test_malformed_trusted_timestamp_or_pid_invalidates_snapshot(self):
        for key, value in (("__MONOTONIC_TIMESTAMP", "NaN"), ("__MONOTONIC_TIMESTAMP", ["102000000"]),
                           ("_PID", None), ("_PID", "-1")):
            evidence = records()
            evidence[0][key] = value
            with self.subTest(key=key, value=value):
                result, summary = self.classify(evidence)
                self.assertEqual(result[0].sleep_kind, "unknown")
                self.assertEqual(summary["status"], "unavailable")

    def test_extra_unmatched_attempt_prevents_borrowing_a_nearby_success(self):
        for extra in (records("suspend", 101, 109, pid="456")[:1],
                      records("suspend", 101, 109, pid="456")[1:]):
            self.assertEqual(self.classify(records() + extra)[0][0].sleep_kind, "unknown")
        evidence = records("suspend", 80, 90)[1:] + records()
        self.assertEqual(self.classify(evidence)[0][0].sleep_kind, "hibernate")

    def test_empty_and_failed_reader_preserve_clock_evidence(self):
        with mock.patch.object(burnbag, "read_sleep_journal", side_effect=AssertionError("must not query")):
            result, summary = burnbag.classify_sleep_intervals([])
        self.assertEqual(result, [])
        self.assertEqual(summary["status"], "not-needed")
        for failure in (FileNotFoundError("missing"), PermissionError("denied"), TimeoutError("slow")):
            with mock.patch.object(burnbag, "read_sleep_journal", side_effect=failure):
                result, summary = burnbag.classify_sleep_intervals([interval()])
            self.assertEqual(result[0], interval())
            self.assertEqual(summary["status"], "unavailable")

    def test_over_limit_snapshot_is_not_partly_trusted(self):
        with mock.patch.object(burnbag, "SLEEP_JOURNAL_MAX_RECORDS", 1):
            result, summary = self.classify(records())
        self.assertEqual(result[0].sleep_kind, "unknown")
        self.assertEqual(summary["status"], "unavailable")


class SleepJournalReaderTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / ".local" / "tmp"
        root.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix="sleep-journal.", dir=root)
        self.addCleanup(self.directory.cleanup)
        self.script = Path(self.directory.name) / "journalctl"
        self.path_patch = mock.patch.dict(os.environ, {"PATH": self.directory.name})
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.created = []
        original_popen = subprocess.Popen

        def capture(*args, **kwargs):
            process = original_popen(*args, **kwargs)
            self.created.append(process)
            return process

        self.process_patch = mock.patch.object(burnbag.subprocess, "Popen", side_effect=capture)
        self.process_patch.start()
        self.addCleanup(self.process_patch.stop)

    def fake(self, body):
        self.script.write_text("#!/usr/bin/python3\n" + body + "\n", encoding="utf-8")
        self.script.chmod(0o700)

    def assert_reaped(self):
        self.assertTrue(self.created)
        self.assertIsNotNone(self.created[-1].returncode)
        with self.assertRaises(ProcessLookupError):
            os.kill(self.created[-1].pid, 0)

    def test_real_child_receives_bounded_filtered_query_and_returns_json(self):
        evidence = records()
        payload = "\n".join(json.dumps(record) for record in evidence)
        self.fake(
            "import sys\n"
            f"assert '--boot={BOOT_ID}' in sys.argv\n"
            "assert '--lines=4097' in sys.argv\n"
            "assert '_UID=0' in sys.argv and '_COMM=systemd-sleep' in sys.argv\n"
            f"print({payload!r})"
        )
        self.assertEqual(burnbag.read_sleep_journal(BOOT_ID), evidence)
        self.assert_reaped()

    def test_missing_executable_and_invalid_boot_need_no_child(self):
        with self.assertRaises(FileNotFoundError):
            burnbag.read_sleep_journal(BOOT_ID)
        with self.assertRaises(ValueError):
            burnbag.read_sleep_journal("bad-boot")
        self.assertEqual(self.created, [])

    def test_nonzero_exit_and_malformed_json_are_rejected_and_reaped(self):
        for body in ("import sys; sys.exit(1)", "print('not json')", "print('[]')",
                     "import os; os.write(1, b'\\xff\\xfe')"):
            with self.subTest(body=body):
                self.fake(body)
                with self.assertRaises((RuntimeError, ValueError, UnicodeError)):
                    burnbag.read_sleep_journal(BOOT_ID)
                self.assert_reaped()

    def test_timeout_kills_and_reaps_child(self):
        self.fake("import time; time.sleep(30)")
        started = time.monotonic()
        with mock.patch.object(burnbag, "SLEEP_JOURNAL_TIMEOUT_SECONDS", 0.2):
            with self.assertRaises(TimeoutError):
                burnbag.read_sleep_journal(BOOT_ID)
        self.assertLess(time.monotonic() - started, 3)
        self.assert_reaped()

    def test_descendant_holding_output_pipe_cannot_block_teardown(self):
        self.fake("import os, time\nif os.fork() == 0:\n    time.sleep(30)\n")
        started = time.monotonic()
        with mock.patch.object(burnbag, "SLEEP_JOURNAL_TIMEOUT_SECONDS", 0.2):
            with self.assertRaises(TimeoutError):
                burnbag.read_sleep_journal(BOOT_ID)
        self.assertLess(time.monotonic() - started, 3)
        self.assert_reaped()

    def test_stdout_and_stderr_share_byte_limit_and_failures_reap_child(self):
        for descriptor in (1, 2):
            self.fake(f"import os, time; os.write({descriptor}, b'x' * 5000); time.sleep(30)")
            with self.subTest(descriptor=descriptor):
                with mock.patch.object(burnbag, "SLEEP_JOURNAL_MAX_BYTES", 1000):
                    with self.assertRaisesRegex(ValueError, "byte limit"):
                        burnbag.read_sleep_journal(BOOT_ID)
                self.assert_reaped()
        self.fake("import os, time; os.write(1, b'x' * 600); os.write(2, b'x' * 600); time.sleep(30)")
        with mock.patch.object(burnbag, "SLEEP_JOURNAL_MAX_BYTES", 1000):
            with self.assertRaisesRegex(ValueError, "byte limit"):
                burnbag.read_sleep_journal(BOOT_ID)
        self.assert_reaped()

    def test_extra_record_detects_history_truncation(self):
        self.fake("print('{}\\n{}')")
        with mock.patch.object(burnbag, "SLEEP_JOURNAL_MAX_RECORDS", 1):
            with self.assertRaisesRegex(ValueError, "record limit"):
                burnbag.read_sleep_journal(BOOT_ID)
        self.assert_reaped()


if __name__ == "__main__":
    unittest.main()
