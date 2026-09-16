"""Headless interaction-state tests; real GTK/SQLite paging is covered by GUI tests."""
from types import SimpleNamespace
import unittest

from burnbag_viewer import Viewer


class Selection:
    def __init__(self):
        self.rows = set()

    def unselect_all(self):
        self.rows.clear()

    def select_item(self, position, exclusive):
        if exclusive:
            self.rows.clear()
        self.rows.add(position)


class ViewerSelectionTests(unittest.TestCase):
    def viewer(self):
        viewer = Viewer.__new__(Viewer)
        viewer.view_range = (100., 200.)
        viewer.initial_range = (100., 200.)
        viewer.range_limits = None
        viewer.selected_range = None
        viewer.table_bounds = None
        viewer.fit_button = SimpleNamespace(set_sensitive=lambda enabled: None)
        viewer.focused = None
        viewer.focused_record_id = None
        viewer.pending_record_id = None
        viewer.graph_area = SimpleNamespace(get_width=lambda: 1000, get_height=lambda: 600,
                                           queue_draw=lambda: None)
        viewer._graph_layout = lambda *args: {'plot': (100, 20, 800, 500), 'traces': []}
        viewer.selection = Selection()
        viewer.column_view = None
        viewer.notebook = SimpleNamespace(get_current_page=lambda: 0)
        viewer.loaded = []
        viewer.after = None
        viewer.has_more = True
        viewer.closed = True  # Suppress graph worker scheduling in state-only tests.
        viewer.load_generation = 0
        viewer.loading = False
        viewer.store = None
        viewer.status = None
        viewer.sources = None
        viewer.search_text = ''
        viewer.search_entry = SimpleNamespace(set_text=lambda text: None)
        viewer._load_next_page = lambda: None
        viewer.drag_moved = False
        viewer.drag_origin = None
        return viewer

    def test_drag_both_directions_selects_without_moving_viewport_or_cursor(self):
        for start, dx in ((300, 400), (700, -400)):
            viewer = self.viewer()
            viewer.focused, viewer.focused_record_id = 130., 'cursor'
            viewer._drag_begin(None, start, 250)
            viewer._drag_update(None, dx, 0)
            self.assertEqual(viewer.selected_range, (125., 175.))
            self.assertIsNone(viewer.table_bounds, 'preview does not repeatedly query table')
            viewer._drag_end(None, dx, 0)
            self.assertEqual(viewer.table_bounds, (125., 175.))
            self.assertEqual(viewer.view_range, (100., 200.))
            self.assertEqual(viewer.focused_record_id, 'cursor')
            viewer._graph_clicked(None, 2, 700, 250)
            self.assertEqual(viewer.selected_range, (125., 175.), 'drag release is not a double-click')

    def test_click_jitter_ignored_and_drag_clamped_to_plot(self):
        viewer = self.viewer()
        viewer._drag_begin(None, 500, 250)
        viewer._drag_end(None, 3, 0)
        self.assertIsNone(viewer.selected_range)
        self.assertFalse(viewer.drag_moved)
        viewer._drag_begin(None, 500, 250)
        viewer._drag_end(None, -1000, 0)
        self.assertEqual(viewer.selected_range, (100., 150.))
        viewer._drag_begin(None, 500, 250)
        viewer._drag_end(None, 1000, 0)
        self.assertEqual(viewer.selected_range, (150., 200.))
        viewer._drag_begin(None, 50, 250)
        viewer._drag_end(None, 400, 0)
        self.assertEqual(viewer.selected_range, (150., 200.))

    def test_empty_plot_double_click_clears_but_axis_click_does_not(self):
        viewer = self.viewer()
        viewer._set_selected_range((125, 175))
        viewer._graph_clicked(None, 2, 50, 250)
        self.assertEqual(viewer.selected_range, (125, 175))
        viewer._graph_clicked(None, 1, 500, 250)
        self.assertEqual(viewer.selected_range, (125, 175))
        viewer._graph_clicked(None, 2, 500, 250)
        self.assertIsNone(viewer.selected_range)
        self.assertIsNone(viewer.table_bounds)
        self.assertIsNone(viewer.focused_record_id)

    def test_fit_and_exact_twofold_zoom_synchronize_table(self):
        viewer = self.viewer()
        viewer._fit_selection()
        self.assertEqual(viewer.view_range, (100, 200))
        viewer._set_selected_range((125, 175))
        viewer._fit_selection()
        self.assertEqual(viewer.view_range, (125, 175))
        viewer._zoom(.5)
        self.assertEqual(viewer.view_range, (137.5, 162.5))
        self.assertEqual(viewer.selected_range, viewer.view_range)
        self.assertEqual(viewer.table_bounds, viewer.view_range)
        viewer._zoom(2)
        self.assertEqual(viewer.view_range, (125, 175))
        viewer._pan(.25)
        self.assertEqual(viewer.view_range, (137.5, 187.5))
        self.assertEqual(viewer.selected_range, (125, 175))

    def test_single_timestamp_fit_and_hard_locks(self):
        viewer = self.viewer()
        viewer.range_limits = (120, 180)
        viewer._set_selected_range((110, 200))
        self.assertEqual(viewer.selected_range, (120, 180))
        viewer._set_selected_range((120, 120))
        viewer._fit_selection()
        self.assertEqual(viewer.view_range, (120, 121))
        self.assertEqual(viewer.table_bounds, (120, 120))
        viewer._zoom(.5)
        self.assertEqual(viewer.view_range, (120, 121))
        viewer._zoom(100)
        self.assertEqual(viewer.view_range, (120, 180))
        self.assertEqual(viewer.table_bounds, (120, 180))

    def test_cursor_identity_not_timestamp_and_outside_filter_stays_hidden(self):
        viewer = self.viewer()
        viewer.column_view = SimpleNamespace()
        viewer.loaded = [{'captured_at': 150., 'id': 'a'}, {'captured_at': 150., 'id': 'b'}]
        viewer._set_cursor(viewer.loaded[1])
        self.assertEqual(viewer.selection.rows, {1})
        viewer.table_bounds = (160, 180)
        viewer._sync_table_cursor()
        self.assertEqual(viewer.selection.rows, set())
        self.assertEqual(viewer.focused_record_id, 'b')
        self.assertIsNone(viewer.pending_record_id)

    def test_cursor_seek_does_not_rebase_range_or_clear_search(self):
        viewer = self.viewer()
        viewer.search_text = 'battery'
        viewer._set_cursor({'captured_at': 190., 'id': 'late'})
        self.assertEqual(viewer.pending_record_id, 'late')
        self.assertIsNone(viewer.table_bounds)
        self.assertEqual(viewer.search_text, 'battery')

    def test_filter_changes_reject_stale_pages_and_resets_clear_cursor_and_range(self):
        viewer = self.viewer()
        viewer._set_selected_range((125, 175))
        generation = viewer.load_generation
        viewer._set_selected_range((130, 160))
        viewer.closed = False
        viewer._finish_page(generation, '', [{'id': 'stale', 'captured_at': 170}], None)
        self.assertEqual(viewer.loaded, [])
        viewer.closed = True
        viewer._set_cursor({'captured_at': 140., 'id': 'cursor'})
        viewer._reset_view()
        self.assertIsNone(viewer.focused_record_id)
        self.assertIsNone(viewer.selected_range)
        self.assertIsNone(viewer.table_bounds)
        self.assertEqual(viewer.view_range, viewer.initial_range)
        viewer._all_history()
        self.assertIsNone(viewer.view_range)
