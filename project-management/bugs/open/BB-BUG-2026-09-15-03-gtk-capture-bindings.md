# Bug: Viewer capture requires newer render-node bindings

- ID: BB-BUG-2026-09-15-03
- Status: Open
- Priority: Medium
- Reported: 2026-09-15
- Reporter and owner: Codex
- Related work: phase 6000, slice 5000; viewer automation from phase 3000

## Symptom And Impact

The existing automation capture endpoint fails on the host's distribution
Python 3.12.13 with PyGObject 3.46.0 and GTK 4.16.7. Ordinary GTK drawing and
the shared-unit plot do not require capture and remain usable. Installation
currently accepts these bindings; capture is therefore not guaranteed by its
prerequisite check.

## Reproduction Or Evidence

The private headless-Weston GUI suite reaches the viewer and exercises its
controls, but capture reports `No means to translate argument or return value
for 'GskClipNode'` at `Gtk.Snapshot.to_node()`. An independent snapshot containing
only a solid rectangle fails with the corresponding `GskColorNode` error,
without loading burnbag or drawing any graph. Explicitly importing Gsk does
not change the failure. This isolates the missing binding capability from
the phase 6000 rendering changes.

## Expected Behavior

Advertised PNG capture works on supported installations, or unsupported
bindings receive an explicit capability diagnostic and documented boundary.

## Actual Behavior

Capture returns a binding error after rendering the snapshot; the viewer
remains open. Screenshot-dependent GUI assertions cannot run with these
native bindings.

## Root Cause

PyGObject 3.46 lacks fundamental-type support for GTK render nodes. Upstream
introduced that support in the development series leading to 3.48; see the
[PyGObject changelog](https://pygobject.gnome.org/changelog.html).

## Resolution

Not implemented in phase 6000. Keep host Python and packages unchanged.
Use isolated newer bindings for frame verification; follow-up work should
choose a compatible capture implementation or an explicit capability boundary.
Do not infer native-binding capture success from that separate environment.

## Validation

The native minimal snapshot reproduction establishes the limitation independently
of burnbag. Direct Cairo plot rendering and interaction tests pass. Phase 6000's
completed-task record will distinguish the native regression run from the
isolated-binding GUI run.

## History

- 2026-09-15: Found during phase 6000 verification; recorded separately from
  the requested plot feature rather than changing system dependencies.
