#!/usr/bin/bash

set -Eeuo pipefail

BURNBAG_INSTALL_ACTION="validating installation options"
BURNBAG_TEMP_LAUNCHER=""

cleanup_temporary_launcher() {
    if [[ -n "${BURNBAG_TEMP_LAUNCHER}" ]]; then
        if ! rm -f -- "${BURNBAG_TEMP_LAUNCHER}"; then
            printf '[WARNING] Could not remove temporary launcher: %s\n' \
                "${BURNBAG_TEMP_LAUNCHER}" >&2
        fi
    fi
}

report_install_failure() {
    local burnbag_status="$1"
    printf '[ERROR] Installer failed while %s (exit %s). Earlier steps may have completed; resolve the error above and rerun.\n' \
        "${BURNBAG_INSTALL_ACTION}" "${burnbag_status}" >&2
    exit "${burnbag_status}"
}

trap cleanup_temporary_launcher EXIT
trap 'report_install_failure "$?"' ERR

BURNBAG_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BURNBAG_PROJECT_ROOT
readonly BURNBAG_PREREQUISITE_INSTALLER="${BURNBAG_PROJECT_ROOT}/scripts/install_prerequisites.sh"
readonly BURNBAG_SERVICE_INSTALLER="${BURNBAG_PROJECT_ROOT}/scripts/install_services.py"
readonly BURNBAG_DEV_LAUNCHER_MARKER="# burnbag-managed-dev-launcher"
readonly BURNBAG_DEV_LAUNCHER_MODE_ENV="BURNBAG_DEV_LAUNCHER_MODE"

usage() {
    cat <<'EOF'
Usage: install.sh [OPTIONS]

Install burnbag, the GTK 4 history viewer and their manual pages, and a system service. The default prefix is /usr/local.

Options:
  --check                 Verify sources and prerequisites without installing.
  --destdir DIR           Stage beneath absolute non-root DIR without sudo or mandb.
  --dev-command MODE      In dev mode, select prompt, local, or system command
                          resolution (default: prompt).
  --force                 Allow replacement of an unmanaged user launcher.
  --install-user-service  Select the login user's service instead of the system service.
  --mode MODE             Select standard or repo-local dev mode (default: standard).
  --prefix DIR            Install beneath absolute DIR (default: /usr/local).
  --skip-prerequisites    Do not check or install prerequisite packages.
  --user-home DIR         Use absolute DIR for the dev launcher or user service.
  -h, --help              Show this help text.

For non-interactive dev setup, BURNBAG_DEV_LAUNCHER_MODE may select local or
system explicitly. Without an explicit selection, command resolution is left
unchanged. Declining the interactive prompt or reaching EOF also preserves it.
Paths must not contain parent-directory (..) components. Staging refuses
symlinks that lead outside DIR; file targets must not be directories or symlinks.
Staging checks prerequisites without installing host packages.
New services are enabled and started; updates preserve stopped/disabled state.
Dev mode deploys a system-daemon copy while the CLI follows the checkout.
Dev plus --install-user-service runs the daemon from the checkout. User lingering
is never changed. Use uninstall.sh to remove managed artifacts and retain history.
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
    case "/${burnbag_path#/}/" in
        */../*)
            printf '[ERROR] %s must not contain parent-directory (..) components: %s\n' \
                "${burnbag_option_name}" "${burnbag_path}" >&2
            return 2
            ;;
    esac
}

validate_standard_targets() {
    local burnbag_target
    local burnbag_resolved_target

    for burnbag_target in \
        "${BURNBAG_BIN_DIR}/burnbag" "${BURNBAG_BIN_DIR}/burnbag-viewer" \
        "${BURNBAG_BIN_DIR}/burnbag-viewerctl" "${BURNBAG_MAN_DIR}/burnbag.1" \
        "${BURNBAG_MAN_DIR}/burnbag-viewer.1"; do
        if [[ -d "${burnbag_target}" || -L "${burnbag_target}" ]]; then
            printf '[ERROR] Installation target must not be a directory or symlink: %s\n' \
                "${burnbag_target}" >&2
            return 2
        fi
        if [[ -n "${BURNBAG_DESTDIR}" ]]; then
            burnbag_resolved_target="$(realpath -m -- "${burnbag_target}")"
            if [[ "${burnbag_resolved_target}" != "${BURNBAG_DESTDIR}/"* ]]; then
                printf '[ERROR] Installation target escapes --destdir through a symlink: %s\n' \
                    "${burnbag_target}" >&2
                return 2
            fi
        fi
    done
}

run_privileged() {
    if [[ ${EUID} -eq 0 || -n "${BURNBAG_DESTDIR}" || "${BURNBAG_USER_PREFIX}" == true ]]; then
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
    if [[ -z "${BURNBAG_USER_HOME}" ]]; then
        case "${BURNBAG_EFFECTIVE_USER_HOME}" in
            */.claude-home|*/.codex-home|*/claude-home|*/codex-home|\
            "${BURNBAG_PROJECT_ROOT}/.local"|"${BURNBAG_PROJECT_ROOT}/.local/"*)
                printf '[ERROR] HOME is an isolated assistant environment: %s\n' \
                    "${burnbag_selected_home}" >&2
                printf '[HINT] Rerun with --user-home /absolute/operator/home.\n' >&2
                return 1
                ;;
        esac
    fi
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
        burnbag_candidate="${burnbag_path_entry}/${1:-burnbag}"
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
        BURNBAG_RESOLVED_DEV_COMMAND="unchanged"
        return 0
    fi

    burnbag_prompt="Use this checkout for burnbag, burnbag-viewer and burnbag-viewerctl? [y/N]: "
    if [[ -z "${burnbag_alternate}" ]]; then
        burnbag_prompt="Install managed user launchers for burnbag, burnbag-viewer and burnbag-viewerctl? [y/N]: "
    fi
    if ! read -r -p "${burnbag_prompt}" burnbag_response; then
        printf '\n[INFO] No response received; leaving burnbag command resolution unchanged.\n'
        BURNBAG_RESOLVED_DEV_COMMAND="unchanged"
        return 0
    fi
    case "${burnbag_response}" in
        y|Y|yes|YES|Yes)
            BURNBAG_RESOLVED_DEV_COMMAND="local"
            ;;
        *)
            BURNBAG_RESOLVED_DEV_COMMAND="unchanged"
            ;;
    esac
}

write_managed_dev_launcher() {
    local burnbag_command="${1:-burnbag}"
    local burnbag_target="${2:-burnbag.py}"
    local BURNBAG_USER_LAUNCHER="${BURNBAG_USER_BIN_DIR}/${burnbag_command}"
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
    if ! user_bin_precedes_other_burnbag "${burnbag_command}"; then
        printf '[ERROR] User launcher directory does not precede the current burnbag command: %s\n' \
            "${BURNBAG_USER_BIN_DIR}" >&2
        printf '[HINT] Move it earlier on PATH before selecting local dev command resolution.\n' >&2
        return 1
    fi

    if [[ -d "${BURNBAG_USER_LAUNCHER}" ]]; then
        printf '[ERROR] Refusing to replace a launcher directory, including with --force: %s\n' \
            "${BURNBAG_USER_LAUNCHER}" >&2
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

    BURNBAG_INSTALL_ACTION="writing the managed user launcher"
    if [[ ! -d "${BURNBAG_USER_BIN_DIR}" ]]; then
        install -d -m 0755 "${BURNBAG_USER_BIN_DIR}"
    fi
    BURNBAG_TEMP_LAUNCHER="$(mktemp "${BURNBAG_USER_BIN_DIR}/.burnbag-launcher.XXXXXXXX")"
    {
        printf '#!/usr/bin/bash\n'
        printf '%s\n' "${BURNBAG_DEV_LAUNCHER_MARKER}"
        printf 'readonly BURNBAG_TARGET=%q\n' "${BURNBAG_PROJECT_ROOT}/${burnbag_target}"
        printf '%s\n' "if [[ ! -x \"\${BURNBAG_TARGET}\" ]]; then"
        printf '%s\n' "    printf '[ERROR] burnbag development target is unavailable: %s\\n' \"\${BURNBAG_TARGET}\" >&2"
        printf '%s\n' '    exit 1'
        printf '%s\n' 'fi'
        printf '%s\n' "exec \"\${BURNBAG_TARGET}\" \"\$@\""
    } >"${BURNBAG_TEMP_LAUNCHER}"
    chmod 0755 "${BURNBAG_TEMP_LAUNCHER}"
    mv -fT -- "${BURNBAG_TEMP_LAUNCHER}" "${BURNBAG_USER_LAUNCHER}"
    BURNBAG_TEMP_LAUNCHER=""

    hash -r
    burnbag_resolved_command="$(command -v "${burnbag_command}" || true)"
    if [[ "${burnbag_resolved_command}" != "${BURNBAG_USER_LAUNCHER}" ]]; then
        printf '[ERROR] Managed launcher was written, but command lookup selects: %s\n' \
            "${burnbag_resolved_command:-<not found>}" >&2
        printf '[HINT] Ensure %s precedes other launcher directories on PATH, then run hash -r.\n' \
            "${BURNBAG_USER_BIN_DIR}" >&2
        return 1
    fi

    printf '[OK] Bare %s commands now select the development checkout: %s\n' \
        "${burnbag_command}" "${BURNBAG_USER_LAUNCHER}"
    printf '[INFO] Run hash -r in shells that previously cached another burnbag path.\n'
}

keep_system_command_resolution() {
    local burnbag_command="${1:-burnbag}"
    local BURNBAG_USER_LAUNCHER="${BURNBAG_USER_BIN_DIR}/${burnbag_command}"
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
    burnbag_resolved_command="$(command -v "${burnbag_command}" || true)"
    if [[ -n "${burnbag_resolved_command}" ]]; then
        printf '[OK] Bare %s command resolution remains: %s\n' \
            "${burnbag_command}" "${burnbag_resolved_command}"
    else
        printf '[INFO] No bare %s command currently resolves on PATH.\n' "${burnbag_command}"
    fi
}

install_dev_mode() {
    local burnbag_dev_bin_dir="${BURNBAG_PROJECT_ROOT}/.local/bin"
    local burnbag_dev_man_dir="${BURNBAG_PROJECT_ROOT}/.local/share/man/man1"

    printf '[INFO] Development launcher user home: %s\n' \
        "${BURNBAG_EFFECTIVE_USER_HOME}"
    resolve_dev_command_mode

    BURNBAG_INSTALL_ACTION="creating repository-local development links"
    local burnbag_dev_directory
    for burnbag_dev_directory in "${burnbag_dev_bin_dir}" "${burnbag_dev_man_dir}"; do
        if [[ ! -d "${burnbag_dev_directory}" ]]; then
            install -d -m 0755 "${burnbag_dev_directory}"
        fi
    done
    ensure_dev_link \
        "${BURNBAG_PROJECT_ROOT}/burnbag.py" "${burnbag_dev_bin_dir}/burnbag"
    ensure_dev_link \
        "${BURNBAG_PROJECT_ROOT}/burnbag_viewer.py" "${burnbag_dev_bin_dir}/burnbag-viewer"
    ensure_dev_link \
        "${BURNBAG_PROJECT_ROOT}/burnbag_viewerctl.py" "${burnbag_dev_bin_dir}/burnbag-viewerctl"
    ensure_dev_link \
        "${BURNBAG_PROJECT_ROOT}/burnbag.1" "${burnbag_dev_man_dir}/burnbag.1"
    ensure_dev_link \
        "${BURNBAG_PROJECT_ROOT}/burnbag-viewer.1" "${burnbag_dev_man_dir}/burnbag-viewer.1"

    printf '[OK] Repository-local development target: %s\n' \
        "${burnbag_dev_bin_dir}/burnbag"
    printf '[INFO] Add %s to MANPATH for man-page discovery.\n' \
        "${BURNBAG_PROJECT_ROOT}/.local/share/man"

    if [[ "${BURNBAG_RESOLVED_DEV_COMMAND}" == "local" ]]; then
        # Validate the whole command family before replacing any user launcher.
        local burnbag_command burnbag_launcher
        for burnbag_command in burnbag burnbag-viewer burnbag-viewerctl; do
            burnbag_launcher="${BURNBAG_USER_BIN_DIR}/${burnbag_command}"
            if [[ -d "${burnbag_launcher}" ]]; then
                printf '[ERROR] Refusing to replace a launcher directory: %s\n' "${burnbag_launcher}" >&2
                return 1
            fi
            if [[ -e "${burnbag_launcher}" || -L "${burnbag_launcher}" ]]; then
                if ! is_managed_dev_launcher "${burnbag_launcher}" && [[ "${BURNBAG_FORCE}" != true ]]; then
                    printf '[ERROR] Refusing to replace unmanaged launcher: %s\n' "${burnbag_launcher}" >&2
                    return 1
                fi
            fi
            if ! user_bin_precedes_other_burnbag "${burnbag_command}"; then
                printf '[ERROR] User launcher directory does not precede the current %s command: %s\n' "${burnbag_command}" "${BURNBAG_USER_BIN_DIR}" >&2
                return 1
            fi
        done
        write_managed_dev_launcher burnbag burnbag.py
        write_managed_dev_launcher burnbag-viewer burnbag_viewer.py
        write_managed_dev_launcher burnbag-viewerctl burnbag_viewerctl.py
    elif [[ "${BURNBAG_RESOLVED_DEV_COMMAND}" == "system" ]]; then
        BURNBAG_INSTALL_ACTION="restoring system command resolution"
        keep_system_command_resolution burnbag
        keep_system_command_resolution burnbag-viewer
        keep_system_command_resolution burnbag-viewerctl
    else
        printf '[INFO] Existing user launcher and command resolution were left unchanged.\n'
    fi
}

main() {
    BURNBAG_CHECK_ONLY=false
    BURNBAG_DESTDIR=""
    BURNBAG_DESTDIR_WAS_SET=false
    BURNBAG_DEV_COMMAND="${BURNBAG_DEV_LAUNCHER_MODE:-prompt}"
    BURNBAG_DEV_COMMAND_WAS_SET=false
    BURNBAG_EFFECTIVE_USER_HOME=""
    BURNBAG_FORCE=false
    BURNBAG_INSTALL_USER_SERVICE=false
    BURNBAG_MODE="standard"
    BURNBAG_PREFIX="/usr/local"
    BURNBAG_PREFIX_WAS_SET=false
    BURNBAG_SKIP_PREREQUISITES=false
    BURNBAG_USER_BIN_DIR=""
    BURNBAG_USER_HOME=""
    BURNBAG_USER_HOME_WAS_SET=false
    BURNBAG_USER_LAUNCHER=""
    BURNBAG_USER_PREFIX=false
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
                BURNBAG_DESTDIR_WAS_SET=true
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
            --install-user-service)
                BURNBAG_INSTALL_USER_SERVICE=true
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
        case "${BURNBAG_DEV_COMMAND}" in
            prompt|local|system) ;;
            *)
                printf '[ERROR] Dev command mode must be prompt, local, or system: %s\n' \
                    "${BURNBAG_DEV_COMMAND}" >&2
                return 2
                ;;
        esac
        if [[ ${EUID} -eq 0 ]]; then
            printf '[ERROR] --mode dev must run as the intended non-root user.\n' >&2
            return 2
        fi
        if [[ "${BURNBAG_DESTDIR_WAS_SET}" == true ]]; then
            printf '[ERROR] --destdir cannot be combined with --mode dev.\n' >&2
            return 2
        fi
        if [[ "${BURNBAG_PREFIX_WAS_SET}" == true ]]; then
            printf '[ERROR] --prefix cannot be combined with --mode dev.\n' >&2
            return 2
        fi
        if [[ "${BURNBAG_USER_HOME_WAS_SET}" == true ]]; then
            require_absolute_path --user-home "${BURNBAG_USER_HOME}"
        fi
        select_user_home
    else
        if [[ "${BURNBAG_DEV_COMMAND_WAS_SET}" == true ]]; then
            printf '[ERROR] --dev-command requires --mode dev.\n' >&2
            return 2
        fi
        if [[ "${BURNBAG_FORCE}" == true ]]; then
            printf '[ERROR] --force is only supported with --mode dev.\n' >&2
            return 2
        fi
        if [[ "${BURNBAG_USER_HOME_WAS_SET}" == true && "${BURNBAG_INSTALL_USER_SERVICE}" != true ]]; then
            printf '[ERROR] --user-home requires --mode dev.\n' >&2
            return 2
        fi
        if [[ "${BURNBAG_INSTALL_USER_SERVICE}" == true ]]; then
            select_user_home
        fi
    fi

    require_absolute_path --prefix "${BURNBAG_PREFIX}"
    if [[ "${BURNBAG_DESTDIR_WAS_SET}" == true ]]; then
        require_absolute_path --destdir "${BURNBAG_DESTDIR}"
        BURNBAG_DESTDIR="$(realpath -m -- "${BURNBAG_DESTDIR}")"
        if [[ "${BURNBAG_DESTDIR}" == "/" ]]; then
            printf '[ERROR] --destdir must not be the filesystem root.\n' >&2
            return 2
        fi
    fi

    BURNBAG_INSTALL_ROOT="${BURNBAG_DESTDIR%/}${BURNBAG_PREFIX%/}"
    BURNBAG_BIN_DIR="${BURNBAG_INSTALL_ROOT}/bin"
    BURNBAG_MAN_DIR="${BURNBAG_INSTALL_ROOT}/share/man/man1"
    if [[ "${BURNBAG_INSTALL_USER_SERVICE}" == true && "${BURNBAG_PREFIX}" == "${BURNBAG_EFFECTIVE_USER_HOME}/"* ]]; then
        BURNBAG_USER_PREFIX=true
    fi
    if [[ "${BURNBAG_MODE}" == "standard" ]]; then
        validate_standard_targets
    fi

    local burnbag_source
    for burnbag_source in \
        "${BURNBAG_PROJECT_ROOT}/burnbag.py" \
        "${BURNBAG_PROJECT_ROOT}/burnbag.1" \
        "${BURNBAG_PROJECT_ROOT}/burnbag_viewer.py" \
        "${BURNBAG_PROJECT_ROOT}/burnbag_viewer_data.py" \
        "${BURNBAG_PROJECT_ROOT}/burnbag_viewerctl.py" \
        "${BURNBAG_PROJECT_ROOT}/burnbag-viewer.1" \
        "${BURNBAG_PREREQUISITE_INSTALLER}" \
        "${BURNBAG_SERVICE_INSTALLER}"; do
        if [[ ! -f "${burnbag_source}" ]]; then
            printf '[ERROR] Required source file not found: %s\n' \
                "${burnbag_source}" >&2
            return 1
        fi
    done

    local -a burnbag_service_options=(--source "${BURNBAG_PROJECT_ROOT}" --prefix "${BURNBAG_PREFIX}" --mode "${BURNBAG_MODE}")
    if [[ "${BURNBAG_INSTALL_USER_SERVICE}" == true ]]; then
        burnbag_service_options+=(--user-service)
    else
        burnbag_service_options+=(--system-service)
    fi
    if [[ -n "${BURNBAG_EFFECTIVE_USER_HOME}" ]]; then
        burnbag_service_options+=(--user-home "${BURNBAG_EFFECTIVE_USER_HOME}")
    fi
    if [[ -n "${BURNBAG_DESTDIR}" ]]; then
        burnbag_service_options+=(--destdir "${BURNBAG_DESTDIR}")
    fi
    BURNBAG_INSTALL_ACTION="validating service installation sources and destinations"
    /usr/bin/python3 -B "${BURNBAG_SERVICE_INSTALLER}" check "${burnbag_service_options[@]}"

    if [[ "${BURNBAG_SKIP_PREREQUISITES}" == false ]]; then
        BURNBAG_INSTALL_ACTION="checking or installing prerequisite packages"
        if [[ "${BURNBAG_CHECK_ONLY}" == true || "${BURNBAG_DESTDIR_WAS_SET}" == true ]]; then
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
        if [[ "${BURNBAG_INSTALL_USER_SERVICE}" == true ]]; then
            BURNBAG_INSTALL_ACTION="installing the development user service"
            /usr/bin/python3 -B "${BURNBAG_SERVICE_INSTALLER}" install "${burnbag_service_options[@]}"
            return 0
        fi
    fi

    BURNBAG_INSTALL_ACTION="installing the executable and manual page"
    local burnbag_install_directory
    for burnbag_install_directory in "${BURNBAG_BIN_DIR}" "${BURNBAG_MAN_DIR}"; do
        if [[ ! -d "${burnbag_install_directory}" ]]; then
            run_privileged install -d -m 0755 "${burnbag_install_directory}"
        fi
    done
    validate_standard_targets
    run_privileged install -T -m 0755 \
        "${BURNBAG_PROJECT_ROOT}/burnbag.py" "${BURNBAG_BIN_DIR}/burnbag"
    run_privileged install -T -m 0644 \
        "${BURNBAG_PROJECT_ROOT}/burnbag.1" "${BURNBAG_MAN_DIR}/burnbag.1"

    BURNBAG_INSTALL_ACTION="installing support modules and the selected service"
    /usr/bin/python3 -B "${BURNBAG_SERVICE_INSTALLER}" install "${burnbag_service_options[@]}"

    if [[ -z "${BURNBAG_DESTDIR}" ]] && command -v mandb >/dev/null 2>&1; then
        BURNBAG_INSTALL_ACTION="updating the manual-page index"
        run_privileged mandb --quiet
    fi

    printf '[OK] Installed burnbag and its GTK 4 history viewer to %s, with manuals under %s.\n' \
        "${BURNBAG_BIN_DIR}" "${BURNBAG_MAN_DIR}"
}

main "$@"
