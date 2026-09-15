"""Read-only, bounded historical battery graphs using the runtime renderer."""

from __future__ import annotations

from datetime import datetime
import math
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple


def parse_history_time(value: str) -> float:
    """Parse an ISO instant; reject ambiguous or nonexistent local clock times."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:Z|[+-].*)", value.strip()):
        raise ValueError("A timezone suffix requires a date and time, for example 2026-01-01T00:00:00Z")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid time {value!r}; use ISO 8601, for example 2026-09-15T12:00:00-07:00") from exc
    if parsed.tzinfo is not None:
        stamp = parsed.timestamp()
    else:
        candidates = set()
        for is_dst in (-1, 0, 1):
            try:
                candidate = time.mktime(tuple(parsed.timetuple()[:8]) + (is_dst,)) + parsed.microsecond / 1e6
                round_trip = datetime.fromtimestamp(candidate)
                if abs((round_trip - parsed).total_seconds()) < 0.000002:
                    candidates.add(round(candidate, 6))
            except (OverflowError, OSError, ValueError):
                continue
        if len(candidates) != 1:
            reason = "ambiguous" if candidates else "nonexistent or unsupported"
            raise ValueError(f"Local time {value!r} is {reason}; supply an explicit UTC offset or Z")
        stamp = candidates.pop()
    if not math.isfinite(stamp):
        raise ValueError("Time is outside the supported range")
    return stamp


def history_range(start: Optional[str], end: Optional[str], now: Optional[float] = None) -> Tuple[float, float]:
    end_stamp = parse_history_time(end) if end is not None else (time.time() if now is None else now)
    start_stamp = parse_history_time(start) if start is not None else end_stamp - 86400
    if start_stamp >= end_stamp:
        raise ValueError("Historical graph --from must be earlier than --to")
    return start_stamp, end_stamp


def graph_observations(runtime: Any, records: Sequence[Dict[str, Any]], start: float, end: float):
    """Translate stored observations without inventing readings across gaps."""
    samples = []
    lids = []
    sleeps = []
    names = set()
    sources: Dict[str, str] = {}
    previous = None
    issues = []
    for record in sorted(records, key=lambda row: (row["captured_at"], row["id"])):
        try:
            stamp = float(record["captured_at"])
            data = record["data"]
            if record["kind"] in {"sample", "snapshot", "telemetry"}:
                percentages = {}
                statuses = {}
                present = {}
                for name, values in data.get("batteries", {}).items():
                    percentage = values.get("percentage")
                    if (isinstance(percentage, (int, float)) and not isinstance(percentage, bool)
                            and math.isfinite(percentage) and 0 <= percentage <= 100):
                        percentages[name] = math.floor(percentage + 0.5)
                        names.add(name)
                        sources[name] = str(values.get("percentage_source", "history"))
                    if isinstance(values.get("status"), str):
                        statuses[name] = values["status"]
                    present[name] = bool(values.get("present", True))
                if not percentages and any(stream.endswith("/percentage")
                                           for stream in record.get("suppressed_streams", ())):
                    # The system supplied this record's gauge observations.
                    # Retained user-only electrical metrics do not create a
                    # missing-gauge marker between valid system samples.
                    continue
                if previous is not None:
                    gap = stamp - previous["captured_at"]
                    gauge_streams = {"batteries/" + name + "/percentage" for name in percentages}
                    continuous = bool(gauge_streams) and all(
                        stream in record.get("coverage_segments", {})
                        and record["coverage_segments"][stream] == previous.get("coverage_segments", {}).get(stream)
                        for stream in gauge_streams
                    )
                    known_break = any(
                        stream in record.get("coverage_segments", {})
                        and stream in previous.get("coverage_segments", {})
                        and record["coverage_segments"][stream] != previous["coverage_segments"][stream]
                        for stream in gauge_streams
                    )
                    if (record["boot_id"] != previous["boot_id"]
                            or record["machine_id"] != previous["machine_id"]
                            or known_break
                            or (gap > 15 and not continuous)):
                        midpoint = previous["captured_at"] + max(0.0, gap) / 2
                        samples.append(runtime.BatterySample(datetime.fromtimestamp(midpoint).astimezone(),
                                                             midpoint - start, {}))
                samples.append(runtime.BatterySample(datetime.fromtimestamp(stamp).astimezone(),
                                                     stamp - start, percentages, statuses, present))
                previous = record
            elif record["kind"] in {"lid_closed", "lid_opened"}:
                if start <= stamp <= end:
                    lids.append(runtime.LidEvent(datetime.fromtimestamp(stamp).astimezone(),
                                                 stamp - start, record["kind"] == "lid_closed"))
            elif record["kind"] == "sleep_interval":
                stored_start = float(data["started_at"])
                stored_end = float(data["ended_at"])
                uncertainty = float(data.get("boundary_uncertainty_seconds", 0))
                if not all(math.isfinite(value) for value in (stored_start, stored_end, uncertainty)):
                    raise ValueError("sleep interval contains a nonfinite boundary or uncertainty")
                begin = max(start, stored_start)
                finish = min(end, stored_end)
                if begin < finish:
                    kind = data.get("sleep_kind", "unknown")
                    if kind not in {"suspend", "hibernate", "unknown"}:
                        kind = "unknown"
                    sleeps.append(runtime.SuspendInterval(
                        datetime.fromtimestamp(begin).astimezone(), datetime.fromtimestamp(finish).astimezone(),
                        begin - start, finish - start,
                        max(0, uncertainty),
                        sleep_kind=kind, classification_source=data.get("classification_source", "history"),
                    ))
        except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
            if len(issues) < 8:
                issues.append(f"Skipped malformed history record {str(record.get('id', '?'))[:80]}: {exc}")
    devices = [runtime.BatteryDevice(name, Path("history")) for name in sorted(names)[:2]]
    if len(names) > 2:
        issues.append("More than two battery identities occur in this interval; plotting the first two alphabetically")
    return devices, samples, lids, sleeps, issues


def event_timeline(runtime: Any, lids: Sequence[Any], sleeps: Sequence[Any],
                   start: float, end: float, style: Any) -> str:
    """Render known events when no gauge exists; never invent a battery scale."""
    if not lids and not sleeps:
        return ""
    width = max(20, shutil.get_terminal_size(fallback=(80, 30)).columns)
    plot_width = width - 6
    masks = [0] * plot_width
    marks = [0] * plot_width

    def column(elapsed: float) -> int:
        return min(plot_width - 1, max(0, round(elapsed / (end - start) * (plot_width - 1))))

    for interval in sleeps:
        mask = 2 if interval.sleep_kind == "hibernate" else 1
        for x in range(column(interval.start_elapsed_seconds), column(interval.end_elapsed_seconds) + 1):
            masks[x] |= mask
    for event in lids:
        marks[column(event.elapsed_seconds)] |= 1 if event.closed else 2
    lines = ["Event timeline; battery scale unavailable (n/a)."]
    for row in range(25):
        cells = []
        for mask, marker in zip(masks, marks):
            if mask:
                kind = "hibernate" if mask == 2 or (mask == 3 and row % 2 == 0) else "suspend"
                symbol, color = runtime.SLEEP_REGION_STYLES[kind]
                cells.append(style.paint(symbol, color, sys.stdout))
            elif marker:
                symbol = {1: "|", 2: ":", 3: "!"}[marker]
                color = runtime.TerminalStyle.MAGENTA if marker == 1 or (marker == 3 and row % 2) else runtime.TerminalStyle.YELLOW
                cells.append(style.paint(symbol, color, sys.stdout))
            else:
                cells.append(" ")
        lines.append(("n/a │ " if row in (0, 24) else "    │ ") + "".join(cells))
    lines.append("    └─" + "─" * plot_width)
    left = datetime.fromtimestamp(start).astimezone().strftime("%H:%M")
    right = datetime.fromtimestamp(end).astimezone().strftime("%H:%M")
    lines.append("      " + left + " " * max(2, plot_width - len(left) - len(right)) + right)
    lines.append("S=suspend (mode may be unverified), H=verified hibernate; |=lid close, :=lid open, !=both.")
    return "\n".join(lines) + "\n"


def history_command(runtime: Any, start_text: Optional[str], end_text: Optional[str],
                    style: Any, no_plot: bool = False) -> int:
    from burnbag_history import SYSTEM_DATABASE, HistoryError, read_history, user_database_path
    from burnbag_service import flush_service

    try:
        start, end = history_range(start_text, end_text)
    except (ValueError, OverflowError, OSError) as exc:
        style.write_status("ERROR", str(exc), sys.stderr)
        return 2
    warnings: List[str] = []
    if end >= time.time() - 60:
        try:
            if flush_service(timeout=3) is False:
                warnings.append("The latest collector batch could not be synchronized; graph uses its last durable history")
        except Exception as exc:
            warnings.append(f"Could not flush the latest collector data; graph uses durable history only: {exc}")
    sources = []
    try:
        paths = [("system", SYSTEM_DATABASE), ("user", user_database_path())]
    except (ValueError, OSError, HistoryError) as exc:
        paths = [("system", SYSTEM_DATABASE)]
        warnings.append(f"User history location is unavailable: {exc}")
    for scope, path in paths:
        try:
            path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            warnings.append(f"Cannot inspect {scope} history: {exc}")
        else:
            sources.append((scope, path))
    records, read_warnings = read_history(sources, start, end, limit=20000)
    warnings.extend(read_warnings)
    devices, samples, lids, sleeps, issues = graph_observations(runtime, records, start, end)
    warnings.extend(issues)
    for warning in warnings:
        style.write_status("WARNING", warning, sys.stderr)
    print("BURNBAG — HISTORICAL POWER OBSERVATIONS")
    print(f"From: {datetime.fromtimestamp(start).astimezone().isoformat(timespec='seconds')}")
    print(f"To:   {datetime.fromtimestamp(end).astimezone().isoformat(timespec='seconds')}")
    print("Sources: " + (", ".join(scope for scope, _ in sources) or "none"))
    if not devices:
        print("No valid battery observations in this interval. Unobserved time does not establish power-off.")
        if not no_plot:
            print(event_timeline(runtime, lids, sleeps, start, end, style), end="")
    elif not no_plot:
        chart = runtime.render_battery_depletion_chart(
            devices, samples, style, sys.stdout, lid_events=lids, suspend_intervals=sleeps,
            coverage_start=(datetime.fromtimestamp(start).astimezone(), 0),
            coverage_end=(datetime.fromtimestamp(end).astimezone(), end - start),
        )
        print(chart, end="" if chart.endswith("\n") else "\n")
    if devices:
        results = [runtime.summarize_battery_statistics(device.name, samples) for device in devices]
        print(runtime.render_battery_statistics(results, style, sys.stdout), end="")
    closes = sum(event.closed for event in lids)
    print(f"Lid events: close={closes}/open={len(lids) - closes}.")
    counts = {kind: sum(item.sleep_kind == kind for item in sleeps) for kind in ("suspend", "hibernate", "unknown")}
    print(f"Sleep regions: suspend={counts['suspend']}/hibernate={counts['hibernate']}/unverified={counts['unknown']}.")
    print("Blank gaps are unobserved; sleep blocks require clock evidence. The horizontal axis is calendar time.")
    return 1 if warnings else 0
