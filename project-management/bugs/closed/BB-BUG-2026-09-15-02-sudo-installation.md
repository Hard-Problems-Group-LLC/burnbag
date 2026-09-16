# BB-BUG-2026-09-15-02 — Standard installation rejects sudo's PATH

Status: resolved. Reported and reproduced: 2026-09-15.
Resolved: 2026-09-15T22:41:38-07:00.
Owner: Codex. Scope: roadmap phase 5000, slices 1000–4000.

## Report and reproduction

The operator's `sudo ./install.sh` exits during option validation with
`Standard command directory is not on PATH: /usr/local/bin`.
The read-only command below reproduces the exact check without installing
files or changing services (substitute the intended existing home):

```bash
env PATH=/usr/sbin:/usr/bin:/sbin:/bin ./install.sh --check --skip-prerequisites --user-home /absolute/operator/home
```

Native PyGObject and GTK 4 prerequisite checks pass. The failure precedes
package installation and service-helper validation.

## Cause and resolution

Standard-mode preflight and post-install activation assume the installer's
PATH is the operator's command-search path. A sudo policy can omit
`/usr/local/bin`, so this assumption fails both checks. Root's HOME also need
not identify the initiating operator whose managed dev launchers should be
retired. Do not fix this by adding user directories to root's PATH or by
loading the user's shell startup files.

Root standard installs now validate installed executable files independently
of root's PATH. Ordinary non-root installs retain strict command-lookup guards.
All three files must exist as regular executables before any dev launcher is
retired. Root does not claim to verify the caller's shell; it prints explicit
PATH/hash/lookup instructions and warns about preserved unmanaged launchers.

Sudo account identity is validated before selecting its account home; explicit
`--user-home` retains priority. Invalid/incomplete identities fail before
writes; non-root invocations ignore sudo metadata. Ordinary isolated-HOME
safeguards and staging isolation remain. Dev mode and live user-service
installation reject root; user-service rejection now also occurs in preflight.

## Validation

The regression failed before the repair with the reported missing-bin PATH
error and now passes. Private full installations exercise restricted root
PATH, source-independent execution of all three installed commands, caller
versus root launcher cleanup, explicit-home priority, unmanaged preservation,
malformed/mismatched account identity, read-only checks, root-mode rejection,
and incomplete publication without retiring old launchers. Bash identity and
account lookup are substituted, and the real service helper publishes to a
private staging tree; no root privilege is granted to tests.

Native Python 3.12.13 discovery: 453 tests run, eight expected opt-in GUI
skips, all others pass. All 88 affected installer/service/prerequisite/tracking
tests pass on Python 3.9.21 and 3.14.6. Bash syntax, shellcheck, generated-doc
checks, both manual renderers, and whitespace checks pass. PyGObject/GTK and
ordinary read-only installer preflight pass.

Initial sandbox runs could not bind Unix sockets and saw remapped system
ownership; reruns outside that sandbox pass without weakening those guards.
An actual sudo read-only check was attempted noninteractively but requires
operator authentication. No host installation, account, service, or user
launcher was changed. [BB-MANUAL-05](../../ai-human-requests.md) records the
operator's deployment/confirmation step separately from the completed repair.
