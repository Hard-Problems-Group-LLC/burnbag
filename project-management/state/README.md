# Project State

This directory holds short-lived project state that is useful during active
work but should stay lightweight.

## Files

- [phase-slice-stack.md](phase-slice-stack.md): current delivery state and the
  contract for regenerating `.local/ubersight/status.json` with
  `scripts/update_ubersight.py`. This tracked stack is authoritative; the
  ignored live file is a disposable projection.
- `pending-commit-changes.md`: optional queue for short commit-summary notes
  while work is in flight

This queue is not release history. Copy durable user- or operator-facing
changes into `CHANGELOG.md` when the project maintains one.
