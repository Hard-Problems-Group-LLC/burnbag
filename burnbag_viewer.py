#!/usr/bin/python3
"""GTK 4 desktop browser for burnbag power history."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import json
import math
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import time
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
        gi.require_foreign("cairo")
        from gi.repository import Gdk, Gio, GLib, Graphene, Gtk
        if Gtk.get_minor_version() < 6:
            raise ValueError("GTK 4.6 or later is required")
        return Gtk, Gdk, Gio, Graphene, GLib
    except (ImportError, ValueError) as exc:
        raise RuntimeError(
            "The burnbag viewer requires GTK 4.6+ and Python GObject/Cairo introspection "
            "(install python3-gi, python3-gi-cairo and gir1.2-gtk-4.0)."
        ) from exc


def field_preferences_path() -> Path:
    """Use the per-user XDG configuration directory, never a telemetry store."""
    configured = os.environ.get("XDG_CONFIG_HOME", "")
    root = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / ".config"
    return root / "burnbag" / "viewer.json"


def load_field_preferences(path: Path) -> tuple[Optional[dict[str, list[str]]], Optional[str]]:
    """Return explicit selections (including empty lists), or defaults and a warning."""
    try:
        with path.open(encoding="utf-8") as stream:
            contents = stream.read(1024 * 1024 + 1)
        if len(contents) > 1024 * 1024:
            raise ValueError("file exceeds 1 MiB")
        value = json.loads(contents)
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("unsupported preference format")
        selected = {}
        for view in ("graph", "table"):
            fields = value.get(view)
            if (not isinstance(fields, list) or
                    any(not isinstance(field, str) or not field for field in fields)):
                raise ValueError("%s fields must be a list of names" % view)
            selected[view] = sorted(set(fields))
        return selected, None
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as exc:
        return None, "Could not load field preferences from %s: %s" % (path, exc)


def save_field_preferences(path: Path, selected: dict[str, list[str]]) -> None:
    """Publish both selections atomically; a failed write leaves the old file intact."""
    contents = json.dumps(dict(version=1, **selected), ensure_ascii=False, indent=2) + "\n"
    if len(contents) > 1024 * 1024:
        raise ValueError("field preferences exceed 1 MiB")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".viewer-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Viewer:
    """Native-decorated GTK application shell and notebook."""

    def __init__(self, Gtk: Any, Gdk: Any, Gio: Any,
                 Graphene: Any, GLib: Any, *, initial_range=None, only=False, sources=None) -> None:
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
        self.series_options: list[str] = []
        self.series_field: Optional[str] = None
        self.graph_fields: list[str] = []
        self.table_fields: list[str] = []
        self.column_options: list[str] = []
        self.column_widgets: dict[str, Any] = {}
        self.preferences_path = field_preferences_path()
        self.field_preferences, self.preference_warning = load_field_preferences(self.preferences_path)
        self.fields_button = None
        self.fields_dialog = None
        self.fields_notebook = None
        self.field_checks: dict[str, dict[str, Any]] = {}
        self.fields_error = None
        self.table_adjustment: Optional[Any] = None
        self.toolbar: Optional[Any] = None
        self.status: Optional[Any] = None
        self.search_entry: Optional[Any] = None
        self.sources: Optional[Any] = sources
        self.initial_range = initial_range
        self.range_limits = initial_range if only else None
        self.table_bounds = initial_range
        self.startup_now = time.time()
        self.graph_data = None
        self.graph_loading = False
        self.graph_generation = 0
        self.graph_timeout = 0
        self.closed = False
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
        self.view_range: Optional[tuple[float, float]] = initial_range
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

        if self.sources is None:
            self.sources = HistorySources(bounds=self.range_limits)
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
        fields_button = Gtk.Button(label="Fields...")
        fields_button.set_tooltip_text("Choose graph fields and table columns")
        fields_button.set_sensitive(False)
        fields_button.connect("clicked", self._open_fields)
        self.fields_button = fields_button
        toolbar.append(fields_button)
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
        all_button = Gtk.Button(label="All in range" if self.range_limits else "All history")
        all_button.connect("clicked", self._all_history)
        toolbar.append(all_button)
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
        reset_click = Gtk.GestureClick()
        reset_click.set_button(3)
        reset_click.connect("released", lambda *_args: self._reset_view())
        graph_area.add_controller(reset_click)
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
        if self.field_preferences is not None:
            for field in ("kind", "source"):
                self.column_widgets[field].set_visible(field in self.field_preferences["table"])
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
        self.column_widgets[field] = column

    def _load_next_page(self) -> None:
        if self.loading or not self.has_more or self.sources is None or self.store is None:
            return
        self.loading = True
        generation, cursor, term = self.load_generation, self.after, self.search_text
        start, end = self.table_bounds or (None, None)

        def read_page() -> None:
            try:
                if term:
                    page = self.sources.search_page(term, cursor, 500, start=start, end=end)
                else:
                    page = self.sources.page(cursor, 500, start=start, end=end)
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

    def _finish_overview(self, overview, error) -> bool:
        if self.closed:
            return False
        if error:
            self.status.set_text("Full-history overview failed: " + error)
            return False
        self.overview = overview
        self._update_series_options()
        self.fields_button.set_sensitive(True)
        self._update_status()
        return False

    def _update_status(self) -> None:
        if self.status is None or self.sources is None:
            return
        total = str(self.overview["count"]) if self.overview is not None else "scanning"
        parts = ["History: %s records; table: %d%s" % (
            total, len(self.loaded), "+" if self.has_more else "")]
        if self.range_limits:
            parts.append("Range locked")
        if self.table_bounds:
            parts.append("Table limited to selected interval")
        if self.search_text:
            parts.append("Search: " + self.search_text)
        if self.graph_loading:
            parts.append("Loading graph")
        details = []
        for scope, info in self.sources.source_info.items():
            summary = ("%d records" % info.get("count", 0) if info["state"] == "ready" else info["state"])
            parts.append("%s: %s" % (scope, summary))
            details.append("%s: %s — %s%s" % (scope, info["path"], summary,
                          ("; " + info["error"]) if "error" in info else ""))
        parts.extend(self.sources.warnings)
        if self.preference_warning:
            parts.insert(0, self.preference_warning)
            details.insert(0, self.preference_warning)
        self.status.set_text(" · ".join(parts))
        self.status.set_tooltip_text("\n".join(details + self.sources.warnings))

    def _finish_page(self, generation: int, term: str,
                     page: list[dict[str, Any]], error: Optional[str]) -> bool:
        if self.closed or generation != self.load_generation or term != self.search_text:
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
            self._update_status()
            if self.graph_area is not None:
                self.graph_area.queue_draw()
        except Exception as exc:
            if self.status is not None:
                self.status.set_text("History read failed: %s" % exc)
            self.has_more = False
        return False

    def _update_series_options(self) -> None:
        fields = sorted((self.overview or {}).get("series", {}))
        fields.sort(key=lambda key: (not key.endswith("percentage"), key))
        self.series_options = fields
        self.column_options = ["kind", "source"] + sorted(
            set((self.overview or {}).get("columns", [])) - {"date", "time", "kind", "source"})
        chosen = self.field_preferences or {"graph": fields[:1], "table": self.column_options}
        self._apply_fields(chosen)

    def _apply_fields(self, selected: dict[str, list[str]]) -> None:
        from burnbag_viewer_data import flatten_data
        self.graph_fields = [field for field in self.series_options if field in selected["graph"]]
        self.series_field = self.graph_fields[0] if self.graph_fields else None
        self.table_fields = [field for field in self.column_options if field in selected["table"]]
        for field in self.column_options:
            self._add_column(field.title() if field in ("kind", "source") else field, field, flatten_data)
            self.column_widgets[field].set_visible(field in self.table_fields)
        self._queue_graph_read()

    def _open_fields(self, *_args: Any) -> None:
        if self.overview is None:
            raise ValueError("Fields are still being discovered")
        if self.fields_dialog is not None:
            self.fields_dialog.present()
            return
        Gtk = self.Gtk
        dialog = Gtk.Window(title="Fields", transient_for=self.window, modal=True)
        dialog.set_destroy_with_parent(True)
        dialog.set_default_size(820, 480)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for edge in ("top", "bottom", "start", "end"):
            getattr(root, "set_margin_" + edge)(12)
        root.append(Gtk.Label(label="Choose fields, then press OK to save and apply.", xalign=0))
        notebook = Gtk.Notebook()
        notebook.set_vexpand(True)
        self.field_checks = {}
        for view, options, selected in (("graph", self.series_options, self.graph_fields),
                                        ("table", self.column_options, self.table_fields)):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.append(Gtk.Label(label=("Numeric measurements; each has its own scale." if view == "graph"
                                        else "Date and Time are always shown first."), xalign=0))
            grid = Gtk.Grid(column_spacing=18, row_spacing=8, column_homogeneous=True)
            self.field_checks[view] = {}
            for index, field in enumerate(options):
                check = Gtk.CheckButton(label=field)
                check.set_active(field in selected)
                check.set_tooltip_text(field)
                # The built-in label is a widget child, not the optional custom
                # CheckButton.child property (which is absent on GTK 4.6).
                label = check.get_last_child()
                if isinstance(label, Gtk.Label):
                    label.set_ellipsize(3)
                    label.set_max_width_chars(40)
                check.set_hexpand(True)
                grid.attach(check, index % 2, index // 2, 1, 1)
                self.field_checks[view][field] = check
            if not options:
                grid.attach(Gtk.Label(label="No fields available in this history."), 0, 0, 2, 1)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_vexpand(True)
            scroll.set_child(grid)
            box.append(scroll)
            notebook.append_page(box, Gtk.Label(label=view.title()))
        root.append(notebook)
        error = Gtk.Label(xalign=0, wrap=True)
        error.add_css_class("error")
        root.append(error)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions.set_halign(Gtk.Align.END)
        for label, commit in (("Cancel", False), ("OK", True)):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _button, apply: self._finish_fields(apply), commit)
            actions.append(button)
            if commit:
                button.add_css_class("suggested-action")
                dialog.set_default_widget(button)
        root.append(actions)
        dialog.set_child(root)
        dialog.connect("close-request", self._cancel_fields_window)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _controller, keyval, _code, _state: self._fields_key(keyval))
        dialog.add_controller(keys)
        self.fields_dialog, self.fields_notebook, self.fields_error = dialog, notebook, error
        dialog.present()

    def _fields_key(self, keyval: int) -> bool:
        if keyval in (self.Gdk.KEY_Escape, self.Gdk.KEY_Return, self.Gdk.KEY_KP_Enter):
            self._finish_fields(keyval != self.Gdk.KEY_Escape)
            return True
        return False

    def _cancel_fields_window(self, _window: Any) -> bool:
        self._finish_fields(False)
        return True

    def _finish_fields(self, commit: bool) -> None:
        if self.fields_dialog is None:
            return
        if commit:
            # Retain choices absent from this history snapshot (e.g. another battery).
            selected = {view: sorted({field for field, check in checks.items() if check.get_active()} |
                                    (set((self.field_preferences or {}).get(view, [])) - set(checks)))
                        for view, checks in self.field_checks.items()}
            try:
                save_field_preferences(self.preferences_path, selected)
            except (OSError, ValueError) as exc:
                self.fields_error.set_text("Could not save fields: %s. Changes have not been applied." % exc)
                return
            self.field_preferences, self.preference_warning = selected, None
            self._apply_fields(selected)
        dialog, self.fields_dialog = self.fields_dialog, None
        self.field_checks = {}
        self.fields_notebook = self.fields_error = None
        dialog.destroy()

    def _scroll_changed(self, adjustment: Any) -> None:
        if (self.has_more and self.loaded and len(self.loaded) % 500 == 0 and
                adjustment.get_value() + adjustment.get_page_size() >=
                adjustment.get_upper() - 600):
            self._load_next_page()

    def _matches_search(self, item: Any) -> bool:
        # SQLite already searched local timestamps and complete metadata.
        # Filtering JSON again would silently remove valid date/time matches.
        return True

    def _search_changed(self, entry: Any) -> None:
        term = entry.get_text().strip()
        if term == self.search_text:
            return
        self.search_text = term
        self.table_bounds = None
        self.pending_record_id = None
        self._reset_table()
        if self.search_timeout:
            self.GLib.source_remove(self.search_timeout)
        self.search_timeout = self.GLib.timeout_add(300, self._start_search)

    def _reset_table(self) -> None:
        self.load_generation += 1
        self.loading = False
        self.has_more = True
        self.after = None
        self.loaded.clear()
        if self.store is not None:
            self.store.remove_all()

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
        if not self.graph_fields:
            cr.set_source_rgb(0.15, 0.15, 0.18)
            cr.set_font_size(14)
            cr.move_to(24, 40)
            cr.show_text("No graph fields selected. Use Fields... to choose measurements." if self.overview
                         else "Discovering available fields…")
        for field, x, y, panel_width, panel_height in self._graph_panels(width, height):
            cr.save()
            cr.rectangle(x, y, panel_width, panel_height)
            cr.clip()
            cr.translate(x, y)
            self._draw_series_graph(cr, panel_width, panel_height, field)
            cr.restore()

    def _graph_panels(self, width: int, height: int) -> list[tuple[str, float, float, float, float]]:
        count = len(self.graph_fields)
        if not count:
            return []
        columns = (1 if count <= 3 else
                   min(count, max(1, math.ceil(math.sqrt(count * width / max(1, height) * .5)))))
        rows = math.ceil(count / columns)
        return [(field, index % columns * width / columns, index // columns * height / rows,
                 width / columns, height / rows) for index, field in enumerate(self.graph_fields)]

    def _draw_series_graph(self, cr: Any, width: float, height: float, selected_field: str) -> None:
        left, right, top, bottom = 78.0, max(80.0, width - 18.0), 32.0, max(34.0, height - 48.0)
        minimum, maximum = self._range()
        data = (self.graph_data or {}).get("series", {}).get(selected_field, {})
        points = data.get("points", []) if data.get("field") == selected_field and data.get("range") == [minimum, maximum] else []
        suffix = "%" if str(selected_field).endswith(("percentage", "percent")) else (
            " W" if str(selected_field).endswith("power_w") else
            " Wh" if str(selected_field).endswith(("energy_wh", "full_wh")) else
            "°C" if str(selected_field).endswith("temperature_c") or str(selected_field).startswith("thermal_c.") else "")
        if points:
            low, high = min(p[1] for p in points), max(p[1] for p in points)
            pad = max(1.0, (high - low) * .08)
            low, high = low - pad, high + pad
            if suffix == "%":
                low, high = max(0.0, low), min(100.0, high)
        else:
            low, high = 0.0, 100.0 if suffix == "%" else 1.0
        if high <= low:
            high = low + 1
        cr.set_line_width(1.0)
        cr.set_source_rgb(0.78, 0.79, 0.81)
        for index in range(6):
            y = top + (bottom - top) * index / 5
            cr.move_to(left, y)
            cr.line_to(right, y)
        cr.stroke()
        cr.save()
        cr.rectangle(left - 2, top - 2, right - left + 4, bottom - top + 4)
        cr.clip()
        cr.set_source_rgb(0.12, 0.35, 0.72)
        cr.set_line_width(1.8)
        pixels, previous_segment = [], None
        for stamp, value, _identity, segment in points:
            x = left + (right - left) * (stamp - minimum) / (maximum - minimum)
            y = bottom - (bottom - top) * (value - low) / (high - low)
            if segment != previous_segment:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
            pixels.append((x, y))
            previous_segment = segment
        cr.stroke()
        # Dots make individual observations and one-point segments visible.
        for x, y in pixels:
            cr.new_sub_path()
            cr.arc(x, y, 1.5, 0, 2 * math.pi)
        cr.fill()
        cr.restore()
        cr.set_source_rgb(0.15, 0.15, 0.18)
        cr.select_font_face("Sans")
        cr.set_font_size(12)
        cr.move_to(8, top + 4)
        cr.show_text("%.4g%s" % (high, suffix))
        cr.move_to(8, bottom)
        cr.show_text("%.4g%s" % (low, suffix))
        for stamp, align_right in ((minimum, False), (maximum, True)):
            for offset, fmt in ((26, "%H:%M:%S"), (10, "%Y-%m-%d")):
                label = datetime.fromtimestamp(stamp).strftime(fmt)
                label_width = cr.text_extents(label)[2]
                cr.move_to(max(left, right - label_width) if align_right else left, height - offset)
                cr.show_text(label)
        cr.move_to(left + 6, 18)
        label = selected_field
        while len(label) > 1 and cr.text_extents(label)[2] > right - left - 8:
            label = label[:-2] + "…"
        cr.show_text(label)
        if not points:
            cr.move_to(left + 18, top + 30)
            cr.show_text("Loading observations…" if self.graph_loading else "No observations in this interval")
        if self.focused is not None and minimum <= self.focused <= maximum:
            x = left + (right - left) * (self.focused - minimum) / (maximum - minimum)
            cr.set_source_rgb(0.85, 0.16, 0.48)
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
        self._set_view_range(stamp - 1800, stamp + 1800)
        if self.notebook is not None:
            self.notebook.set_current_page(0)

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
            self._set_view_range(low - margin, high + margin)
            self.focused = None
            if self.notebook is not None:
                self.notebook.set_current_page(0)
            if self.graph_area is not None:
                self.graph_area.queue_draw()

    def _graph_clicked(self, gesture: Any, count: int, x: float, y: float) -> None:
        if count < 1 or self.graph_area is None:
            return
        panel = next((p for p in self._graph_panels(self.graph_area.get_width(), self.graph_area.get_height())
                      if p[1] <= x < p[1] + p[3] and p[2] <= y < p[2] + p[4]), None)
        if panel is None:
            return
        field, origin_x, _origin_y, width, _height = panel
        points = (self.graph_data or {}).get("series", {}).get(field, {}).get("points", [])
        if not points:
            return
        minimum, maximum = self._range()
        if (self.graph_data or {}).get("range") != [minimum, maximum]:
            return
        left, right = 78.0, max(80.0, width - 18.0)
        stamp = minimum + max(0, min(1, (x - origin_x - left) / (right - left))) * (maximum - minimum)
        nearest = min(points, key=lambda row: abs(row[0] - stamp))
        self.focused = nearest[0]
        if count >= 2:
            self._show_table_record({"captured_at": nearest[0], "id": nearest[2]})
            self.notebook.set_current_page(1)
        self.graph_area.queue_draw()

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
        # Seek the table by time, preserving context instead of replacing the
        # user's search with an opaque ID or scanning all preceding pages.
        self.search_text = ""
        self.search_entry.set_text("")
        self.table_bounds = (record["captured_at"], self.range_limits[1] if self.range_limits else None)
        self._reset_table()
        self.pending_record_id = record["id"]
        self._load_next_page()

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
        panels = self._graph_panels(self.graph_area.get_width(), self.graph_area.get_height())
        self.drag_width = max(1, (panels[0][3] if panels else self.graph_area.get_width()) - 96)

    def _drag_update(self, gesture: Any, dx: float, dy: float) -> None:
        if self.drag_origin is None or self.graph_area is None:
            return
        _origin, low, high = self.drag_origin
        width = self.drag_width
        shift = -dx / width * (high - low)
        self._set_view_range(low + shift, high + shift)

    def _drag_end(self, gesture: Any, dx: float, dy: float) -> None:
        self.drag_origin = None

    def _zoom(self, factor: float) -> None:
        low, high = self._range()
        center = (low + high) / 2
        half = max(.5, (high - low) * factor / 2)
        self._set_view_range(center - half, center + half)

    def _pan(self, fraction: float) -> None:
        low, high = self._range()
        shift = (high - low) * fraction
        self._set_view_range(low + shift, high + shift)

    def _range(self) -> tuple[float, float]:
        if self.view_range is not None:
            return self.view_range
        if self.overview is not None and self.overview.get("range"):
            low, high = self.overview["range"]
            return (low, high) if high > low else (low - 1, high + 1)
        return self.startup_now - 3600, self.startup_now

    def _set_view_range(self, low: float, high: float) -> None:
        self.view_range = constrain_range((low, high), self.range_limits)
        self._queue_graph_read()

    def _reset_view(self) -> None:
        self.focused = None
        self.view_range = self.initial_range
        self._queue_graph_read()

    def _all_history(self, *_args: Any) -> None:
        self.focused = None
        self.view_range = self.range_limits
        self.table_bounds = self.range_limits
        self.search_text = ""
        self.search_entry.set_text("")
        self.pending_record_id = None
        self._reset_table()
        self._load_next_page()
        self._queue_graph_read()

    def _queue_graph_read(self) -> None:
        if self.closed or self.sources is None:
            return
        self.graph_generation += 1
        if self.graph_timeout:
            self.GLib.source_remove(self.graph_timeout)
            self.graph_timeout = 0
        self.graph_loading = bool(self.graph_fields)
        if self.graph_fields:
            self.graph_timeout = self.GLib.timeout_add(75, self._start_graph_read)
        else:
            self.graph_data = {"range": list(self._range()), "series": {}}
        if self.graph_area is not None:
            self.graph_area.queue_draw()
        self._update_status()

    def _start_graph_read(self) -> bool:
        self.graph_timeout = 0
        generation, fields, bounds = self.graph_generation, list(self.graph_fields), self._range()
        def read() -> None:
            try:
                result = {"range": list(bounds), "series": self.sources.series_many(fields, *bounds)}
                error = None
            except Exception as exc:
                result, error = None, str(exc)
            self.GLib.idle_add(self._finish_graph_read, generation, result, error)
        threading.Thread(target=read, name="burnbag-viewer-graph-read", daemon=True).start()
        return False

    def _finish_graph_read(self, generation, result, error) -> bool:
        if self.closed or generation != self.graph_generation:
            return False
        self.graph_loading = False
        if error:
            self.graph_data = None
            self.status.set_text("Graph read failed: " + error)
        else:
            self.graph_data = result
            self._update_status()
        self.graph_area.queue_draw()
        return False

    def automation_state(self) -> dict[str, Any]:
        series = (self.graph_data or {}).get("series", {})
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
            "graph_fields": list(self.graph_fields),
            "table_fields": [field for field, column in self.column_widgets.items() if column.get_visible()],
            "column_options": list(self.column_options),
            "fields_dialog": ({"tab": "graph" if self.fields_notebook.get_current_page() == 0 else "table",
                               "draft": {view: [field for field, check in checks.items() if check.get_active()]
                                         for view, checks in self.field_checks.items()},
                               "error": self.fields_error.get_text()} if self.fields_dialog else None),
            "preferences_path": str(self.preferences_path),
            "preference_warning": self.preference_warning,
            "series_options": list(self.series_options),
            "range": list(self._range()),
            "initial_range": self.initial_range,
            "range_limits": self.range_limits,
            "table_bounds": self.table_bounds,
            "table_range": [self.loaded[0]["captured_at"], self.loaded[-1]["captured_at"]] if self.loaded else None,
            "table_sources": sorted({row["source"] for row in self.loaded}),
            "search": self.search_text,
            "selection_count": self.selection.get_selection().get_size() if self.selection else 0,
            "graph_loading": self.graph_loading,
            "graph_samples": sum(data.get("sample_count", 0) for data in series.values()),
            "graph_points": sum(len(data.get("points", [])) for data in series.values()),
            "graph_details": {field: {"samples": data["sample_count"], "points": len(data["points"])}
                              for field, data in series.items()},
            "graph_range": (self.graph_data or {}).get("range"),
            "program": str(Path(__file__).resolve()),
            "source_details": self.sources.source_info,
            "merged_source_counts": (self.overview or {}).get("source_counts", {}),
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
        if operation == "fields":
            action = request.get("action", "open")
            if action == "open":
                self._open_fields()
            elif self.fields_dialog is None:
                raise ValueError("open Fields before editing or confirming")
            elif action in ("ok", "cancel"):
                self._finish_fields(action == "ok")
            elif action == "set":
                view, name, checked = request.get("view"), request.get("name"), request.get("checked")
                if (not isinstance(view, str) or not isinstance(name, str) or
                        view not in self.field_checks or name not in self.field_checks[view] or
                        not isinstance(checked, bool)):
                    raise ValueError("fields set requires view, available field name and boolean checked")
                self.fields_notebook.set_current_page(0 if view == "graph" else 1)
                self.field_checks[view][name].set_active(checked)
            elif action == "tab" and request.get("view") in ("graph", "table"):
                self.fields_notebook.set_current_page(0 if request["view"] == "graph" else 1)
            else:
                raise ValueError("fields action must be open, set, tab, ok or cancel")
            return self.automation_state()
        if self.fields_dialog is not None:
            if operation == "key" and request.get("key") in ("Escape", "Return", "KP_Enter"):
                self._fields_key(self.Gdk.keyval_from_name(request["key"]))
                return self.automation_state()
            if operation == "window" and request.get("action") == "close":
                self.fields_dialog.close()
                return self.automation_state()
            raise ValueError("Fields is modal; use fields controls, Return, Escape or window close")
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
            if not isinstance(field, str) or field not in self.series_options:
                raise ValueError("graph series name is not a loaded numeric measurement")
            # Backward-compatible transient single-series command. Persistence
            # remains explicit through Fields OK, as it is for ordinary input.
            self._apply_fields({"graph": [field], "table": self.table_fields})
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
            if (target not in ("graph", "table", "tab-graph", "tab-table", "view-selection", "fields") or
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
            dragging = False
            if target == "graph" and self.graph_area is not None:
                pixels_x, pixels_y = x * self.graph_area.get_width(), y * self.graph_area.get_height()
                if action == "press" and button == 1:
                    self._drag_begin(None, pixels_x, pixels_y)
                elif action in ("move", "release") and self.drag_origin is not None:
                    dragging = True
                    dx = pixels_x - self.drag_origin[0]
                    self._drag_update(None, dx, 0)
                    if action == "release":
                        self._drag_end(None, dx, 0)
            if action in ("click", "release") and target == "fields":
                self._open_fields()
            elif action in ("click", "release") and target == "tab-graph" and self.notebook is not None:
                self.notebook.set_current_page(0)
            elif action in ("click", "release") and target == "tab-table" and self.notebook is not None:
                self.notebook.set_current_page(1)
            elif action in ("click", "release") and target == "view-selection":
                self._view_selection()
            elif action in ("click", "release") and not dragging and target == "graph" and self.graph_area is not None:
                if button == 3:
                    self._reset_view()
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
        target = self.fields_dialog or self.window
        width, height = target.get_width(), target.get_height()
        if width < 1 or height < 1 or width * height > 40_000_000:
            raise RuntimeError("viewer client dimensions are unavailable or too large")
        snapshot = self.Gtk.Snapshot.new()
        paintable = self.Gtk.WidgetPaintable.new(target)
        paintable.snapshot(snapshot, width, height)
        node = snapshot.to_node()
        if node is None:
            raise RuntimeError("viewer client has no renderable frame")
        native = target.get_native()
        renderer = native.get_renderer()
        rect = self.Graphene.Rect().init(0, 0, width, height)
        texture = renderer.render_texture(node, rect)
        if texture is None:
            raise RuntimeError("GTK could not render a viewer frame")
        encoded_png = texture.save_to_png_bytes().get_data()
        if len(encoded_png) > 8 * 1024 * 1024:
            raise RuntimeError("viewer frame exceeds the 8 MiB automation limit")
        return {"content_type": "image/png", "width": width, "height": height,
                "base64": base64.b64encode(encoded_png).decode("ascii")}

    def _close_request(self, window: Any) -> bool:
        return False

    def _shutdown(self, application: Any) -> None:
        self.closed = True
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


def constrain_range(viewport, limits=None):
    low, high = viewport
    if not all(math.isfinite(value) for value in (low, high)) or high <= low:
        raise ValueError("viewport must have finite increasing endpoints")
    if limits is not None:
        width = min(high - low, limits[1] - limits[0])
        low = max(limits[0], min(low, limits[1] - width))
        high = low + width
    # Reject actions outside the same calendar bounds supported by --last.
    for value in (low, high):
        datetime.fromtimestamp(value)
    return low, high


def parse_viewer_options(argv=None, *, now=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--automation", metavar="SOCKET_PATH",
                        help="enable the local Unix-socket UI automation endpoint")
    parser.add_argument("--last", metavar="DURATION", help="initial interval ending now, e.g. '5h' or 'five hours'")
    parser.add_argument("--from", dest="history_from", metavar="TIME", help="initial start as ISO 8601 local time or with offset")
    parser.add_argument("--to", dest="history_to", metavar="TIME", help="initial end as ISO 8601 (default: now)")
    parser.add_argument("--only", action="store_true", help="restrict data and navigation to the supplied range")
    args = parser.parse_args(argv)
    supplied = any(value is not None for value in (args.last, args.history_from, args.history_to))
    if args.only and not supplied:
        parser.error("--only requires --last or --from/--to")
    args.initial_range = None
    if supplied:
        from burnbag_graph import history_range
        try:
            args.initial_range = history_range(args.history_from, args.history_to, now=now, last=args.last)
        except (ValueError, OverflowError, OSError) as exc:
            parser.error(str(exc))
    return args


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_viewer_options(argv)
    try:
        Gtk, Gdk, Gio, Graphene, GLib = _load_gtk()
        viewer = Viewer(Gtk, Gdk, Gio, Graphene, GLib,
                        initial_range=args.initial_range, only=args.only)
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
