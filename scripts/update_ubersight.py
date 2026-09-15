#!/usr/bin/env python3
"""Validate the tracked delivery stack and publish with Ubersight's writer."""

import argparse
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Dict, List, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STACK = PROJECT_ROOT / "project-management/state/phase-slice-stack.md"
STATES = {"pending", "active", "done", "blocked"}
HEADERS = {
    "Phases": ["ID", "State", "Title"],
    "Slices": ["ID", "Phase", "State", "Title"],
}


def writer_arguments(path: Path) -> List[str]:
    """Parse the documented Markdown tables and reject inconsistent state."""
    sections: Dict[str, List[str]] = {}
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            if section in sections:
                raise ValueError(f"duplicate section: {section}")
            sections[section] = []
        elif section:
            sections[section].append(line.strip())

    publication = {}
    for line in sections.get("Publication", []):
        if not line:
            continue
        key, separator, value = line.partition(":")
        if not separator or key not in {"Delivery", "Notes"} or key in publication:
            raise ValueError("Publication requires one Delivery and one Notes line")
        publication[key] = value.strip()
    if set(publication) != {"Delivery", "Notes"}:
        raise ValueError("Publication requires Delivery and Notes")
    delivery, notes = publication["Delivery"], publication["Notes"]
    if delivery not in {"active", "blocked", "complete"}:
        raise ValueError("Delivery must be active, blocked, or complete")
    if not notes or len(notes) > 500 or not notes.isprintable():
        raise ValueError("Notes must contain 1 to 500 printable characters")

    tables = {}
    for name, header in HEADERS.items():
        identifiers = set()
        lines = [line for line in sections.get(name, []) if line]
        rows = []
        for line in lines:
            if not line.startswith("|") or not line.endswith("|"):
                raise ValueError(f"{name} must contain only its Markdown table")
            cells = [cell.strip() for cell in line[1:-1].split("|")]
            if len(cells) != len(header):
                raise ValueError(f"wrong number of columns in {name}")
            rows.append(cells)
        if len(rows) < 3 or rows[0] != header or any(
            re.fullmatch(r":?-{3,}:?", cell) is None for cell in rows[1]
        ):
            raise ValueError(f"missing or malformed {name} table header")
        entries = [dict(zip(header, row)) for row in rows[2:]]
        for entry in entries:
            identifier = entry["ID"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", identifier):
                raise ValueError(f"invalid ID: {identifier}")
            # Phases have project-wide IDs; a slice ID belongs only to its
            # owning phase. Separate namespaces also allow phase 1000 to own
            # slice 1000 without inventing a qualified display identifier.
            identity = identifier if name == "Phases" else (entry["Phase"], identifier)
            if identity in identifiers:
                if name == "Phases":
                    raise ValueError(f"duplicate phase ID: {identifier}")
                raise ValueError(f"duplicate slice ID {identifier} in phase {entry['Phase']}")
            identifiers.add(identity)
            if entry["State"] not in STATES:
                raise ValueError(f"invalid state for {identifier}")
            title = entry["Title"]
            if not title or len(title) > 80 or not title.isprintable():
                raise ValueError(f"{identifier} needs a printable title of 1 to 80 characters")
        tables[name] = entries

    phases, slices = tables["Phases"], tables["Slices"]
    phase_ids = {phase["ID"] for phase in phases}
    active_phases = [phase for phase in phases if phase["State"] == "active"]
    if len(active_phases) != 1:
        raise ValueError("exactly one phase must be active")
    active_phase = active_phases[0]["ID"]
    for item in slices:
        if item["Phase"] not in phase_ids:
            raise ValueError(f"invalid owning phase for {item['ID']}")
        if item["State"] == "active" and item["Phase"] != active_phase:
            raise ValueError(f"active slice {item['ID']} is outside the active phase")
    for phase in phases:
        owned = [item for item in slices if item["Phase"] == phase["ID"]]
        if not owned:
            raise ValueError(f"phase {phase['ID']} has no slices")
        if phase["State"] == "done" and any(item["State"] != "done" for item in owned):
            raise ValueError(f"done phase {phase['ID']} contains unfinished slices")
    active_slices = [item for item in slices if item["State"] == "active"]
    if delivery == "complete":
        if any(item["State"] != "done" for item in slices) or any(
            phase["State"] != "done" for phase in phases if phase["ID"] != active_phase
        ):
            raise ValueError("complete delivery requires every slice and other phase done")
    elif len(active_slices) != 1:
        raise ValueError("exactly one slice must be active unless delivery is complete")

    arguments = ["ubersight", "--write-status", "--project-name", "burnbag-main"]
    for phase in phases:
        arguments.extend(["--phase-row", f"{phase['ID']}:{phase['State']}:{phase['Title']}"])
    for item in slices:
        if item["Phase"] == active_phase:
            arguments.extend(["--slice", f"{item['ID']}:{item['State']}:{item['Title']}"])
    arguments.extend(["--notes", notes])
    if delivery != "active":
        arguments.append("--" + delivery)
    return arguments


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Publish current tracked state, or print the validated command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate and print without writing")
    args = parser.parse_args(argv)
    try:
        command = writer_arguments(STACK)
        if args.dry_run:
            print(shlex.join(command))
        else:
            subprocess.run(command, cwd=PROJECT_ROOT, check=True, timeout=30)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Ubersight update failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
