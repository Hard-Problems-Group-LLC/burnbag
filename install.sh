#!/usr/bin/bash

set -euo pipefail

BURNBAG_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BURNBAG_PROJECT_ROOT
readonly BURNBAG_PREREQUISITE_INSTALLER="${BURNBAG_PROJECT_ROOT}/scripts/install_prerequisites.sh"

usage() {
    cat <<'EOF'
Usage: install.sh [OPTIONS]

Install burnbag and its manual page. The default prefix is /usr/local.

Options:
  --check                 Verify sources and prerequisites without installing.
  --destdir DIR           Stage files beneath absolute DIR without sudo or mandb.
  --mode MODE             Select standard or repo-local dev mode (default: standard).
  --prefix DIR            Install beneath absolute DIR (default: /usr/local).
  --skip-prerequisites    Do not check or install prerequisite packages.
  -h, --help              Show this help text.
EOF
}

require_absolute_path() {
    local burnbag_option_name="$1"
    local burnbag_path="$2"

    if [[ "${burnbag_path}" != /* ]]; then
        printf '[ERROR] %s requires an absolute path: %s\n' \
            "${burnbag_option_name}" "${burnbag_path}" >&2
        return 2
    fi
}

run_privileged() {
    if [[ ${EUID} -eq 0 || -n "${BURNBAG_DESTDIR}" ]]; then
        "$@"
        return
    fi

    if ! command -v sudo >/dev/null 2>&1; then
        printf '[ERROR] sudo is required to install outside a staging directory.\n' >&2
        return 1
    fi
    sudo "$@"
}

ensure_dev_link() {
    local burnbag_source="$1"
    local burnbag_target="$2"

    if [[ -L "${burnbag_target}" ]]; then
        if [[ "$(readlink -f -- "${burnbag_target}")" == "${burnbag_source}" ]]; then
            return 0
        fi
        printf '[ERROR] Refusing to replace an unrelated development link: %s\n' \
            "${burnbag_target}" >&2
        return 1
    fi
    if [[ -e "${burnbag_target}" ]]; then
        printf '[ERROR] Refusing to replace an existing development file: %s\n' \
            "${burnbag_target}" >&2
        return 1
    fi

    ln -s -- "${burnbag_source}" "${burnbag_target}"
}

install_dev_mode() {
    local burnbag_dev_bin_dir="${BURNBAG_PROJECT_ROOT}/.local/bin"
    local burnbag_dev_man_dir="${BURNBAG_PROJECT_ROOT}/.local/share/man/man1"

    install -d -m 0755 "${burnbag_dev_bin_dir}" "${burnbag_dev_man_dir}"
    ensure_dev_link \
        "${BURNBAG_PROJECT_ROOT}/burnbag.py" "${burnbag_dev_bin_dir}/burnbag"
    ensure_dev_link \
        "${BURNBAG_PROJECT_ROOT}/burnbag.1" "${burnbag_dev_man_dir}/burnbag.1"

    printf '[OK] Development launcher: %s\n' "${burnbag_dev_bin_dir}/burnbag"
    printf '[INFO] Add %s to PATH for bare burnbag commands.\n' \
        "${burnbag_dev_bin_dir}"
    printf '[INFO] Add %s to MANPATH for man-page discovery.\n' \
        "${BURNBAG_PROJECT_ROOT}/.local/share/man"
}

main() {
    BURNBAG_CHECK_ONLY=false
    BURNBAG_DESTDIR=""
    BURNBAG_MODE="standard"
    BURNBAG_PREFIX="/usr/local"
    BURNBAG_PREFIX_WAS_SET=false
    BURNBAG_SKIP_PREREQUISITES=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --check)
                BURNBAG_CHECK_ONLY=true
                shift
                ;;
            --destdir)
                if [[ $# -lt 2 ]]; then
                    printf '[ERROR] --destdir requires a value.\n' >&2
                    return 2
                fi
                BURNBAG_DESTDIR="$2"
                shift 2
                ;;
            --mode)
                if [[ $# -lt 2 ]]; then
                    printf '[ERROR] --mode requires a value.\n' >&2
                    return 2
                fi
                BURNBAG_MODE="$2"
                shift 2
                ;;
            --mode=*)
                BURNBAG_MODE="${1#--mode=}"
                shift
                ;;
            --prefix)
                if [[ $# -lt 2 ]]; then
                    printf '[ERROR] --prefix requires a value.\n' >&2
                    return 2
                fi
                BURNBAG_PREFIX="$2"
                BURNBAG_PREFIX_WAS_SET=true
                shift 2
                ;;
            --skip-prerequisites)
                BURNBAG_SKIP_PREREQUISITES=true
                shift
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
    done

    case "${BURNBAG_MODE}" in
        standard|dev)
            ;;
        *)
            printf '[ERROR] --mode must be standard or dev: %s\n' \
                "${BURNBAG_MODE}" >&2
            return 2
            ;;
    esac

    if [[ "${BURNBAG_MODE}" == "dev" ]]; then
        if [[ -n "${BURNBAG_DESTDIR}" ]]; then
            printf '[ERROR] --destdir cannot be combined with --mode dev.\n' >&2
            return 2
        fi
        if [[ "${BURNBAG_PREFIX_WAS_SET}" == true ]]; then
            printf '[ERROR] --prefix cannot be combined with --mode dev.\n' >&2
            return 2
        fi
    fi

    require_absolute_path --prefix "${BURNBAG_PREFIX}"
    if [[ -n "${BURNBAG_DESTDIR}" ]]; then
        require_absolute_path --destdir "${BURNBAG_DESTDIR}"
        if [[ "${BURNBAG_DESTDIR}" == "/" ]]; then
            printf '[ERROR] --destdir must not be the filesystem root.\n' >&2
            return 2
        fi
    fi

    local burnbag_source
    for burnbag_source in \
        "${BURNBAG_PROJECT_ROOT}/burnbag.py" \
        "${BURNBAG_PROJECT_ROOT}/burnbag.1" \
        "${BURNBAG_PREREQUISITE_INSTALLER}"; do
        if [[ ! -f "${burnbag_source}" ]]; then
            printf '[ERROR] Required source file not found: %s\n' \
                "${burnbag_source}" >&2
            return 1
        fi
    done

    if [[ "${BURNBAG_SKIP_PREREQUISITES}" == false ]]; then
        if [[ "${BURNBAG_CHECK_ONLY}" == true ]]; then
            "${BURNBAG_PREREQUISITE_INSTALLER}" --check
        else
            "${BURNBAG_PREREQUISITE_INSTALLER}"
        fi
    fi

    if [[ "${BURNBAG_CHECK_ONLY}" == true ]]; then
        printf '[OK] burnbag %s installation sources are present.\n' \
            "${BURNBAG_MODE}"
        return 0
    fi

    if [[ "${BURNBAG_MODE}" == "dev" ]]; then
        install_dev_mode
        return 0
    fi

    local burnbag_install_root="${BURNBAG_DESTDIR%/}${BURNBAG_PREFIX%/}"
    local burnbag_bin_dir="${burnbag_install_root}/bin"
    local burnbag_man_dir="${burnbag_install_root}/share/man/man1"

    run_privileged install -d -m 0755 "${burnbag_bin_dir}" "${burnbag_man_dir}"
    run_privileged install -m 0755 \
        "${BURNBAG_PROJECT_ROOT}/burnbag.py" "${burnbag_bin_dir}/burnbag"
    run_privileged install -m 0644 \
        "${BURNBAG_PROJECT_ROOT}/burnbag.1" "${burnbag_man_dir}/burnbag.1"

    if [[ -z "${BURNBAG_DESTDIR}" ]] && command -v mandb >/dev/null 2>&1; then
        run_privileged mandb --quiet
    fi

    printf '[OK] Installed burnbag to %s and its manual page to %s.\n' \
        "${burnbag_bin_dir}/burnbag" "${burnbag_man_dir}/burnbag.1"
}

main "$@"
