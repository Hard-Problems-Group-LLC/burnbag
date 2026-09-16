"""Read-only, incrementally merged access to burnbag history databases."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from burnbag_history import HistoryError, SAMPLE_KINDS, SYSTEM_DATABASE, _streams, user_database_path


class HistorySources:
    """Keyset-paged reader that never creates or writes either history store."""

    def __init__(self, sources: Optional[Sequence[Tuple[str, Path]]] = None) -> None:
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
            self.sources = selected
        else:
            self.sources = list(sources)
        for scope, path in self.sources:
            try:
                uri = "file:" + quote(str(path.absolute()), safe="/") + "?mode=ro"
                connection = sqlite3.connect(uri, uri=True, timeout=1.0,
                                              check_same_thread=False)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version != 1:
                    raise ValueError("unsupported or missing schema version %s" % version)
                connection.execute("SELECT id,kind,captured_at,data FROM records LIMIT 0")
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
                    except sqlite3.Error:
                        # Older/hand-built schema fixtures can still be read; only
                        # coverage-based overlap suppression is unavailable.
                        self.warnings.append("System coverage metadata is unavailable")
            except (OSError, sqlite3.Error, ValueError) as exc:
                self.errors[scope] = str(exc)

    def close(self) -> None:
        with self.lock:
            for connection in self.connections.values():
                connection.close()
            self.connections.clear()

    def page(self, after: Optional[Tuple[float, str]] = None,
             limit: int = 500) -> List[Dict[str, Any]]:
        if not 1 <= limit <= 5000:
            raise ValueError("page size must be between 1 and 5000")
        fetched: List[Tuple[str, Dict[str, Any]]] = []
        with self.lock:
            for scope, connection in self.connections.items():
                fetched.extend(self._source_page(scope, connection, after, limit))
        return self._merge(fetched, limit)

    def search_page(self, text: str, after: Optional[Tuple[float, str]] = None,
                    limit: int = 500) -> List[Dict[str, Any]]:
        """Search serialized measurements and event metadata, then page matches."""
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise ValueError("search text must contain 1 to 4096 characters")
        if not 1 <= limit <= 5000:
            raise ValueError("page size must be between 1 and 5000")
        fetched: List[Tuple[str, Dict[str, Any]]] = []
        with self.lock:
            for scope, connection in self.connections.items():
                fetched.extend(self._source_page(scope, connection, after, limit, text))
        return self._merge(fetched, limit)

    def overview(self, max_buckets: int = 2400) -> Dict[str, Any]:
        """Summarize the full merged history without retaining every row.

        The table remains keyset-paged, while this bounded-size overview makes
        the initial graph and field catalog cover the complete available
        history. Each time bucket retains both extrema for every numeric field.
        """
        if not 10 <= max_buckets <= 20000:
            raise ValueError("overview bucket count must be between 10 and 20000")
        bounds = []
        with self.lock:
            for connection in self.connections.values():
                row = connection.execute(
                    "SELECT min(captured_at),max(captured_at) FROM records"
                ).fetchone()
                if row and row[0] is not None:
                    bounds.extend((float(row[0]), float(row[1])))
        if not bounds:
            return {"count": 0, "range": None, "columns": [], "series": {}}
        low, high = min(bounds), max(bounds)
        span = max(1.0, high - low)
        buckets: Dict[str, Dict[int, Tuple[Tuple[float, float, str],
                                           Tuple[float, float, str]]]] = {}
        columns = set()
        count = 0
        after = None
        while True:
            page = self.page(after, 500)
            if not page:
                break
            for record in page:
                count += 1
                flat = flatten_data(record["data"])
                columns.update(flat)
                bucket = min(max_buckets - 1, int((record["captured_at"] - low) /
                                                   span * max_buckets))
                if record["kind"] not in SAMPLE_KINDS:
                    continue
                for field, value in flat.items():
                    if not isinstance(value, (int, float)) or isinstance(value, bool):
                        continue
                    sample = (float(record["captured_at"]), float(value), record["id"])
                    field_buckets = buckets.setdefault(field, {})
                    prior = field_buckets.get(bucket)
                    if prior is None:
                        field_buckets[bucket] = (sample, sample)
                    else:
                        field_buckets[bucket] = (
                            sample if sample[1] < prior[0][1] else prior[0],
                            sample if sample[1] > prior[1][1] else prior[1],
                        )
            after = (page[-1]["captured_at"], page[-1]["id"])
            if len(page) < 500:
                break
        series = {}
        for field, field_buckets in buckets.items():
            points = []
            for low_point, high_point in field_buckets.values():
                points.append(low_point)
                if high_point != low_point:
                    points.append(high_point)
            series[field] = sorted(points)
        return {"count": count, "range": [low, high],
                "columns": sorted(columns), "series": series}

    def _source_page(self, scope: str, connection: sqlite3.Connection,
                     after: Optional[Tuple[float, str]], limit: int,
                     search: Optional[str] = None) -> List[Tuple[str, Dict[str, Any]]]:
        selected: List[Tuple[str, Dict[str, Any]]] = []
        cursor = after
        while len(selected) < limit:
            sql = ("SELECT id,kind,captured_at,boottime,machine_id,boot_id,collector_id,scope,data "
                   "FROM records")
            params: Tuple[Any, ...] = ()
            if search is not None:
                sql += (" WHERE instr(lower(id || ' ' || kind || ' ' || scope || ' ' || data "
                        "|| ' ' || datetime(captured_at,'unixepoch','localtime')),lower(?))>0")
                params = (search,)
            if cursor is not None:
                sql += (" AND " if search is not None else " WHERE ") + "(captured_at,id)>(?,?)"
                params += cursor
            sql += " ORDER BY captured_at,id LIMIT ?"
            batch_size = min(5000, max(64, limit - len(selected)))
            rows = connection.execute(sql, params + (batch_size,)).fetchall()
            if not rows:
                break
            collisions = self._system_collisions(rows) if scope == "user" else set()
            consumed_all = True
            for row in rows:
                cursor = (float(row["captured_at"]), row["id"])
                decoded = self._decode_rows(scope, (row,))
                if not decoded:
                    continue
                item = decoded[0][1]
                if item["id"] in collisions:
                    self._collision_warning()
                    continue
                selected.append((scope, item))
                if len(selected) >= limit:
                    consumed_all = False
                    break
            if not consumed_all:
                break
        return selected

    def _system_collisions(self, rows: Sequence[sqlite3.Row]) -> set[str]:
        system = self.connections.get("system")
        if system is None:
            return set()
        identities = [row["id"] for row in rows]
        collisions: set[str] = set()
        for offset in range(0, len(identities), 400):
            chunk = identities[offset:offset + 400]
            marks = ",".join("?" for _ in chunk)
            collisions.update(row[0] for row in system.execute(
                "SELECT id FROM records WHERE id IN (" + marks + ")", chunk
            ).fetchall())
        return collisions

    def _collision_warning(self) -> None:
        warning = "History ID collision detected; system record takes precedence"
        if warning not in self.warnings:
            self.warnings.append(warning)

    def _decode_rows(self, scope: str, rows: Sequence[sqlite3.Row]) -> List[Tuple[str, Dict[str, Any]]]:
        result = []
        for row in rows:
            try:
                data = json.loads(row["data"])
                if not isinstance(data, dict):
                    raise ValueError("record data is not an object")
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                warning = "%s history contains a record with invalid JSON: %s" % (scope, exc)
                if warning not in self.warnings:
                    self.warnings.append(warning)
                continue
            item = dict(row)
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
