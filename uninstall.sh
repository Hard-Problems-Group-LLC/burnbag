#!/usr/bin/bash
set -Eeuo pipefail
burnbag_uninstall_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -f "${burnbag_uninstall_dir}/scripts/install_services.py" ]]; then
    exec /usr/bin/python3 -B "${burnbag_uninstall_dir}/scripts/install_services.py" uninstall "$@"
fi
burnbag_uninstall_prefix="$(cd -- "${burnbag_uninstall_dir}/.." && pwd -P)"
exec /usr/bin/python3 -B "${burnbag_uninstall_prefix}/lib/burnbag/install_services.py" uninstall --prefix "${burnbag_uninstall_prefix}" "$@"
