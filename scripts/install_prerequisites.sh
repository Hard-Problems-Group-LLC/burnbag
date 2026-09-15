#!/usr/bin/bash

set -euo pipefail

readonly BURNBAG_SYSTEM_PYTHON="/usr/bin/python3"

usage() {
    cat <<'EOF'
Usage: install_prerequisites.sh [--check]

Install burnbag's system-Python D-Bus and GTK 4 bindings on Ubuntu/Debian or Fedora/RHEL.

Options:
  --check   Verify the prerequisite without changing the system.
  -h, --help
            Show this help text.
EOF
}

check_python() {
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
}

check_pygobject() {

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

check_gtk4() {
    if ! "${BURNBAG_SYSTEM_PYTHON}" -c \
        'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0"); from gi.repository import Gtk, Gdk' \
        >/dev/null 2>&1; then
        printf '[ERROR] GTK 4 introspection is not importable by %s.\n' \
            "${BURNBAG_SYSTEM_PYTHON}" >&2
        return 1
    fi
    printf '[OK] GTK 4 is available to %s.\n' "${BURNBAG_SYSTEM_PYTHON}"
}

read_distribution() {
    local burnbag_release=/etc/os-release
    local burnbag_key burnbag_value burnbag_id="" burnbag_like=""
    [[ -r "${burnbag_release}" ]] || burnbag_release=/usr/lib/os-release
    [[ -r "${burnbag_release}" ]] || return 1
    # Read only the two selectors. Never execute os-release as shell code.
    while IFS='=' read -r burnbag_key burnbag_value; do
        burnbag_value="${burnbag_value%\"}"
        burnbag_value="${burnbag_value#\"}"
        burnbag_value="${burnbag_value%\'}"
        burnbag_value="${burnbag_value#\'}"
        case "${burnbag_key}" in
            ID) burnbag_id="${burnbag_value}" ;;
            ID_LIKE) burnbag_like="${burnbag_value}" ;;
        esac
    done <"${burnbag_release}"
    printf '%s %s\n' "${burnbag_id}" "${burnbag_like}"
}

select_package_source() {
    local burnbag_distribution burnbag_id
    local -a burnbag_ids
    burnbag_distribution="$(read_distribution)" || burnbag_distribution=""
    read -r -a burnbag_ids <<<"${burnbag_distribution}"
    for burnbag_id in "${burnbag_ids[@]}"; do
        case "${burnbag_id}" in
            ubuntu|debian)
                BURNBAG_PACKAGE_MANAGER=apt-get
                BURNBAG_PACKAGES=(python3-gi gir1.2-glib-2.0 gir1.2-gtk-4.0)
                return 0
                ;;
            fedora|rhel|centos|rocky|almalinux)
                BURNBAG_PACKAGE_MANAGER=dnf
                BURNBAG_PACKAGES=(python3-gobject gtk4)
                return 0
                ;;
        esac
    done
    printf '[ERROR] Cannot select packages for this distribution (%s).\n' \
        "${burnbag_distribution:-unknown}" >&2
    printf '[HINT] Install distribution PyGObject/Gio/GLib for /usr/bin/python3, then rerun --check.\n' >&2
    return 1
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

    check_python || return 1
    if check_pygobject && check_gtk4; then
        return 0
    fi

    select_package_source || return 1

    if [[ "${burnbag_mode}" == "check" ]]; then
        printf '[HINT] Install these bindings with this script or with: sudo %s install %s\n' \
            "${BURNBAG_PACKAGE_MANAGER}" "${BURNBAG_PACKAGES[*]}" >&2
        return 1
    fi

    if ! command -v "${BURNBAG_PACKAGE_MANAGER}" >/dev/null 2>&1; then
        printf '[ERROR] %s is required to install %s on this distribution.\n' \
            "${BURNBAG_PACKAGE_MANAGER}" "${BURNBAG_PACKAGES[*]}" >&2
        return 1
    fi

    local -a burnbag_privilege=()
    if [[ ${EUID} -ne 0 ]]; then
        if ! command -v sudo >/dev/null 2>&1; then
            printf '[ERROR] sudo is required when this script is not run as root.\n' >&2
            return 1
        fi
        burnbag_privilege=(sudo)
    fi
    printf '[INFO] Installing %s with %s for the distribution Python.\n' \
        "${BURNBAG_PACKAGES[*]}" "${BURNBAG_PACKAGE_MANAGER}"
    if ! "${burnbag_privilege[@]}" "${BURNBAG_PACKAGE_MANAGER}" install -y "${BURNBAG_PACKAGES[@]}"; then
        printf '[ERROR] %s package installation failed. Resolve the package-manager error and rerun.\n' \
            "${BURNBAG_PACKAGE_MANAGER}" >&2
        return 1
    fi

    if ! check_pygobject || ! check_gtk4; then
        printf '[ERROR] %s was installed, but %s still cannot import the required bindings.\n' \
            "${BURNBAG_PACKAGES[*]}" "${BURNBAG_SYSTEM_PYTHON}" >&2
        return 1
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
