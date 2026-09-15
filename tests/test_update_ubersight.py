"""Phase-local slice identity and delivery-state publication contracts."""

import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "burnbag_update_ubersight", PROJECT_ROOT / "scripts/update_ubersight.py")
assert SPEC is not None and SPEC.loader is not None
UPDATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATE)


class UbersightStackTests(unittest.TestCase):
    def setUp(self):
        temporary = PROJECT_ROOT / ".local/tmp"
        temporary.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="ubersight-stack.", dir=temporary)
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "stack.md"

    def write_stack(self, phases=None, slices=None, delivery="active", notes="Current work"):
        if phases is None:
            phases = [("1000", "done", "Completed phase"), ("2000", "active", "Current phase")]
        if slices is None:
            slices = [("1000", "1000", "done", "Previously completed slice"),
                      ("1000", "2000", "active", "Current slice"),
                      ("2000", "2000", "pending", "Later slice")]
        self.path.write_text(
            "# Delivery\n\n## Publication\n\nDelivery: " + delivery + "\nNotes: " + notes
            + "\n\n## Phases\n\n| ID | State | Title |\n| --- | --- | --- |\n"
            + "".join("| " + " | ".join(row) + " |\n" for row in phases)
            + "\n## Slices\n\n| ID | Phase | State | Title |\n| --- | --- | --- | --- |\n"
            + "".join("| " + " | ".join(row) + " |\n" for row in slices),
            encoding="utf-8")
        return self.path

    def arguments(self, **kwargs):
        return UPDATE.writer_arguments(self.write_stack(**kwargs))

    @staticmethod
    def values(arguments, flag):
        return [arguments[index + 1] for index, value in enumerate(arguments) if value == flag]

    def test_local_slice_ids_can_repeat_across_phases_and_equal_phase_ids(self):
        arguments = self.arguments()
        self.assertEqual(self.values(arguments, "--phase-row"), [
            "1000:done:Completed phase", "2000:active:Current phase"])
        self.assertEqual(self.values(arguments, "--slice"), [
            "1000:active:Current slice", "2000:pending:Later slice"])
        self.assertNotIn("Previously completed slice", " ".join(arguments))

    def test_duplicate_phase_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate phase ID: 1000"):
            self.arguments(phases=[("1000", "done", "First"), ("1000", "active", "Second")])

    def test_duplicate_slice_id_within_one_phase_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate slice ID 1000 in phase 2000"):
            self.arguments(slices=[("1000", "1000", "done", "Previous"),
                                   ("1000", "2000", "active", "First"),
                                   ("1000", "2000", "pending", "Duplicate")])

    def test_local_ids_are_published_verbatim_without_a_phase_prefix(self):
        arguments = self.arguments(slices=[("1000", "1000", "done", "Previous"),
                                          ("1500", "2000", "active", "Inserted slice")])
        self.assertEqual(self.values(arguments, "--slice"), ["1500:active:Inserted slice"])

    def test_unknown_owning_phase_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid owning phase for 1000"):
            self.arguments(slices=[("1000", "1000", "done", "Previous"),
                                   ("1000", "missing", "active", "Unknown owner")])

    def test_active_slices_must_belong_to_active_phase(self):
        with self.assertRaisesRegex(ValueError, "outside the active phase"):
            self.arguments(slices=[("1000", "1000", "active", "Wrong phase"),
                                   ("1000", "2000", "pending", "Waiting")])

    def test_exactly_one_phase_must_be_active(self):
        for states in (("done", "pending"), ("active", "active")):
            with self.subTest(states=states), self.assertRaisesRegex(ValueError, "exactly one phase"):
                self.arguments(phases=[("1000", states[0], "First"), ("2000", states[1], "Second")])

    def test_each_phase_requires_slices(self):
        with self.assertRaisesRegex(ValueError, "phase 1000 has no slices"):
            self.arguments(slices=[("1000", "2000", "active", "Only current phase")])

    def test_done_phases_cannot_have_unfinished_slices(self):
        with self.assertRaisesRegex(ValueError, "done phase 1000 contains unfinished slices"):
            self.arguments(slices=[("1000", "1000", "blocked", "Unfinished"),
                                   ("1000", "2000", "active", "Current")])

    def test_active_and_blocked_delivery_require_exactly_one_active_slice(self):
        for delivery in ("active", "blocked"):
            for states in (("pending", "pending"), ("active", "active")):
                with self.subTest(delivery=delivery, states=states), \
                        self.assertRaisesRegex(ValueError, "exactly one slice"):
                    self.arguments(delivery=delivery, slices=[
                        ("1000", "1000", "done", "Previous"),
                        ("1000", "2000", states[0], "First"),
                        ("2000", "2000", states[1], "Second")])

    def test_blocked_delivery_preserves_active_context(self):
        arguments = self.arguments(delivery="blocked", notes="Awaiting operator")
        self.assertEqual(arguments[-1], "--blocked")
        self.assertEqual(self.values(arguments, "--notes"), ["Awaiting operator"])
        self.assertIn("1000:active:Current slice", self.values(arguments, "--slice"))

    def test_complete_delivery_requires_all_slices_and_other_phases_done(self):
        slices = [("1000", "1000", "done", "Previous"), ("1000", "2000", "done", "Finished")]
        arguments = self.arguments(delivery="complete", slices=slices)
        self.assertEqual(arguments[-1], "--complete")
        self.assertEqual(self.values(arguments, "--slice"), ["1000:done:Finished"])
        with self.assertRaisesRegex(ValueError, "complete delivery requires"):
            self.arguments(delivery="complete")
        with self.assertRaisesRegex(ValueError, "complete delivery requires"):
            self.arguments(delivery="complete", slices=slices,
                           phases=[("1000", "blocked", "Not complete"), ("2000", "active", "Final")])

    def test_id_state_and_title_validation_are_retained(self):
        for identifier, state, title, error in (
            ("bad id", "active", "Title", "invalid ID"),
            ("1000", "invalid", "Title", "invalid state"),
            ("1000", "active", "", "printable title"),
            ("1000", "active", "x" * 81, "printable title"),
            ("1000", "active", "nonprintable\x07", "printable title"),
        ):
            with self.subTest(identifier=identifier, state=state, title=title), \
                    self.assertRaisesRegex(ValueError, error):
                self.arguments(slices=[("1000", "1000", "done", "Previous"),
                                       (identifier, "2000", state, title)])

    def test_publication_validation_is_retained(self):
        for options, error in (({"delivery": "unknown"}, "Delivery must"),
                               ({"notes": ""}, "Notes must"),
                               ({"notes": "x" * 501}, "Notes must"),
                               ({"notes": "invalid\x07"}, "Notes must")):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, error):
                self.arguments(**options)

    def test_markdown_table_validation_is_retained(self):
        for original, replacement in (("| ID | Phase | State | Title |", "| Phase | ID | State | Title |"),
                                      ("| --- | --- | --- | --- |", "| -- | --- | --- | --- |")):
            path = self.write_stack()
            path.write_text(path.read_text().replace(original, replacement))
            with self.subTest(replacement=replacement), self.assertRaisesRegex(ValueError, "malformed Slices"):
                UPDATE.writer_arguments(path)

    def test_dry_run_validates_without_invoking_external_writer(self):
        self.write_stack()
        output = io.StringIO()
        with patch.object(UPDATE, "STACK", self.path), patch.object(UPDATE.subprocess, "run") as run, \
                contextlib.redirect_stdout(output):
            self.assertEqual(UPDATE.main(["--dry-run"]), 0)
        run.assert_not_called()
        self.assertIn("--slice '1000:active:Current slice'", output.getvalue())

    def test_repository_stack_is_valid_and_publishes_local_slice_ids(self):
        arguments = UPDATE.writer_arguments(UPDATE.STACK)
        self.assertTrue(self.values(arguments, "--phase-row"))
        slices = self.values(arguments, "--slice")
        self.assertTrue(slices)
        for item in slices:
            self.assertRegex(item.split(":", 1)[0], r"^[0-9]+$")


if __name__ == "__main__":
    unittest.main()
