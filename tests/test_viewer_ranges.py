"""Viewer duration semantics and hard viewport boundary contracts."""
from contextlib import redirect_stderr
from datetime import datetime
import io
import unittest

from burnbag_graph import history_range
from burnbag_viewer import constrain_range, parse_viewer_options


class ViewerRangeTests(unittest.TestCase):
    def test_default_has_no_implicit_time_filter(self):
        args = parse_viewer_options([], now=10000)
        self.assertIsNone(args.initial_range)
        self.assertFalse(args.only)

    def test_last_spellings_match_terminal_and_capture_now_once(self):
        now = datetime(2026, 9, 15, 18, 0).timestamp()
        for text in ('5h', '5H', '5 h', '5 H', '5 hours', 'five hours', '5:00:00', '05:00:00',
                     '5:00', 'one month', 'two years', 'one century', 'one millennium'):
            with self.subTest(text=text):
                args = parse_viewer_options(['--last', text], now=now)
                self.assertEqual(args.initial_range, history_range(None, None, now=now, last=text))
                self.assertEqual(args.initial_range[1], now)

    def test_month_end_calendar_subtraction_is_shared(self):
        now = datetime(2026, 3, 31, 12, 30).timestamp()
        args = parse_viewer_options(['--last', '1 month', '--only'], now=now)
        self.assertTrue(args.only)
        self.assertEqual(datetime.fromtimestamp(args.initial_range[0]), datetime(2026, 2, 28, 12, 30))

    def test_only_requires_explicit_valid_range_before_loading_gtk(self):
        for argv in (['--only'], ['--last', '0h'], ['--last', '5h', '--to', '2026-09-15'],
                     ['--from', '2026-09-16', '--to', '2026-09-15']):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as raised:
                    parse_viewer_options(argv)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn('error:', output.getvalue())

    def test_iso_endpoints_and_only_are_accepted(self):
        args = parse_viewer_options(['--from', '2026-09-15T00:00Z', '--to', '2026-09-15T01:00Z', '--only'])
        self.assertEqual(args.initial_range[1] - args.initial_range[0], 3600)
        self.assertTrue(args.only)

    def test_lock_clamps_pan_zoom_out_and_focus_but_allows_inner_zoom(self):
        limits = (1000, 2000)
        for viewport, expected in [((0, 3000), limits), ((900, 1100), (1000, 1200)),
                                   ((1900, 2100), (1800, 2000)), ((1200, 1300), (1200, 1300))]:
            self.assertEqual(constrain_range(viewport, limits), expected)
            self.assertEqual(constrain_range(viewport), viewport)

    def test_nonfinite_and_inverted_viewports_rejected(self):
        for viewport in ((2, 1), (1, 1), (float('nan'), 2), (1, float('inf'))):
            with self.assertRaises(ValueError):
                constrain_range(viewport)
