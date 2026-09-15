"""Suspend annotations retain elapsed timing and cover the entire plot height."""

from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import re
import unittest

import burnbag


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class SuspendChartTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
        self.devices = [burnbag.BatteryDevice("BAT0", Path("/unused/BAT0"))]

    def sample(self, elapsed, percentages=None):
        return burnbag.BatterySample(
            self.start + timedelta(seconds=elapsed), elapsed,
            {"BAT0": 80} if percentages is None else percentages,
        )

    def interval(self, start, end, wall_offset=0):
        return burnbag.SuspendInterval(
            self.start + timedelta(seconds=start + wall_offset),
            self.start + timedelta(seconds=end + wall_offset), start, end,
        )

    def coverage(self, elapsed):
        return self.start + timedelta(seconds=elapsed), elapsed

    def render(self, samples, intervals=(), columns=80, color=False, **kwargs):
        return burnbag.render_battery_depletion_chart(
            self.devices, samples, burnbag.TerminalStyle(color, False),
            io.StringIO(), columns=columns, suspend_intervals=intervals, **kwargs,
        )

    def plot_rows(self, rendered):
        return [line for line in ANSI_ESCAPE.sub("", rendered).splitlines() if " |" in line]

    def endpoint_labels(self, rendered):
        lines = ANSI_ESCAPE.sub("", rendered).splitlines()
        axis_index = next(i for i, line in enumerate(lines) if re.match(r"^\s+\+[-+]", line))
        return re.findall(r"\d{2}:\d{2}", lines[axis_index + 1])

    def test_multiple_periods_are_full_height_with_separate_unsuspended_gap(self):
        samples = [self.sample(0), self.sample(60)]
        intervals = [self.interval(10, 20), self.interval(40, 50)]
        for columns in (20, 40, 190):
            for color in (False, True):
                with self.subTest(columns=columns, color=color):
                    raw = self.render(samples, intervals, columns, color)
                    rows = self.plot_rows(raw)
                    self.assertEqual(len(rows), 25)
                    self.assertTrue(all(len(row) == columns for row in rows))
                    self.assertTrue(rows[0].startswith("80% |"))
                    self.assertTrue(rows[-1].startswith("80% |"))
                    plot_max = columns - 6
                    covered = {
                        5 + column
                        for start, end in ((10, 20), (40, 50))
                        for column in range(round(start / 60 * plot_max), round(end / 60 * plot_max) + 1)
                    }
                    for row in rows:
                        self.assertEqual({i for i, cell in enumerate(row) if cell == "S"}, covered)
                    gap = 5 + round(plot_max / 2)
                    self.assertEqual(rows[0][gap], " ")
                    self.assertEqual(rows[12][gap], "*" if color else "1")
                    self.assertNotEqual(rows[0][5], "S")
                    self.assertNotEqual(rows[0][-1], "S")
                    self.assertEqual(self.endpoint_labels(raw), [
                        self.start.astimezone().strftime("%H:%M"),
                        self.coverage(60)[0].astimezone().strftime("%H:%M"),
                    ])
                    if color:
                        self.assertEqual(raw.count("\x1b[37;41mS\x1b[0m"), len(covered) * 25 + 1)
                    else:
                        self.assertNotIn("\x1b[", raw)
                    self.assertIn("=suspended (full-height block)", raw)

    def test_suspend_covers_lid_and_battery_intersections_but_retains_lid_header(self):
        samples = [self.sample(0), self.sample(60)]
        events = [
            burnbag.LidEvent(self.start + timedelta(seconds=20), 20, True),
            burnbag.LidEvent(self.start + timedelta(seconds=50), 50, False),
        ]
        for color in (False, True):
            raw = self.render(samples, [self.interval(10, 30)], 40, color, lid_events=events)
            header = ANSI_ESCAPE.sub("", raw).splitlines()[2]
            close_column, open_column = header.index("C"), header.index("O")
            rows = self.plot_rows(raw)
            self.assertTrue(all(row[close_column] == "S" for row in rows))
            self.assertTrue(all(row[open_column] == ("|" if color else ":")
                                for i, row in enumerate(rows) if i != 12))
            self.assertEqual(rows[12][open_column], "*" if color else "1")

    def test_explicit_coverage_includes_time_before_and_after_battery_sampling(self):
        samples = [self.sample(60), self.sample(120)]
        raw = self.render(
            samples, [self.interval(10, 30)], columns=40,
            coverage_start=self.coverage(0), coverage_end=self.coverage(180),
        )
        rows = self.plot_rows(raw)
        self.assertEqual(self.endpoint_labels(raw)[0], self.start.astimezone().strftime("%H:%M"))
        self.assertEqual(self.endpoint_labels(raw)[-1], self.coverage(180)[0].astimezone().strftime("%H:%M"))
        self.assertTrue(all(row[5] == row[-1] == " " for row in rows))
        cells = rows[12][5:]
        self.assertEqual(cells.count("1"), round(34 * 2 / 3) - round(34 / 3) + 1)
        self.assertIn("S", rows[0])

    def test_suspend_edges_extend_domain_without_creating_battery_samples(self):
        samples = [self.sample(60)]
        intervals = [self.interval(0, 30), self.interval(90, 120)]
        raw = self.render(samples, intervals, columns=40)
        rows = self.plot_rows(raw)
        self.assertTrue(all(row[5] == row[-1] == "S" for row in rows))
        self.assertEqual("".join(rows).count("1"), 1)
        self.assertEqual(self.endpoint_labels(raw)[0], self.start.astimezone().strftime("%H:%M"))
        self.assertEqual(self.endpoint_labels(raw)[-1], self.coverage(120)[0].astimezone().strftime("%H:%M"))

    def test_intervals_clip_to_coverage_and_outside_periods_disappear(self):
        samples = [self.sample(60), self.sample(120)]
        intervals = [self.interval(0, 50), self.interval(55, 70), self.interval(110, 150), self.interval(160, 180)]
        clipped = [self.interval(60, 70), self.interval(110, 120)]
        coverage = dict(coverage_start=self.coverage(60), coverage_end=self.coverage(120))
        self.assertEqual(self.render(samples, intervals, **coverage), self.render(samples, clipped, **coverage))
        rows = self.plot_rows(self.render(samples, intervals, **coverage))
        self.assertTrue(all(row[5] == row[-1] == "S" for row in rows))
        self.assertEqual(rows[0][40], " ")

    def test_invalid_and_zero_duration_intervals_do_not_create_suspend_blocks(self):
        samples = [self.sample(0), self.sample(60)]
        invalid = [self.interval(20, 20), self.interval(30, 20), self.interval(-10, 10)]
        for start, end in ((float("nan"), 20), (0, float("inf")), (float("-inf"), 20)):
            invalid.append(burnbag.SuspendInterval(self.start, self.start, start, end))
        baseline = self.render(samples)
        self.assertEqual(self.render(samples, invalid), baseline)
        self.assertNotIn("Suspend:", baseline)
        self.assertEqual(self.render([self.sample(0)], [self.interval(0, 0)]), self.render([self.sample(0)]))

    def test_subcolumn_period_still_occupies_one_full_column(self):
        samples = [self.sample(0), self.sample(60)]
        for columns in (20, 40, 190):
            with self.subTest(columns=columns):
                rows = self.plot_rows(self.render(samples, [self.interval(25, 25.00001)], columns))
                self.assertTrue(all(row.count("S") == 1 for row in rows))
                self.assertTrue(all(row[5 + round(25 / 60 * (columns - 6))] == "S" for row in rows))

    def test_interval_wall_clock_adjustments_do_not_move_suspend_blocks(self):
        samples = [self.sample(0), self.sample(60)]
        ordinary = [self.interval(10, 20), self.interval(40, 50)]
        adjusted = [self.interval(10, 20, 3600), self.interval(40, 50, -3600)]
        self.assertEqual(self.render(samples, ordinary), self.render(samples, adjusted))

    def test_intervals_without_valid_battery_data_do_not_invent_a_chart(self):
        intervals = [self.interval(10, 20)]
        for samples in ([], [self.sample(0, {})], [self.sample(0, {"BAT1": 80})]):
            with self.subTest(samples=samples):
                self.assertEqual(self.render(samples, intervals), "")
        self.assertEqual(burnbag.render_battery_depletion_chart(
            [], [self.sample(0)], burnbag.TerminalStyle(False, False),
            io.StringIO(), suspend_intervals=intervals,
        ), "")

    def test_unavailable_battery_readings_remain_gaps_outside_suspend_blocks(self):
        samples = [self.sample(0), self.sample(30, {}), self.sample(60)]
        rows = self.plot_rows(self.render(samples, [self.interval(10, 20)], columns=40))
        self.assertEqual("".join(rows).count("1"), 2)
        self.assertEqual(rows[12][5 + round(34 / 2)], " ")


if __name__ == "__main__":
    unittest.main()
