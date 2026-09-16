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
        env = dict(os.environ, PYTHONPATH=str(ROOT), GDK_BACKEND='x11')
        self.process = subprocess.Popen(['/usr/bin/python3', '-B', '-c', RUNNER,
            *(str(p) for p in self.paths), str(BASE+7200), '--automation', self.sock, *options],
            cwd=ROOT, env=env, stdout=self.log, stderr=self.log)
        return self.wait(lambda state: state['overview_ready'] and not state['graph_loading'] and state['graph_points'] > 0)

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
        self.call('pointer', target='graph', x=.98, y=.5, clicks=2)
        state = self.wait(lambda x: x['tab'] == 'table' and x['table_sources'] == ['user'] and x['selection_count'] == 1)
        self.assertGreater(state['table_range'][0], BASE+6000)
        self.assertEqual(state['search'], '')
        self.call('row', position=0, clicks=2)
        self.wait(lambda x: x['tab'] == 'graph' and not x['graph_loading'])

    def test_last_is_initial_viewport_but_unlocked_navigation_reads_earlier_data(self):
        state = self.launch('--last', '1h')
        self.assertEqual(state['initial_range'], [BASE+3600, BASE+7200])
        self.assertEqual(state['range'], state['initial_range'])
        self.assertIsNone(state['range_limits'])
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
