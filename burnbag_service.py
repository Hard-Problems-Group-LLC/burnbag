"""Optional power recorder and dependency-free service discovery/control.

One abstract Unix socket owns the machine-wide background-collector lease.
Socket ownership is atomic; status checks alone are never used as a lock.
The system and user units must share the host network namespace.
"""

import contextlib
import copy
import errno
import importlib
import json
import queue
import os
from pathlib import Path
import pwd
import signal
import select
import socket
import struct
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional


SERVICE_NAME = "burnbag.service"
SOCKET_ADDRESS = "\0burnbag.collector.v1"
PROTOCOL_VERSION = 1
SAMPLE_SECONDS = 5.0
MAX_MESSAGE_BYTES = 256 * 1024
MAX_CLIENTS = 32
CONFLICT_EXIT = 73
MIRRORED_EVENTS = frozenset(("lid_closed", "lid_opened", "power_profile_changed",
                             "charger_changed", "sleep_interval"))
CLIENT_EVENTS = MIRRORED_EVENTS | frozenset(("run_started", "run_stopped", "power_profile_restored",
                                            "suspend_request_intent", "hibernate_request_intent"))


def _boottime() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def _history() -> Any:
    return importlib.import_module("burnbag_history")


def _foreground_address() -> str:
    return "\0burnbag.foreground.v1.%d" % os.geteuid()


def _send(connection: socket.socket, value: Dict[str, Any]) -> None:
    payload = json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("Service message exceeds its size limit")
    connection.sendall(payload)


def _receive(connection: socket.socket, deadline: Optional[float] = None) -> Dict[str, Any]:
    chunks = bytearray()
    if deadline is None:
        deadline = time.monotonic() + (connection.gettimeout() or 3.0)
    while b"\n" not in chunks:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Collector response exceeded its total deadline")
        connection.settimeout(remaining)
        part = connection.recv(min(4096, MAX_MESSAGE_BYTES + 1 - len(chunks)))
        if not part:
            raise ConnectionError("Collector closed the connection")
        chunks.extend(part)
        if len(chunks) > MAX_MESSAGE_BYTES:
            raise ValueError("Collector message exceeds its size limit")
    line, _, remainder = bytes(chunks).partition(b"\n")
    if remainder:
        raise ValueError("Multiple messages are not accepted in one request")
    value = json.loads(line)
    if not isinstance(value, dict):
        raise ValueError("Collector message must be an object")
    return value


def _credentials(connection: socket.socket) -> tuple:
    return struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                   struct.calcsize("3i")))


def _validate_peer(connection: socket.socket, response: Dict[str, Any], foreground: bool = False) -> None:
    pid, uid, _gid = _credentials(connection)
    if response.get("version") != PROTOCOL_VERSION or response.get("pid") != pid or response.get("uid") != uid:
        raise PermissionError("Collector identity or protocol could not be verified")
    scope = response.get("scope")
    if foreground:
        if uid != os.geteuid() or scope != "user":
            raise PermissionError("Foreground collector belongs to another user")
    elif scope == "system":
        try:
            expected = pwd.getpwnam("burnbag").pw_uid
        except KeyError as exc:
            raise PermissionError("The burnbag service account does not exist") from exc
        if uid != expected:
            raise PermissionError("System collector has an unexpected owner")
        # The UID alone also identifies processes outside the installed unit.
        try:
            groups = Path("/proc/%d/cgroup" % pid).read_text(encoding="ascii")
        except OSError as exc:
            raise PermissionError("System collector membership could not be verified") from exc
        if not any(line.rstrip().endswith("/system.slice/" + SERVICE_NAME) for line in groups.splitlines()):
            raise PermissionError("System collector is outside its systemd unit")
    elif scope != "user":
        raise PermissionError("Collector supplied an unknown service scope")


def _request(command: str, timeout: float = 0.25, address: Optional[str] = None,
             payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    target = SOCKET_ADDRESS if address is None else address
    deadline = time.monotonic() + max(0.01, timeout)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(max(0.01, timeout))
        connection.connect(target)
        request = {"command": command, "version": PROTOCOL_VERSION}
        request.update(payload or {})
        _send(connection, request)
        response = _receive(connection, deadline)
        _validate_peer(connection, response, target != SOCKET_ADDRESS)
        if not response.get("ok", False):
            raise RuntimeError(str(response.get("error", "Collector request failed")))
        return response


def probe_service(timeout: float = 0.25) -> Dict[str, Any]:
    """Inspect the collector without starting services, importing GI, or opening a DB."""
    try:
        response = _request("status", timeout)
    except OSError as exc:
        absent = exc.errno in (errno.ENOENT, errno.ECONNREFUSED)
        return {"status": "absent" if absent else "unhealthy", "reason": str(exc)}
    except (ValueError, RuntimeError, ConnectionError) as exc:
        return {"status": "unhealthy", "reason": str(exc)}
    if response["scope"] == "user" and response["uid"] != os.geteuid():
        response["status"] = "foreign"
        response.pop("database", None)
    elif not response.get("ready") or not response.get("health", {}).get("healthy", False):
        response["status"] = "unhealthy"
    else:
        response["status"] = "ready"
    return response


def warning_for_service(status: Dict[str, Any]) -> Optional[str]:
    """Return a clear warning suitable for both the top and bottom of CLI output."""
    state = status.get("status", "unhealthy")
    if state == "ready":
        return None
    if state == "foreign":
        return ("The background collector belongs to another user; its history is private. "
                "Burnbag runs record locally; continuous history for your user is unavailable.")
    if state == "absent":
        return ("The burnbag monitoring service is NOT RUNNING. Continuous power history is not being "
                "recorded; operational runs record only their own coverage in your user database.")
    return ("The burnbag monitoring service is unavailable or unhealthy. Continuous power history "
            "cannot be relied on; operational runs use your user database. " + str(status.get("reason", ""))).rstrip()


class PrudentLease:
    """A per-connection durability request; closing or crashing releases only this lease."""

    def __init__(self, address: Optional[str] = None, timeout: float = 3.0) -> None:
        self.connection: Optional[socket.socket] = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        target = SOCKET_ADDRESS if address is None else address
        deadline = time.monotonic() + max(0.01, timeout)
        try:
            self.connection.settimeout(timeout)
            self.connection.connect(target)
            _send(self.connection, {"command": "prudent", "version": PROTOCOL_VERSION})
            response = _receive(self.connection, deadline)
            _validate_peer(self.connection, response, target != SOCKET_ADDRESS)
            if not response.get("ok"):
                raise RuntimeError(str(response.get("error", "Prudent writes were not accepted")))
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.connection is not None:
            connection, self.connection = self.connection, None
            with contextlib.suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
            connection.close()

    def alive(self) -> bool:
        if self.connection is None:
            return False
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return not readable or bool(self.connection.recv(1, socket.MSG_PEEK))
        except OSError:
            return False

    def __enter__(self) -> "PrudentLease":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def lease_prudent(timeout: float = 3.0) -> PrudentLease:
    return PrudentLease(timeout=timeout)


def flush_service(timeout: float = 3.0) -> Optional[bool]:
    """Flush accessible recording: True=durable, False=failed, None=none exists.

    Prefer healthy background recording. A same-user foreground collector is
    usable when background recording is absent, private to another user, or
    unhealthy. This lookup never creates a database or starts a service.
    """
    deadline = time.monotonic() + max(0.0, timeout)
    observed = probe_service(timeout=min(0.25, max(0.01, timeout)))
    failed = observed.get("status") in ("unhealthy", "ready")
    candidates = ([SOCKET_ADDRESS] if observed.get("status") == "ready" else []) + [_foreground_address()]
    for address in candidates:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            if address != SOCKET_ADDRESS:
                status = _request("status", min(0.25, remaining), address=address)
                if not status.get("ready") or not status.get("health", {}).get("healthy"):
                    failed = True
                    continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if _request("flush", remaining, address=address,
                        payload={"timeout": min(3.0, max(0.01, remaining - 0.05))}).get("flushed"):
                return True
            failed = True
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ECONNREFUSED):
                failed = True
        except (ValueError, RuntimeError, ConnectionError):
            failed = True
    return False if failed else None


def connect_snapshot(timeout: float = 0.25) -> Optional[Dict[str, Any]]:
    try:
        return _request("snapshot", timeout).get("snapshot")
    except (OSError, ValueError, RuntimeError, ConnectionError):
        return None


def _notify(message: str) -> None:
    target = os.environ.get("NOTIFY_SOCKET")
    if not target:
        return
    if target.startswith("@"):
        target = "\0" + target[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.settimeout(0.25)
            connection.sendto(message.encode("utf-8"), target)
    except OSError:
        pass


class _Collector:
    """Owned collector resources; transport is bounded and never accepts SQL or paths."""

    def __init__(self, scope: str, prudent: bool = False, address: Optional[str] = None,
                 on_warning: Optional[Callable[[str], None]] = None, runtime: Any = None) -> None:
        self.scope = scope
        self.address = SOCKET_ADDRESS if address is None else address
        self.foreground = self.address != SOCKET_ADDRESS
        self.on_warning = on_warning or (lambda message: print("[WARNING] " + message, file=sys.stderr))
        self.runtime = runtime
        self.base_prudent = prudent
        self.leases = 0
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.writer: Any = None
        self.sampler: Any = None
        self.listener: Optional[socket.socket] = None
        self.snapshot: Optional[Dict[str, Any]] = None
        self.ready = False
        self.sampling_progress = time.monotonic()
        self.failure: Optional[str] = None
        self.threads = []
        self.connections = set()
        self.client_threads = set()
        self.client_slots = threading.BoundedSemaphore(MAX_CLIENTS)
        self.last_warning: Dict[str, float] = {}
        self.delegated = False
        self.monitor: Any = None
        self.monitor_start = _boottime()
        self.observer: Any = None
        self.prudent_upstream: Optional[PrudentLease] = None

    def warn(self, message: str) -> None:
        now = time.monotonic()
        with self.lock:
            if now - self.last_warning.get(message, -60.0) < 60.0:
                return
            if len(self.last_warning) >= 64:
                self.last_warning.clear()
            self.last_warning[message] = now
        self.on_warning(message)
        if not self.foreground:
            _notify("STATUS=" + message.replace("\n", " ")[:400])

    def start(self) -> None:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(self.address)
            listener.listen(MAX_CLIENTS)
            listener.settimeout(None)
        except Exception:
            listener.close()
            raise
        self.listener = listener
        try:
            history = _history()
            self.database = history.SYSTEM_DATABASE if self.scope == "system" else history.user_database_path()
            self.writer = history.TelemetryWriter(self.database, self.scope, prudent=self.base_prudent, on_error=self.warn)
            self.sampler = history.PowerSampler()
            self.writer.submit("collector_started", {"scope": self.scope, "pid": os.getpid(),
                                                     "foreground": self.foreground}, urgent=True)
            self.writer.flush(timeout=3.0)
            self.ready = True
            for target, name in ((self._serve, "burnbag-service-ipc"), (self._sample_loop, "burnbag-service-sampling")):
                thread = threading.Thread(target=target, name=name, daemon=True)
                self.threads.append(thread)
                thread.start()
            if self.runtime is not None:
                self.monitor = self.runtime.SuspendMonitor(self.monitor_start)
                self.monitor.start()
                self.observer = _BusObserver(self)
                self.observer.start()
        except Exception:
            self.close()
            raise

    def status(self, peer_uid: int) -> Dict[str, Any]:
        health = self.writer.status() if self.writer is not None else {"healthy": False}
        if self.failure:
            health = dict(health, healthy=False, error=self.failure)
        if self.ready and time.monotonic() - self.sampling_progress > SAMPLE_SECONDS * 3:
            health = dict(health, healthy=False, error="The collector sampling loop has stopped making progress")
        result = {"ok": True, "version": PROTOCOL_VERSION, "scope": self.scope,
                  "uid": os.geteuid(), "pid": os.getpid(), "ready": self.ready,
                  "health": health, "delegated": self.delegated}
        if self.scope == "system" or peer_uid == os.geteuid():
            result["database"] = str(self.database)
        else:
            result["health"] = {"healthy": bool(health.get("healthy"))}
        return result

    def _serve(self) -> None:
        while not self.stop.is_set():
            try:
                assert self.listener is not None
                connection, _address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.client_slots.acquire(blocking=False):
                connection.close()
                continue
            with self.lock:
                self.connections.add(connection)
            thread = threading.Thread(target=self._client, args=(connection,), daemon=True)
            with self.lock:
                self.client_threads.add(thread)
            thread.start()

    def _client(self, connection: socket.socket) -> None:
        prudent = False
        try:
            connection.settimeout(3.0)
            _pid, uid, _gid = _credentials(connection)
            request = _receive(connection)
            if request.get("version") != PROTOCOL_VERSION:
                raise ValueError("Unsupported collector protocol")
            command = request.get("command")
            response = self.status(uid)
            readable = self.scope == "system" or uid == os.geteuid()
            if command == "status":
                pass
            elif not readable:
                raise PermissionError("This user's collector history and controls are private")
            elif command == "snapshot":
                response["snapshot"] = self.snapshot
            elif command == "flush":
                timeout = float(request.get("timeout", 3.0))
                self.writer.flush(timeout=max(0.01, min(3.0, timeout)))
                response["flushed"] = True
            elif command == "prudent":
                with self.lock:
                    self.leases += 1
                    prudent = True
                    self.writer.set_prudent(True)
                self.writer.flush(timeout=2.5)
            elif command == "event":
                kind, data = request.get("kind"), request.get("data")
                if not isinstance(kind, str) or not 1 <= len(kind) <= 80 or not isinstance(data, dict):
                    raise ValueError("Invalid event")
                if len(json.dumps(data)) > 16384:
                    raise ValueError("Event exceeds its size limit")
                if not self.foreground and kind not in CLIENT_EVENTS:
                    raise PermissionError("Collector-owned or unsupported event type")
                if self.foreground and self.delegated:
                    _request("event", timeout=2.0, payload={key: value for key, value in request.items()
                                                          if key not in ("version", "command")})
                elif kind in MIRRORED_EVENTS and (not self.foreground or self.runtime is not None):
                    response["ignored"] = True
                else:
                    # Do not allow a client to forge sensor/lifecycle authority.
                    if not self.foreground and kind in ("sample", "collector_started", "collector_stopped"):
                        raise PermissionError("Collector-owned event type")
                    self.writer.submit(kind, dict(data, reporting_uid=uid),
                                       urgent=bool(request.get("urgent")), event=True,
                                       captured_at=request.get("captured_at"), boottime=request.get("boottime"))
            else:
                raise ValueError("Unknown collector operation")
            _send(connection, response)
            if prudent:
                connection.settimeout(0.5)
                while not self.stop.is_set():
                    try:
                        if not connection.recv(1):
                            break
                        raise ValueError("Prudent leases do not accept additional messages")
                    except socket.timeout:
                        continue
        except (OSError, ValueError, RuntimeError, ConnectionError, TypeError) as exc:
            with contextlib.suppress(OSError, ValueError):
                response = self.status(-1)
                response.update(ok=False, error=str(exc))
                _send(connection, response)
        finally:
            if prudent:
                with self.lock:
                    self.leases -= 1
                    if self.writer is not None:
                        with contextlib.suppress(RuntimeError):
                            self.writer.set_prudent(self.base_prudent or self.leases > 0)
            with self.lock:
                self.connections.discard(connection)
                self.client_threads.discard(threading.current_thread())
            connection.close()
            self.client_slots.release()

    def _sample_loop(self) -> None:
        try:
            self._sample_loop_inner()
        except Exception as exc:
            self.failure = "The collector sampling loop failed: " + str(exc)
            self.warn(self.failure)
            self.stop.set()

    def _publish_snapshot(self, snapshot: Optional[Dict[str, Any]]) -> None:
        if snapshot is not None:
            with self.lock:
                self.snapshot = snapshot

    def _set_delegated(self, delegated: bool) -> None:
        if delegated == self.delegated:
            return
        self.writer.flush(timeout=3.0)
        if self.monitor is not None:
            if not self.delegated:
                self._drain_sleep()
            # Each ownership episode starts with a new paired-clock baseline.
            # A foreground observer must not recreate the daemon's intervals.
            with self.monitor._lock:
                self.monitor.intervals.clear()
                self.monitor.initial = self.monitor.latest = self.monitor.accounted = None
                self.monitor.pending_start = None
        self.delegated = delegated
        if self.observer is not None:
            if delegated:
                self.observer.pause()
            else:
                self.observer.resume()

    def _sample_loop_inner(self) -> None:
        next_sample = 0.0
        # Publish ownership before recording. Existing foreground readers check
        # the lease again after each hardware read and yield before submitting.
        if not self.foreground:
            self.stop.wait(0.75)
        while not self.stop.is_set():
            if self.foreground:
                status = probe_service()
                delegated = status.get("status") == "ready"
                if delegated != self.delegated:
                    self._set_delegated(delegated)
                    self.warn("Recording switched to the background service." if delegated else
                              "Background recording is unavailable; recording this run in your user database.")
                if delegated:
                    self._publish_snapshot(connect_snapshot())
                    self.sampling_progress = time.monotonic()
                    with self.lock:
                        needs_prudent = self.base_prudent or self.leases > 0
                    if self.prudent_upstream is not None and not self.prudent_upstream.alive():
                        self.prudent_upstream.close()
                        self.prudent_upstream = None
                    if needs_prudent and self.prudent_upstream is None:
                        try:
                            self.prudent_upstream = lease_prudent()
                        except (OSError, ValueError, RuntimeError) as exc:
                            self.warn("Prudent writes could not be requested: " + str(exc))
                    elif not needs_prudent and self.prudent_upstream is not None:
                        self.prudent_upstream.close()
                        self.prudent_upstream = None
                    self.stop.wait(0.5)
                    continue
                if self.prudent_upstream is not None:
                    self.prudent_upstream.close()
                    self.prudent_upstream = None
            if time.monotonic() >= next_sample:
                try:
                    captured_at, boottime = time.time(), _boottime()
                    sample = self.sampler.sample()
                    if self.foreground and probe_service().get("status") == "ready":
                        self._set_delegated(True)
                        self._publish_snapshot(connect_snapshot())
                        continue
                    self._publish_snapshot({"captured_at": captured_at, "boottime": boottime, "data": sample})
                    # Use the kernel's explicit condition, rather than guessing
                    # a universal critical threshold from battery percentages.
                    critical = any(
                        isinstance(reading.get("capacity_level"), str)
                        and reading["capacity_level"].strip().casefold() == "critical"
                        for reading in sample.get("batteries", {}).values()
                        if isinstance(reading, dict)
                    )
                    self.writer.submit("sample", sample, urgent=critical,
                                       captured_at=captured_at, boottime=boottime)
                    self.sampling_progress = time.monotonic()
                except Exception as exc:
                    self.warn("Power sampling failed: " + str(exc))
                next_sample = time.monotonic() + SAMPLE_SECONDS
            try:
                self._drain_sleep()
            except Exception as exc:
                self.warn("Sleep interval persistence is incomplete: " + str(exc))
            self.stop.wait(0.5 if self.foreground else 1.0)

    def _drain_sleep(self) -> None:
        if self.monitor is None:
            return
        with self.monitor._lock:
            intervals = list(self.monitor.intervals)
            self.monitor.intervals.clear()
        if not intervals:
            return
        if self.delegated:
            return
        try:
            intervals, evidence = self.runtime.classify_sleep_intervals(intervals)
        except Exception as exc:
            evidence = {"status": "unavailable", "reason": str(exc)}
            self.warn("Sleep mode classification is unavailable: " + str(exc))
        for interval in intervals:
            self.writer.submit("sleep_interval", {
                "start_boottime": self.monitor_start + interval.start_elapsed_seconds,
                "end_boottime": self.monitor_start + interval.end_elapsed_seconds,
                "started_at": interval.started_at.timestamp(), "ended_at": interval.ended_at.timestamp(),
                "sleep_kind": interval.sleep_kind, "classification_source": interval.classification_source,
                "boundary_uncertainty_seconds": interval.boundary_uncertainty_seconds,
                "classification": evidence,
            }, urgent=True)

    def close(self) -> None:
        self.ready = False
        self.stop.set()
        if self.listener is not None:
            # Wake blocking accept without periodic polling; retain the bound
            # descriptor until pending writes are synchronized below.
            with contextlib.suppress(OSError):
                self.listener.shutdown(socket.SHUT_RDWR)
        if self.observer is not None:
            self.observer.close()
        if self.monitor is not None:
            self.monitor.finish()
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(timeout=4.0)
                if thread.is_alive():
                    self.failure = "Collector worker did not stop within its shutdown deadline"
                    self.warn(self.failure)
        if self.writer is not None:
            try:
                self._drain_sleep()
            except Exception as exc:
                self.warn("Final sleep intervals could not be persisted: " + str(exc))
            with contextlib.suppress(Exception):
                self.writer.submit("collector_stopped", {"scope": self.scope, "foreground": self.foreground}, urgent=True)
                self.writer.flush(timeout=3.0)
        with self.lock:
            connections = list(self.connections)
        for connection in connections:
            with contextlib.suppress(OSError):
                connection.shutdown(socket.SHUT_RDWR)
        with self.lock:
            client_threads = list(self.client_threads)
        for thread in client_threads:
            thread.join(timeout=0.25)
        if self.prudent_upstream is not None:
            self.prudent_upstream.close()
            self.prudent_upstream = None
        if self.writer is not None:
            try:
                self.writer.close()
            except Exception as exc:
                self.failure = "Power history did not close cleanly: " + str(exc)
                self.warn("Power history did not close cleanly: " + str(exc))
            self.writer = None
        if self.listener is not None:
            self.listener.close()
            self.listener = None


class _BusObserver:
    """Observe transitions; only bounded delay inhibitors are requested."""

    def __init__(self, collector: _Collector) -> None:
        self.collector = collector
        self.loop: Any = None
        self.connection: Any = None
        self.subscriptions = []
        self.inhibitors: Dict[str, int] = {}
        self.lock = threading.RLock()
        self.thread: Optional[threading.Thread] = None
        self.context: Any = None
        self.lid_state: Optional[bool] = None
        self.initial_state: Dict[str, Any] = {}
        self.diagnostics = set()

    def _diagnostic(self, message: str) -> None:
        self.collector.warn(message)
        if message in self.diagnostics:
            return
        if len(self.diagnostics) < 64:
            self.diagnostics.add(message)
        try:
            self.collector.writer.submit("observer_coverage", {"complete": False, "reason": message}, event=True)
        except Exception:
            # The writer reports its own disk failure; avoid recursive logging.
            pass

    def _properties(self, sender: str, path: str, interface: str) -> Dict[str, Any]:
        runtime = self.collector.runtime
        response = self.connection.call_sync(sender, path, "org.freedesktop.DBus.Properties", "GetAll",
            runtime.GLib.Variant("(s)", (interface,)), None, runtime.Gio.DBusCallFlags.NONE, 1000, None)
        values = response.unpack()[0]
        if not isinstance(values, dict):
            raise ValueError("D-Bus GetAll returned invalid properties")
        return values

    def _initial_observations(self) -> None:
        runtime = self.collector.runtime
        self.initial_state = {}
        try:
            values = self._properties(runtime.UPOWER_BUS_NAME, runtime.UPOWER_OBJECT_PATH, runtime.UPOWER_IFACE)
            if type(values.get("LidIsClosed")) is bool:
                self.lid_state = values["LidIsClosed"]
                self.initial_state["lid_closed"] = self.lid_state
            else:
                self._diagnostic("Initial lid state is unavailable; the first valid observation establishes its baseline")
            if type(values.get("OnBattery")) is bool:
                self.initial_state["on_battery"] = values["OnBattery"]
            else:
                self._diagnostic("Initial charger state is unavailable")
        except Exception as exc:
            self._diagnostic("Initial lid and charger observation failed: " + str(exc))
        try:
            values = self._properties(runtime.POWER_BUS_NAME, runtime.POWER_OBJECT_PATH, runtime.POWER_IFACE)
            if isinstance(values.get("ActiveProfile"), str):
                self.initial_state["power_profile"] = values["ActiveProfile"]
            else:
                self._diagnostic("Initial power profile is unavailable")
        except Exception as exc:
            self._diagnostic("Initial power-profile observation failed: " + str(exc))
        self.collector.writer.submit("observer_state", dict(self.initial_state, initial=True), event=True)

    def pause(self) -> None:
        self._release()
        with self.lock:
            self.lid_state = None

    def resume(self) -> None:
        if self.context is None or self.collector.stop.is_set():
            return
        runtime = self.collector.runtime
        source = runtime.GLib.idle_source_new()
        source.set_callback(self._rearm)
        source.attach(self.context)

    def _rearm(self, *_args: Any) -> bool:
        if self.collector.stop.is_set() or self.collector.delegated:
            return False
        try:
            self._initial_observations()
            for what in ("sleep", "shutdown"):
                self._inhibit(what)
        except Exception as exc:
            self._diagnostic("Could not resume foreground event observation: " + str(exc))
        return False

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="burnbag-service-dbus", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        runtime = self.collector.runtime
        Gio, GLib = runtime.Gio, runtime.GLib
        try:
            context = GLib.MainContext.new()
            self.context = context
            context.push_thread_default()
            try:
                self.loop = GLib.MainLoop.new(context, False)
                self.connection = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
                for sender, interface, path, member in (
                    (runtime.POWER_BUS_NAME, "org.freedesktop.DBus.Properties", runtime.POWER_OBJECT_PATH, "PropertiesChanged"),
                    (runtime.UPOWER_BUS_NAME, "org.freedesktop.DBus.Properties", None, "PropertiesChanged"),
                    (runtime.LOGIND_BUS_NAME, runtime.LOGIND_MANAGER_IFACE, runtime.LOGIND_OBJECT_PATH, "PrepareForSleep"),
                    (runtime.LOGIND_BUS_NAME, runtime.LOGIND_MANAGER_IFACE, runtime.LOGIND_OBJECT_PATH, "PrepareForShutdown"),
                ):
                    self.subscriptions.append(self.connection.signal_subscribe(
                        sender, interface, member, path, None, Gio.DBusSignalFlags.NONE, self._signal, None))
                self._rearm()
                if not self.collector.stop.is_set():
                    self.loop.run()
            finally:
                for subscription in self.subscriptions:
                    self.connection.signal_unsubscribe(subscription)
                self.subscriptions.clear()
                context.pop_thread_default()
        except Exception as exc:
            self._diagnostic("D-Bus transition observation is unavailable: " + str(exc))
        finally:
            self._release()

    def _inhibit(self, what: str) -> None:
        if self.collector.stop.is_set() or self.collector.delegated:
            return
        runtime = self.collector.runtime
        try:
            proxy = runtime.Gio.DBusProxy.new_sync(self.connection, runtime.Gio.DBusProxyFlags.NONE,
                None, runtime.LOGIND_BUS_NAME, runtime.LOGIND_OBJECT_PATH, runtime.LOGIND_MANAGER_IFACE, None)
            result, descriptors = proxy.call_with_unix_fd_list_sync("Inhibit",
                runtime.GLib.Variant("(ssss)", (what, "burnbag", "Synchronize pending power history", "delay")),
                runtime.Gio.DBusCallFlags.NONE, 2000, None, None)
            descriptor = descriptors.get(result.unpack()[0])
            os.set_inheritable(descriptor, False)
            with self.lock:
                self._release(what)
                if self.collector.stop.is_set() or self.collector.delegated:
                    os.close(descriptor)
                else:
                    self.inhibitors[what] = descriptor
        except Exception as exc:
            self._diagnostic("Could not acquire the bounded %s flush delay: %s" % (what, exc))

    def _release(self, what: Optional[str] = None) -> None:
        with self.lock:
            for key in list(self.inhibitors):
                if what is None or key == what:
                    with contextlib.suppress(OSError):
                        os.close(self.inhibitors.pop(key))

    def _signal(self, _connection: Any, _sender: str, path: str, _interface: str,
                member: str, parameters: Any, _userdata: Any) -> None:
        try:
            unpacked = parameters.unpack()
            if member in ("PrepareForSleep", "PrepareForShutdown"):
                active = bool(unpacked[0])
                what = "sleep" if member == "PrepareForSleep" else "shutdown"
                if self.collector.delegated:
                    self._release(what)
                    return
                if active:
                    try:
                        self.collector.writer.submit("prepare_" + what, {"preparing": True}, urgent=True)
                        self.collector.writer.flush(timeout=2.0)
                    finally:
                        self._release(what)
                else:
                    self.collector.writer.submit("resume" if what == "sleep" else "shutdown_cancelled",
                                                 {"preparing": False}, urgent=True)
                    self._inhibit(what)
            elif member == "PropertiesChanged":
                if self.collector.delegated:
                    return
                changed_interface, changed, invalidated = unpacked
                if not isinstance(changed, dict) or not isinstance(invalidated, (list, tuple)):
                    raise ValueError("Invalid D-Bus property change payload")
                watched = {"LidIsClosed", "ActiveProfile", "OnBattery", "Online"}
                reread = watched.intersection(invalidated)
                if reread:
                    values = self._properties(_sender, path, changed_interface)
                    changed = dict(changed)
                    for key in reread:
                        if key in values:
                            changed[key] = values[key]
                        else:
                            self._diagnostic("Invalidated power property could not be recovered: " + key)
                if "LidIsClosed" in changed:
                    closed = changed["LidIsClosed"]
                    if type(closed) is not bool:
                        self._diagnostic("The lid sensor supplied a non-boolean state; observation was ignored")
                    else:
                        previous, self.lid_state = self.lid_state, closed
                        if previous is not None and closed != previous:
                            self.collector.writer.submit("lid_closed" if closed else "lid_opened", {"closed": closed}, event=True)
                        elif previous is None:
                            self.collector.writer.submit("observer_state", {"lid_closed": closed, "initial": True}, event=True)
                if "ActiveProfile" in changed:
                    self.collector.writer.submit("power_profile_changed", {"profile": changed["ActiveProfile"]}, event=True)
                if "OnBattery" in changed or "Online" in changed:
                    self.collector.writer.submit("charger_changed", {"path": path,
                        "properties": {key: changed[key] for key in ("OnBattery", "Online") if key in changed}}, event=True)
        except Exception as exc:
            self._diagnostic("Could not record a power transition: " + str(exc))

    def close(self) -> None:
        if self.loop is not None:
            self.loop.quit()
        if self.thread is not None:
            self.thread.join(timeout=2.5)
        self._release()


def run_collector(scope: str, prudent: bool = False, runtime: Any = None) -> int:
    """Run a passive collector until SIGINT/SIGTERM; never request a power action."""
    if scope not in ("system", "user"):
        print("[ERROR] Collector scope must be system or user.", file=sys.stderr)
        return 2
    if scope == "system":
        try:
            correct_user = os.geteuid() == pwd.getpwnam("burnbag").pw_uid
        except KeyError:
            correct_user = False
        if not correct_user:
            print("[ERROR] The system collector must run as the burnbag service account.", file=sys.stderr)
            return 1
    if runtime is None:
        try:
            runtime = importlib.import_module("burnbag")
            import gi
            gi.require_version("Gio", "2.0")
            gi.require_version("GLib", "2.0")
            from gi.repository import Gio, GLib
            runtime.Gio, runtime.GLib = Gio, GLib
        except (ImportError, ValueError) as exc:
            print("[ERROR] Collector D-Bus dependencies are unavailable: " + str(exc), file=sys.stderr)
            return 1
    collector = _Collector(scope, prudent, runtime=runtime)
    previous = {}
    result_code = 0
    try:
        for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, lambda _signal, _frame: collector.stop.set())
        collector.start()
        _notify("READY=1\nSTATUS=Power history collector is recording")
        while not collector.stop.wait(10.0):
            if not collector.writer.status().get("healthy", False):
                _notify("STATUS=Power history storage is unhealthy; recording is degraded")
        result_code = 1 if collector.failure else 0
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print("[ERROR] Another background collector already owns this machine. Stop it before starting this service.", file=sys.stderr)
            result_code = CONFLICT_EXIT
        else:
            print("[ERROR] Collector failed: " + str(exc), file=sys.stderr)
            result_code = 1
    except Exception as exc:
        print("[ERROR] Collector failed: " + str(exc), file=sys.stderr)
        result_code = 1
    finally:
        _notify("STOPPING=1")
        try:
            collector.close()
        except Exception as exc:
            print("[ERROR] Collector cleanup failed: " + str(exc), file=sys.stderr)
            result_code = 1
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    return 1 if collector.failure and result_code == 0 else result_code


def _unit_state(scope: str) -> Dict[str, str]:
    command = ["systemctl"] + (["--user"] if scope == "user" else ["--system"])
    command += ["show", SERVICE_NAME, "--no-pager", "--property=LoadState,ActiveState,UnitFileState"]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2.0)
    if result.returncode:
        return {"LoadState": "unavailable", "error": result.stderr.strip()}
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def manage_service(action: str, scope: Optional[str] = None) -> int:
    """Control only the system unit or caller's user unit, preserving systemctl semantics."""
    if action not in ("start", "stop", "status", "enable", "disable") or scope not in (None, "system", "user"):
        print("[ERROR] Invalid service operation or scope.", file=sys.stderr)
        return 2
    try:
        observed = probe_service()
        states = {candidate: _unit_state(candidate) for candidate in ("system", "user")}
        if action == "status":
            for candidate in ((scope,) if scope else ("system", "user")):
                state = states[candidate]
                print("%s service: installed=%s active=%s enabled=%s" % (candidate,
                    state.get("LoadState", "unknown"), state.get("ActiveState", "unknown"), state.get("UnitFileState", "unknown")))
            print("Collector: %s%s" % (observed.get("status", "unknown"),
                " (scope=%s uid=%s pid=%s)" % (observed.get("scope"), observed.get("uid"), observed.get("pid")) if "scope" in observed else ""))
            return 0 if observed.get("status") == "ready" and (scope is None or observed.get("scope") == scope) else 3
        if observed.get("status") == "foreign" and (scope is None or action == "start"):
            print("[ERROR] Another user's collector is running; no other user's service will be changed.", file=sys.stderr)
            return 1
        if scope is None:
            active = [candidate for candidate, state in states.items() if state.get("ActiveState") in ("active", "activating", "reloading")]
            installed = [candidate for candidate, state in states.items() if state.get("LoadState") == "loaded"]
            candidates = active or installed
            if len(candidates) != 1:
                print("[ERROR] Service scope is ambiguous or no unit is installed; specify user or system explicitly.", file=sys.stderr)
                return 2
            scope = candidates[0]
        if action == "start" and observed.get("status") == "ready" and observed.get("scope") != scope:
            print("[ERROR] The other service scope is already recording; stop it before switching scopes.", file=sys.stderr)
            return 1
        command = ["systemctl", "--user" if scope == "user" else "--system", action, SERVICE_NAME, "--no-pager"]
        # systemctl uses the platform's existing polkit authentication; do not run arbitrary sudo commands.
        return subprocess.run(command, timeout=30.0).returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("[ERROR] Could not manage the service: " + str(exc), file=sys.stderr)
        return 1


class ForegroundRecorder:
    """Use accessible background history, otherwise share one fallback per user."""

    def __init__(self, prudent: bool = False, on_warning: Optional[Callable[[str], None]] = None,
                 runtime: Any = None) -> None:
        self.prudent = prudent
        self.on_warning = on_warning or (lambda message: print("[WARNING] " + message, file=sys.stderr))
        self.runtime = runtime
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.collector: Optional[_Collector] = None
        self.lease: Optional[PrudentLease] = None
        self.snapshot: Optional[Dict[str, Any]] = None
        self.snapshot_condition = threading.Condition()
        self.address = SOCKET_ADDRESS
        self.last_state = None
        self.pending: Any = queue.Queue(maxsize=1024)
        self.last_error: Optional[str] = None
        self.error_lock = threading.Lock()
        self.drain_lock = threading.Lock()
        self.closed = False

    def _error(self, message: str) -> None:
        with self.error_lock:
            self.last_error = message
        self.on_warning(message)

    def start(self) -> "ForegroundRecorder":
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name="burnbag-foreground-history", daemon=True)
            self.thread.start()
        return self

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                status = probe_service()
                state = status.get("status")
                target = SOCKET_ADDRESS if state == "ready" else _foreground_address()
                if state != self.last_state:
                    message = warning_for_service(status)
                    if message:
                        self.on_warning(message)
                    elif self.last_state is not None:
                        self.on_warning("Background recording is available; subsequent measurements use the service.")
                    self.last_state = state
                if target != self.address and self.lease is not None:
                    self.lease.close()
                    self.lease = None
                self.address = target
                if target != SOCKET_ADDRESS and self.collector is None:
                    try:
                        _request("status", address=target)
                    except OSError as exc:
                        if exc.errno not in (errno.ENOENT, errno.ECONNREFUSED):
                            raise
                        candidate = _Collector("user", self.prudent, target, self.on_warning, runtime=self.runtime)
                        try:
                            candidate.start()
                        except OSError as conflict:
                            if conflict.errno != errno.EADDRINUSE:
                                raise
                        else:
                            if self.stop.is_set():
                                candidate.close()
                                break
                            self.collector = candidate
                if self.lease is not None and not self.lease.alive():
                    self.lease.close()
                    self.lease = None
                if self.prudent and self.lease is None:
                    self.lease = PrudentLease(target)
                self._publish_snapshot(_request("snapshot", address=target).get("snapshot"))
                self._drain_events()
            except (OSError, ValueError, RuntimeError, ConnectionError) as exc:
                if self.lease is not None:
                    self.lease.close()
                    self.lease = None
                message = "Power-history recording is degraded: " + str(exc)
                if message != self.last_state:
                    self._error(message)
                    self.last_state = message
            self.stop.wait(0.5)

    def _publish_snapshot(self, snapshot: Optional[Dict[str, Any]]) -> None:
        if snapshot is None:
            return
        with self.snapshot_condition:
            if self.snapshot is None or snapshot["boottime"] >= self.snapshot["boottime"]:
                self.snapshot = snapshot
                self.snapshot_condition.notify_all()

    def latest_snapshot(self, timeout: float = 0.0) -> Optional[Dict[str, Any]]:
        """Return the latest immutable observation, optionally awaiting the first.

        A caller receives an independent copy. Waiting is bounded by one total
        deadline and never causes hardware sampling. Locally owned snapshots
        remain available after the coordinator and collector stop.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            collector = self.collector
            if collector is not None:
                with collector.lock:
                    local = collector.snapshot
                self._publish_snapshot(local)
            with self.snapshot_condition:
                if self.snapshot is not None:
                    return copy.deepcopy(self.snapshot)
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self.closed:
                    return None
                # A local collector can publish before the IPC coordinator's
                # next cycle. Brief waits apply only to the initial rendezvous.
                self.snapshot_condition.wait(min(0.05, remaining))

    def record_event(self, kind: str, data: Dict[str, Any], urgent: bool = False) -> None:
        try:
            self.pending.put_nowait({"kind": kind, "data": json.loads(json.dumps(data, allow_nan=False)),
                                    "urgent": urgent, "captured_at": time.time(), "boottime": _boottime()})
        except (queue.Full, ValueError, TypeError) as exc:
            self._error("Power-history event %s was not accepted: %s" % (kind, exc))

    def _drain_events(self, deadline: Optional[float] = None) -> bool:
        if deadline is None:
            deadline = time.monotonic() + 3.0
        if not self.drain_lock.acquire(timeout=max(0.0, deadline - time.monotonic())):
            return False
        try:
            return self._drain_events_locked(deadline)
        finally:
            self.drain_lock.release()

    def _drain_events_locked(self, deadline: float) -> bool:
        while True:
            if time.monotonic() >= deadline:
                return self.pending.empty()
            try:
                payload = self.pending.get_nowait()
            except queue.Empty:
                return True
            try:
                _request("event", timeout=min(3.0 if payload["urgent"] else 0.5, max(0.01, deadline - time.monotonic())),
                         address=self.address, payload=payload)
            except (OSError, ValueError, RuntimeError, ConnectionError) as exc:
                self._error("Could not persist power-history event %s: %s" % (payload["kind"], exc))
            finally:
                self.pending.task_done()

    def flush(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        try:
            # A shared foreground owner may have exited just before its last
            # follower. Reacquire a writer before draining the follower's queue.
            try:
                _request("status", timeout=min(0.25, max(0.01, timeout)), address=self.address)
            except OSError as exc:
                if exc.errno not in (errno.ENOENT, errno.ECONNREFUSED):
                    raise
                available = probe_service(timeout=min(0.25, max(0.01, deadline - time.monotonic())))
                self.address = SOCKET_ADDRESS if available.get("status") == "ready" else _foreground_address()
                if self.address != SOCKET_ADDRESS and self.collector is None:
                    candidate = _Collector("user", self.prudent, self.address, self.on_warning, runtime=self.runtime)
                    try:
                        candidate.start()
                    except OSError as conflict:
                        if conflict.errno != errno.EADDRINUSE:
                            raise
                    else:
                        self.collector = candidate
            if not self._drain_events(deadline):
                raise TimeoutError("Pending history events could not be sent before the flush deadline")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("History flush deadline elapsed")
            return bool(_request("flush", remaining, address=self.address,
                                 payload={"timeout": max(0.01, remaining - 0.05)}).get("flushed"))
        except (OSError, ValueError, RuntimeError, ConnectionError):
            self._error("Pending power-history records could not be synchronized to disk")
            return False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=4.0)
            if self.thread.is_alive():
                self._error("Foreground history worker did not stop within its shutdown deadline")
        self.flush()
        if self.lease is not None:
            self.lease.close()
            self.lease = None
        if self.collector is not None:
            if self.collector.writer is not None:
                health = self.collector.status(os.geteuid())["health"]
                if not health.get("healthy"):
                    self._error(str(health.get("error", "The foreground collector is unhealthy")))
            self.collector.close()
            self._publish_snapshot(self.collector.snapshot)
            self.collector = None
        if self.last_error:
            raise RuntimeError(self.last_error)
