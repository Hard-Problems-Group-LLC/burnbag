# AI Human Requests

Use this queue for non-blocking actions that AI agents need humans to perform.

Record each request with concise context, owner or requestor details, and ISO
8601 timestamps.

## Pending Requests

- `BB-MANUAL-01` — Physical Ubuntu/ARM lifecycle confirmation.
  - Created: 2026-09-14. Owner: operator. Requestor: Codex.
  - Covers roadmap P2.4 and P3.4. Queue only: request execution after
    automated fixes and delivery documentation are ready.
  - Observe screen off/on and original profile restoration over a physical
    close/open cycle, repeated `--ignore-lid` cycles, and Ctrl-C with a visible
    battery graph and summary. Exact checkout commands will be supplied after
    final automated verification; no untested live suspend is requested yet.
  - 2026-09-14: operator supplied installed-baseline evidence of successful
    physical lid events, delayed backlight off, verified backlight restoration,
    and inhibitor release. This closes P1.4. It does not validate the revised
    battery reader, a changed-and-restored profile, or hardware suspend/resume.

## Active Requests

No active requests.

## Completed Requests

No completed requests yet.
