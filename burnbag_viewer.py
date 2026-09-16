#!/usr/bin/python3
"""GTK 4 desktop browser for burnbag power history."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

_support_directory = Path(__file__).resolve().parent.parent / "lib" / "burnbag"
if _support_directory.is_dir():
    sys.path.insert(0, str(_support_directory))


def _load_gtk() -> tuple[Any, Any, Any, Any, Any]:
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        gi.require_version("Graphene", "1.0")
        from gi.repository import Gdk, Gio, GLib, Graphene, Gtk
        return Gtk, Gdk, Gio, Graphene, GLib
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            "The burnbag viewer requires GTK 4 and Python GObject introspection "
            "(install python3-gi and gir1.2-gtk-4.0)."
        ) from exc


class Viewer:
    """Native-decorated GTK application shell and notebook."""

    def __init__(self, Gtk: Any, Gdk: Any, Gio: Any,
                 Graphene: Any, GLib: Any) -> None:
        self.Gtk, self.Gdk, self.Gio = Gtk, Gdk, Gio
        self.Graphene, self.GLib = Graphene, GLib
        self.application = Gtk.Application(
            application_id="com.hardproblemsgroup.burnbag.viewer",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.application.connect("activate", self._activate)
        self.application.connect("shutdown", self._shutdown)
        self.window: Optional[Any] = None
        self.notebook: Optional[Any] = None
        self.graph_page: Optional[Any] = None
        self.graph_area: Optional[Any] = None
        self.store: Optional[Any] = None
        self.selection: Optional[Any] = None
        self.filter_model: Optional[Any] = None
        self.search_filter: Optional[Any] = None
        self.column_view: Optional[Any] = None
        self.series_picker: Optional[Any] = None
        self.series_options: list[str] = []
        self.series_field: Optional[str] = None
        self.table_adjustment: Optional[Any] = None
        self.toolbar: Optional[Any] = None
        self.status: Optional[Any] = None
        self.search_entry: Optional[Any] = None
        self.sources: Optional[Any] = None
        self.columns: set[str] = set()
        self.loaded: list[dict[str, Any]] = []
        self.overview: Optional[dict[str, Any]] = None
        self.after: Optional[tuple[float, str]] = None
        self.loading = False
        self.load_generation = 0
        self.search_timeout = 0
        self.pending_record_id: Optional[str] = None
        self.has_more = True
        self.search_text = ""
        self.view_range: Optional[tuple[float, float]] = None
        self.focused: Optional[float] = None
        self.drag_origin: Optional[tuple[float, float, float]] = None
        self.pointer_state = {"target": None, "x": 0.0, "y": 0.0, "buttons": []}
        self.fullscreen = False
        self.automation_path: Optional[str] = None
        self.automation: Optional[AutomationServer] = None

    def _activate(self, application: Any) -> None:
        Gtk = self.Gtk
        if self.window is not None:
            self.window.present()
            return
        window = Gtk.ApplicationWindow(application=application)
        window.set_title("Burnbag Power History")
        window.set_default_size(1100, 720)
        window.set_name("burnbag-history-viewer")

        from burnbag_viewer_data import HistorySources, flatten_data

        self.sources = HistorySources()
        store = self.Gio.ListStore.new(Gtk.StringObject)
        search_filter = Gtk.CustomFilter.new(self._matches_search)
        filtered = Gtk.FilterListModel.new(store, search_filter)
        selection = Gtk.MultiSelection.new(filtered)
        self.store, self.filter_model = store, filtered
        self.search_filter, self.selection = search_filter, selection

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        toolbar.set_margin_start(8)
        toolbar.set_margin_end(8)
        toolbar.set_margin_top(6)
        toolbar.set_margin_bottom(6)
        search = Gtk.SearchEntry()
        search.set_placeholder_text("Search all history…")
        search.set_hexpand(True)
        search.connect("search-changed", self._search_changed)
        self.search_entry = search
        toolbar.append(search)
        series_model = Gtk.StringList.new(["No numeric measurements"])
        expression = Gtk.PropertyExpression.new(Gtk.StringObject, None, "string")
        series_picker = Gtk.DropDown.new(series_model, expression)
        series_picker.set_tooltip_text("Numeric measurement shown in the graph")
        series_picker.connect("notify::selected", self._series_changed)
        self.series_picker = series_picker
        toolbar.append(series_picker)
        for label, callback in (("−", lambda *_: self._zoom(1.8)),
                                ("+", lambda *_: self._zoom(0.55)),
                                ("←", lambda *_: self._pan(-0.25)),
                                ("→", lambda *_: self._pan(0.25))):
            button = Gtk.Button(label=label)
            button.connect("clicked", callback)
            toolbar.append(button)
        view_button = Gtk.Button(label="View selection")
        view_button.connect("clicked", self._view_selection)
        toolbar.append(view_button)
        self.toolbar = toolbar
        root.append(toolbar)
        status = Gtk.Label(xalign=0)
        status.set_ellipsize(3)
        status.set_margin_start(8)
        status.set_margin_end(8)
        status.set_margin_bottom(4)
        self.status = status
        root.append(status)

        notebook = Gtk.Notebook()
        notebook.set_name("history-notebook")
        graph = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        graph.set_name("history-graph-page")
        graph.set_hexpand(True)
        graph.set_vexpand(True)
        graph_area = Gtk.DrawingArea()
        graph_area.set_name("history-graph")
        graph_area.set_content_width(900)
        graph_area.set_content_height(600)
        graph_area.set_hexpand(True)
        graph_area.set_vexpand(True)
        graph_area.set_draw_func(self._draw_graph)
        graph.append(graph_area)
        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("released", self._graph_clicked)
        graph_area.add_controller(click)
        scroll_controller = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
        )
        scroll_controller.connect("scroll", self._graph_scrolled)
        graph_area.add_controller(scroll_controller)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        graph_area.add_controller(drag)
        scroll_controller = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
        )
        scroll_controller.connect("scroll", self._graph_scrolled)
        graph_area.add_controller(scroll_controller)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        graph_area.add_controller(drag)
        table = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        table.set_name("history-table-page")
        table.set_hexpand(True)
        table.set_vexpand(True)
        view = Gtk.ColumnView.new(selection)
        view.set_name("history-table")
        view.set_vexpand(True)
        view.set_reorderable(False)
        view.connect("activate", self._row_activated)
        self.column_view = view
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(view)
        scroll.get_vadjustment().connect("value-changed", self._scroll_changed)
        self.table_adjustment = scroll.get_vadjustment()
        table.append(scroll)
        notebook.append_page(graph, Gtk.Label(label="Graph"))
        notebook.append_page(table, Gtk.Label(label="Measurements"))
        root.append(notebook)
        window.set_child(root)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key_pressed)
        window.add_controller(keys)
        window.connect("close-request", self._close_request)
        self.window, self.notebook, self.graph_page = window, notebook, graph
        self.graph_area = graph_area
        self._add_column("Date", "date", flatten_data)
        self._add_column("Time", "time", flatten_data)
        for field in ("kind", "source"):
            self._add_column(field.title(), field, flatten_data)
        self._load_next_page()
        self._load_overview()
        window.present()

    def _add_column(self, title: str, field: str, flatten_data: Any) -> None:
        if field in self.columns or self.column_view is None:
            return
        Gtk = self.Gtk
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda _factory, item: item.set_child(Gtk.Label(xalign=0)))

        def bind(_factory: Any, item: Any) -> None:
            try:
                record = json.loads(item.get_item().get_string())
                if field == "date":
                    value = datetime.fromtimestamp(record["captured_at"]).strftime("%Y-%m-%d")
                elif field == "time":
                    value = datetime.fromtimestamp(record["captured_at"]).strftime("%H:%M:%S.%f")[:-3]
                else:
                    flat = {"kind": record["kind"], "source": record["source"]}
                    flat.update(flatten_data(record["data"]))
                    value = flat.get(field, "")
                item.get_child().set_text(str(value))
                item.get_child().set_tooltip_text(str(value))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                item.get_child().set_text("")

        factory.connect("bind", bind)
        column = Gtk.ColumnViewColumn.new(title, factory)
        column.set_resizable(True)
        self.column_view.append_column(column)
        self.columns.add(field)

    def _load_next_page(self) -> None:
        if self.loading or not self.has_more or self.sources is None or self.store is None:
            return
        self.loading = True
        generation, cursor, term = self.load_generation, self.after, self.search_text

        def read_page() -> None:
            try:
                if term:
                    page = self.sources.search_page(term, cursor, 500)
                else:
                    page = self.sources.page(cursor, 500)
                error = None
            except Exception as exc:
                page, error = [], str(exc)
            self.GLib.idle_add(self._finish_page, generation, term, page, error)

        threading.Thread(target=read_page, name="burnbag-viewer-history-read",
                          daemon=True).start()

    def _load_overview(self) -> None:
        if self.sources is None:
            return

        def read_overview() -> None:
            try:
                overview = self.sources.overview()
                error = None
            except Exception as exc:
                overview, error = None, str(exc)
            self.GLib.idle_add(self._finish_overview, overview, error)

        threading.Thread(target=read_overview, name="burnbag-viewer-history-overview",
                          daemon=True).start()

    def _finish_overview(self, overview: Optional[dict[str, Any]],
                         error: Optional[str]) -> bool:
        if error:
            if self.status is not None:
                self.status.set_text("Full-history overview failed: " + error)
            return False
        self.overview = overview or {"count": 0, "range": None, "columns": [], "series": {}}
        from burnbag_viewer_data import flatten_data
        for field in self.overview["columns"]:
            self._add_column(field, field, flatten_data)
        self._update_series_options()
        if self.graph_area is not None:
            self.graph_area.queue_draw()
        if self.status is not None and not self.search_text:
            message = "%d total history rows; %d loaded in table; scroll for all records" % (
                self.overview["count"], len(self.loaded))
            source_status = []
            for scope, source_error in (self.sources.errors.items() if self.sources else []):
                source_status.append("%s history unavailable: %s" % (scope, source_error))
            source_status.extend(self.sources.warnings if self.sources else [])
            if source_status:
                message += " — " + "; ".join(source_status)
            self.status.set_text(message)
        return False

    def _finish_page(self, generation: int, term: str,
                     page: list[dict[str, Any]], error: Optional[str]) -> bool:
        if generation != self.load_generation or term != self.search_text:
            return False
        self.loading = False
        if error:
            if self.status is not None:
                self.status.set_text("History read failed: " + error)
            self.has_more = False
            return False
        try:
            from burnbag_viewer_data import flatten_data
            for record in page:
                self.store.append(self.Gtk.StringObject.new(json.dumps(record, separators=(",", ":"))))
                record["_flat"] = flatten_data(record["data"])
                self.loaded.append(record)
                for field in record["_flat"]:
                    self._add_column(field, field, flatten_data)
            if page:
                self._update_series_options()
            if page:
                last = page[-1]
                self.after = (last["captured_at"], last["id"])
            self.has_more = len(page) == 500
            if self.pending_record_id:
                for position, record in enumerate(self.loaded):
                    if record.get("id") == self.pending_record_id:
                        self._select_table_position(position)
                        self.pending_record_id = None
                        break
            if self.status is not None:
                source_status = []
                for scope, error in (self.sources.errors.items() if self.sources else []):
                    source_status.append("%s history unavailable: %s" % (scope, error))
                source_status.extend(self.sources.warnings if self.sources else [])
                if term:
                    message = ("%d matching history rows loaded%s" % (
                        len(self.loaded), "; scroll for more matches" if self.has_more else ""))
                elif self.overview is not None:
                    if self.has_more:
                        message = "%d total history rows; %d loaded in table; scroll for all records" % (
                            self.overview["count"], len(self.loaded))
                    else:
                        message = "All %d history rows loaded in table" % len(self.loaded)
                else:
                    message = "%d history rows loaded; scanning all available history" % len(self.loaded)
                if source_status:
                    message += " — " + "; ".join(source_status)
                self.status.set_text(message)
            if self.graph_area is not None:
                self.graph_area.queue_draw()
        except Exception as exc:
            if self.status is not None:
                self.status.set_text("History read failed: %s" % exc)
            self.has_more = False
        return False

    def _series_changed(self, picker: Any, property_spec: Any) -> None:
        item = picker.get_selected_item()
        if item is None:
            return
        value = item.get_string()
        self.series_field = None if value == "No numeric measurements" else value
        if self.graph_area is not None:
            self.graph_area.queue_draw()

    def _update_series_options(self) -> None:
        if self.series_picker is None:
            return
        if self.overview is not None:
            fields = sorted(self.overview.get("series", {}))
        else:
            fields = sorted({key for row in self.loaded for key, value in row.get("_flat", {}).items()
                             if isinstance(value, (int, float)) and not isinstance(value, bool)})
        fields.sort(key=lambda key: (not key.endswith("percentage"), key))
        self.series_options = fields
        if self.series_field not in fields:
            self.series_field = fields[0] if fields else None
        display = fields or ["No numeric measurements"]
        self.series_picker.set_model(self.Gtk.StringList.new(display))
        self.series_picker.set_sensitive(bool(fields))
        if self.series_field is not None:
            self.series_picker.set_selected(display.index(self.series_field))

    def _scroll_changed(self, adjustment: Any) -> None:
        if (self.has_more and self.loaded and len(self.loaded) % 500 == 0 and
                adjustment.get_value() + adjustment.get_page_size() >=
                adjustment.get_upper() - 600):
            self._load_next_page()

    def _matches_search(self, item: Any) -> bool:
        if not self.search_text:
            return True
        return self.search_text.casefold() in item.get_string().casefold()

    def _search_changed(self, entry: Any) -> None:
        self.search_text = entry.get_text().strip()
        self.view_range = None
        self.focused = None
        if self.search_filter is not None:
            self.search_filter.changed(self.Gtk.FilterChange.DIFFERENT)
        self.load_generation += 1
        self.loading = False
        self.has_more = True
        self.after = None
        self.loaded.clear()
        if self.store is not None:
            self.store.remove_all()
        if self.search_timeout:
            self.GLib.source_remove(self.search_timeout)
        self.search_timeout = self.GLib.timeout_add(300, self._start_search)

    def _start_search(self) -> bool:
        self.search_timeout = 0
        self._load_next_page()
        return False

    def _key_pressed(self, controller: Any, keyval: int, keycode: int,
                     state: Any) -> bool:
        return self._handle_keyval(keyval)

    def _handle_keyval(self, keyval: int) -> bool:
        if keyval == self.Gdk.KEY_F11 and self.window is not None:
            self._set_fullscreen(not self.fullscreen)
            return True
        if keyval == self.Gdk.KEY_Escape and self.fullscreen:
            self._set_fullscreen(False)
            return True
        if keyval in (self.Gdk.KEY_plus, self.Gdk.KEY_equal, self.Gdk.KEY_KP_Add):
            self._zoom(0.55)
            return True
        if keyval in (self.Gdk.KEY_minus, self.Gdk.KEY_KP_Subtract):
            self._zoom(1.8)
            return True
        if keyval in (self.Gdk.KEY_Left, self.Gdk.KEY_KP_Left):
            self._pan(-0.25)
            return True
        if keyval in (self.Gdk.KEY_Right, self.Gdk.KEY_KP_Right):
            self._pan(0.25)
            return True
        if keyval == self.Gdk.KEY_BackSpace and self.search_entry is not None:
            self.search_entry.set_text(self.search_entry.get_text()[:-1])
            return True
        if keyval == self.Gdk.KEY_Return:
            self._view_selection()
            return True
        return False

    def _set_fullscreen(self, enabled: bool) -> None:
        if self.window is None or self.notebook is None:
            return
        if enabled:
            self.notebook.set_current_page(0)
            self.notebook.set_show_tabs(False)
            if self.toolbar is not None:
                self.toolbar.set_visible(False)
            if self.status is not None:
                self.status.set_visible(False)
            self.window.fullscreen()
        else:
            self.window.unfullscreen()
            self.notebook.set_show_tabs(True)
            if self.toolbar is not None:
                self.toolbar.set_visible(True)
            if self.status is not None:
                self.status.set_visible(True)
        self.fullscreen = enabled

    def _draw_graph(self, area: Any, cr: Any, width: int, height: int) -> None:
        cr.set_source_rgb(0.98, 0.98, 0.98)
        cr.paint()
        left, right, top, bottom = 68.0, max(70.0, width - 18.0), 24.0, max(30.0, height - 48.0)
        cr.set_line_width(1.0)
        cr.set_source_rgb(0.78, 0.79, 0.81)
        for index in range(6):
            y = top + (bottom - top) * index / 5
            cr.move_to(left, y)
            cr.line_to(right, y)
        cr.stroke()
        samples = []
        selected_field = self.series_field
        overview_points = (self.overview or {}).get("series", {}).get(selected_field, [])
        if overview_points:
            samples = [(stamp, value) for stamp, value, _identity in overview_points]
        else:
            for record in self.loaded:
                if record.get("kind") not in ("sample", "snapshot", "telemetry"):
                    continue
                value = record.get("_flat", {}).get(selected_field) if selected_field else None
                samples.append((record["captured_at"],
                                float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
                                else None))
        numeric = [(stamp, value) for stamp, value in samples if value is not None]
        if not numeric:
            cr.set_source_rgb(0.25, 0.27, 0.3)
            cr.select_font_face("Sans")
            cr.set_font_size(16)
            cr.move_to(left + 18, top + 30)
            cr.show_text("No numeric observations loaded for the selected measurement")
            return
        minimum = min(t for t, _ in numeric)
        maximum = max(t for t, _ in numeric)
        if self.view_range is not None:
            minimum, maximum = self.view_range
        if maximum <= minimum:
            maximum = minimum + 1.0
        low = min(value for _, value in numeric)
        high = max(value for _, value in numeric)
        suffix = "%" if str(selected_field).endswith("percentage") else (
            " W" if str(selected_field).endswith("power_w") else
            " Wh" if str(selected_field).endswith("energy_wh") else
            "°C" if str(selected_field).endswith("temperature_c") else "")
        pad = max(1.0, (high - low) * .08)
        low, high = low - pad, high + pad
        if suffix == "%":
            low, high = max(0.0, low), min(100.0, high)
        if high <= low:
            low, high = low - 1, high + 1
        cr.set_source_rgb(0.12, 0.35, 0.72)
        cr.set_line_width(2.0)
        previous_stamp: Optional[float] = None
        cr.save()
        cr.rectangle(left, top, right - left, bottom - top)
        cr.clip()
        for stamp, value in samples:
            if value is None:
                previous_stamp = None
                continue
            x = left + (right - left) * (stamp - minimum) / (maximum - minimum)
            y = bottom - (bottom - top) * (value - low) / (high - low)
            if previous_stamp is None or stamp - previous_stamp > 60:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
            previous_stamp = stamp
        cr.stroke()
        cr.restore()
        cr.set_source_rgb(0.15, 0.15, 0.18)
        cr.select_font_face("Sans")
        cr.set_font_size(12)
        cr.move_to(8, top + 4)
        cr.show_text("%.4g%s" % (high, suffix))
        cr.move_to(8, bottom)
        cr.show_text("%.4g%s" % (low, suffix))
        cr.move_to(left, height - 12)
        cr.show_text(datetime.fromtimestamp(minimum).strftime("%Y-%m-%d %H:%M"))
        label = datetime.fromtimestamp(maximum).strftime("%Y-%m-%d %H:%M")
        cr.move_to(max(left + 1, right - 150), height - 12)
        cr.show_text(label)
        cr.move_to(left + 6, top + 18)
        cr.set_source_rgb(0.12, 0.35, 0.72)
        cr.show_text(str(selected_field or "measurement")[:80])
        if self.focused is not None and minimum <= self.focused <= maximum:
            x = left + (right - left) * (self.focused - minimum) / (maximum - minimum)
            cr.set_source_rgb(0.85, 0.16, 0.48)
            cr.set_line_width(2.0)
            cr.move_to(x, top)
            cr.line_to(x, bottom)
            cr.stroke()

    def _row_record(self, position: int) -> Optional[dict[str, Any]]:
        if self.filter_model is None or self.store is None:
            return None
        item = self.filter_model.get_item(position)
        if item is None:
            return None
        try:
            return json.loads(item.get_string())
        except (ValueError, TypeError):
            return None

    def _row_activated(self, view: Any, position: int) -> None:
        record = self._row_record(position)
        if record:
            self._focus_record(record)

    def _focus_record(self, record: dict[str, Any]) -> None:
        stamp = float(record["captured_at"])
        self.focused = stamp
        self.view_range = (stamp - 1800, stamp + 1800)
        if self.notebook is not None:
            self.notebook.set_current_page(0)
        if self.graph_area is not None:
            self.graph_area.queue_draw()

    def _view_selection(self, *_args: Any) -> None:
        if self.selection is None:
            return
        bitset = self.selection.get_selection()
        indexes = [bitset.get_nth(index) for index in range(bitset.get_size())]
        records = [self._row_record(index) for index in indexes]
        stamps = [float(row["captured_at"]) for row in records if row]
        if stamps:
            low, high = min(stamps), max(stamps)
            margin = max(60.0, (high - low) * .05)
            self.view_range = (low - margin, high + margin)
            self.focused = None
            if self.notebook is not None:
                self.notebook.set_current_page(0)
            if self.graph_area is not None:
                self.graph_area.queue_draw()

    def _graph_clicked(self, gesture: Any, count: int, x: float, y: float) -> None:
        if count < 1 or not self.loaded or self.graph_area is None:
            return
        width = float(self.graph_area.get_width())
        left, right = 68.0, max(70.0, width - 18.0)
        minimum = self.view_range[0] if self.view_range else min(row["captured_at"] for row in self.loaded)
        maximum = self.view_range[1] if self.view_range else max(row["captured_at"] for row in self.loaded)
        if maximum <= minimum:
            maximum = minimum + 1
        stamp = minimum + max(0, min(1, (x - left) / max(1, right - left))) * (maximum - minimum)
        overview_points = (self.overview or {}).get("series", {}).get(self.series_field, [])
        if overview_points:
            nearest = min(overview_points, key=lambda row: abs(row[0] - stamp))
            record = {"captured_at": nearest[0], "id": nearest[2]}
        else:
            record = min(self.loaded, key=lambda row: abs(row["captured_at"] - stamp))
        if count >= 2:
            self._focus_record(record)
            self._show_table_record(record)
        else:
            self.focused = float(record["captured_at"])
            self.graph_area.queue_draw()
        if count >= 2 and self.notebook is not None:
            self.notebook.set_current_page(1)

    def _show_table_record(self, record: dict[str, Any]) -> None:
        if self.filter_model is None or self.selection is None or self.column_view is None:
            return
        for position in range(self.filter_model.get_n_items()):
            item = self.filter_model.get_item(position)
            try:
                match = json.loads(item.get_string()).get("id") == record.get("id")
            except (AttributeError, ValueError, TypeError):
                match = False
            if match:
                self.selection.select_item(position, True)
                try:
                    self.column_view.scroll_to(position, None, self.Gtk.ListScrollFlags.FOCUS, None)
                except (AttributeError, TypeError):
                    pass
                return
        identity = record.get("id")
        if identity and self.search_entry is not None:
            term = str(identity)
            self.pending_record_id = term
            saved_range, saved_focus = self.view_range, self.focused
            old_entry = self.search_entry.get_text().strip()
            if old_entry != term:
                self.search_entry.set_text(term)
            if self.search_text != term or old_entry == term:
                self._search_changed(self.search_entry)
            self.view_range, self.focused = saved_range, saved_focus

    def _select_table_position(self, position: int) -> None:
        if self.selection is None or self.column_view is None:
            return
        self.selection.unselect_all()
        self.selection.select_item(position, True)
        try:
            self.column_view.scroll_to(position, None, self.Gtk.ListScrollFlags.FOCUS, None)
        except (AttributeError, TypeError):
            pass

    def _graph_scrolled(self, controller: Any, dx: float, dy: float) -> bool:
        if dy:
            self._zoom(0.8 if dy < 0 else 1.25)
            return True
        return False

    def _drag_begin(self, gesture: Any, x: float, y: float) -> None:
        low, high = self._range()
        self.drag_origin = (x, low, high)

    def _drag_update(self, gesture: Any, dx: float, dy: float) -> None:
        if self.drag_origin is None or self.graph_area is None:
            return
        _origin, low, high = self.drag_origin
        width = max(1, self.graph_area.get_width() - 86)
        shift = -dx / width * (high - low)
        self.view_range = (low + shift, high + shift)
        self.graph_area.queue_draw()

    def _drag_end(self, gesture: Any, dx: float, dy: float) -> None:
        self.drag_origin = None

    def _zoom(self, factor: float) -> None:
        low, high = self._range()
        center = (low + high) / 2
        half = max(.5, (high - low) * factor / 2)
        self.view_range = (center - half, center + half)
        if self.graph_area is not None:
            self.graph_area.queue_draw()

    def _pan(self, fraction: float) -> None:
        low, high = self._range()
        shift = (high - low) * fraction
        self.view_range = (low + shift, high + shift)
        if self.graph_area is not None:
            self.graph_area.queue_draw()

    def _range(self) -> tuple[float, float]:
        if self.view_range is not None:
            return self.view_range
        if self.overview is not None and self.overview.get("range"):
            low, high = self.overview["range"]
            if high <= low:
                high = low + 3600
            return low, high
        if self.loaded:
            stamps = [row["captured_at"] for row in self.loaded]
            low, high = min(stamps), max(stamps)
            if high <= low:
                high = low + 3600
            return low, high
        now = __import__("time").time()
        self.view_range = (now - 86400, now)
        return self.view_range

    def automation_state(self) -> dict[str, Any]:
        return {
            "title": "Burnbag Power History",
            "fullscreen": self.fullscreen,
            "maximized": bool(self.window and self.window.is_maximized()),
            "tab": ("graph" if self.notebook and self.notebook.get_current_page() == 0
                    else "table"),
            "loaded_rows": len(self.loaded),
            "available_rows": (self.overview.get("count") if self.overview is not None else None),
            "overview_ready": self.overview is not None,
            "graph_series": self.series_field,
            "series_options": list(self.series_options),
            "range": list(self._range()),
            "sources": {"available": sorted(self.sources.connections),
                        "errors": dict(self.sources.errors),
                        "warnings": list(self.sources.warnings)},
            "pointer": dict(self.pointer_state),
        }

    def automation_request(self, request: dict[str, Any]) -> dict[str, Any]:
        operation = request.get("op")
        if operation == "state":
            return self.automation_state()
        if operation == "capture":
            return self._capture_client()
        if operation == "tab":
            target = request.get("name")
            if target not in ("graph", "table") or self.notebook is None:
                raise ValueError("tab name must be graph or table")
            self.notebook.set_current_page(0 if target == "graph" else 1)
            return self.automation_state()
        if operation == "search":
            if not isinstance(request.get("text"), str) or self.search_entry is None:
                raise ValueError("search requires text")
            self.search_entry.set_text(request["text"][:4096])
            self._search_changed(self.search_entry)
            return self.automation_state()
        if operation == "view":
            self._view_selection()
            return self.automation_state()
        if operation == "series":
            field = request.get("name")
            if not isinstance(field, str) or field not in self.series_options or self.series_picker is None:
                raise ValueError("graph series name is not a loaded numeric measurement")
            self.series_field = field
            self.series_picker.set_selected(self.series_options.index(field))
            if self.graph_area is not None:
                self.graph_area.queue_draw()
            return self.automation_state()
        if operation == "select":
            first, last = request.get("first"), request.get("last")
            if (self.selection is None or not isinstance(first, int) or
                    not isinstance(last, int) or first < 0 or last < first or
                    last >= self.filter_model.get_n_items()):
                raise ValueError("selection range must identify currently loaded table rows")
            self.selection.unselect_all()
            for position in range(first, last + 1):
                self.selection.select_item(position, False)
            return self.automation_state()
        if operation == "row":
            position = request.get("position")
            clicks = request.get("clicks", 1)
            if (not isinstance(position, int) or position < 0 or
                    position >= self.filter_model.get_n_items() or clicks not in (1, 2)):
                raise ValueError("row operation needs a loaded row index and one or two clicks")
            if clicks == 1:
                self.selection.select_item(position, True)
            else:
                self._row_activated(self.column_view, position)
            return self.automation_state()
        if operation == "key":
            name = request.get("key")
            keyval = self.Gdk.keyval_from_name(name) if isinstance(name, str) else 0
            modifiers = request.get("modifiers", [])
            if not isinstance(modifiers, list) or any(m not in ("CTRL", "SHIFT", "ALT") for m in modifiers):
                raise ValueError("key modifiers may contain CTRL, SHIFT, and ALT")
            if not keyval:
                raise ValueError("unknown viewer key")
            handled = self._handle_keyval(keyval)
            if not handled and self.search_entry is not None and "CTRL" in modifiers:
                if keyval in (self.Gdk.KEY_f, self.Gdk.KEY_F):
                    self.search_entry.grab_focus()
                    handled = True
                elif keyval in (self.Gdk.KEY_a, self.Gdk.KEY_A):
                    self.search_entry.select_region(0, -1)
                    handled = True
            if not handled and self.search_entry is not None and not modifiers:
                codepoint = self.Gdk.keyval_to_unicode(keyval)
                char = chr(codepoint) if codepoint else ""
                if char and char.isprintable():
                    self.search_entry.set_text(self.search_entry.get_text() + char)
                    handled = True
            if not handled:
                raise ValueError("unsupported viewer key")
            return self.automation_state()
        if operation == "zoom":
            factor = float(request.get("factor", 0))
            if not 0.05 <= factor <= 20:
                raise ValueError("zoom factor must be between 0.05 and 20")
            self._zoom(factor)
            return self.automation_state()
        if operation == "pan":
            fraction = float(request.get("fraction", 0))
            if not -10 <= fraction <= 10:
                raise ValueError("pan fraction must be between -10 and 10")
            self._pan(fraction)
            return self.automation_state()
        if operation == "pointer":
            target = request.get("target")
            button = request.get("button", 1)
            clicks = request.get("clicks", 1)
            action = request.get("action", "click")
            x, y = request.get("x", 0), request.get("y", 0)
            if (target not in ("graph", "table", "tab-graph", "tab-table", "view-selection") or
                    button not in (1, 2, 3) or clicks not in (1, 2) or
                    not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or
                    not 0 <= x <= 1 or not 0 <= y <= 1 or
                    action not in ("move", "press", "release", "click", "wheel")):
                raise ValueError("pointer needs a supported target, action, and normalized coordinates")
            self.pointer_state.update(target=target, x=float(x), y=float(y))
            pressed = set(self.pointer_state["buttons"])
            if action == "press":
                pressed.add(button)
            elif action in ("release", "click"):
                pressed.discard(button)
            self.pointer_state["buttons"] = sorted(pressed)
            if action in ("click", "release") and target == "tab-graph" and self.notebook is not None:
                self.notebook.set_current_page(0)
            elif action in ("click", "release") and target == "tab-table" and self.notebook is not None:
                self.notebook.set_current_page(1)
            elif action in ("click", "release") and target == "view-selection":
                self._view_selection()
            elif action in ("click", "release") and target == "graph" and self.graph_area is not None:
                if button == 3:
                    self.view_range = None
                    self.focused = None
                    self.graph_area.queue_draw()
                else:
                    self._graph_clicked(None, clicks, x * self.graph_area.get_width(),
                                         y * self.graph_area.get_height())
            elif action == "wheel":
                delta = float(request.get("delta", 0))
                if not -100 <= delta <= 100:
                    raise ValueError("wheel delta must be between -100 and 100")
                if delta and target == "table" and self.table_adjustment is not None:
                    adjustment = self.table_adjustment
                    target_value = adjustment.get_value() + delta * max(40, adjustment.get_page_size() * .8)
                    adjustment.set_value(max(0, min(target_value,
                                                    adjustment.get_upper() - adjustment.get_page_size())))
                elif delta and target == "graph":
                    self._zoom(0.8 ** delta)
            return self.automation_state()
        if operation == "type_text":
            value = request.get("text")
            if not isinstance(value, str) or self.search_entry is None or len(value) > 4096:
                raise ValueError("type_text requires at most 4096 characters")
            self.search_entry.set_text(self.search_entry.get_text() + value)
            return self.automation_state()
        if operation == "window":
            action = request.get("action")
            if self.window is None or action not in ("minimize", "maximize", "restore", "close"):
                raise ValueError("window action must be minimize, maximize, restore, or close")
            if action == "minimize":
                self.window.minimize()
            elif action == "maximize":
                self.window.maximize()
            elif action == "restore":
                self.window.unmaximize()
            else:
                self.GLib.timeout_add(100, self._close_window_later)
            return self.automation_state()
        raise ValueError("unknown automation operation")

    def _close_window_later(self) -> bool:
        if self.window is not None:
            self.window.close()
        return False

    def _capture_client(self) -> dict[str, Any]:
        if self.window is None:
            raise RuntimeError("viewer window is not ready")
        width, height = self.window.get_width(), self.window.get_height()
        if width < 1 or height < 1 or width * height > 40_000_000:
            raise RuntimeError("viewer client dimensions are unavailable or too large")
        snapshot = self.Gtk.Snapshot.new()
        paintable = self.Gtk.WidgetPaintable.new(self.window)
        paintable.snapshot(snapshot, width, height)
        node = snapshot.to_node()
        if node is None:
            raise RuntimeError("viewer client has no renderable frame")
        native = self.window.get_native()
        renderer = native.get_renderer()
        rect = self.Graphene.Rect().init(0, 0, width, height)
        texture = renderer.render_texture(node, rect)
        if texture is None:
            raise RuntimeError("GTK could not render a viewer frame")
        directory = Path(__file__).resolve().parent / ".local" / "tmp"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="viewer-frame-", suffix=".png", dir=str(directory))
        os.close(fd)
        try:
            if not texture.save_to_png(name):
                raise RuntimeError("GTK could not encode the viewer frame")
            size = os.stat(name).st_size
            if size > 8 * 1024 * 1024:
                raise RuntimeError("viewer frame exceeds the 8 MiB automation limit")
            encoded = base64.b64encode(Path(name).read_bytes()).decode("ascii")
            return {"content_type": "image/png", "width": width,
                    "height": height, "base64": encoded}
        finally:
            os.unlink(name)

    def _close_request(self, window: Any) -> bool:
        return False

    def _shutdown(self, application: Any) -> None:
        if self.automation is not None:
            self.automation.stop()
            self.automation = None
        if self.sources is not None:
            self.sources.close()

    def run(self, argv: list[str]) -> int:
        return int(self.application.run(argv))


class AutomationServer:
    """Small, opt-in, same-UID newline JSON control endpoint."""

    MAX_REQUEST = 256 * 1024
    MAX_RESPONSE = 12 * 1024 * 1024

    def __init__(self, viewer: Viewer, socket_path: str) -> None:
        self.viewer = viewer
        self.path = Path(socket_path)
        if not self.path.is_absolute():
            raise ValueError("automation socket path must be absolute")
        if ".." in self.path.parts:
            raise ValueError("automation socket path must not contain parent-directory components")
        if len(os.fsencode(str(self.path))) >= 104:
            raise ValueError("automation socket path exceeds the Linux Unix-socket limit")
        parent = self.path.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or self.path.parent.resolve() != self.path.parent or
                parent.st_uid != os.geteuid() or
                parent.st_mode & 0o022):
            raise ValueError("automation socket parent must be a private, owned directory")
        self.sock: Optional[socket.socket] = None
        self.inode: Optional[tuple[int, int]] = None
        self.thread: Optional[threading.Thread] = None
        self.stopping = threading.Event()

    def start(self) -> None:
        endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        endpoint.set_inheritable(False)
        try:
            endpoint.bind(str(self.path))
            os.chmod(self.path, 0o600)
            info = self.path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise RuntimeError("automation socket ownership verification failed")
            self.inode = (info.st_dev, info.st_ino)
            endpoint.listen(4)
            endpoint.settimeout(0.25)
            self.sock = endpoint
            self.thread = threading.Thread(target=self._serve, name="burnbag-viewer-automation",
                                           daemon=True)
            self.thread.start()
        except BaseException:
            endpoint.close()
            self._remove_owned_socket()
            raise

    def _serve(self) -> None:
        while not self.stopping.is_set() and self.sock is not None:
            try:
                connection, _address = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                request: dict[str, Any] = {}
                try:
                    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    _pid, uid, _gid = __import__("struct").unpack("3i", credentials)
                    if uid != os.geteuid():
                        raise PermissionError("automation client UID does not match viewer")
                    connection.settimeout(5)
                    data = bytearray()
                    while b"\n" not in data and len(data) <= self.MAX_REQUEST:
                        chunk = connection.recv(min(65536, self.MAX_REQUEST + 1 - len(data)))
                        if not chunk:
                            break
                        data.extend(chunk)
                    if len(data) > self.MAX_REQUEST or b"\n" not in data:
                        raise ValueError("automation request exceeds its limit or lacks newline")
                    request = json.loads(bytes(data).split(b"\n", 1)[0].decode("utf-8"))
                    if not isinstance(request, dict):
                        raise ValueError("automation request must be a JSON object")
                    identity = request.get("id")
                    if not isinstance(identity, (str, int)) or len(str(identity)) > 128:
                        raise ValueError("automation request needs a short string or integer id")
                    response = self._dispatch(request)
                    response["id"] = identity
                    response["ok"] = "error" not in response
                except Exception as exc:
                    response = {"id": request.get("id"),
                                "ok": False, "error": str(exc)[:2048]}
                try:
                    payload = (json.dumps(response, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
                    if len(payload) > self.MAX_RESPONSE:
                        payload = b'{"id":null,"ok":false,"error":"response exceeds size limit"}\n'
                    connection.sendall(payload)
                except OSError:
                    continue

    def _dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        done = threading.Event()
        result: dict[str, Any] = {}
        def invoke() -> bool:
            try:
                result["result"] = self.viewer.automation_request(request)
            except Exception as exc:
                result["error"] = str(exc)[:2048]
            finally:
                done.set()
            return False
        self.viewer.GLib.idle_add(invoke)
        if not done.wait(10):
            raise TimeoutError("viewer did not complete automation request in 10 seconds")
        return result

    def stop(self) -> None:
        self.stopping.set()
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)
        self._remove_owned_socket()

    def _remove_owned_socket(self) -> None:
        try:
            info = self.path.lstat()
            if self.inode == (info.st_dev, info.st_ino) and stat.S_ISSOCK(info.st_mode):
                self.path.unlink()
        except FileNotFoundError:
            pass


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--automation", metavar="SOCKET_PATH",
                        help="enable the local Unix-socket UI automation endpoint")
    args = parser.parse_args(argv)
    try:
        Gtk, Gdk, Gio, Graphene, GLib = _load_gtk()
        viewer = Viewer(Gtk, Gdk, Gio, Graphene, GLib)
        viewer.automation_path = args.automation
        if args.automation:
            viewer.automation = AutomationServer(viewer, args.automation)
            viewer.automation.start()
        try:
            return viewer.run([sys.argv[0]])
        finally:
            viewer._shutdown(None)
    except (OSError, RuntimeError, ValueError) as exc:
        print("burnbag-viewer: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
