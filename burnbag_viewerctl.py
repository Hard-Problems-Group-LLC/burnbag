#!/usr/bin/python3
"""Control an explicitly automation-enabled burnbag GTK viewer."""
from __future__ import annotations

import argparse
import base64
import json
import socket
import sys
import uuid
from pathlib import Path
from typing import Any, Optional, Sequence


def request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > 256 * 1024:
        raise ValueError("request exceeds 256 KiB")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(12)
        connection.connect(path)
        connection.sendall(data)
        response = bytearray()
        while b"\n" not in response and len(response) <= 12 * 1024 * 1024:
            chunk = connection.recv(min(65536, 12 * 1024 * 1024 + 1 - len(response)))
            if not chunk:
                break
            response.extend(chunk)
    if len(response) > 12 * 1024 * 1024 or b"\n" not in response:
        raise ValueError("viewer response exceeded its limit or lacked newline")
    result = json.loads(bytes(response).split(b"\n", 1)[0].decode("utf-8"))
    if result.get("id") != payload["id"]:
        raise ValueError("viewer response ID did not match request")
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "viewer request failed"))
    return result.get("result", {})


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True, help="viewer automation Unix socket")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show viewer state")
    capture = sub.add_parser("capture", help="capture full viewer client area as PNG")
    capture.add_argument("--output", help="write PNG bytes to this file")
    key = sub.add_parser("key", help="send a semantic key")
    key.add_argument("name")
    key.add_argument("--modifier", action="append", choices=("CTRL", "SHIFT", "ALT"), default=[])
    tab = sub.add_parser("tab", help="select graph or table tab")
    tab.add_argument("name", choices=("graph", "table"))
    search = sub.add_parser("search", help="set the history search text")
    search.add_argument("text")
    zoom = sub.add_parser("zoom", help="change graph and table time window")
    zoom.add_argument("factor", type=float, help="scale multiplier (below 1 zooms in)")
    pan = sub.add_parser("pan", help="pan graph by a fraction of the current width")
    pan.add_argument("fraction", type=float)
    view = sub.add_parser("view", help="fit the graph to the selected table rows")
    sub.add_parser("fit", help="fit the graph to the highlighted time interval")
    series = sub.add_parser("series", help="select a loaded numeric graph measurement")
    series.add_argument("name")
    fields = sub.add_parser("fields", help="edit graph/table checkboxes; only OK saves and applies")
    fields.add_argument("action", choices=("open", "set", "tab", "ok", "cancel"))
    fields.add_argument("--view", choices=("graph", "table"))
    fields.add_argument("--name", help="field name for set")
    fields.add_argument("--checked", choices=("yes", "no"), help="checkbox state for set")
    row = sub.add_parser("row", help="activate a loaded table row")
    row.add_argument("position", type=int)
    row.add_argument("--clicks", type=int, choices=(1, 2), default=1)
    select = sub.add_parser("select", help="select an inclusive loaded table row range")
    select.add_argument("first", type=int)
    select.add_argument("last", type=int)
    click = sub.add_parser("click", help="click a normalized point on the graph")
    click.add_argument("x", type=float)
    click.add_argument("y", type=float)
    click.add_argument("--button", type=int, default=1)
    click.add_argument("--clicks", type=int, choices=(1, 2), default=1)
    pointer = sub.add_parser("pointer", help="send a pointer operation")
    pointer.add_argument("action", choices=("move", "press", "release", "click", "wheel"))
    pointer.add_argument("target", choices=("graph", "table", "tab-graph", "tab-table", "view-selection", "fields", "fit"))
    pointer.add_argument("x", type=float, nargs="?", default=0.5)
    pointer.add_argument("y", type=float, nargs="?", default=0.5)
    pointer.add_argument("--delta", type=float, default=0)
    pointer.add_argument("--button", type=int, default=1)
    pointer.add_argument("--clicks", type=int, choices=(1, 2), default=1)
    window = sub.add_parser("window", help="apply a window manager action")
    window.add_argument("action", choices=("minimize", "maximize", "restore", "close"))
    typing = sub.add_parser("type", help="type text into the viewer search field")
    typing.add_argument("text")
    args = parser.parse_args(argv)
    identity = uuid.uuid4().hex
    payload: dict[str, Any] = {"id": identity}
    if args.command == "status":
        payload["op"] = "state"
    elif args.command == "capture":
        payload["op"] = "capture"
    elif args.command == "key":
        payload.update(op="key", key=args.name, modifiers=args.modifier)
    elif args.command == "tab":
        payload.update(op="tab", name=args.name)
    elif args.command == "search":
        payload.update(op="search", text=args.text)
    elif args.command == "zoom":
        payload.update(op="zoom", factor=args.factor)
    elif args.command == "pan":
        payload.update(op="pan", fraction=args.fraction)
    elif args.command in ("view", "fit"):
        payload["op"] = args.command
    elif args.command == "series":
        payload.update(op="series", name=args.name)
    elif args.command == "fields":
        payload.update(op="fields", action=args.action, view=args.view, name=args.name,
                       checked=(args.checked == "yes") if args.checked is not None else None)
    elif args.command == "row":
        payload.update(op="row", position=args.position, clicks=args.clicks)
    elif args.command == "select":
        payload.update(op="select", first=args.first, last=args.last)
    elif args.command == "click":
        payload.update(op="pointer", target="graph", x=args.x, y=args.y,
                       button=args.button, clicks=args.clicks)
    elif args.command == "pointer":
        payload.update(op="pointer", action=args.action, target=args.target,
                       x=args.x, y=args.y, delta=args.delta, button=args.button,
                       clicks=args.clicks)
    elif args.command == "window":
        payload.update(op="window", action=args.action)
    elif args.command == "type":
        payload.update(op="type_text", text=args.text)
    try:
        result = request(args.socket, payload)
        if args.command == "capture":
            destination = getattr(args, "output", None)
            if destination:
                Path(destination).write_bytes(base64.b64decode(result["base64"], validate=True))
            else:
                print(json.dumps({k: v for k, v in result.items() if k != "base64"}), file=sys.stderr)
                sys.stdout.buffer.write(base64.b64decode(result["base64"], validate=True))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print("burnbag-viewerctl: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
