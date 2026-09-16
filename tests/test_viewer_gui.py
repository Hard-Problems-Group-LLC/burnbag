"""Opt-in real GTK/socket/rendering regression tests on a graphical session.

Run BURNBAG_TEST_GTK=1 /usr/bin/python3 -B -m unittest tests.test_viewer_gui.
Both telemetry sources are isolated SQLite fixtures; no service is changed.
"""
import base64
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from burnbag_viewerctl import request
from tests import test_viewer_data

ROOT = Path(__file__).resolve().parents[1]
BASE = 1789470000.0
RUNNER = '''
from pathlib import Path
import sys
from burnbag_viewer import Viewer, AutomationServer, _load_gtk, parse_viewer_options
from burnbag_viewer_data import HistorySources
args = parse_viewer_options(sys.argv[4:], now=float(sys.argv[3]))
reader = HistorySources([("system", Path(sys.argv[1])), ("user", Path(sys.argv[2]))],
                        bounds=args.initial_range if args.only else None)
viewer = Viewer(*_load_gtk(), initial_range=args.initial_range, only=args.only, sources=reader)
viewer.automation = AutomationServer(viewer, args.automation)
viewer.automation.start()
try:
    viewer.run(["burnbag-viewer-test"])
finally:
    viewer._shutdown(None)
'''


@unittest.skipUnless(os.environ.get('BURNBAG_TEST_GTK') == '1', 'requires opt-in graphical session')
class ViewerGuiTests(unittest.TestCase):
    def setUp(self):
        temp_root = ROOT / '.local/tmp'
        temp_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='vgui-', dir=temp_root)
        self.root = Path(self.temp.name)
        self.paths = [self.root / 'system.db', self.root / 'user.db']
        for path, indexes in zip(self.paths, (range(1200), range(1200, 1440))):
            test_viewer_data.HistorySourcesTests._create(path)
            con = sqlite3.connect(path)
            con.executemany('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)', [
                ('r%04d' % i, 'sample', BASE + i*5, i*5, 'm', 'b', 'c',
                 'system' if i < 1200 else 'user', json.dumps({'batteries': {'BAT0': {
                     'percentage': 80 - (i % 30), 'energy_wh': 30 + i % 20}}}), None, None)
                for i in indexes])
            con.commit()
            con.close()
        self.sock = str(self.root / 'ctl.sock')
        self.process = None
        self.counter = 0
        self.log = (self.root / 'gui.log').open('w+')

    def tearDown(self):
        if self.process:
            if self.process.poll() is None:
                try:
                    self.call('window', action='close')
                    self.process.wait(timeout=10)
                except Exception:
                    self.process.terminate()
                    self.process.wait(timeout=10)
            self.log.flush()
            self.log.seek(0)
            output = self.log.read()
            self.assertNotIn('Traceback', output, output)
            self.assertEqual(self.process.returncode, 0, output)
        self.log.close()
        self.temp.cleanup()

    def launch(self, *options):
        env = dict(os.environ, PYTHONPATH=str(ROOT),
                   GDK_BACKEND=os.environ.get('BURNBAG_TEST_GDK_BACKEND', 'x11'),
                   XDG_CONFIG_HOME=str(self.root / 'config'))
        self.process = subprocess.Popen([sys.executable, '-B', '-c', RUNNER,
            *(str(p) for p in self.paths), str(BASE+7200), '--automation', self.sock, *options],
            cwd=ROOT, env=env, stdout=self.log, stderr=self.log)
        return self.wait(lambda state: state['overview_ready'] and not state['graph_loading'])

    def restart(self):
        self.call('window', action='close')
        self.process.wait(timeout=10)
        self.assertEqual(self.process.returncode, 0)
        return self.launch()

    def set_field(self, view, name, checked):
        return self.call('fields', action='set', view=view, name=name, checked=checked)

    def call(self, operation, **values):
        self.counter += 1
        return request(self.sock, dict(id=str(self.counter), op=operation, **values))

    def wait(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail('viewer exited before acceptance')
            try:
                last = self.call('state')
                if predicate(last):
                    return last
            except (FileNotFoundError, ConnectionRefusedError, RuntimeError):
                pass
            time.sleep(.05)
        self.fail('viewer did not reach requested state: %r' % last)

    def graph_pointer(self, state, fraction, **values):
        plot, size = state['graph_layout']['plot'], state['graph_layout']['size']
        return self.call('pointer', target='graph', x=(plot[0] + plot[2] * fraction) / size[0],
                         y=(plot[1] + plot[3] * .5) / size[1], **values)

    def drag_interval(self, state, first, last):
        self.graph_pointer(state, first, action='press')
        self.graph_pointer(state, last, action='move')
        return self.graph_pointer(state, last, action='release')

    def test_default_merges_both_sources_renders_and_navigates_beyond_first_page(self):
        state = self.launch()
        self.assertEqual(state['available_rows'], 1440)
        self.assertEqual(state['merged_source_counts'], {'system': 1200, 'user': 240})
        self.assertEqual(state['graph_samples'], 1440)
        self.assertEqual(state['range'], [BASE, BASE+7195])
        time.sleep(.15)  # Allow the compositor frame following the completed query.
        frame = self.call('capture')
        import cairo
        surface = cairo.ImageSurface.create_from_png(io.BytesIO(base64.b64decode(frame['base64'])))
        pixels = bytes(surface.get_data())
        blue = sum(pixels[i] > 150 and pixels[i+2] < 100 and pixels[i+1] < 150 for i in range(0, len(pixels), 4))
        self.assertGreater(blue, 1000, 'data curve should be visible in the actual PNG')
        plot = state['graph_layout']['plot']
        self.call('pointer', target='graph', x=(plot[0] + plot[2] * .98) / state['graph_layout']['size'][0],
                  y=.5, clicks=2)
        state = self.call('tab', name='table')
        state = self.wait(lambda x: x['tab'] == 'table' and x['cursor_row_selected'])
        self.assertGreater(state['cursor']['captured_at'], BASE+6000)
        self.assertEqual(state['table_range'][0], BASE)
        self.assertEqual(state['table_sources'], ['system', 'user'])
        self.assertIsNone(state['table_bounds'])
        self.assertEqual(state['search'], '')
        self.call('row', position=0, clicks=2)
        self.wait(lambda x: x['tab'] == 'graph' and not x['graph_loading'])

    def test_last_is_initial_viewport_but_unlocked_navigation_reads_earlier_data(self):
        state = self.launch('--last', '1h')
        self.assertEqual(state['initial_range'], [BASE+3600, BASE+7200])
        self.assertEqual(state['range'], state['initial_range'])
        self.assertIsNone(state['range_limits'])
        self.assertIsNone(state['table_bounds'])
        self.assertEqual(state['table_range'][0], BASE)
        self.assertEqual(state['graph_samples'], 720)
        self.call('pan', fraction=-1)
        state = self.wait(lambda x: not x['graph_loading'] and x['graph_range'] == [BASE, BASE+3600])
        self.assertEqual(state['graph_samples'], 721)
        self.call('series', name='batteries.BAT0.energy_wh')
        state = self.wait(lambda x: not x['graph_loading'])
        self.assertEqual(state['graph_series'], 'batteries.BAT0.energy_wh')
        self.assertEqual(state['range'], [BASE, BASE+3600])

    def test_only_constrains_queries_search_reset_focus_zoom_pan_and_drag(self):
        state = self.launch('--last', '1h', '--only')
        limits = [BASE+3600, BASE+7200]
        self.assertEqual(state['range_limits'], limits)
        self.assertEqual(state['available_rows'], 720)
        for op, values in [('zoom', {'factor': .5}), ('pan', {'fraction': -10}),
                           ('pan', {'fraction': 10}), ('zoom', {'factor': 20}),
                           ('zoom', {'factor': .5}),
                           ('pointer', {'target': 'graph', 'action': 'press', 'x': .2, 'y': .5}),
                           ('pointer', {'target': 'graph', 'action': 'move', 'x': .95, 'y': .5}),
                           ('pointer', {'target': 'graph', 'action': 'release', 'x': .95, 'y': .5}),
                           ('row', {'position': 0, 'clicks': 2}),
                           ('pointer', {'target': 'graph', 'button': 3, 'x': .5, 'y': .5})]:
            state = self.call(op, **values)
            self.assertGreaterEqual(state['range'][0], limits[0])
            self.assertLessEqual(state['range'][1], limits[1])
            self.wait(lambda x: not x['table_loading'])
        # SQL local-time search matches must survive the GTK table filter.
        date = time.strftime('%Y-%m-%d', time.localtime(BASE+3600))
        self.assertEqual(self.call('search', text=date)['search'], date)
        state = self.wait(lambda x: x['search'] == date and x['loaded_rows'] > 0)
        self.assertGreaterEqual(state['table_range'][0], limits[0])
        self.assertLessEqual(state['table_range'][1], limits[1])
        self.call('search', text='r0001')
        state = self.wait(lambda x: x['search'] == 'r0001' and x['loaded_rows'] == 0)
        self.assertEqual(state['range'], limits)
        self.call('key', key='F11')
        state = self.call('key', key='F11')
        self.assertEqual(state['range'], limits)

    def test_fields_cancel_close_escape_never_apply_or_persist(self):
        before = self.launch()
        path = Path(before['preferences_path'])
        self.assertFalse(path.exists())
        for operation, values in (('fields', {'action': 'cancel'}),
                                  ('key', {'key': 'Escape'}),
                                  ('window', {'action': 'close'})):
            self.call('pointer', target='fields')
            draft = self.set_field('graph', 'batteries.BAT0.energy_wh', True)
            self.set_field('table', 'kind', False)
            self.assertIn('batteries.BAT0.energy_wh', draft['fields_dialog']['draft']['graph'])
            self.assertEqual(draft['graph_fields'], before['graph_fields'])
            self.assertEqual(draft['table_fields'], before['table_fields'])
            state = self.call(operation, **values)
            self.assertIsNone(state['fields_dialog'])
            self.assertEqual(state['graph_fields'], before['graph_fields'])
            self.assertEqual(state['table_fields'], before['table_fields'])
            self.assertEqual(state['range'], before['range'])
            self.assertFalse(path.exists())

    def test_fields_ok_saves_overlaid_traces_and_table_columns_across_launches(self):
        before = self.launch('--last', '1h', '--only')
        self.call('select', first=0, last=2)
        result = subprocess.run(['/usr/bin/python3', '-B', str(ROOT / 'burnbag_viewerctl.py'),
                                 '--socket', self.sock, 'fields', 'open'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNotNone(json.loads(result.stdout)['fields_dialog'])
        self.set_field('graph', 'batteries.BAT0.energy_wh', True)
        self.set_field('table', 'kind', False)
        self.set_field('table', 'batteries.BAT0.percentage', False)
        time.sleep(.15)
        frame = self.call('capture')
        self.assertGreater(len(base64.b64decode(frame['base64'])), 4000)
        applied = self.call('key', key='Return')
        self.assertIsNone(applied['fields_dialog'])
        state = self.wait(lambda x: not x['graph_loading'] and len(x['graph_details']) == 2)
        self.assertEqual(state['range'], before['range'])
        self.assertEqual(state['selection_count'], 3)
        self.assertNotIn('kind', state['table_fields'])
        self.assertNotIn('batteries.BAT0.percentage', state['table_fields'])
        self.assertEqual(state['table_fields'][:2], ['date', 'time'])
        self.assertEqual([v['samples'] for v in state['graph_details'].values()], [720, 720])
        time.sleep(.15)
        import cairo
        surface = cairo.ImageSurface.create_from_png(io.BytesIO(base64.b64decode(self.call('capture')['base64'])))
        pixels = bytes(surface.get_data())
        for trace in state['graph_layout']['traces']:
            target = [round(v * 255) for v in reversed(trace['color'])]
            count = sum(all(abs(pixels[i+j] - target[j]) < 18 for j in range(3))
                        for i in range(0, len(pixels), 4))
            self.assertGreater(count, 400, 'both colored traces must be rendered')
            self.assertEqual(trace['plot'], state['graph_layout']['plot'])
        path = Path(state['preferences_path'])
        saved = path.read_bytes()
        self.call('fields', action='open')
        self.set_field('graph', 'batteries.BAT0.percentage', False)
        self.call('fields', action='cancel')
        self.assertEqual(path.read_bytes(), saved)
        restarted = self.restart()
        self.assertEqual(restarted['graph_fields'], state['graph_fields'])
        self.assertEqual(restarted['table_fields'], state['table_fields'])
        # Hit testing uses the shared rectangle, not an obsolete lower panel.
        restarted = self.wait(lambda x: not x['graph_loading'])
        plot, size = restarted['graph_layout']['plot'], restarted['graph_layout']['size']
        self.call('pointer', target='graph', x=(plot[0] + plot[2] * .98) / size[0],
                  y=(plot[1] + plot[3] * .5) / size[1], clicks=2)
        self.call('tab', name='table')
        self.wait(lambda x: x['tab'] == 'table' and x['cursor_row_selected'] and 'user' in x['table_sources'])

    def test_drag_highlight_fit_twofold_zoom_and_clear_keep_views_synchronized(self):
        before = self.launch()
        self.assertFalse(before['fit_enabled'])
        self.assertIsNone(before['selected_range'])
        self.assertEqual(self.call('fit')['range'], before['range'])
        # A press/release with no motion is a click, not a zero-width interval.
        self.graph_pointer(before, .7, action='press')
        clicked = self.graph_pointer(before, .7, action='release')
        cursor = clicked['cursor']
        self.assertIsNotNone(cursor)
        self.assertIsNone(clicked['selected_range'])
        selected = self.drag_interval(before, .8, .2)
        self.assertEqual(selected['range'], before['range'])
        self.assertEqual(selected['cursor'], cursor)
        self.assertTrue(selected['fit_enabled'])
        interval = selected['selected_range']
        self.assertAlmostEqual(interval[0], BASE + 7195 * .2, places=4)
        self.assertAlmostEqual(interval[1], BASE + 7195 * .8, places=4)
        self.call('tab', name='table')
        state = self.wait(lambda x: not x['table_loading'] and x['cursor_row_selected'])
        self.assertGreater(state['loaded_rows'], 500, 'cursor seek must page within the selected interval')
        self.assertGreaterEqual(state['table_range'][0], interval[0])
        self.assertLessEqual(state['table_range'][1], interval[1])
        # Fit works on the table tab, retains cursor, and invokes the real controller.
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'burnbag_viewerctl.py'),
                                 '--socket', self.sock, 'fit'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        fitted = self.wait(lambda x: not x['graph_loading'])
        self.assertEqual(fitted['range'], interval)
        self.assertEqual(fitted['table_bounds'], interval)
        self.assertEqual(fitted['tab'], 'table')
        self.assertEqual(fitted['cursor'], cursor)
        self.call('key', key='plus')
        zoomed = self.wait(lambda x: not x['graph_loading'] and not x['table_loading'])
        self.assertAlmostEqual(zoomed['range'][1] - zoomed['range'][0], (interval[1] - interval[0]) / 2)
        self.assertEqual(zoomed['range'], zoomed['selected_range'])
        self.assertEqual(zoomed['range'], zoomed['table_bounds'])
        self.call('key', key='minus')
        state = self.wait(lambda x: not x['graph_loading'] and not x['table_loading'])
        self.assertEqual(state['range'], interval)
        self.call('tab', name='graph')
        self.graph_pointer(state, .5, clicks=2)
        cleared = self.wait(lambda x: not x['table_loading'])
        self.assertEqual(cleared['tab'], 'graph')
        self.assertIsNone(cleared['selected_range'])
        self.assertIsNone(cleared['table_bounds'])
        self.assertFalse(cleared['fit_enabled'])
        self.assertEqual(cleared['range'], interval)
        self.call('tab', name='table')
        self.wait(lambda x: x['cursor_row_selected'])

    def test_selected_range_search_and_cursor_outside_filter_remain_orthogonal(self):
        state = self.launch()
        cursor = self.graph_pointer(state, .9)['cursor']
        self.drag_interval(state, .1, .3)
        self.call('tab', name='table')
        selected = self.wait(lambda x: not x['table_loading'])
        self.assertEqual(selected['cursor'], cursor)
        self.assertFalse(selected['cursor_row_selected'])
        bounds = selected['table_bounds']
        self.call('search', text='r0001')
        state = self.wait(lambda x: not x['table_loading'] and not x['table_has_more'] and x['loaded_rows'] == 0)
        self.assertEqual(state['selected_range'], bounds)
        self.call('search', text='r0300')
        state = self.wait(lambda x: not x['table_loading'] and x['loaded_rows'] == 1)
        self.assertEqual(state['table_range'], [BASE + 1500, BASE + 1500])
        self.assertEqual(state['table_bounds'], bounds)
        self.assertFalse(state['cursor_row_selected'])
        # Clearing the interval does not clear an independently chosen search.
        self.call('tab', name='graph')
        state = self.graph_pointer(state, .9, clicks=2)
        self.assertIsNone(state['selected_range'])
        self.assertEqual(state['search'], 'r0300')
        self.call('search', text='')
        self.call('tab', name='table')
        state = self.wait(lambda x: x['cursor_row_selected'] and not x['table_loading'])
        self.assertEqual(state['table_range'][0], BASE)
        self.assertIsNone(state['table_bounds'])

    def test_selection_highlight_capture_and_fast_filter_replacement(self):
        state = self.launch()
        self.drag_interval(state, .15, .65)
        self.drag_interval(state, .7, .9)
        self.drag_interval(state, .25, .4)
        selected = self.wait(lambda x: not x['table_loading'])
        bounds = selected['selected_range']
        self.assertEqual(selected['table_bounds'], bounds)
        self.assertGreaterEqual(selected['table_range'][0], bounds[0])
        self.assertLessEqual(selected['table_range'][1], bounds[1])
        self.assertFalse(selected['table_has_more'])
        time.sleep(.15)
        frame = self.call('capture')
        self.assertGreater(len(base64.b64decode(frame['base64'])), 8000)
        capture_dir = os.environ.get('BURNBAG_TEST_CAPTURE_DIR')
        if capture_dir:
            Path(capture_dir, 'selected-range-viewer.png').write_bytes(base64.b64decode(frame['base64']))
        # View table rows also establishes a real time selection and uses Fit.
        self.call('tab', name='table')
        self.call('select', first=0, last=2)
        self.call('view')
        state = self.wait(lambda x: not x['table_loading'] and not x['graph_loading'])
        self.assertEqual(state['tab'], 'graph')
        self.assertEqual(state['range'], state['selected_range'])
        self.assertEqual(state['loaded_rows'], 3)
        # Reset clears all selection/cursor state and restores snapshot coverage.
        self.graph_pointer(state, .5, button=3)
        state = self.wait(lambda x: not x['table_loading'] and not x['graph_loading'])
        self.assertIsNone(state['selected_range'])
        self.assertIsNone(state['cursor'])
        self.assertFalse(state['fit_enabled'])
        self.assertEqual(state['range'], [BASE, BASE+7195])

    def test_empty_selections_and_save_failure_keep_view_transactional(self):
        before = self.launch()
        path = Path(before['preferences_path'])
        path.mkdir(parents=True)  # A real invalid destination, without permission mocks.
        self.call('fields', action='open')
        for view, fields in (('graph', before['graph_fields']), ('table', before['table_fields'][2:])):
            for name in fields:
                self.set_field(view, name, False)
        state = self.call('fields', action='ok')
        self.assertIn('Could not save', state['fields_dialog']['error'])
        self.assertEqual(state['graph_fields'], before['graph_fields'])
        self.assertEqual(state['table_fields'], before['table_fields'])
        path.rmdir()
        state = self.call('fields', action='ok')
        self.assertIsNone(state['fields_dialog'])
        self.assertEqual(state['graph_fields'], [])
        self.assertEqual(state['table_fields'], ['date', 'time'])
        self.assertFalse(state['graph_loading'])
        self.assertEqual(state['graph_points'], 0)
        state = self.restart()
        self.assertEqual(state['graph_fields'], [])
        self.assertEqual(state['table_fields'], ['date', 'time'])

    def test_saved_unavailable_names_survive_and_new_fields_are_unchecked(self):
        path = self.root / 'config/burnbag/viewer.json'
        path.parent.mkdir(parents=True)
        choices = {'version': 1, 'graph': ['batteries.BAT0.percentage', 'missing_sensor'],
                   'table': ['kind', 'missing_column']}
        path.write_text(json.dumps(choices))
        state = self.launch()
        self.assertEqual(state['graph_fields'], ['batteries.BAT0.percentage'])
        self.assertEqual(state['table_fields'], ['date', 'time', 'kind'])
        self.call('fields', action='open')
        with self.assertRaisesRegex(RuntimeError, 'modal'):
            self.call('pan', fraction=1)
        self.call('fields', action='ok')
        self.assertEqual(json.loads(path.read_text()), choices)

    def test_corrupt_preferences_warn_and_cancel_preserves_file(self):
        path = self.root / 'config/burnbag/viewer.json'
        path.parent.mkdir(parents=True)
        path.write_text('broken json')
        state = self.launch()
        self.assertIn('Could not load', state['preference_warning'])
        self.assertEqual(state['graph_fields'], ['batteries.BAT0.percentage'])
        self.call('fields', action='open')
        self.call('fields', action='cancel')
        self.assertEqual(path.read_text(), 'broken json')
        self.call('fields', action='open')
        state = self.call('fields', action='ok')
        self.assertIsNone(state['preference_warning'])
        self.assertEqual(json.loads(path.read_text())['version'], 1)

    def test_shared_units_four_strips_key_fullscreen_and_snapshot_stability(self):
        for path in self.paths:
            with sqlite3.connect(path) as connection:
                rows = connection.execute('SELECT id, data FROM records').fetchall()
                for identity, payload in rows:
                    data = json.loads(payload)
                    index = int(identity[1:])
                    data['batteries']['BAT0']['percentage'] = 10 + index % 10
                    data['batteries']['BAT0']['power_w'] = 2 + index % 4
                    data['batteries']['BAT1'] = {'percentage': 85 + index % 10}
                    data['thermal_c'] = {'zone0': 30 + index % 20}
                    connection.execute('UPDATE records SET data=? WHERE id=?', (json.dumps(data), identity))
        state = self.launch()
        self.call('fields', action='open')
        for field in ('batteries.BAT1.percentage', 'batteries.BAT0.energy_wh',
                      'batteries.BAT0.power_w', 'thermal_c.zone0'):
            self.set_field('graph', field, True)
        self.call('fields', action='ok')
        state = self.wait(lambda state: not state['graph_loading'] and len(state['graph_fields']) == 5)
        layout = state['graph_layout']
        self.assertIsNotNone(layout['plot'])
        self.assertEqual([axis['label'] for axis in layout['axes']], ['%', 'Wh', 'W', '°C'])
        self.assertEqual([axis['side'] for axis in layout['axes']], ['left', 'right', 'left', 'right'])
        self.assertEqual(layout['axes'][0]['fields'], ['batteries.BAT0.percentage', 'batteries.BAT1.percentage'])
        self.assertLessEqual(layout['axes'][0]['range'][0], 10)
        self.assertGreaterEqual(layout['axes'][0]['range'][1], 94)
        self.assertEqual(layout['legend']['alpha'], .5)
        self.assertEqual(len(layout['legend']['entries']), 5)
        for axis in layout['axes']:
            self.assertEqual(axis['label_rotation'], -90)
            self.assertLessEqual(len(axis['ticks']), 11)
            self.assertTrue(all(a['y'] - b['y'] >= 1.5 * layout['label_height']
                                for a, b in zip(axis['ticks'], axis['ticks'][1:])))
        for trace in layout['traces']:
            self.assertEqual(trace['plot'], layout['plot'])
        time.sleep(.15)
        frame = self.call('capture')
        self.assertGreater(len(base64.b64decode(frame['base64'])), 10000)
        # Optional review artifacts belong only to the caller's private test tree.
        capture_dir = os.environ.get('BURNBAG_TEST_CAPTURE_DIR')
        if capture_dir:
            Path(capture_dir, 'shared-unit-viewer.png').write_bytes(base64.b64decode(frame['base64']))
        self.call('key', key='F11')
        fullscreen = self.wait(lambda state: state['fullscreen'] and
                               state['graph_layout']['size'] != layout['size'])
        self.assertEqual([axis['range'] for axis in fullscreen['graph_layout']['axes']],
                         [axis['range'] for axis in layout['axes']])
        self.call('key', key='F11')
        self.wait(lambda state: not state['fullscreen'])
        # A newly committed row stays out of this launch's fixed snapshot.
        test_viewer_data.HistorySourcesTests._insert(self.paths[0], 'after-open', BASE+7300,
                                                    {'batteries': {'BAT0': {'percentage': 100}}})
        self.call('zoom', factor=.5)
        self.wait(lambda state: not state['graph_loading'])
        self.call('pointer', target='graph', button=3, x=.5, y=.5)
        state = self.wait(lambda state: not state['graph_loading'])
        self.assertEqual(state['available_rows'], 1440)
        self.assertEqual(state['range'], [BASE, BASE+7195])
        self.assertEqual(state['graph_details']['batteries.BAT0.percentage']['samples'], 1440)
