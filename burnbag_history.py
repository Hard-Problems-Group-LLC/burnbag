"""Durable, bounded power telemetry and read-only Linux measurement collection.

SQLite owns synchronization: each committed batch uses a rollback journal and
``synchronous=EXTRA``.  The sampler never writes to a device or inhibits sleep.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import stat
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import uuid


SYSTEM_DATABASE = Path("/var/lib/burnbag/history.sqlite3")
SCHEMA_VERSION = 1
SAMPLE_KINDS = ("sample", "snapshot", "telemetry")


class HistoryError(RuntimeError):
    """Telemetry could not be accepted, stored, or read safely."""


def user_database_path() -> Path:
    """Select the invoking user's private XDG state database."""
    state = os.environ.get("XDG_STATE_HOME")
    if state:
        base = Path(state)
    else:
        home = os.environ.get("HOME")
        if not home:
            raise HistoryError("HOME or an absolute XDG_STATE_HOME is required")
        base = Path(home) / ".local" / "state"
    if not base.is_absolute():
        raise HistoryError("History state directory must be an absolute path")
    return base / "burnbag" / "history.sqlite3"


def _boottime() -> float:
    return time.clock_gettime(getattr(time, "CLOCK_BOOTTIME", time.CLOCK_MONOTONIC))


def _identity(path: str, fallback: str) -> str:
    try:
        value = Path(path).read_text(encoding="ascii").strip()
        if value:
            return value
    except (OSError, UnicodeError):
        pass
    return fallback


def _epoch(value: Any) -> float:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise HistoryError("Telemetry timestamps must include a timezone")
        value = value.timestamp()
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HistoryError("Telemetry timestamp must be a finite number") from exc
    if not math.isfinite(result):
        raise HistoryError("Telemetry timestamp must be a finite number")
    return result


def _regular_file(path: Path, *, owned: bool) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise HistoryError(f"History file must be regular with one hard link: {path}")
    if owned and info.st_uid != os.geteuid():
        raise HistoryError(f"History file is not owned by the effective user: {path}")
    if info.st_mode & 0o022:
        raise HistoryError(f"History file is writable by group or other users: {path}")
    return info


def _prepare_database(path: Path, scope: str) -> None:
    """Acquire an owned path without following final-component symlinks."""
    if not path.is_absolute():
        raise HistoryError("History database path must be absolute")
    directory_mode = 0o755 if scope == "system" else 0o700
    file_mode = 0o644 if scope == "system" else 0o600
    try:
        path.parent.mkdir(mode=directory_mode, parents=True, exist_ok=True)
        parent = path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid():
            raise HistoryError(f"History parent must be an owned directory: {path.parent}")
        if parent.st_mode & 0o022:
            raise HistoryError(f"History parent must not be writable by others: {path.parent}")
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fchmod(directory_fd, directory_mode)
            for suffix in ("-journal", "-wal", "-shm"):
                sidecar = Path(str(path) + suffix)
                if os.path.lexists(sidecar):
                    _regular_file(sidecar, owned=True)
            descriptor = os.open(
                path.name, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                file_mode, dir_fd=directory_fd,
            )
            try:
                opened = os.fstat(descriptor)
                checked = _regular_file(path, owned=True)
                if (opened.st_dev, opened.st_ino) != (checked.st_dev, checked.st_ino):
                    raise HistoryError("History file changed while opening it")
                os.fchmod(descriptor, file_mode)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise HistoryError(f"Could not prepare history database {path}: {exc}") from exc


def _streams(data: Dict[str, Any]) -> List[str]:
    """Identify individual measurements, excluding descriptive provenance."""
    streams = []
    for section in ("batteries", "supplies", "backlight"):
        values = data.get(section)
        if isinstance(values, dict):
            for name, fields in values.items():
                if isinstance(name, str) and isinstance(fields, dict):
                    streams.extend(section + "/" + name + "/" + field for field in fields
                                   if field not in ("metadata", "percentage_source", "power_source"))
    if isinstance(data.get("thermal_c"), dict):
        streams.extend("thermal_c/" + name for name in data["thermal_c"])
    if isinstance(data.get("cpu"), dict):
        streams.extend("cpu/" + field for field in data["cpu"])
    return streams


class TelemetryWriter:
    """Thread-safe RAM queue with one SQLite writer and durable flush barriers.

    ``submit`` accepts a record into memory; ``flush`` acknowledges durability.
    Disk errors fail the writer visibly instead of discarding queued data.
    """

    BATCH_SECONDS = 60.0
    EVENT_SECONDS = 5.0
    BATCH_BYTES = 64 * 1024
    MAX_RECORD_BYTES = 64 * 1024
    MAX_PENDING_BYTES = 4 * 1024 * 1024
    MAX_PENDING_RECORDS = 4096
    SQLITE_BUSY_SECONDS = 1.0

    def __init__(
        self, path: Path, scope: str, prudent: bool = False,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        if scope not in ("user", "system"):
            raise HistoryError("History scope must be 'user' or 'system'")
        self.path = Path(path)
        self.scope = scope
        self.collector_id = str(uuid.uuid4())
        self.machine_id = _identity(
            "/etc/machine-id", hashlib.sha256(socket.gethostname().encode()).hexdigest()
        )
        self.boot_id = _identity("/proc/sys/kernel/random/boot_id", str(uuid.uuid4()))
        self._condition = threading.Condition()
        self._pending: Any = deque()
        self._pending_bytes = 0
        self._pending_records = 0
        self._sequence = 0
        self._committed = 0
        self._flush_through = 0
        self._last_commit: Optional[float] = None
        self._error: Optional[str] = None
        self._prudent = bool(prudent)
        self._closing = False
        self._closed = False
        self._dropped = 0
        self._on_error = on_error
        self._ready = threading.Event()
        self._coverage_heads: Dict[str, Dict[str, Any]] = {}
        self._sample_index = 0
        _prepare_database(self.path, self.scope)
        self._thread = threading.Thread(
            target=self._run, name="burnbag-history-writer", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(3.0):
            with self._condition:
                self._closing = True
                self._condition.notify_all()
            raise HistoryError("History database initialization timed out")
        if self._error:
            raise HistoryError(self._error)

    def submit(
        self, kind: str, data: Dict[str, Any], urgent: bool = False,
        event: bool = False, captured_at: Any = None, boottime: Optional[float] = None,
    ) -> str:
        """Queue an immutable JSON snapshot, returning its unique record ID."""
        if not isinstance(kind, str) or not kind or len(kind) > 128:
            raise HistoryError("History record kind must contain 1--128 characters")
        if not isinstance(data, dict):
            raise HistoryError("History record data must be an object")
        captured = _epoch(time.time() if captured_at is None else captured_at)
        boot = _epoch(_boottime() if boottime is None else boottime)
        if boot < 0:
            raise HistoryError("History boottime must be non-negative")
        interval_start = interval_end = None
        if kind == "sleep_interval":
            interval_start = _epoch(data.get("started_at"))
            interval_end = _epoch(data.get("ended_at"))
            if interval_end < interval_start:
                raise HistoryError("Sleep interval ends before it starts")
        try:
            encoded = json.dumps(data, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise HistoryError(f"History record is not finite JSON: {exc}") from exc
        size = len(encoded.encode("utf-8")) + 512
        if size > self.MAX_RECORD_BYTES:
            raise HistoryError(f"History record exceeds {self.MAX_RECORD_BYTES} bytes")
        with self._condition:
            self._check_open()
            if (self._pending_bytes + size > self.MAX_PENDING_BYTES or
                    self._pending_records >= self.MAX_PENDING_RECORDS):
                self._dropped += 1
                raise HistoryError("History queue is full; this record was not accepted")
            self._sequence += 1
            record_id = f"{self.collector_id}:{self._sequence:020d}"
            row = (
                record_id, kind, captured, boot, self.machine_id, self.boot_id,
                self.collector_id, self.scope, encoded, interval_start, interval_end,
            )
            queued = time.monotonic()
            deadline = queued + (self.EVENT_SECONDS if event else self.BATCH_SECONDS)
            self._pending.append((self._sequence, row, size, queued, deadline))
            self._pending_bytes += size
            self._pending_records += 1
            if urgent:
                self._flush_through = self._sequence
            self._condition.notify_all()
            return record_id

    def _check_open(self) -> None:
        if self._error:
            raise HistoryError(self._error)
        if self._closing or self._closed:
            raise HistoryError("History writer is closed")

    def flush(self, timeout: float = 3.0) -> None:
        """Wait until every update accepted before this call is durable."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            if self._error:
                raise HistoryError(self._error)
            target = self._sequence
            self._flush_through = max(self._flush_through, target)
            self._condition.notify_all()
            while self._committed < target:
                if self._error:
                    raise HistoryError(self._error)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HistoryError("History flush timed out; pending records are not confirmed durable")
                self._condition.wait(remaining)

    def set_prudent(self, prudent: bool) -> None:
        """Change commit frequency without weakening SQLite durability."""
        with self._condition:
            self._check_open()
            self._prudent = bool(prudent)
            self._condition.notify_all()

    def status(self) -> Dict[str, Any]:
        """Return bounded state; this method never performs disk I/O."""
        with self._condition:
            return {
                "collector_id": self.collector_id, "machine_id": self.machine_id,
                "boot_id": self.boot_id, "last_commit": self._last_commit,
                "healthy": self._error is None and not self._closed,
                "error": self._error, "prudent": self._prudent,
                "pending_records": self._pending_records, "pending_bytes": self._pending_bytes,
                "dropped_records": self._dropped, "last_sequence": self._sequence,
                "committed_sequence": self._committed,
            }

    def close(self) -> None:
        """Flush and stop the writer with bounded waiting, preserving failures."""
        with self._condition:
            if self._closed:
                if self._error:
                    raise HistoryError(self._error)
                return
            self._closing = True
            self._flush_through = self._sequence
            self._condition.notify_all()
        self._thread.join(3.0)
        if self._thread.is_alive():
            raise HistoryError("History writer did not stop within three seconds")
        if self._error:
            raise HistoryError(self._error)

    def _fail(self, exc: BaseException) -> None:
        message = f"History database {self.path}: {exc}"
        with self._condition:
            self._error = message
            self._condition.notify_all()
        if self._on_error is not None:
            try:
                self._on_error(message)
            except Exception:
                # Diagnostic reporting cannot obscure the original disk failure.
                pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=self.SQLITE_BUSY_SECONDS)
        try:
            mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if mode.lower() != "delete":
                raise HistoryError("Could not select rollback journaling")
            connection.execute("PRAGMA synchronous=EXTRA")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, SCHEMA_VERSION):
                raise HistoryError(f"Unsupported history schema version {version}")
            if version == 0:
                existing = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if existing:
                    raise HistoryError("Refusing to initialize an unrelated SQLite database")
                connection.executescript(
                    "BEGIN IMMEDIATE;"
                    "CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT NOT NULL,"
                    " captured_at REAL NOT NULL, boottime REAL NOT NULL,"
                    " machine_id TEXT NOT NULL, boot_id TEXT NOT NULL,"
                    " collector_id TEXT NOT NULL, scope TEXT NOT NULL, data TEXT NOT NULL,"
                    " interval_start REAL, interval_end REAL);"
                    "CREATE INDEX records_time ON records(captured_at,id);"
                    "CREATE INDEX records_kind_time ON records(kind,captured_at,id);"
                    "CREATE INDEX records_interval ON records(kind,interval_end,interval_start);"
                    "CREATE TABLE coverage (collector_id TEXT NOT NULL, machine_id TEXT NOT NULL,"
                    " boot_id TEXT NOT NULL, stream TEXT NOT NULL, segment INTEGER NOT NULL,"
                    " first_boot REAL NOT NULL, last_boot REAL NOT NULL,"
                    " first_wall REAL NOT NULL, last_wall REAL NOT NULL,"
                    " PRIMARY KEY(collector_id,stream,segment));"
                    "CREATE INDEX coverage_time ON coverage(last_wall,first_wall);"
                    f"PRAGMA user_version={SCHEMA_VERSION}; COMMIT;"
                )
            connection.execute("SELECT id,kind,captured_at,boottime,machine_id,boot_id,"
                               "collector_id,scope,data FROM records LIMIT 0")
            return connection
        except BaseException:
            connection.close()
            raise

    def _commit(self, connection: sqlite3.Connection, batch: List[Any]) -> None:
        with connection:
            connection.executemany("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                   [item[1] for item in batch])
            for item in batch:
                row = item[1]
                if row[1] in SAMPLE_KINDS:
                    self._sample_index += 1
                    streams = _streams(json.loads(row[8]))
                    coverage = []
                    for stream in streams:
                        previous = self._coverage_heads.get(stream)
                        continuous = (previous is not None and
                                      previous["index"] == self._sample_index - 1 and
                                      previous["boot_id"] == row[5] and
                                      0 <= row[3] - previous["last_boot"] <= 15 and
                                      row[2] >= previous["last_wall"] and
                                      abs((row[2] - previous["last_wall"]) -
                                          (row[3] - previous["last_boot"])) <= 2)
                        segment = previous["segment"] if continuous else (
                            0 if previous is None else previous["segment"] + 1
                        )
                        first_boot = previous["first_boot"] if continuous else row[3]
                        first_wall = previous["first_wall"] if continuous else row[2]
                        self._coverage_heads[stream] = {
                            "index": self._sample_index, "segment": segment,
                            "boot_id": row[5], "first_boot": first_boot, "last_boot": row[3],
                            "first_wall": first_wall, "last_wall": row[2],
                        }
                        coverage.append((row[6], row[4], row[5], stream, segment,
                                         first_boot, row[3], first_wall, row[2]))
                    connection.executemany(
                        "INSERT INTO coverage VALUES (?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(collector_id,stream,segment) DO UPDATE SET "
                        "last_boot=excluded.last_boot,last_wall=excluded.last_wall", coverage,
                    )

    def _run(self) -> None:
        connection: Optional[sqlite3.Connection] = None
        try:
            connection = self._connect()
            self._ready.set()
            while True:
                with self._condition:
                    while not self._pending:
                        if self._closing:
                            return
                        self._condition.wait()
                    deadline = min(item[4] for item in self._pending)
                    immediate = (self._prudent or self._closing or
                                 self._flush_through > self._committed or
                                 self._pending_bytes >= self.BATCH_BYTES)
                    if not immediate and deadline > time.monotonic():
                        self._condition.wait(deadline - time.monotonic())
                        continue
                    if self._prudent:
                        batch = [self._pending.popleft()]
                    else:
                        batch = list(self._pending)
                        self._pending.clear()
                self._commit(connection, batch)
                with self._condition:
                    self._committed = batch[-1][0]
                    self._last_commit = time.time()
                    self._pending_bytes -= sum(item[2] for item in batch)
                    self._pending_records -= len(batch)
                    self._condition.notify_all()
        except Exception as exc:
            self._fail(exc)
        finally:
            if connection is not None:
                connection.close()
            with self._condition:
                self._closed = True
                self._condition.notify_all()
            self._ready.set()


def _read_connection(path: Path) -> sqlite3.Connection:
    """Open without creating databases or acquiring write permission."""
    _regular_file(path, owned=False)
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True,
                                 timeout=1.0, isolation_level=None)
    try:
        connection.execute("PRAGMA query_only=ON")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise HistoryError(f"Unsupported history schema version {version}")
        connection.row_factory = sqlite3.Row
        return connection
    except BaseException:
        connection.close()
        raise


def _spread(items: List[Any], count: int) -> List[Any]:
    """Choose deterministic representatives including both interval extrema."""
    if len(items) <= count:
        return items
    if count <= 0:
        return []
    if count == 1:
        return [items[-1]]
    return [items[(index * (len(items) - 1)) // (count - 1)] for index in range(count)]


def _read_subset(
    connection: sqlite3.Connection, start: float, end: float, samples: bool,
    limit: int, last_rowid: int,
) -> Tuple[List[Dict[str, Any]], int]:
    predicate = "kind IN ('sample','snapshot','telemetry')" if samples else (
        "kind NOT IN ('sample','snapshot','telemetry')"
    )
    where = "(captured_at>=? AND captured_at<=? AND " + predicate + ")"
    parameters: Tuple[Any, ...] = (start, end)
    if not samples:
        where += " OR (kind='sleep_interval' AND interval_start<=? AND interval_end>=?)"
        parameters += (end, start)
    where = "(" + where + ") AND rowid<=?"
    parameters += (last_rowid,)
    count = connection.execute("SELECT count(*) FROM records WHERE " + where, parameters).fetchone()[0]
    # Rank only keys, then fetch selected payloads in bounded pages. Even a
    # query that needs no reduction must not pin a long-lived reader lock.
    if count <= limit:
        wanted = list(range(1, count + 1))
    elif limit == 1:
        wanted = [count]
    else:
        wanted = [(index * (count - 1)) // (limit - 1) + 1 for index in range(limit)]
    selected: List[str] = []
    target = iter(wanted)
    next_rank = next(target, None)
    last_key: Optional[Tuple[float, str]] = None
    rank = 0
    while next_rank is not None:
        page_where, page_parameters = where, parameters
        if last_key is not None:
            page_where += " AND (captured_at,id)>(?,?)"
            page_parameters += last_key
        keys = connection.execute("SELECT id,captured_at FROM records WHERE " + page_where +
                                  " ORDER BY captured_at,id LIMIT 2048", page_parameters).fetchall()
        if not keys:
            break
        for key in keys:
            rank += 1
            if rank == next_rank:
                selected.append(key[0])
                next_rank = next(target, None)
                if next_rank is None:
                    break
        last_key = (keys[-1][1], keys[-1][0])
    rows = []
    for offset in range(0, len(selected), 400):
        chunk = selected[offset:offset + 400]
        marks = ",".join("?" for _ in chunk)
        rows.extend(connection.execute("SELECT * FROM records WHERE id IN (" + marks + ")", chunk).fetchall())
    rows.sort(key=lambda row: (row["captured_at"], row["id"]))
    result = []
    for row in rows:
        record = dict(row)
        record.pop("interval_start", None)
        record.pop("interval_end", None)
        record["data"] = json.loads(record["data"])
        if not isinstance(record["data"], dict):
            raise HistoryError("History record payload is not an object")
        record["captured_at"] = _epoch(record["captured_at"])
        record["boottime"] = _epoch(record["boottime"])
        if record["boottime"] < 0 or not all(isinstance(record[key], str) and record[key]
                                            for key in ("id", "kind", "machine_id", "boot_id", "collector_id")):
            raise HistoryError("History record has invalid identity or timing fields")
        result.append(record)
    return result, count


def read_history(
    sources: Sequence[Tuple[str, Path]], start: float, end: float, limit: int = 100000,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Read both stores, preferring system observations on conflicting coverage.

    Measurements and events each have an independent ``limit``, so results
    contain at most twice that number. Every reduction is explicit. Returned
    samples include query-only ``coverage_segments`` identities from actual
    recorded coverage, so graph continuity survives representative sampling.
    """
    start, end = _epoch(start), _epoch(end)
    if end < start:
        raise HistoryError("History end precedes its start")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 2 or limit > 1000000:
        raise HistoryError("History limit must be an integer between 2 and 1000000")
    warnings: List[str] = []
    gathered: List[Tuple[str, Dict[str, Any]]] = []
    system_coverage: Dict[Tuple[str, str, str], List[Tuple[float, float]]] = {}
    seen_paths = set()
    for source, supplied_path in sources:
        path = Path(supplied_path)
        canonical = str(path.absolute())
        if canonical in seen_paths:
            continue
        seen_paths.add(canonical)
        try:
            path.lstat()
        except FileNotFoundError:
            warnings.append(f"History source {source} is missing: {path}")
            continue
        except OSError as exc:
            warnings.append(f"History source {source} failed; results are partial ({path}): {exc}")
            continue
        connection = None
        try:
            connection = _read_connection(path)
            # Records are append-only. An initial rowid ceiling provides a
            # stable snapshot while keyset pages release read locks promptly.
            last_rowid = connection.execute("SELECT coalesce(max(rowid),0) FROM records").fetchone()[0]
            samples, sample_count = _read_subset(connection, start, end, True, limit, last_rowid)
            events, event_count = _read_subset(connection, start, end, False, limit, last_rowid)
            if sample_count > len(samples):
                warnings.append(f"History source {source}: reduced {sample_count} measurements to "
                                f"{len(samples)} representatives spanning the entire interval")
            if event_count > len(events):
                warnings.append(f"History source {source}: {event_count} events exceed the bound; "
                                f"retained {len(events)} representatives spanning the entire interval")
            coverage_limit = min(100000, 10 * limit)
            coverage = connection.execute(
                "SELECT * FROM coverage WHERE last_wall>=? AND first_wall<=? "
                "ORDER BY last_wall,collector_id,stream,segment LIMIT ?",
                (start, end, coverage_limit + 1),
            ).fetchall()
            if len(coverage) > coverage_limit:
                warnings.append(f"History source {source}: coverage exceeds the query bound; "
                                "continuity metadata and collision resolution are partial")
                coverage = coverage[:coverage_limit]
            source_coverage: Dict[Tuple[str, str, str, str], List[Tuple[float, float, str]]] = {}
            for row in coverage:
                first, last = _epoch(row["first_boot"]), _epoch(row["last_boot"])
                if first < 0 or last < first:
                    raise HistoryError("Invalid history coverage bounds")
                identity = f"{row['boot_id']}:{row['collector_id']}:{row['segment']}"
                key = (row["machine_id"], row["boot_id"], row["collector_id"], row["stream"])
                source_coverage.setdefault(key, []).append((first, last, identity))
            for record in samples:
                segments = {}
                for stream in _streams(record["data"]):
                    key = (record["machine_id"], record["boot_id"], record["collector_id"], stream)
                    for first, last, identity in source_coverage.get(key, []):
                        if first <= record["boottime"] <= last:
                            segments[stream] = identity
                            break
                record["coverage_segments"] = segments
            if source == "system":
                # Publish precedence only after the whole source has been
                # validated. A failed source must never suppress usable data.
                for key, intervals in source_coverage.items():
                    system_key = (key[0], key[1], key[3])
                    system_coverage.setdefault(system_key, []).extend(
                        (first, last) for first, last, _identity in intervals
                    )
            gathered.extend((source, record) for record in samples + events)
        except (OSError, sqlite3.Error, ValueError, HistoryError) as exc:
            warnings.append(f"History source {source} failed; results are partial ({path}): {exc}")
        finally:
            if connection is not None:
                connection.close()
    chosen: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    duplicate_count = 0
    overlap_count = 0
    for source, record in gathered:
        if record["id"] in chosen:
            duplicate_count += 1
            if source != "system":
                continue
        if source != "system" and record["kind"] in SAMPLE_KINDS:
            data = record["data"]
            suppressed = []
            for stream in _streams(data):
                intervals = system_coverage.get((record["machine_id"], record["boot_id"], stream), [])
                if any(first <= record["boottime"] <= last for first, last in intervals):
                    suppressed.append(stream)
            if suppressed:
                overlap_count += 1
                data = json.loads(json.dumps(data))
                for stream in suppressed:
                    components = stream.split("/")
                    parent = data
                    for component in components[:-1]:
                        parent = parent[component]
                    parent.pop(components[-1], None)
                    if components[-1] == "percentage":
                        parent.pop("percentage_source", None)
                    if components[-1] == "power_w":
                        parent.pop("power_source", None)
                for section in ("batteries", "supplies", "backlight"):
                    for name, fields in list(data.get(section, {}).items()):
                        if not any(field not in ("metadata", "percentage_source", "power_source")
                                   for field in fields):
                            data[section].pop(name)
                if not _streams(data):
                    continue
                retained_segments = {stream: identity for stream, identity in
                                     record.get("coverage_segments", {}).items() if stream not in suppressed}
                record = dict(record, data=data, suppressed_streams=suppressed,
                              coverage_segments=retained_segments)
        chosen[record["id"]] = (source, record)
    if duplicate_count:
        warnings.append(f"History collision: {duplicate_count} duplicate record IDs; system records take precedence")
    if overlap_count:
        warnings.append(f"History collision: {overlap_count} user measurements overlap system coverage; "
                        "system observations take precedence for matching measurement streams")
    ordered = sorted((value[1] for value in chosen.values()), key=lambda record: (record["captured_at"], record["id"]))
    events = [record for record in ordered if record["kind"] not in SAMPLE_KINDS]
    samples = [record for record in ordered if record["kind"] in SAMPLE_KINDS]
    if len(events) > limit:
        warnings.append(f"History event limit: reduced {len(events)} merged events to {limit}; "
                        "representatives span the entire interval")
        events = _spread(events, limit)
    if len(samples) > limit:
        warnings.append(f"History sample limit: reduced {len(samples)} merged measurements to "
                        f"{limit} representatives spanning the entire interval")
        samples = _spread(samples, limit)
    ordered = sorted(events + samples, key=lambda record: (record["captured_at"], record["id"]))
    return ordered, warnings


class PowerSampler:
    """Read selected Linux power attributes, caching static device metadata.

    Discovery lists only named class directories.  Unsupported optional fields
    are absent; failed or invalid exposed fields are reported as gaps/errors.
    """

    def __init__(self, sys_root: Path = Path("/sys"), proc_root: Path = Path("/proc")) -> None:
        self.sys_root = Path(sys_root)
        self.proc_root = Path(proc_root)
        self._metadata: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._last_cpu: Optional[Tuple[int, int]] = None

    @staticmethod
    def _text(path: Path, errors: List[str]) -> Optional[str]:
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError as exc:
            if exc.errno in (errno.ENODATA, errno.ENODEV, errno.EOPNOTSUPP):
                return None
            errors.append(f"Could not read {path}: {exc}")
            return None
        except UnicodeError as exc:
            errors.append(f"Could not decode {path}: {exc}")
            return None

    @classmethod
    def _number(cls, path: Path, errors: List[str], scale: float = 1.0) -> Optional[float]:
        text = cls._text(path, errors)
        if text is None:
            return None
        try:
            value = float(text) / scale
            if not math.isfinite(value):
                raise ValueError("non-finite value")
            return value
        except (ValueError, OverflowError):
            errors.append(f"Invalid numeric power attribute {path}: {text[:80]!r}")
            return None

    @staticmethod
    def _entries(path: Path, errors: List[str]) -> List[Path]:
        try:
            return sorted(path.iterdir(), key=lambda entry: entry.name)
        except FileNotFoundError:
            return []
        except OSError as exc:
            errors.append(f"Could not enumerate {path}: {exc}")
            return []

    def _static(self, entry: Path, category: str, fields: Sequence[str], errors: List[str]) -> Dict[str, Any]:
        key = (category, entry.name)
        if key not in self._metadata:
            self._metadata[key] = {field: self._text(entry / field, errors) for field in fields}
        return {field: value for field, value in self._metadata[key].items() if value is not None}

    def sample(self) -> Dict[str, Any]:
        """Return a JSON-safe snapshot; individual sensor failures are nonfatal."""
        errors: List[str] = []
        result: Dict[str, Any] = {
            "batteries": {}, "supplies": {}, "thermal_c": {},
            "cpu": {}, "backlight": {}, "errors": errors,
        }
        for entry in self._entries(self.sys_root / "class" / "power_supply", errors):
            metadata = self._static(entry, "supply", ("type", "manufacturer", "model_name", "technology"), errors)
            supply_type = metadata.get("type", "")
            battery = supply_type.casefold() == "battery"
            reading: Dict[str, Any] = {"metadata": metadata}
            fields = {
                "voltage_now": ("voltage_v", 1000000),
                "current_now": ("current_a", 1000000),
                "power_now": ("power_w", 1000000),
            }
            if battery:
                fields.update({
                    "capacity": ("percentage", 1), "energy_now": ("energy_wh", 1000000),
                    "energy_full": ("full_wh", 1000000), "charge_now": ("charge_ah", 1000000),
                    "charge_full": ("full_ah", 1000000), "temp": ("temperature_c", 10),
                    "cycle_count": ("cycle_count", 1),
                })
            else:
                fields["online"] = ("online", 1)
            for attribute, (name, scale) in fields.items():
                value = self._number(entry / attribute, errors, scale)
                if value is not None:
                    reading[name] = value
            for attribute in ("status", "health", "capacity_level") if battery else ("usb_type",):
                value = self._text(entry / attribute, errors)
                if value is not None:
                    reading[attribute] = value
            present = self._number(entry / "present", errors)
            if present is not None:
                if present in (0, 1):
                    reading["present"] = bool(present)
                else:
                    errors.append(f"Invalid presence value for {entry.name}: {present}")
            if battery:
                if "percentage" in reading:
                    if not 0 <= reading["percentage"] <= 100:
                        errors.append(f"Battery {entry.name} percentage is outside 0--100")
                        reading.pop("percentage")
                    else:
                        reading["percentage_source"] = "capacity"
                else:
                    for remaining, full, source in (
                        ("energy_wh", "full_wh", "energy_now/energy_full"),
                        ("charge_ah", "full_ah", "charge_now/charge_full"),
                    ):
                        now, maximum = reading.get(remaining), reading.get(full)
                        if now is not None and maximum is not None:
                            if maximum > 0 and 0 <= now <= maximum:
                                reading["percentage"] = 100.0 * now / maximum
                                reading["percentage_source"] = source
                            else:
                                errors.append(f"Battery {entry.name} has invalid {source} values")
                            break
                if "power_w" not in reading and "current_a" in reading and "voltage_v" in reading:
                    reading["power_w"] = reading["current_a"] * reading["voltage_v"]
                    reading["power_source"] = "current_now*voltage_now"
            result["batteries" if battery else "supplies"][entry.name] = reading
        for entry in self._entries(self.sys_root / "class" / "thermal", errors):
            if not entry.name.startswith("thermal_zone"):
                continue
            temperature = self._number(entry / "temp", errors, 1000)
            if temperature is not None:
                result["thermal_c"][entry.name] = temperature
        for entry in self._entries(self.sys_root / "class" / "backlight", errors):
            values = {}
            for field in ("brightness", "actual_brightness", "bl_power"):
                value = self._number(entry / field, errors)
                if value is not None:
                    values[field] = value
            static = self._static(entry, "backlight", ("max_brightness", "type"), errors)
            if static:
                values["metadata"] = static
            result["backlight"][entry.name] = values
        cpu_stat = self._text(self.proc_root / "stat", errors)
        if cpu_stat:
            try:
                line = next(line for line in cpu_stat.splitlines() if line.startswith("cpu "))
                ticks = [int(value) for value in line.split()[1:9]]
                if len(ticks) < 4 or any(value < 0 for value in ticks):
                    raise ValueError("invalid CPU counters")
                total = sum(ticks)
                idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
                if self._last_cpu is not None:
                    delta = total - self._last_cpu[0]
                    idle_delta = idle - self._last_cpu[1]
                    if delta > 0 and 0 <= idle_delta <= delta:
                        result["cpu"]["busy_percent"] = 100.0 * (delta - idle_delta) / delta
                self._last_cpu = (total, idle)
            except (StopIteration, ValueError) as exc:
                errors.append(f"Invalid aggregate CPU counters: {exc}")
        frequencies = {}
        for entry in self._entries(self.sys_root / "devices" / "system" / "cpu" / "cpufreq", errors):
            if entry.name.startswith("policy"):
                value = self._number(entry / "scaling_cur_freq", errors, 1000)
                if value is not None:
                    frequencies[entry.name] = value
        if frequencies:
            result["cpu"]["frequency_mhz"] = frequencies
        load = self._text(self.proc_root / "loadavg", errors)
        if load:
            try:
                averages = [float(value) for value in load.split()[:3]]
                if len(averages) != 3 or not all(math.isfinite(value) and value >= 0 for value in averages):
                    raise ValueError("invalid load averages")
                result["cpu"]["load_average"] = averages
            except ValueError as exc:
                errors.append(f"Invalid load averages: {exc}")
        return result
