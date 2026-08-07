#!/usr/bin/bash

set -euo pipefail

readonly BURNBAG_SYSTEM_PYTHON="/usr/bin/python3"
readonly BURNBAG_PYGOBJECT_PACKAGE="python3-gobject"

usage() {
    cat <<'EOF'
Usage: install_prerequisites.sh [--check]

Install burnbag's system-Python D-Bus binding on Fedora/RHEL systems.

Options:
  --check   Verify the prerequisite without changing the system.
  -h, --help
            Show this help text.
EOF
}

check_pygobject() {
    if [[ ! -x "${BURNBAG_SYSTEM_PYTHON}" ]]; then
        printf '[ERROR] Required system interpreter not found: %s\n' \
            "${BURNBAG_SYSTEM_PYTHON}" >&2
        return 1
    fi

    if ! "${BURNBAG_SYSTEM_PYTHON}" -c \
        'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' \
        >/dev/null 2>&1; then
        printf '[ERROR] burnbag requires Python 3.9+ at %s.\n' \
            "${BURNBAG_SYSTEM_PYTHON}" >&2
        return 1
    fi

    if ! "${BURNBAG_SYSTEM_PYTHON}" -c \
        'import gi; gi.require_version("Gio", "2.0"); gi.require_version("GLib", "2.0"); from gi.repository import Gio, GLib' \
        >/dev/null 2>&1; then
        printf '[ERROR] PyGObject is not importable by %s.\n' \
            "${BURNBAG_SYSTEM_PYTHON}" >&2
        return 1
    fi

    printf '[OK] PyGObject is available to %s (%s).\n' \
        "${BURNBAG_SYSTEM_PYTHON}" \
        "$("${BURNBAG_SYSTEM_PYTHON}" --version 2>&1)"
}

main() {
    local burnbag_mode="install"

    case "${1:-}" in
        "")
            ;;
        --check)
            burnbag_mode="check"
            ;;
        -h|--help)
            usage
            return 0
            ;;
        *)
            printf '[ERROR] Unknown option: %s\n' "$1" >&2
            usage >&2
            return 2
            ;;
    esac

    if [[ $# -gt 1 ]]; then
        printf '[ERROR] Too many arguments.\n' >&2
        usage >&2
        return 2
    fi

    if check_pygobject; then
        return 0
    fi

    if [[ "${burnbag_mode}" == "check" ]]; then
        printf '[HINT] Install it with this script or with: sudo dnf install %s\n' \
            "${BURNBAG_PYGOBJECT_PACKAGE}" >&2
        return 1
    fi

    if ! command -v dnf >/dev/null 2>&1; then
        printf '[ERROR] dnf is required to install %s on this supported platform.\n' \
            "${BURNBAG_PYGOBJECT_PACKAGE}" >&2
        return 1
    fi

    printf '[INFO] Installing %s for the distribution Python.\n' \
        "${BURNBAG_PYGOBJECT_PACKAGE}"
    if [[ ${EUID} -eq 0 ]]; then
        dnf install -y "${BURNBAG_PYGOBJECT_PACKAGE}"
    else
        if ! command -v sudo >/dev/null 2>&1; then
            printf '[ERROR] sudo is required when this script is not run as root.\n' >&2
            return 1
        fi
        sudo dnf install -y "${BURNBAG_PYGOBJECT_PACKAGE}"
    fi

    if ! check_pygobject; then
        printf '[ERROR] %s was installed, but %s still cannot import gi.\n' \
            "${BURNBAG_PYGOBJECT_PACKAGE}" "${BURNBAG_SYSTEM_PYTHON}" >&2
        return 1
    fi
}

main "$@"
