"""Shared-unit plot geometry and actual Cairo rendering, without a display."""
import math
import sys
import unittest

from burnbag_viewer_data import axis_scale, graph_layout, graph_point, measurement_unit

PERCENT0 = 'batteries.BAT0.percentage'
PERCENT1 = 'batteries.BAT1.percentage'
WATTS = 'batteries.BAT0.power_w'
ENERGY = 'batteries.BAT0.energy_wh'
TEMP = 'thermal_c.zone0'


def series_for(values, bounds=(100, 200)):
    return {field: {'field': field, 'range': list(bounds), 'sample_count': len(data),
                    'points': [(100 + index * 10, value, field + str(index), 1)
                               for index, value in enumerate(data)]}
            for field, data in values.items()}


class PlotLayoutTests(unittest.TestCase):
    def layout(self, values, width=1100, height=700):
        return graph_layout(list(values), series_for(values), (100, 200), width, height,
                            lambda text: len(text) * 7, 14)

    def test_known_units_and_semantic_dimensionless_groups(self):
        for first, second in ((PERCENT0, PERCENT1), (PERCENT0, 'cpu.busy_percent'),
                              (ENERGY, 'batteries.BAT1.full_wh'),
                              ('batteries.BAT0.charge_ah', 'batteries.BAT1.full_ah'),
                              (TEMP, 'batteries.BAT0.temperature_c'),
                              ('cpu.frequency_mhz.policy0', 'cpu.frequency_mhz.policy1'),
                              ('backlight.panel.brightness', 'backlight.panel.actual_brightness')):
            self.assertEqual(measurement_unit(first), measurement_unit(second))
        fields = ['batteries.BAT0.cycle_count', 'supplies.AC.online', 'backlight.panel.bl_power',
                  'backlight.panel.brightness', 'backlight.other.brightness', 'unknown.x', 'unknown.y']
        self.assertEqual(len({measurement_unit(field)[0] for field in fields}), len(fields))
        self.assertEqual(measurement_unit('unrecognized.percentage')[0], 'field:unrecognized.percentage')

    def test_both_batteries_share_bounds_containing_all_values_on_same_rect(self):
        layout = self.layout({PERCENT0: [10, 15, 12], PERCENT1: [85, 90, 88]})
        self.assertEqual(len(layout['axes']), 1)
        self.assertEqual(layout['axes'][0]['fields'], [PERCENT0, PERCENT1])
        self.assertLessEqual(layout['axes'][0]['range'][0], 10)
        self.assertGreaterEqual(layout['axes'][0]['range'][1], 90)
        self.assertEqual(layout['traces'][0]['range'], layout['traces'][1]['range'])
        for trace in layout['traces']:
            self.assertEqual(trace['plot'], layout['plot'])

    def test_units_alternate_from_outer_edges_inward_with_independent_ranges(self):
        layout = self.layout({PERCENT0: [10, 90], WATTS: [2, 8], ENERGY: [30, 45], TEMP: [-20, 100]})
        axes = layout['axes']
        self.assertEqual([a['side'] for a in axes], ['left', 'right', 'left', 'right'])
        self.assertLess(axes[0]['strip'][0], axes[2]['strip'][0])
        self.assertGreater(axes[1]['strip'][0], axes[3]['strip'][0])
        self.assertEqual(len({tuple(a['range']) for a in axes}), 4)
        for axis in axes:
            self.assertEqual(axis['strip'][1], layout['plot'][1])
            self.assertEqual(axis['strip'][3], layout['plot'][3])
            self.assertEqual(axis['label_rotation'], -90)
            self.assertEqual(axis['label_center'][1], layout['plot'][1] + layout['plot'][3] / 2)

    def test_hidden_fields_stale_data_and_offscreen_extrema_do_not_set_range(self):
        series = series_for({PERCENT0: [40, 41], PERCENT1: [99]})
        series[PERCENT0]['points'] += [(300, -999, 'outside', 1), (150, float('nan'), 'bad', 1)]
        layout = graph_layout([PERCENT0], series, (100, 200), 900, 600, len, 14)
        self.assertGreater(layout['axes'][0]['range'][0], 30)
        self.assertLess(layout['axes'][0]['range'][1], 50)
        stale = graph_layout([PERCENT0], series, (200, 300), 900, 600, len, 14)
        self.assertEqual(stale['traces'][0]['points'], [])

    def test_ticks_target_ten_divisions_but_reduce_for_small_height(self):
        tall = self.layout({WATTS: [-10, 10]})
        short = self.layout({WATTS: [-10, 10]}, height=160)
        self.assertLess(len(short['axes'][0]['ticks']), len(tall['axes'][0]['ticks']))
        for layout in (tall, short):
            ticks = layout['axes'][0]['ticks']
            self.assertLessEqual(len(ticks), 11)
            self.assertGreater(len(ticks), 2)
            self.assertEqual(len({t['label'] for t in ticks}), len(ticks))
            self.assertTrue(all(a['y'] - b['y'] >= 1.5 * layout['label_height']
                                for a, b in zip(ticks, ticks[1:])))

    def test_flat_empty_extreme_tiny_and_out_of_domain_percentages(self):
        for values in ([], [0], [50], [-7], [1e-200, 9e-200], [1e200, 9e200],
                       [-sys.float_info.max, sys.float_info.max], [5e-324],
                       [1e100, math.nextafter(1e100, math.inf)]):
            for unit in ('percent', 'watts'):
                with self.subTest(values=values, unit=unit):
                    axis = axis_scale(values, 10, unit)
                    low, high = axis['range']
                    self.assertTrue(math.isfinite(low) and math.isfinite(high))
                    self.assertLess(low, high)
                    for value in values:
                        self.assertLessEqual(low, value)
                        self.assertGreaterEqual(high, value)
                        point = graph_point([50, 20, 800, 400], [0, 10], [low, high], 5, value)
                        self.assertTrue(all(math.isfinite(v) for v in point))
                        self.assertGreaterEqual(point[1], 20 - 1e-6)
                        self.assertLessEqual(point[1], 420 + 1e-6)
        outlier = axis_scale([-2, 105], 10, 'percent')
        self.assertLessEqual(outlier['range'][0], -2)
        self.assertGreaterEqual(outlier['range'][1], 105)

    def test_key_centered_lower_inside_plot_half_alpha_and_labels_match_traces(self):
        layout = self.layout({PERCENT0: [20, 30], PERCENT1: [80, 90], ENERGY: [10, 40]})
        x, y, width, height = layout['plot']
        kx, ky, kw, kh = layout['legend']['box']
        self.assertEqual(layout['legend']['alpha'], .5)
        self.assertAlmostEqual(kx + kw / 2, x + width / 2)
        self.assertGreater(ky, y + height / 2)
        self.assertGreaterEqual(kx, x)
        self.assertLessEqual(kx + kw, x + width)
        self.assertLessEqual(ky + kh, y + height)
        self.assertEqual(len({trace['color'] for trace in layout['traces']}), 3)
        for entry, trace in zip(layout['legend']['entries'], layout['traces']):
            self.assertEqual(entry['color'], trace['color'])
            self.assertIn(trace['field'], entry['label'])
            self.assertLessEqual(entry['position'][0] + len(entry['display_label']) * 7, kw)

    def test_small_canvas_is_explicit_not_overlapping_or_negative_rectangles(self):
        for width, height in ((100, 700), (1200, 50), (0, 0)):
            layout = self.layout({PERCENT0: [50], WATTS: [5], ENERGY: [40], TEMP: [30]}, width, height)
            self.assertIsNone(layout['plot'])
            self.assertIn('Enlarge', layout['message'])
        empty = self.layout({})
        self.assertIn('No graph fields', empty['message'])


try:
    import cairo
except ImportError:
    cairo = None


@unittest.skipIf(cairo is None, 'requires native Cairo')
class PlotRenderTests(unittest.TestCase):
    def viewer(self, values):
        from burnbag_viewer import Viewer
        viewer = Viewer.__new__(Viewer)
        viewer.graph_fields = list(values)
        viewer.graph_data = {'range': [100, 200], 'series': series_for(values)}
        viewer.view_range = (100, 200)
        viewer.overview = {'range': [100, 200]}
        viewer.focused = None
        viewer.graph_loading = False
        return viewer

    def test_real_cairo_shared_rect_colors_and_rotated_strip_text(self):
        viewer = self.viewer({PERCENT0: [20, 30, 25], PERCENT1: [80, 90, 85], WATTS: [2, 8, 6]})
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1100, 700)
        cr = cairo.Context(surface)
        viewer._draw_graph(None, cr, 1100, 700)
        layout = viewer._graph_layout(1100, 700, cr)
        pixels, stride = bytes(surface.get_data()), surface.get_stride()
        def count_color(box, rgb):
            x, y, w, h = map(int, box)
            total = 0
            target = [round(v * 255) for v in reversed(rgb)]
            for py in range(max(0, y), min(700, y+h)):
                for px in range(max(0, x), min(1100, x+w)):
                    offset = py * stride + px * 4
                    total += all(abs(pixels[offset+i] - target[i]) < 18 for i in range(3))
            return total
        for trace in layout['traces']:
            self.assertGreater(count_color(layout['plot'], trace['color']), 70)
            self.assertGreater(count_color(layout['legend']['box'], trace['color']), 35)
        for axis in layout['axes']:
            cx, cy = axis['label_center']
            dark = sum(all(pixels[y * stride + x * 4 + channel] < 180 for channel in range(3))
                       for y in range(int(cy-30), int(cy+30))
                       for x in range(int(cx-8), int(cx+8)))
            self.assertGreater(dark, 10, 'rotated unit title must be visible in its strip')
        kx, ky, kw, kh = map(int, layout['legend']['box'])
        translucent_background = sum(all(251 <= pixels[y * stride + x * 4 + channel] <= 253
                                         for channel in range(3))
                                     for y in range(ky+2, ky+kh-2) for x in range(kx+2, kx+kw-2))
        self.assertGreater(translucent_background, kw * kh / 2,
                           'white box must blend at 50% alpha over the off-white plot')

    def test_hit_testing_uses_both_coordinates_and_ignores_axis_strips(self):
        from types import SimpleNamespace
        viewer = self.viewer({PERCENT0: [20, 25], PERCENT1: [80, 85]})
        viewer.graph_area = SimpleNamespace(get_width=lambda: 1100, get_height=lambda: 700,
                                           queue_draw=lambda: None)
        layout = viewer._graph_layout(1100, 700)
        trace = layout['traces'][1]
        point = trace['points'][1]
        position = graph_point(layout['plot'], layout['range'], trace['range'], *point[:2])
        selected = []
        viewer._show_table_record = selected.append
        viewer.notebook = SimpleNamespace(set_current_page=lambda page: None)
        viewer._graph_clicked(None, 2, *position)
        self.assertEqual(selected[0]['id'], point[2])
        viewer._graph_clicked(None, 2, 0, position[1])
        self.assertEqual(len(selected), 1)
        viewer._drag_begin(None, *position)
        self.assertEqual(viewer.drag_width, layout['plot'][2])
        viewer._drag_begin(None, 0, position[1])
        self.assertIsNone(viewer.drag_origin)
