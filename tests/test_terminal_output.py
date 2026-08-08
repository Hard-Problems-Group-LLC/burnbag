"""TTY capability, color opt-out, help, and zero-argument output tests."""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import unittest
from unittest import mock

import burnbag


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class FakeTTY(io.StringIO):
    """In-memory stream that advertises interactive-terminal capability."""

    def isatty(self) -> bool:
        return True


class TerminalOutputTests(unittest.TestCase):
    def test_detection_enables_only_tty_streams(self) -> None:
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            interactive = burnbag.TerminalStyle.detect(
                stdout=FakeTTY(), stderr=FakeTTY()
            )
            redirected = burnbag.TerminalStyle.detect(
                stdout=io.StringIO(), stderr=io.StringIO()
            )

        self.assertTrue(interactive.stdout_color)
        self.assertTrue(interactive.stderr_color)
        self.assertFalse(redirected.stdout_color)
        self.assertFalse(redirected.stderr_color)

    def test_environment_and_explicit_opt_outs_disable_color(self) -> None:
        environments = (
            {"TERM": "dumb"},
            {"TERM": "xterm-256color", "NO_COLOR": ""},
        )
        for environment in environments:
            with self.subTest(environment=environment):
                with mock.patch.dict(os.environ, environment, clear=True):
                    style = burnbag.TerminalStyle.detect(
                        stdout=FakeTTY(), stderr=FakeTTY()
                    )
                self.assertFalse(style.stdout_color)
                self.assertFalse(style.stderr_color)

        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            explicit = burnbag.TerminalStyle.detect(
                no_color=True, stdout=FakeTTY(), stderr=FakeTTY()
            )
        self.assertFalse(explicit.stdout_color)
        self.assertFalse(explicit.stderr_color)

    def test_help_styling_changes_only_ansi_presentation(self) -> None:
        styled_stream = FakeTTY()
        plain_stream = io.StringIO()
        burnbag.build_argument_parser(
            burnbag.TerminalStyle(stdout_color=True, stderr_color=True)
        ).print_help(styled_stream)
        burnbag.build_argument_parser(
            burnbag.TerminalStyle(stdout_color=False, stderr_color=False)
        ).print_help(plain_stream)

        styled_help = styled_stream.getvalue()
        self.assertIn("\x1b[", styled_help)
        self.assertIn("--no-color", styled_help)
        self.assertIn("\x1b[32m  --suspend-after-minutes MIN", styled_help)
        self.assertEqual(ANSI_ESCAPE.sub("", styled_help), plain_stream.getvalue())

    def test_help_uses_color_on_tty_by_default(self) -> None:
        stdout = FakeTTY()
        stderr = FakeTTY()
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
                sys, "stderr", stderr
            ):
                with self.assertRaises(SystemExit) as raised:
                    burnbag.main(["--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertIn("\x1b[", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_no_color_flag_keeps_tty_help_plain(self) -> None:
        stdout = FakeTTY()
        stderr = FakeTTY()
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
                sys, "stderr", stderr
            ):
                with self.assertRaises(SystemExit) as raised:
                    burnbag.main(["--no-color", "--help"])

        self.assertEqual(raised.exception.code, 0)
        self.assertNotRegex(stdout.getvalue(), ANSI_ESCAPE)
        self.assertIn("--no-color", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_parse_error_retains_text_label_and_honors_no_color(self) -> None:
        cases = ((["invalid"], True), (["invalid", "--no-color"], False))
        for arguments, expect_color in cases:
            with self.subTest(arguments=arguments):
                stdout = FakeTTY()
                stderr = FakeTTY()
                with mock.patch.dict(
                    os.environ, {"TERM": "xterm-256color"}, clear=True
                ):
                    with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
                        sys, "stderr", stderr
                    ):
                        with self.assertRaises(SystemExit) as raised:
                            burnbag.main(arguments)

                self.assertEqual(raised.exception.code, 2)
                self.assertIn("[ERROR]", ANSI_ESCAPE.sub("", stderr.getvalue()))
                self.assertEqual("\x1b[" in stderr.getvalue(), expect_color)

    def test_runtime_status_color_retains_text_label(self) -> None:
        output = FakeTTY()
        style = burnbag.TerminalStyle(stdout_color=True, stderr_color=True)

        with mock.patch.object(sys, "stdout", output):
            style.write_status("OK", "Runtime status remains explicit.")

        rendered = output.getvalue()
        self.assertIn("\x1b[", rendered)
        self.assertEqual(
            ANSI_ESCAPE.sub("", rendered),
            "[OK] Runtime status remains explicit.\n",
        )

    def test_zero_arguments_print_colored_quick_start_on_tty(self) -> None:
        stdout = FakeTTY()
        stderr = FakeTTY()
        with mock.patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            with mock.patch.object(sys, "stdout", stdout), mock.patch.object(
                sys, "stderr", stderr
            ):
                exit_code = burnbag.main([])

        plain_output = ANSI_ESCAPE.sub("", stderr.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("[ERROR] An operational mode is required.", plain_output)
        self.assertIn("Quick start", plain_output)
        self.assertIn("burnbag run-cool", plain_output)
        self.assertIn("burnbag --help", plain_output)
        self.assertIn("\x1b[", stderr.getvalue())

    def test_redirected_narrative_remains_plain(self) -> None:
        output = io.StringIO()
        manager = burnbag.LidCloseManager(
            mode="run-cool",
            suspend_after_minutes=20,
            no_inhibit_auto_suspend=False,
            ignore_lid=False,
            terminal_style=burnbag.TerminalStyle(
                stdout_color=False, stderr_color=False
            ),
        )

        with contextlib.redirect_stdout(output):
            manager.print_startup_narrative()

        self.assertNotRegex(output.getvalue(), ANSI_ESCAPE)
        self.assertIn("BURNBAG — STARTUP NARRATIVE", output.getvalue())
        self.assertIn("Operating Mode", output.getvalue())


if __name__ == "__main__":
    unittest.main()
