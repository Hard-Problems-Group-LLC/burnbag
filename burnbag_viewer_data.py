"""Read-only, incrementally merged access to burnbag history databases."""
from __future__ import annotations

import colorsys
import json
import math
from pathlib import Path
import sqlite3
import sys
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from burnbag_history import HistoryError, SAMPLE_KINDS, SYSTEM_DATABASE, _streams, user_database_path


class HistorySources:
    """Keyset-paged reader that never creates or writes either history store."""

    def __init__(self, sources: Optional[Sequence[Tuple[str, Path]]] = None,
                 bounds: Optional[Tuple[float, float]] = None) -> None:
        self.bounds = bounds
        self.source_info: Dict[str, Dict[str, Any]] = {}
        self.ceilings: Dict[str, int] = {}
        self.errors: Dict[str, str] = {}
        self.connections: Dict[str, sqlite3.Connection] = {}
        self.warnings: List[str] = []
        self.lock = threading.RLock()
        self.system_coverage: Dict[Tuple[str, str, str], List[Tuple[float, float]]] = {}
        self.overlap_warning = False
        if sources is None:
            selected = [("system", SYSTEM_DATABASE)]
            try:
                selected.append(("user", user_database_path()))
            except HistoryError as exc:
                self.errors["user"] = str(exc)
                self.source_info["user"] = {"path": "unresolved", "state": "error", "error": str(exc)}
            self.sources = selected
        else:
            self.sources = list(sources)
        for scope, path in self.sources:
            connection = None
            self.source_info[scope] = {"path": str(path.absolute()), "state": "unavailable"}
            try:
                path.stat()
                uri = "file:" + quote(str(path.absolute()), safe="/") + "?mode=ro"
                connection = sqlite3.connect(uri, uri=True, timeout=1.0,
                                              check_same_thread=False)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version != 1:
                    raise ValueError("unsupported or missing schema version %s" % version)
                connection.execute("SELECT id,kind,captured_at,boottime,machine_id,boot_id,collector_id,scope,data FROM records LIMIT 0")
                self.ceilings[scope] = connection.execute("SELECT coalesce(max(rowid),0) FROM records").fetchone()[0]
                where, params = self._conditions(scope)
                count, first, last = connection.execute(
                    "SELECT count(*),min(captured_at),max(captured_at) FROM records WHERE " + where,
                    params).fetchone()
                if count and not all(math.isfinite(float(value)) for value in (first, last)):
                    raise ValueError("history contains invalid time bounds")
                self.source_info[scope].update(state="ready", count=count,
                                              snapshot_rowid=self.ceilings[scope],
                                              range=[float(first), float(last)] if count else None)
                self.connections[scope] = connection
                if scope == "system":
                    try:
                        rows = connection.execute(
                            "SELECT machine_id,boot_id,stream,first_boot,last_boot FROM coverage"
                        ).fetchall()
                        for row in rows:
                            key = (row["machine_id"], row["boot_id"], row["stream"])
                            self.system_coverage.setdefault(key, []).append(
                                (float(row["first_boot"]), float(row["last_boot"]))
                            )
                    except (sqlite3.Error, ValueError, TypeError):
                        # Older/hand-built schema fixtures can still be read; only
                        # coverage-based overlap suppression is unavailable.
                        self.warnings.append("System coverage metadata is unavailable")
                        self.system_coverage.clear()
            except (OSError, sqlite3.Error, ValueError) as exc:
                self.errors[scope] = str(exc)
                self.source_info[scope].update(state="missing" if isinstance(exc, FileNotFoundError) else "error", error=str(exc))
                self.connections.pop(scope, None)
                if scope == "system":
                    self.system_coverage.clear()
                if connection is not None:
                    connection.close()

    def close(self) -> None:
        with self.lock:
            for connection in self.connections.values():
                connection.close()
            self.connections.clear()

    def _conditions(self, scope: str, start: Optional[float] = None,
                    end: Optional[float] = None) -> Tuple[str, Tuple[Any, ...]]:
        terms, params = ["rowid<=?"], [self.ceilings[scope]]
        if self.bounds:
            start = self.bounds[0] if start is None else max(start, self.bounds[0])
            end = self.bounds[1] if end is None else min(end, self.bounds[1])
        if start is not None:
            terms.append("captured_at>=?")
            params.append(start)
        if end is not None:
            terms.append("captured_at<=?")
            params.append(end)
        return " AND ".join(terms), tuple(params)

    def page(self, after: Optional[Tuple[float, str]] = None,
             limit: int = 500, *, start: Optional[float] = None,
             end: Optional[float] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
        if not 1 <= limit <= 5000:
            raise ValueError("page size must be between 1 and 5000")
        fetched: List[Tuple[str, Dict[str, Any]]] = []
        with self.lock:
            for scope, connection in self.connections.items():
                try:
                    fetched.extend(self._source_page(scope, connection, after, limit, search, start, end))
                except (sqlite3.Error, ValueError, TypeError) as exc:
                    self.errors[scope] = str(exc)
                    self.source_info[scope].update(state="error", error=str(exc))
                    if scope == "system":
                        self.system_coverage.clear()
        return self._merge(fetched, limit)

    def search_page(self, text: str, after: Optional[Tuple[float, str]] = None,
                    limit: int = 500, *, start: Optional[float] = None,
                    end: Optional[float] = None) -> List[Dict[str, Any]]:
        """Search all permitted records, including local timestamps."""
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise ValueError("search text must contain 1 to 4096 characters")
        return self.page(after, limit, search=text, start=start, end=end)

    def _records(self, start: Optional[float] = None, end: Optional[float] = None):
        after = None
        while True:
            page = self.page(after, 500, start=start, end=end)
            if not page:
                return
            yield from page
            after = (page[-1]["captured_at"], page[-1]["id"])
            if len(page) < 500:
                return

    def overview(self, max_buckets: int = 2400) -> Dict[str, Any]:
        """Catalog the complete merged snapshot; retain bounded graph representatives."""
        if not 10 <= max_buckets <= 20000:
            raise ValueError("overview bucket count must be between 10 and 20000")
        raw_bounds = [value for info in self.source_info.values()
                      for value in (info.get("range") or [])]
        if not raw_bounds:
            return {"count": 0, "range": None, "columns": [], "series": {}, "source_counts": {}}
        low, high = min(raw_bounds), max(raw_bounds)
        builders: Dict[str, SeriesBuilder] = {}
        columns, counts = set(), {}
        count, first, last = 0, None, None
        for record in self._records():
            count += 1
            if first is None:
                first = record["captured_at"]
            last = record["captured_at"]
            counts[record["source"]] = counts.get(record["source"], 0) + 1
            flat = flatten_data(record["data"])
            columns.update(flat)
            if record["kind"] not in SAMPLE_KINDS:
                continue
            for field, value in flat.items():
                if _numeric(value) and field not in builders:
                    builders[field] = SeriesBuilder(low, high, max_buckets)
            for field, builder in builders.items():
                builder.add(record, flat.get(field))
        return {"count": count, "range": [first, last] if count else None,
                "columns": sorted(columns), "source_counts": counts,
                "series": {field: builder.points() for field, builder in builders.items()}}

    def series(self, field: str, start: float, end: float,
               max_buckets: int = 1200) -> Dict[str, Any]:
        """Read current viewport at its own resolution, preserving raw continuity."""
        return self.series_many([field], start, end, max_buckets)[field]

    def series_many(self, fields: List[str], start: float, end: float,
                    max_buckets: int = 1200) -> Dict[str, Any]:
        """Read selected measurements in one pass, with independent scales and gaps."""
        builders = {field: SeriesBuilder(start, end, max_buckets) for field in fields}
        for record in self._records(start, end):
            if record["kind"] in SAMPLE_KINDS:
                flat = flatten_data(record["data"])
                for field, builder in builders.items():
                    builder.add(record, flat.get(field))
        return {field: {"field": field, "range": [start, end], "points": builder.points(),
                        "sample_count": builder.count} for field, builder in builders.items()}

    def _source_page(self, scope: str, connection: sqlite3.Connection,
                     after: Optional[Tuple[float, str]], limit: int,
                     search: Optional[str] = None, start: Optional[float] = None,
                     end: Optional[float] = None) -> List[Tuple[str, Dict[str, Any]]]:
        selected: List[Tuple[str, Dict[str, Any]]] = []
        cursor = after
        while len(selected) < limit:
            where, params = self._conditions(scope, start, end)
            if search is not None:
                where += (" AND instr(lower(id || ' ' || kind || ' ' || scope || ' ' || data "
                          "|| ' ' || datetime(captured_at,'unixepoch','localtime')),lower(?))>0")
                params += (search,)
            if cursor is not None:
                where += " AND (captured_at,id)>(?,?)"
                params += cursor
            batch_size = min(5000, max(64, limit - len(selected)))
            rows = connection.execute(
                "SELECT id,kind,captured_at,boottime,machine_id,boot_id,collector_id,scope,data "
                "FROM records WHERE " + where + " ORDER BY captured_at,id LIMIT ?",
                params + (batch_size,)).fetchall()
            if not rows:
                break
            collisions = self._system_collisions(rows) if scope == "user" else set()
            for row in rows:
                cursor = (row["captured_at"], row["id"])
                decoded = self._decode_rows(scope, (row,))
                if not decoded:
                    continue
                item = decoded[0][1]
                if item["id"] in collisions:
                    self._collision_warning()
                    continue
                selected.append((scope, item))
                if len(selected) >= limit:
                    break
        return selected

    def _system_collisions(self, rows: Sequence[sqlite3.Row]) -> set[str]:
        system = self.connections.get("system")
        if system is None or self.source_info["system"]["state"] != "ready":
            return set()
        identities = [row["id"] for row in rows]
        collisions: set[str] = set()
        for offset in range(0, len(identities), 400):
            chunk = identities[offset:offset + 400]
            marks = ",".join("?" for _ in chunk)
            rows = system.execute(
                "SELECT * FROM records WHERE rowid<=? AND id IN (" + marks + ")",
                [self.ceilings["system"]] + chunk).fetchall()
            collisions.update(item["id"] for _, item in self._decode_rows("system", rows))
        return collisions

    def _collision_warning(self) -> None:
        warning = "History ID collision detected; system record takes precedence"
        if warning not in self.warnings:
            self.warnings.append(warning)

    def _decode_rows(self, scope: str, rows: Sequence[sqlite3.Row]) -> List[Tuple[str, Dict[str, Any]]]:
        result = []
        for row in rows:
            try:
                if not all(math.isfinite(float(row[key])) for key in ("captured_at", "boottime")):
                    raise ValueError("record time is not finite")
                data = json.loads(row["data"])
                if not isinstance(data, dict):
                    raise ValueError("record data is not an object")
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                warning = "%s history contains an invalid record: %s" % (scope, exc)
                if warning not in self.warnings:
                    self.warnings.append(warning)
                if scope == "system":
                    self.system_coverage.clear()
                continue
            item = dict(row)
            item["captured_at"] = float(item["captured_at"])
            item["boottime"] = float(item["boottime"])
            item["data"] = data
            item["source"] = scope
            if scope == "user" and item["kind"] in SAMPLE_KINDS:
                item, suppressed = self._suppress_system_covered(item)
                if item is None:
                    continue
                if suppressed and not self.overlap_warning:
                    self.warnings.append(
                        "System coverage takes precedence for overlapping user measurement streams"
                    )
                    self.overlap_warning = True
            result.append((scope, item))
        return result

    def _suppress_system_covered(self, item: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], bool]:
        payload = item["data"]
        suppressed = []
        for stream in _streams(payload):
            intervals = self.system_coverage.get(
                (item["machine_id"], item["boot_id"], stream), ()
            )
            if any(first <= item["boottime"] <= last for first, last in intervals):
                suppressed.append(stream)
        if not suppressed:
            return item, False
        data = json.loads(json.dumps(payload))
        for stream in suppressed:
            parts = stream.split("/")
            parent = data
            for part in parts[:-1]:
                parent = parent.get(part, {})
            if isinstance(parent, dict):
                parent.pop(parts[-1], None)
                if parts[-1] == "percentage":
                    parent.pop("percentage_source", None)
                if parts[-1] == "power_w":
                    parent.pop("power_source", None)
        for section in ("batteries", "supplies", "backlight"):
            values = data.get(section)
            if isinstance(values, dict):
                for name, fields in list(values.items()):
                    if isinstance(fields, dict) and not any(
                        field not in ("metadata", "percentage_source", "power_source")
                        for field in fields
                    ):
                        values.pop(name)
        if not _streams(data):
            return None, True
        copied = dict(item)
        copied["data"] = data
        copied["suppressed_streams"] = suppressed
        return copied, True

    def _merge(self, fetched: List[Tuple[str, Dict[str, Any]]], limit: int) -> List[Dict[str, Any]]:
        fetched.sort(key=lambda pair: (pair[1]["captured_at"], pair[1]["id"], pair[0]))
        unique: Dict[str, Dict[str, Any]] = {}
        duplicates = 0
        for scope, item in fetched:
            prior = unique.get(item["id"])
            if prior is None or (scope == "system" and prior["source"] != "system"):
                unique[item["id"]] = item
            if prior is not None:
                duplicates += 1
        if duplicates:
            warning = "%d duplicate history record ID(s); system record preferred" % duplicates
            if warning not in self.warnings:
                self.warnings.append(warning)
        return sorted(unique.values(), key=lambda item: (item["captured_at"], item["id"]))[:limit]


def flatten_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten nested telemetry into stable dotted measurement column names."""
    result: Dict[str, Any] = {}
    def visit(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                name = str(key) if not prefix else prefix + "." + str(key)
                visit(name, value[key])
        elif isinstance(value, list):
            result[prefix] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        elif value is not None:
            result[prefix] = value
    visit("", data)
    return result


def _numeric(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def measurement_unit(field: str) -> Tuple[str, str]:
    """Return a semantic grouping key and display unit, never generic unitless.

    Brightness counts depend on the device's hardware scale. Unknown fields
    are intentionally isolated until their units have an explicit contract.
    """
    suffix = field.rsplit('.', 1)[-1]
    units = {
        'percentage': ('percent', '%'), 'busy_percent': ('percent', '%'),
        'power_w': ('watts', 'W'), 'energy_wh': ('watt_hours', 'Wh'),
        'full_wh': ('watt_hours', 'Wh'), 'voltage_v': ('volts', 'V'),
        'current_a': ('amps', 'A'), 'charge_ah': ('amp_hours', 'Ah'),
        'full_ah': ('amp_hours', 'Ah'), 'temperature_c': ('celsius', '°C'),
        'cycle_count': ('cycles', 'Cycles'),
    }
    if field.startswith('thermal_c.'):
        return 'celsius', '°C'
    if field.startswith('cpu.frequency_mhz.'):
        return 'megahertz', 'MHz'
    if field.startswith(('batteries.', 'supplies.', 'cpu.')) and suffix in units:
        return units[suffix]
    if field.startswith('supplies.') and suffix == 'online':
        return 'online_state', 'Online state'
    if field.startswith('backlight.'):
        if suffix == 'bl_power':
            return 'backlight_power_state', 'Backlight power state'
        if suffix in ('brightness', 'actual_brightness'):
            device = field.rsplit('.', 1)[0]
            return device + '.counts', 'Brightness counts: ' + device.split('.', 1)[1]
    return 'field:' + field, 'Value: ' + field


def axis_scale(values: Sequence[float], divisions: int, unit: str) -> Dict[str, Any]:
    """Finite shared bounds and at most the requested number of divisions.

    Compute nice steps in a scaled domain to avoid overflowing a large signed
    range or losing tiny measurements. Endpoints always contain observations.
    """
    divisions = max(1, min(10, divisions))
    if not values:
        values = [0.0, 100.0 if unit == 'percent' else 1.0]
    observed_low, observed_high = min(values), max(values)
    magnitude = max(abs(observed_low), abs(observed_high))
    scale = 10.0 ** max(-300, min(300, math.floor(math.log10(magnitude)))) if magnitude else 1.0
    low, high = observed_low / scale, observed_high / scale
    pad = (high - low) * .08 if high > low else (abs(low) * .05 if low else 1.0)
    limit = sys.float_info.max / scale if scale >= 1 else sys.float_info.max
    low, high = max(-limit, low - pad), min(limit, high + pad)
    percent = unit == 'percent' and 0 <= observed_low <= observed_high <= 100
    if percent:
        low, high = max(0, low), min(100 / scale, high)
    # Choose a readable step, increasing it if rounded endpoints add a division.
    raw_step = (high - low) / divisions
    power = 10.0 ** math.floor(math.log10(raw_step))
    step = next(multiplier * power for multiplier in (1, 2, 2.5, 5, 10)
                if multiplier * power >= raw_step * (1 - 1e-12))
    for _attempt in range(20):
        lower, upper = max(-limit, math.floor(low / step) * step), min(limit, math.ceil(high / step) * step)
        if percent:
            lower, upper = max(0, lower), min(100 / scale, upper)
        count = max(1, math.ceil((upper - lower) / step - 1e-10))
        if count <= divisions:
            break
        step *= 2
    # Equal spacing also handles a finite endpoint clamped near float limits.
    low, high = min(observed_low, lower * scale), max(observed_high, upper * scale)
    if high <= low:
        low, high = math.nextafter(low, -math.inf), math.nextafter(high, math.inf)
    while True:
        ticks = [low * (1 - index / count) + high * (index / count) for index in range(count + 1)]
        if len(set(ticks)) == len(ticks) or count == 1:
            break
        count -= 1
    for precision in (5, 8, 12, 17):
        labels = [format(0.0 if value == 0 else value, '.%dg' % precision) for value in ticks]
        if len(set(labels)) == len(labels):
            break
    return {'range': [low, high], 'ticks': [{'value': value, 'label': label}
                                          for value, label in zip(ticks, labels)]}


def trace_color(index: int) -> Tuple[float, float, float]:
    """Distinct reproducible colors in selected-field order, extended as needed."""
    palette = ((.12, .35, .72), (.82, .27, .05), (.12, .53, .25), (.58, .23, .68),
               (.05, .53, .60), (.76, .12, .30), (.51, .40, .05), (.35, .37, .43))
    return palette[index] if index < len(palette) else colorsys.hsv_to_rgb((index * .618034) % 1, .72, .65)


def fit_graph_text(text: str, width: float, measure: Callable[[str], float]) -> str:
    """Keep text inside its allocation, with the full name retained in state."""
    if measure(text) <= width:
        return text
    # Middle elision retains both device identity and measurement suffix.
    for count in range(len(text) - 1, 0, -1):
        candidate = text[:(count + 1) // 2] + '…' + (text[-(count // 2):] if count // 2 else '')
        if measure(candidate) <= width:
            return candidate
    return '…' if measure('…') <= width else ''


def graph_layout(fields: Sequence[str], series: Dict[str, Any], bounds: Sequence[float],
                 width: float, height: float, measure: Callable[[str], float],
                 label_height: float) -> Dict[str, Any]:
    """One geometry model used by Cairo drawing, hit testing and automation."""
    top, bottom = 20.0, height - 48.0
    plot_height = bottom - top
    divisions = max(1, min(10, int(plot_height / (1.5 * label_height))))
    axes, traces, groups = [], [], {}
    for index, field in enumerate(fields):
        key, title = measurement_unit(field)
        data = series.get(field, {})
        points = [p for p in data.get('points', []) if _numeric(p[0]) and _numeric(p[1])
                  and bounds[0] <= p[0] <= bounds[1]] if data.get('range') == list(bounds) else []
        if key not in groups:
            groups[key] = {'unit': key, 'label': title, 'fields': [], 'values': []}
            axes.append(groups[key])
        groups[key]['fields'].append(field)
        groups[key]['values'].extend(p[1] for p in points)
        traces.append({'field': field, 'unit': key, 'color': trace_color(index), 'points': points})
    left, right = 8.0, width - 8.0
    for index, axis in enumerate(axes):
        axis.update(axis_scale(axis.pop('values'), divisions, axis['unit']))
        strip_width = max(measure(tick['label']) for tick in axis['ticks']) + label_height + 24
        axis['side'] = 'left' if index % 2 == 0 else 'right'
        origin = left if index % 2 == 0 else right - strip_width
        axis['strip'] = [origin, top, strip_width, plot_height]
        axis['axis_x'] = origin + strip_width - 1 if index % 2 == 0 else origin + 1
        title_x = origin + 4 + label_height / 2 if index % 2 == 0 else origin + strip_width - 4 - label_height / 2
        axis['label_center'] = [title_x, (top + bottom) / 2]
        axis['label_rotation'] = -90
        axis['display_label'] = fit_graph_text(axis['label'], max(0, plot_height - 12), measure)
        for position, tick in enumerate(axis['ticks']):
            tick['y'] = bottom - plot_height * position / (len(axis['ticks']) - 1)
        if index % 2 == 0:
            left += strip_width
        else:
            right -= strip_width
    result = {'plot': None, 'axes': axes, 'traces': traces, 'legend': None,
              'range': list(bounds), 'size': [width, height], 'label_height': label_height,
              'message': None}
    if not fields:
        result['message'] = 'No graph fields selected. Use Fields... to choose measurements.'
        return result
    if right - left < 160 or plot_height < 3 * label_height:
        result['message'] = 'Enlarge the window or select fewer unit types to show the graph.'
        return result
    result['plot'] = [left, top, right - left, plot_height]
    for trace in traces:
        trace['range'] = groups[trace['unit']]['range']
        trace['plot'] = list(result['plot'])
    # Lower-center key. Text is opaque in trace colors; only the box is 50% alpha.
    available = right - left - 24
    entries, cursor_x, cursor_y, row_width = [], 10.0, 10.0, 0.0
    row_height = label_height * 1.5
    for trace in traces:
        label = trace['field'] + ' [' + groups[trace['unit']]['label'] + ']'
        shown = fit_graph_text(label, available - 20, measure)
        item_width = measure(shown) + 20
        if cursor_x > 10 and cursor_x + item_width > available:
            cursor_x, cursor_y = 10.0, cursor_y + row_height
        entries.append({'field': trace['field'], 'label': label, 'display_label': shown,
                        'color': trace['color'], 'position': [cursor_x, cursor_y + label_height]})
        cursor_x += item_width
        row_width = max(row_width, cursor_x)
    key_width, key_height = min(available, row_width), cursor_y + row_height + 6
    if key_height > plot_height - 16:
        result['plot'] = None
        result['message'] = 'Enlarge the window or select fewer fields to fit the color key.'
        return result
    result['legend'] = {'box': [(left + right - key_width) / 2, bottom - key_height - 8,
                                key_width, key_height], 'alpha': .5, 'entries': entries}
    return result


def graph_point(plot: Sequence[float], bounds: Sequence[float], value_range: Sequence[float],
                stamp: float, value: float) -> Tuple[float, float]:
    """Transform one observation with the same exact rectangle for every unit."""
    low, high = value_range
    scale = max(abs(low), abs(high), sys.float_info.min)
    fraction = (value / scale - low / scale) / (high / scale - low / scale)
    return (plot[0] + plot[2] * (stamp - bounds[0]) / (bounds[1] - bounds[0]),
            plot[1] + plot[3] * (1 - fraction))


class SeriesBuilder:
    """Bound rendering work without treating reduced sampling as a data gap.

    Every bucket retains first, last, minimum and maximum. Segment identities
    come from raw records, so decimation cannot erase long continuous stretches
    or draw a line across an actual missing-reading/sleep/collector boundary.
    """

    def __init__(self, start: float, end: float, buckets: int) -> None:
        self.start, self.span, self.limit = start, max(1.0, end - start), buckets
        self.buckets: Dict[int, list] = {}
        self.segment = 0
        self.previous = None
        self.identity = None
        self.count = 0

    def add(self, record: Dict[str, Any], value: Any) -> None:
        identity = tuple(record[key] for key in ("source", "machine_id", "boot_id", "collector_id"))
        if not _numeric(value):
            if identity == self.identity:
                self.previous = None
            return
        stamp = float(record["captured_at"])
        if self.previous is None or identity != self.identity or stamp - self.previous > 60:
            self.segment += 1
        self.previous, self.identity = stamp, identity
        self.count += 1
        point = (stamp, float(value), record["id"], self.segment)
        index = min(self.limit - 1, max(0, int((stamp - self.start) / self.span * self.limit)))
        prior = self.buckets.get(index)
        if prior is None:
            self.buckets[index] = [point] * 4
        else:
            prior[1] = point
            if value < prior[2][1]:
                prior[2] = point
            if value > prior[3][1]:
                prior[3] = point

    def points(self) -> list:
        return sorted({point for bucket in self.buckets.values() for point in bucket})
