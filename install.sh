#!/usr/bin/bash

set -euo pipefail

BURNBAG_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BURNBAG_PROJECT_ROOT
readonly BURNBAG_PREREQUISITE_INSTALLER="${BURNBAG_PROJECT_ROOT}/scripts/install_prerequisites.sh"
readonly BURNBAG_DEV_LAUNCHER_MARKER="# burnbag-managed-dev-launcher"
readonly BURNBAG_DEV_LAUNCHER_MODE_ENV="BURNBAG_DEV_LAUNCHER_MODE"

usage() {
    cat <<'EOF'
Usage: install.sh [OPTIONS]

Install burnbag and its manual page. The default prefix is /usr/local.

Options:
  --check                 Verify sources and prerequisites without installing.
  --destdir DIR           Stage files beneath absolute DIR without sudo or mandb.
  --dev-command MODE      In dev mode, select prompt, local, or system command
                          resolution (default: prompt).
  --force                 Allow replacement of an unmanaged user launcher.
  --mode MODE             Select standard or repo-local dev mode (default: standard).
  --prefix DIR            Install beneath absolute DIR (default: /usr/local).
  --skip-prerequisites    Do not check or install prerequisite packages.
  --user-home DIR         Use absolute DIR for the dev launcher user scope.
  -h, --help              Show this help text.

For non-interactive dev setup, BURNBAG_DEV_LAUNCHER_MODE may select local or
system explicitly. Without an explicit selection, command resolution is left
unchanged.
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

select_user_home() {
    local burnbag_selected_home

    if [[ -n "${BURNBAG_USER_HOME}" ]]; then
        burnbag_selected_home="${BURNBAG_USER_HOME}"
    else
        burnbag_selected_home="${HOME:-}"
        case "${burnbag_selected_home##*/}" in
            .claude-home|.codex-home)
                printf '[ERROR] HOME is an isolated assistant environment: %s\n' \
                    "${burnbag_selected_home}" >&2
                printf '[HINT] Rerun with --user-home /absolute/operator/home.\n' >&2
                return 1
                ;;
        esac
    fi

    if [[ -z "${burnbag_selected_home}" ]]; then
        printf '[ERROR] Dev mode requires HOME or --user-home.\n' >&2
        return 1
    fi
    require_absolute_path --user-home "${burnbag_selected_home}"
    if [[ ! -d "${burnbag_selected_home}" ]]; then
        printf '[ERROR] --user-home must name an existing directory: %s\n' \
            "${burnbag_selected_home}" >&2
        return 1
    fi

    BURNBAG_EFFECTIVE_USER_HOME="$(cd -- "${burnbag_selected_home}" && pwd -P)"
    BURNBAG_USER_BIN_DIR="${BURNBAG_EFFECTIVE_USER_HOME}/.local/bin"
    BURNBAG_USER_LAUNCHER="${BURNBAG_USER_BIN_DIR}/burnbag"
}

is_managed_dev_launcher() {
    local burnbag_launcher="$1"

    [[ -f "${burnbag_launcher}" ]] \
        && grep -Fqx -- "${BURNBAG_DEV_LAUNCHER_MARKER}" "${burnbag_launcher}"
}

detect_alternate_burnbag() {
    local burnbag_path_entry
    local burnbag_candidate

    while IFS= read -r burnbag_path_entry; do
        [[ -n "${burnbag_path_entry}" ]] || burnbag_path_entry="."
        burnbag_candidate="${burnbag_path_entry%/}/burnbag"
        if [[ ! -x "${burnbag_candidate}" ]]; then
            continue
        fi
        if [[ "${burnbag_candidate}" == "${BURNBAG_USER_LAUNCHER}" ]]; then
            continue
        fi
        printf '%s\n' "${burnbag_candidate}"
        return 0
    done < <(printf '%s' "${PATH:-}" | tr ':' '\n')

    return 1
}

user_bin_precedes_other_burnbag() {
    local burnbag_path_entry
    local burnbag_candidate

    while IFS= read -r burnbag_path_entry; do
        [[ -n "${burnbag_path_entry}" ]] || burnbag_path_entry="."
        burnbag_path_entry="${burnbag_path_entry%/}"
        if [[ "${burnbag_path_entry}" == "${BURNBAG_USER_BIN_DIR}" ]]; then
            return 0
        fi
        burnbag_candidate="${burnbag_path_entry}/burnbag"
        if [[ -x "${burnbag_candidate}" ]]; then
            return 1
        fi
    done < <(printf '%s' "${PATH:-}" | tr ':' '\n')

    return 1
}

resolve_dev_command_mode() {
    local burnbag_alternate=""
    local burnbag_prompt
    local burnbag_response

    burnbag_alternate="$(detect_alternate_burnbag || true)"
    if [[ -n "${burnbag_alternate}" ]]; then
        printf '[INFO] Another burnbag command appears on PATH at %s.\n' \
            "${burnbag_alternate}"
    else
        printf '[INFO] No other burnbag command was detected on PATH.\n'
    fi

    case "${BURNBAG_DEV_COMMAND}" in
        local|system)
            BURNBAG_RESOLVED_DEV_COMMAND="${BURNBAG_DEV_COMMAND}"
            return 0
            ;;
        prompt)
            ;;
        *)
            printf '[ERROR] Dev command mode must be prompt, local, or system: %s\n' \
                "${BURNBAG_DEV_COMMAND}" >&2
            return 2
            ;;
    esac

    if [[ ! -t 0 || ! -t 1 ]]; then
        printf '[INFO] Non-interactive dev install: leaving burnbag command resolution unchanged.\n'
        printf '[HINT] Use --dev-command local or set %s=local to select the checkout.\n' \
            "${BURNBAG_DEV_LAUNCHER_MODE_ENV}"
        BURNBAG_RESOLVED_DEV_COMMAND="system"
        return 0
    fi

    burnbag_prompt="When you type 'burnbag', use this checkout instead of the current PATH result? [y/N]: "
    if [[ -z "${burnbag_alternate}" ]]; then
        burnbag_prompt="Install a managed user launcher so 'burnbag' uses this checkout? [y/N]: "
    fi
    read -r -p "${burnbag_prompt}" burnbag_response
    case "${burnbag_response}" in
        y|Y|yes|YES|Yes)
            BURNBAG_RESOLVED_DEV_COMMAND="local"
            ;;
        *)
            BURNBAG_RESOLVED_DEV_COMMAND="system"
            ;;
    esac
}

write_managed_dev_launcher() {
    local burnbag_temp_launcher
    local burnbag_resolved_command

    case ":${PATH:-}:" in
        *":${BURNBAG_USER_BIN_DIR}:"*)
            ;;
        *)
            printf '[ERROR] User launcher directory is not on PATH: %s\n' \
                "${BURNBAG_USER_BIN_DIR}" >&2
            printf '[HINT] Add it to PATH before selecting local dev command resolution.\n' >&2
            return 1
            ;;
    esac
    if ! user_bin_precedes_other_burnbag; then
        printf '[ERROR] User launcher directory does not precede the current burnbag command: %s\n' \
            "${BURNBAG_USER_BIN_DIR}" >&2
        printf '[HINT] Move it earlier on PATH before selecting local dev command resolution.\n' >&2
        return 1
    fi

    if [[ -e "${BURNBAG_USER_LAUNCHER}" || -L "${BURNBAG_USER_LAUNCHER}" ]]; then
        if ! is_managed_dev_launcher "${BURNBAG_USER_LAUNCHER}"; then
            if [[ "${BURNBAG_FORCE}" != true ]]; then
                printf '[ERROR] Refusing to replace unmanaged launcher: %s\n' \
                    "${BURNBAG_USER_LAUNCHER}" >&2
                printf '[HINT] Use --force only if this target may be replaced.\n' >&2
                return 1
            fi
            printf '[WARNING] Replacing unmanaged launcher by explicit --force: %s\n' \
                "${BURNBAG_USER_LAUNCHER}" >&2
        fi
    fi

    install -d -m 0755 "${BURNBAG_USER_BIN_DIR}"
    burnbag_temp_launcher="$(mktemp "${BURNBAG_USER_BIN_DIR}/.burnbag-launcher.XXXXXXXX")"
    {
        printf '#!/usr/bin/bash\n'
        printf '%s\n' "${BURNBAG_DEV_LAUNCHER_MARKER}"
        printf 'readonly BURNBAG_TARGET=%q\n' "${BURNBAG_PROJECT_ROOT}/burnbag.py"
        printf '%s\n' "if [[ ! -x \"\${BURNBAG_TARGET}\" ]]; then"
        printf '%s\n' "    printf '[ERROR] burnbag development target is unavailable: %s\\n' \"\${BURNBAG_TARGET}\" >&2"
        printf '%s\n' '    exit 1'
        printf '%s\n' 'fi'
        printf '%s\n' "exec \"\${BURNBAG_TARGET}\" \"\$@\""
    } >"${burnbag_temp_launcher}"
    chmod 0755 "${burnbag_temp_launcher}"
    mv -f -- "${burnbag_temp_launcher}" "${BURNBAG_USER_LAUNCHER}"

    hash -r
    burnbag_resolved_command="$(command -v burnbag || true)"
    if [[ "${burnbag_resolved_command}" != "${BURNBAG_USER_LAUNCHER}" ]]; then
        printf '[ERROR] Managed launcher was written, but command lookup selects: %s\n' \
            "${burnbag_resolved_command:-<not found>}" >&2
        printf '[HINT] Ensure %s precedes other launcher directories on PATH, then run hash -r.\n' \
            "${BURNBAG_USER_BIN_DIR}" >&2
        return 1
    fi

    printf '[OK] Bare burnbag commands now select the development checkout: %s\n' \
        "${BURNBAG_USER_LAUNCHER}"
    printf '[INFO] Run hash -r in shells that previously cached another burnbag path.\n'
}

keep_system_command_resolution() {
    local burnbag_resolved_command

    if is_managed_dev_launcher "${BURNBAG_USER_LAUNCHER}"; then
        rm -f -- "${BURNBAG_USER_LAUNCHER}"
        printf '[INFO] Removed managed development launcher: %s\n' \
            "${BURNBAG_USER_LAUNCHER}"
    elif [[ -e "${BURNBAG_USER_LAUNCHER}" || -L "${BURNBAG_USER_LAUNCHER}" ]]; then
        printf '[INFO] Leaving unmanaged user launcher unchanged: %s\n' \
            "${BURNBAG_USER_LAUNCHER}"
    fi

    hash -r
    burnbag_resolved_command="$(command -v burnbag || true)"
    if [[ -n "${burnbag_resolved_command}" ]]; then
        printf '[OK] Bare burnbag command resolution remains: %s\n' \
            "${burnbag_resolved_command}"
    else
        printf '[INFO] No bare burnbag command currently resolves on PATH.\n'
    fi
}

install_dev_mode() {
    local burnbag_dev_bin_dir="${BURNBAG_PROJECT_ROOT}/.local/bin"
    local burnbag_dev_man_dir="${BURNBAG_PROJECT_ROOT}/.local/share/man/man1"

    select_user_home
    printf '[INFO] Development launcher user home: %s\n' \
        "${BURNBAG_EFFECTIVE_USER_HOME}"
    resolve_dev_command_mode

    install -d -m 0755 "${burnbag_dev_bin_dir}" "${burnbag_dev_man_dir}"
    ensure_dev_link \
        "${BURNBAG_PROJECT_ROOT}/burnbag.py" "${burnbag_dev_bin_dir}/burnbag"
    ensure_dev_link \
        "${BURNBAG_PROJECT_ROOT}/burnbag.1" "${burnbag_dev_man_dir}/burnbag.1"

    printf '[OK] Repository-local development target: %s\n' \
        "${burnbag_dev_bin_dir}/burnbag"
    printf '[INFO] Add %s to MANPATH for man-page discovery.\n' \
        "${BURNBAG_PROJECT_ROOT}/.local/share/man"

    if [[ "${BURNBAG_RESOLVED_DEV_COMMAND}" == "local" ]]; then
        write_managed_dev_launcher
    else
        keep_system_command_resolution
    fi
}

main() {
    BURNBAG_CHECK_ONLY=false
    BURNBAG_DESTDIR=""
    BURNBAG_DEV_COMMAND="${BURNBAG_DEV_LAUNCHER_MODE:-prompt}"
    BURNBAG_DEV_COMMAND_WAS_SET=false
    BURNBAG_EFFECTIVE_USER_HOME=""
    BURNBAG_FORCE=false
    BURNBAG_MODE="standard"
    BURNBAG_PREFIX="/usr/local"
    BURNBAG_PREFIX_WAS_SET=false
    BURNBAG_SKIP_PREREQUISITES=false
    BURNBAG_USER_BIN_DIR=""
    BURNBAG_USER_HOME=""
    BURNBAG_USER_HOME_WAS_SET=false
    BURNBAG_USER_LAUNCHER=""
    BURNBAG_RESOLVED_DEV_COMMAND=""

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
            --dev-command)
                if [[ $# -lt 2 ]]; then
                    printf '[ERROR] --dev-command requires a value.\n' >&2
                    return 2
                fi
                BURNBAG_DEV_COMMAND="$2"
                BURNBAG_DEV_COMMAND_WAS_SET=true
                shift 2
                ;;
            --dev-command=*)
                BURNBAG_DEV_COMMAND="${1#--dev-command=}"
                BURNBAG_DEV_COMMAND_WAS_SET=true
                shift
                ;;
            --force)
                BURNBAG_FORCE=true
                shift
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
            --user-home)
                if [[ $# -lt 2 ]]; then
                    printf '[ERROR] --user-home requires a value.\n' >&2
                    return 2
                fi
                BURNBAG_USER_HOME="$2"
                BURNBAG_USER_HOME_WAS_SET=true
                shift 2
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
        if [[ ${EUID} -eq 0 ]]; then
            printf '[ERROR] --mode dev must run as the intended non-root user.\n' >&2
            return 2
        fi
        if [[ -n "${BURNBAG_DESTDIR}" ]]; then
            printf '[ERROR] --destdir cannot be combined with --mode dev.\n' >&2
            return 2
        fi
        if [[ "${BURNBAG_PREFIX_WAS_SET}" == true ]]; then
            printf '[ERROR] --prefix cannot be combined with --mode dev.\n' >&2
            return 2
        fi
    else
        if [[ "${BURNBAG_DEV_COMMAND_WAS_SET}" == true ]]; then
            printf '[ERROR] --dev-command requires --mode dev.\n' >&2
            return 2
        fi
        if [[ "${BURNBAG_FORCE}" == true ]]; then
            printf '[ERROR] --force is only supported with --mode dev.\n' >&2
            return 2
        fi
        if [[ "${BURNBAG_USER_HOME_WAS_SET}" == true ]]; then
            printf '[ERROR] --user-home requires --mode dev.\n' >&2
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
