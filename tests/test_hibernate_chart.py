"""Sleep-mode annotations retain evidence, timing, and chart geometry."""

from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import re
import unittest

import burnbag


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class HibernateChartTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
        self.devices = [burnbag.BatteryDevice("BAT0", Path("/unused/BAT0"))]

    def sample(self, elapsed, percentages=None):
        return burnbag.BatterySample(
            self.start + timedelta(seconds=elapsed), elapsed,
            {"BAT0": 80} if percentages is None else percentages,
        )

    def interval(self, start, end, kind="hibernate", wall_offset=0):
        return burnbag.SuspendInterval(
            self.start + timedelta(seconds=start + wall_offset),
            self.start + timedelta(seconds=end + wall_offset), start, end,
            sleep_kind=kind,
        )

    def render(self, intervals, columns=80, color=False, samples=None, **kwargs):
        return burnbag.render_battery_depletion_chart(
            self.devices, [self.sample(0), self.sample(60)] if samples is None else samples,
            burnbag.TerminalStyle(color, False), io.StringIO(), columns=columns,
            suspend_intervals=intervals, **kwargs,
        )

    def plot_rows(self, rendered):
        return [line for line in ANSI_ESCAPE.sub("", rendered).splitlines() if " |" in line]

    def test_hibernate_regions_use_green_h_on_magenta_and_fill_all_rows(self):
        intervals = [self.interval(10, 20), self.interval(40, 50)]
        for columns in (20, 40, 190):
            for color in (False, True):
                with self.subTest(columns=columns, color=color):
                    raw = self.render(intervals, columns, color)
                    rows = self.plot_rows(raw)
                    self.assertEqual(len(rows), 25)
                    self.assertTrue(all(len(row) == columns for row in rows))
                    self.assertTrue(rows[0].startswith("80% |"))
                    self.assertTrue(rows[-1].startswith("80% |"))
                    covered = {
                        5 + column
                        for start, end in ((10, 20), (40, 50))
                        for column in range(round(start / 60 * (columns - 6)),
                                            round(end / 60 * (columns - 6)) + 1)
                    }
                    for row in rows:
                        self.assertEqual({i for i, cell in enumerate(row) if cell == "H"}, covered)
                        self.assertNotIn("S", row)
                    middle = 5 + round((columns - 6) / 2)
                    self.assertEqual(rows[0][middle], " ")
                    self.assertEqual(rows[12][middle], "*" if color else "1")
                    plain = ANSI_ESCAPE.sub("", raw)
                    self.assertIn("Hibernate: H=hibernated (full-height block)", plain)
                    self.assertNotIn("Suspend:", plain)
                    self.assertNotIn("mode-unverified", plain)
                    if color:
                        self.assertEqual(raw.count("\x1b[32;45mH\x1b[0m"), len(covered) * 25 + 1)
                    else:
                        self.assertNotIn("\x1b[", raw)

    def test_mixed_periods_keep_distinct_types_and_unchanged_elapsed_positions(self):
        intervals = [self.interval(10, 20, "suspend"), self.interval(40, 50)]
        for color in (False, True):
            raw = self.render(intervals, 40, color)
            rows = self.plot_rows(raw)
            for row in rows:
                self.assertEqual(row[5 + round(15 / 60 * 34)], "S")
                self.assertEqual(row[5 + round(45 / 60 * 34)], "H")
            plain = ANSI_ESCAPE.sub("", raw)
            self.assertIn("Suspend: S=suspended", plain)
            self.assertIn("Hibernate: H=hibernated", plain)
            self.assertNotIn("mode-unverified", plain)
            self.assertNotIn("both types share", plain)
            adjusted = [self.interval(10, 20, "suspend", 3600), self.interval(40, 50, wall_offset=-3600)]
            self.assertEqual(raw, self.render(adjusted, 40, color))
            if color:
                self.assertIn("\x1b[37;41mS\x1b[0m", raw)
                self.assertIn("\x1b[32;45mH\x1b[0m", raw)

    def test_distinct_subcolumn_periods_preserve_both_modes_by_alternating_rows(self):
        intervals = [self.interval(25, 25.00001, "suspend"), self.interval(25.00002, 25.00003)]
        for columns in (20, 40, 190):
            for color in (False, True):
                with self.subTest(columns=columns, color=color):
                    raw = self.render(intervals, columns, color)
                    rows = self.plot_rows(raw)
                    column = 5 + round(25 / 60 * (columns - 6))
                    self.assertEqual([row[column] for row in rows], ["H", "S"] * 12 + ["H"])
                    self.assertTrue(all(row.count("S") + row.count("H") == 1 for row in rows))
                    self.assertIn("S/H alternate where both types share one column", raw)
                    if color:
                        self.assertEqual(raw.count("\x1b[32;45mH\x1b[0m"), 14)
                        self.assertEqual(raw.count("\x1b[37;41mS\x1b[0m"), 13)

    def test_overlapping_intervals_preserve_both_modes_regardless_of_input_order(self):
        intervals = [self.interval(10, 30, "suspend"), self.interval(20, 40)]
        raw = self.render(intervals, 40, True)
        self.assertEqual(raw, self.render(list(reversed(intervals)), 40, True))
        rows = self.plot_rows(raw)
        self.assertTrue(all(row[5 + round(15 / 60 * 34)] == "S" for row in rows))
        self.assertTrue(all(row[5 + round(35 / 60 * 34)] == "H" for row in rows))
        overlap = 5 + round(25 / 60 * 34)
        self.assertEqual({row[overlap] for row in rows}, {"S", "H"})

    def test_hibernation_covers_battery_and_lid_lines_but_retains_lid_header(self):
        events = [burnbag.LidEvent(self.start + timedelta(seconds=15), 15, True)]
        raw = self.render([self.interval(10, 20)], 40, True, lid_events=events)
        header = ANSI_ESCAPE.sub("", raw).splitlines()[2]
        column = header.index("C")
        self.assertTrue(all(row[column] == "H" for row in self.plot_rows(raw)))
        self.assertIn("\x1b[35mC\x1b[0m", raw)

    def test_unknown_mode_keeps_s_and_never_infers_hibernation_or_powered_off(self):
        for kind in ("unknown", "unrecognized", "powered-off"):
            with self.subTest(kind=kind):
                raw = self.render([self.interval(10, 20, kind)], 40, True)
                rows = self.plot_rows(raw)
                self.assertTrue(all("S" in row and "H" not in row for row in rows))
                self.assertTrue(all("0" not in row[5:] for row in rows))
                self.assertIn("S includes mode-unverified sleep", raw)
                self.assertNotIn("Hibernate:", raw)
                self.assertNotIn("\x1b[30;100m", raw)

    def test_hibernate_intervals_clip_to_coverage_and_invalid_periods_disappear(self):
        samples = [self.sample(10), self.sample(50)]
        coverage = dict(coverage_start=(self.start + timedelta(seconds=10), 10),
                        coverage_end=(self.start + timedelta(seconds=50), 50))
        intervals = [self.interval(0, 5), self.interval(5, 20), self.interval(40, 55), self.interval(55, 60)]
        self.assertEqual(self.render(intervals, samples=samples, **coverage),
                         self.render([self.interval(10, 20), self.interval(40, 50)], samples=samples, **coverage))
        invalid = [self.interval(20, 20), self.interval(30, 20), self.interval(-10, 10)]
        invalid.extend(burnbag.SuspendInterval(self.start, self.start, start, end, sleep_kind="hibernate")
                       for start, end in ((float("nan"), 20), (0, float("inf")), (float("-inf"), 20)))
        self.assertEqual(self.render(invalid), self.render([]))

    def test_hibernate_intervals_do_not_create_missing_battery_observations(self):
        intervals = [self.interval(10, 20)]
        for samples in ([], [self.sample(0, {})], [self.sample(0, {"BAT1": 80})]):
            with self.subTest(samples=samples):
                self.assertEqual(self.render(intervals, samples=samples), "")
        raw = self.render(intervals, samples=[self.sample(0), self.sample(30, {}), self.sample(60)])
        self.assertEqual("".join(self.plot_rows(raw)).count("1"), 2)

    def test_sleep_style_reserves_black_zero_on_dark_gray_without_detection(self):
        self.assertEqual(burnbag.SLEEP_REGION_STYLES, {
            "suspend": ("S", "37;41"),
            "hibernate": ("H", "32;45"),
            "powered-off": ("0", "30;100"),
        })


if __name__ == "__main__":
    unittest.main()
