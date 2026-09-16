"""Read-only, incrementally merged access to burnbag history databases."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple
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
