"""Lid annotations preserve battery data, event timing, and chart geometry."""

from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import re
import unittest

import burnbag


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class LidEventChartTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)
        self.devices = [burnbag.BatteryDevice("BAT0", Path("/unused/BAT0"))]

    def sample(self, elapsed):
        return burnbag.BatterySample(
            self.start + timedelta(seconds=elapsed), elapsed, {"BAT0": 80}
        )

    def event(self, elapsed, closed, wall_offset=0):
        return burnbag.LidEvent(
            self.start + timedelta(seconds=elapsed + wall_offset), elapsed, closed
        )

    def render(self, samples, events=(), columns=80, color=False):
        return burnbag.render_battery_depletion_chart(
            self.devices, samples, burnbag.TerminalStyle(color, False),
            io.StringIO(), columns=columns, lid_events=events,
        )

    def test_event_lines_have_requested_colors_and_preserve_battery_intersections(self):
        samples = [self.sample(0), self.sample(60)]
        events = [self.event(15, True), self.event(45, False)]
        for columns in (20, 40, 190):
            for color in (False, True):
                with self.subTest(columns=columns, color=color):
                    raw = self.render(samples, events, columns, color)
                    lines = ANSI_ESCAPE.sub("", raw).splitlines()
                    baseline = self.render(samples, columns=columns, color=color)
                    raw_rows = [line for line in raw.splitlines() if " |" in line]
                    baseline_rows = [line for line in baseline.splitlines() if " |" in line]
                    rows = [line for line in lines if " |" in line]
                    self.assertEqual(len(rows), 25)
                    self.assertTrue(all(len(row) == columns for row in rows))
                    self.assertEqual(raw_rows[12], baseline_rows[12])
                    self.assertTrue(rows[0].startswith("80% |"))
                    self.assertTrue(rows[-1].startswith("80% |"))
                    header = lines[2]
                    self.assertEqual(len(header), columns)
                    close_column, open_column = header.index("C"), header.index("O")
                    # Quarter/three-quarter placement is in plot coordinates,
                    # independent of local wall-clock labels or sample cadence.
                    self.assertEqual(close_column, 5 + round((columns - 6) / 4))
                    self.assertEqual(open_column, 5 + round((columns - 6) * 3 / 4))
                    for index, row in enumerate(rows):
                        if index == 12:
                            continue
                        self.assertEqual(row[close_column], "|")
                        self.assertEqual(row[open_column], "|" if color else ":")
                    if color:
                        self.assertIn("\x1b[35m|\x1b[0m", raw)
                        self.assertIn("\x1b[33m|\x1b[0m", raw)
                    else:
                        self.assertNotIn("\x1b[", raw)
                        self.assertIn("C/|=close", raw)
                        self.assertIn("O/:=open", raw)

    def test_fast_close_open_pairs_share_a_marker_without_losing_either_kind(self):
        samples = [self.sample(0), self.sample(60)]
        events = [self.event(30, True), self.event(30.001, False), self.event(30.002, True)]
        for columns in (20, 40, 190):
            for color in (False, True):
                with self.subTest(columns=columns, color=color):
                    raw = self.render(samples, events, columns, color)
                    lines = ANSI_ESCAPE.sub("", raw).splitlines()
                    header = lines[2]
                    self.assertEqual(header.count("B"), 1)
                    self.assertNotIn("C", header)
                    self.assertNotIn("O", header)
                    column = header.index("B")
                    rows = [line for line in lines if " |" in line]
                    self.assertEqual(sum(row[column] == "!" for row in rows), 24)
                    self.assertEqual(rows[12][column], "*" if color else "1")
                    self.assertIn("B/!=both in one column", raw)
                    if color:
                        self.assertIn("\x1b[35m!\x1b[0m", raw)
                        self.assertIn("\x1b[33m!\x1b[0m", raw)

    def test_events_beyond_battery_samples_extend_only_the_plot_time_domain(self):
        samples = [self.sample(20), self.sample(40)]
        events = [self.event(0, True), self.event(60, False)]
        for columns in (20, 40, 190):
            with self.subTest(columns=columns):
                lines = self.render(samples, events, columns).splitlines()
                self.assertEqual(lines[2][5], "C")
                self.assertEqual(lines[2][-1], "O")
                rows = [line for line in lines if " |" in line]
                self.assertTrue(all(row[5] == "|" and row[-1] == ":" for row in rows))
                cells = rows[12][5:]
                first_point = round((columns - 6) / 3)
                last_point = round((columns - 6) * 2 / 3)
                self.assertEqual(cells.count("1"), last_point - first_point + 1)
                self.assertEqual(cells[first_point:last_point + 1], "1" * (last_point - first_point + 1))
                axis_index = next(i for i, line in enumerate(lines) if re.match(r"^\s+\+[-+]", line))
                callouts = re.findall(r"\d{2}:\d{2}", lines[axis_index + 1])
                self.assertEqual(callouts[0], events[0].captured_at.astimezone().strftime("%H:%M"))
                self.assertEqual(callouts[-1], events[-1].captured_at.astimezone().strftime("%H:%M"))

    def test_event_position_uses_elapsed_time_when_wall_clock_changes(self):
        samples = [self.sample(0), self.sample(60)]
        ordinary = [self.event(15, True), self.event(45, False)]
        adjusted = [self.event(15, True, 3600), self.event(45, False, -3600)]
        self.assertEqual(self.render(samples, ordinary), self.render(samples, adjusted))

    def test_zero_duration_events_do_not_create_an_extra_battery_point(self):
        samples = [self.sample(0)]
        events = [self.event(0, True), self.event(0, False)]
        lines = self.render(samples, events, 40).splitlines()
        self.assertEqual(lines[2][5], "B")
        self.assertEqual(lines[2].count("B"), 1)
        cells = "".join(line.split("|", 1)[1] for line in lines if " |" in line)
        self.assertEqual(cells.count("1"), 1)
        self.assertEqual(cells.count("!"), 24)

    def test_events_without_battery_observations_do_not_invent_a_battery_chart(self):
        self.assertEqual(self.render([], [self.event(0, True)]), "")


if __name__ == "__main__":
    unittest.main()
