#!/usr/bin/python3
"""Install or remove burnbag's scoped service and tracked application artifacts.

The shell installer owns prerequisite and development-launcher selection. This
helper never modifies dependencies, lingering, unrelated units, or private home
permissions. Staging operates on files only, including account declarations.
"""

from __future__ import annotations

import argparse
import contextlib
import errno
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import uuid
from typing import Any, Optional


class InstallError(Exception):
    """A bounded, actionable installation failure."""


def absolute(value: str, label: str) -> Path:
    if not value or not Path(value).is_absolute() or ".." in Path(value).parts:
        raise InstallError(f"{label} requires an absolute path without '..': {value!r}")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise InstallError(f"{label} must not contain control characters")
    return Path(value)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def systemd_quote(path: Path | str, *, expand_environment: bool = True) -> str:
    # Unit specifiers and environment substitution have their own escaping.
    text = str(path).replace("%", "%%")
    if expand_environment:
        text = text.replace("$", "$$")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class ServiceInstaller:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.prefix = absolute(args.prefix, "--prefix")
        self.stage = absolute(args.destdir, "--destdir").resolve() if args.destdir else None
        if self.stage == Path("/"):
            raise InstallError("--destdir must not be the filesystem root")
        self.source = absolute(args.source, "--source").resolve() if args.source else None
        self.user_home = absolute(args.user_home or os.environ.get("HOME", ""), "--user-home")
        state_home = os.environ.get("XDG_STATE_HOME")
        config_home = os.environ.get("XDG_CONFIG_HOME")
        if args.user_home and str(self.user_home) != os.environ.get("HOME"):
            state_home = None
            config_home = None
        self.user_state = absolute(state_home, "XDG_STATE_HOME") if state_home else self.user_home / ".local/state"
        self.user_config = absolute(config_home, "XDG_CONFIG_HOME") if config_home else self.user_home / ".config"
        self.user_id = os.getuid()
        self.scope = "user" if args.user_service else "system"
        self.dev = args.mode == "dev"

    def path(self, logical: Path) -> Path:
        target = self.stage / str(logical).lstrip("/") if self.stage else logical
        if self.stage and not target.resolve().is_relative_to(self.stage):
            raise InstallError(f"Installation target escapes --destdir through a symlink: {target}")
        return target

    def validate_target(self, logical: Path, *, allow_link: bool = False) -> Path:
        target = self.path(logical)
        if target.is_dir() or (target.is_symlink() and not allow_link):
            raise InstallError(f"Installation target must not be a directory or symlink: {target}")
        return target

    def validate_privileged_ancestors(self, logical: Path) -> None:
        """Never publish privileged code through operator-controlled directories."""
        if not self.privileged(logical):
            return
        parent = logical.parent
        resolved = parent.resolve()
        for directory in dict.fromkeys((parent, *parent.parents, resolved, *resolved.parents)):
            try:
                state = directory.stat()
            except FileNotFoundError:
                continue
            if state.st_uid != 0 or state.st_mode & 0o022:
                raise InstallError(f"System installation requires root-owned directories without group/other write access: {directory}")

    def privileged(self, logical: Path) -> bool:
        if self.stage or (self.scope == "user" and self.dev) or logical.is_relative_to(self.user_home):
            return False
        return self.scope == "system" or logical.is_relative_to(self.prefix)

    def run(self, arguments: list[str], *, privileged: bool = False, timeout: int = 45) -> subprocess.CompletedProcess[str]:
        command = list(arguments)
        if privileged and os.geteuid() != 0:
            if not shutil.which("sudo"):
                raise InstallError("sudo is required for system installation or removal")
            command.insert(0, "sudo")
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InstallError(f"Could not run {arguments[0]}: {exc}") from exc
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise InstallError(f"{' '.join(arguments)} failed (exit {result.returncode}): {detail}")
        return result

    def control(self, action: str) -> None:
        self.run(["systemctl", "--user" if self.scope == "user" else "--system", action, "burnbag.service"],
                 privileged=self.scope == "system")

    def reload(self) -> None:
        self.run(["systemctl", "--user" if self.scope == "user" else "--system", "daemon-reload"],
                 privileged=self.scope == "system")

    def state(self, scope: Optional[str] = None) -> dict[str, str]:
        result = self.run(["systemctl", "--user" if (scope or self.scope) == "user" else "--system",
                           "show", "burnbag.service", "--property=LoadState,ActiveState,UnitFileState,FragmentPath", "--no-pager"], timeout=5)
        return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)

    def manifest_path(self, scope: Optional[str] = None, *, dev: Optional[bool] = None) -> Path:
        selected = scope or self.scope
        if selected == "user" and (self.dev if dev is None else dev):
            return self.user_state / "burnbag/install-user.json"
        suffix = "system" if selected == "system" else f"user-{self.user_id}"
        return self.prefix / f"lib/burnbag/install-{suffix}.json"

    def unit_path(self, scope: Optional[str] = None) -> Path:
        if (scope or self.scope) == "user":
            return self.user_config / "systemd/user/burnbag.service"
        return self.prefix / "lib/systemd/system/burnbag.service"

    def source_bytes(self, relative: str) -> bytes:
        if self.source is None:
            raise InstallError("An installation requires --source")
        try:
            return (self.source / relative).read_bytes()
        except OSError as exc:
            raise InstallError(f"Required installation source unavailable: {relative}: {exc}") from exc

    def plan(self) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        if self.scope == "system" and not self.stage:
            for directory in (self.prefix, *self.prefix.parents):
                try:
                    stat = directory.stat()
                except FileNotFoundError:
                    continue
                if stat.st_uid != 0 or stat.st_mode & 0o022:
                    raise InstallError(f"System installation requires root-owned directories without group/other write access: {directory}")
            self.ensure_account(create=False)

        def add(path: Path, data: bytes, mode: int = 0o644, shared: bool = False) -> None:
            self.validate_target(path)
            self.validate_privileged_ancestors(path)
            files.append({"path": str(path), "data": data, "mode": mode, "sha256": digest(data), "shared": shared})

        if not (self.dev and self.scope == "user"):
            for relative, target, mode in (
                ("burnbag.py", "bin/burnbag", 0o755), ("burnbag.1", "share/man/man1/burnbag.1", 0o644),
                ("burnbag_viewer.py", "bin/burnbag-viewer", 0o755),
                ("burnbag_viewerctl.py", "bin/burnbag-viewerctl", 0o755),
                ("burnbag-viewer.1", "share/man/man1/burnbag-viewer.1", 0o644),
                ("uninstall.sh", "bin/burnbag-uninstall", 0o755),
                ("scripts/install_services.py", "lib/burnbag/install_services.py", 0o644),
                ("burnbag_history.py", "lib/burnbag/burnbag_history.py", 0o644),
                ("burnbag_service.py", "lib/burnbag/burnbag_service.py", 0o644),
                ("burnbag_graph.py", "lib/burnbag/burnbag_graph.py", 0o644),
                ("burnbag_duration.py", "lib/burnbag/burnbag_duration.py", 0o644),
                ("burnbag_viewer_data.py", "lib/burnbag/burnbag_viewer_data.py", 0o644),
            ):
                add(self.prefix / target, self.source_bytes(relative), mode, shared=True)

        executable = self.source / "burnbag.py" if self.dev and self.source else self.prefix / "bin/burnbag"
        command = systemd_quote(executable)
        unit = self.source_bytes(f"systemd/burnbag-{self.scope}.service").decode("utf-8")
        if self.dev and self.scope == "system":
            if ":" in str(self.source):
                raise InstallError("A system dev checkout path cannot contain ':' (systemd bind-mount separator)")
            # PID 1 binds the checkout into this unit's namespace. This works
            # with private home ancestors without exposing or chmodding them.
            # Bind the directory, not files: atomic editor replacements remain
            # visible when the collector next starts.
            mount = Path("/run/burnbag-dev/source")
            # The separator must be outside the quotes: systemd otherwise
            # interprets the entire mapping as a single source path.
            binding = (systemd_quote(self.source, expand_environment=False) + ":" +
                       systemd_quote(mount, expand_environment=False))
            unit = unit.replace("[Unit]\n", "[Unit]\nRequiresMountsFor=" +
                                systemd_quote(self.source, expand_environment=False) + "\n")
            unit = unit.replace("[Service]\n", "[Service]\nRuntimeDirectory=burnbag-dev\n"
                                "RuntimeDirectoryMode=0755\nBindReadOnlyPaths=" + binding + "\n")
            command = '/usr/bin/python3 -B ' + systemd_quote(mount / "burnbag.py")
        if self.scope == "user":
            state = str(self.user_state).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
            unit = unit.replace("[Service]\n", '[Service]\nEnvironment="XDG_STATE_HOME=' + state + '"\n')
        rendered_unit = unit.replace("@EXECUTABLE@", command).encode("utf-8")
        add(self.unit_path(), rendered_unit)
        if self.scope == "system":
            if self.prefix not in {Path("/usr"), Path("/usr/local")}:
                # A custom application prefix is outside systemd's lookup
                # path. Publish a tracked unit in its administrator directory.
                add(Path("/etc/systemd/system/burnbag.service"), rendered_unit)
            add(self.prefix / "lib/sysusers.d/burnbag.conf", self.source_bytes("systemd/burnbag.sysusers"))
            add(Path("/usr/share/polkit-1/rules.d/49-burnbag-delay.rules"), self.source_bytes("systemd/49-burnbag-delay.rules"))
        elif self.dev and self.source:
            # The checkout link supports explicit MANPATH use. Also publish a
            # regular user manual so this entirely unprivileged installation
            # has documentation in the user's normal manual-page tree.
            add(self.user_home / ".local/share/man/man1/burnbag.1",
                self.source_bytes("burnbag.1"), shared=True)
            add(self.user_home / ".local/share/man/man1/burnbag-viewer.1",
                self.source_bytes("burnbag-viewer.1"), shared=True)
            wrapper = "#!/usr/bin/bash\n# burnbag-managed uninstaller\nexec /usr/bin/python3 -B " + shlex.quote(str(self.source / "scripts/install_services.py")) + " uninstall --user-service \"$@\"\n"
            add(self.user_home / ".local/bin/burnbag-uninstall", wrapper.encode("utf-8"), 0o755)
        self.validate_target(self.manifest_path())
        self.validate_privileged_ancestors(self.manifest_path())
        for item in files:
            path = self.path(Path(item["path"]))
            if path.is_file() and (path.name == "burnbag.service" or path.suffix == ".rules"):
                if b"burnbag-managed" not in path.read_bytes():
                    raise InstallError(f"Refusing to replace an unmanaged service or policy file: {path}")
        return files

    def write(self, logical: Path, data: bytes, mode: int) -> None:
        target = self.validate_target(logical)
        self.validate_privileged_ancestors(logical)
        privileged = self.privileged(logical)
        temporary = target.with_name(target.name + ".burnbag-" + uuid.uuid4().hex)
        with tempfile.TemporaryDirectory(prefix="burnbag-install-") as workspace:
            source = Path(workspace) / "content"
            source.write_bytes(data)
            try:
                directory_mode = "0700" if logical.parent == self.user_state / "burnbag" else "0755"
                if not target.parent.is_dir():
                    self.run(["install", "-d", "-m", directory_mode, str(target.parent)], privileged=privileged)
                self.validate_target(logical)
                self.validate_privileged_ancestors(logical)
                self.run(["install", "-m", f"{mode:o}", str(source), str(temporary)], privileged=privileged)
                self.run(["mv", "-T", "--", str(temporary), str(target)], privileged=privileged)
            finally:
                if temporary.exists():
                    self.run(["rm", "-f", "--", str(temporary)], privileged=privileged)

    def ensure_account(self, *, create: bool = True) -> None:
        try:
            account = pwd.getpwnam("burnbag")
        except KeyError:
            account = None
        if account is not None:
            try:
                group = grp.getgrnam("burnbag")
            except KeyError as exc:
                raise InstallError("Existing burnbag account has no matching burnbag group") from exc
            if account.pw_uid == 0 or account.pw_gid != group.gr_gid or Path(account.pw_shell).name not in {"nologin", "false"}:
                raise InstallError("Existing burnbag account is not a compatible non-login service account")
            return
        if not create:
            return
        declaration = self.path(self.prefix / "lib/sysusers.d/burnbag.conf")
        self.run(["systemd-sysusers", str(declaration)], privileged=True)

    def development_records(self) -> list[dict[str, Any]]:
        if not self.dev or self.source is None:
            return []
        records: list[dict[str, Any]] = []
        for relative, source in (
            (".local/bin/burnbag", "burnbag.py"),
            (".local/bin/burnbag-viewer", "burnbag_viewer.py"),
            (".local/bin/burnbag-viewerctl", "burnbag_viewerctl.py"),
            (".local/share/man/man1/burnbag.1", "burnbag.1"),
            (".local/share/man/man1/burnbag-viewer.1", "burnbag-viewer.1"),
        ):
            target = self.source / relative
            if target.is_symlink() and target.resolve() == self.source / source:
                records.append({"path": str(target), "symlink": os.readlink(target), "shared": True})
        for command in ("burnbag", "burnbag-viewer", "burnbag-viewerctl"):
            launcher = self.user_home / ".local/bin" / command
            if launcher.is_file() and not launcher.is_symlink():
                data = launcher.read_bytes()
                if b"# burnbag-managed-dev-launcher\n" in data and str(self.source).encode() in data:
                    records.append({"path": str(launcher), "sha256": digest(data), "shared": True})
        return records

    def install(self) -> None:
        files = self.plan()
        if self.scope == "user" and not self.stage and os.geteuid() == 0:
            raise InstallError("A user service must be installed as its intended non-root login user")
        if self.scope == "user" and not self.stage:
            login_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
            if self.user_home.resolve() != login_home:
                raise InstallError(f"A user service must target the login user's actual home: {login_home}")
        before: dict[str, str] = {}
        pending_activation = False
        previous_manifest = self.path(self.manifest_path())
        if previous_manifest.is_file():
            try:
                pending_activation = bool(json.loads(previous_manifest.read_text()).get("activation_pending", False))
            except (OSError, ValueError, AttributeError) as exc:
                raise InstallError(f"Cannot read existing installation manifest: {exc}") from exc
        if not self.stage:
            before = self.state()
            try:
                peer = self.state("user" if self.scope == "system" else "system")
            except InstallError:
                peer = {}
            if peer.get("ActiveState") in {"active", "activating", "reloading"}:
                raise InstallError("The other service scope is running; stop it explicitly before installing this scope")
        pending_activation = pending_activation or self.stage is not None or before.get("LoadState") == "not-found"
        for item in files:
            self.write(Path(item["path"]), item["data"], item["mode"])
        manifest = {"version": 1, "scope": self.scope, "mode": self.args.mode or "standard", "prefix": str(self.prefix),
                    "user_home": str(self.user_home), "user_id": self.user_id,
                    "user_state": str(self.user_state),
                    "user_config": str(self.user_config),
                    "activation_pending": pending_activation,
                    "source": str(self.source),
                    "files": [{key: value for key, value in item.items() if key != "data"} for item in files] + self.development_records()}
        manifest_mode = 0o600 if self.scope == "user" and self.manifest_path().is_relative_to(self.user_home) else 0o644
        self.write(self.manifest_path(), (json.dumps(manifest, indent=2) + "\n").encode(), manifest_mode)
        if self.stage:
            print(f"[OK] Staged {self.scope} service and its installation manifest; no host services or accounts changed.")
            return
        if self.scope == "system":
            self.ensure_account()
        self.reload()
        if pending_activation:
            self.control("enable")
            self.control("start")
        elif before.get("ActiveState") in {"active", "activating", "reloading"}:
            self.control("restart")
        if pending_activation:
            manifest["activation_pending"] = False
            self.write(self.manifest_path(), (json.dumps(manifest, indent=2) + "\n").encode(), manifest_mode)
        print(f"[OK] Installed {self.scope} service; existing activation preferences preserved on updates.")
        if self.scope == "user":
            print("[INFO] User lingering was left unchanged; without lingering, collection follows the login session.")

    def find_manifest(self) -> Path:
        candidates = [self.manifest_path("system"), self.manifest_path("user", dev=False), self.manifest_path("user", dev=True)]
        if self.args.system_service:
            candidates = candidates[:1]
        elif self.args.user_service:
            candidates = candidates[1:]
        if self.args.mode is not None:
            candidates = [path for path in candidates if path.name == "install-system.json" or
                          path == self.manifest_path("user", dev=self.dev)]
        existing = [path for path in candidates if self.path(path).is_file()]
        if len(existing) == 1:
            return existing[0]
        if len(existing) > 1 and not self.stage and not (self.args.user_service or self.args.system_service):
            active = []
            for candidate in existing:
                scope = "system" if candidate.name == "install-system.json" else "user"
                try:
                    if self.state(scope).get("ActiveState") == "active":
                        active.append(candidate)
                except InstallError:
                    pass
            if len(active) == 1:
                return active[0]
        if not existing:
            raise InstallError("No managed installation found; select its --prefix, --user-home, and service scope")
        raise InstallError("Multiple managed installations found; specify --system-service or --user-service, the matching --prefix, and --mode standard|dev when both user modes exist")

    @contextlib.contextmanager
    def foreground_purge_guard(self) -> Any:
        """Keep fallback collection from opening a database being removed.

        The collector binds this ownership socket before opening SQLite and
        retains it until its writer closes. Reservation therefore covers both
        an existing foreground run and a new fallback after service shutdown.
        """
        if self.stage or self.scope != "user" or not self.args.purge_data:
            yield
            return
        reservation = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            try:
                reservation.bind("\0burnbag.foreground.v1.%d" % self.user_id)
            except OSError as exc:
                if exc.errno == errno.EADDRINUSE:
                    raise InstallError("Foreground burnbag recording is active; end those runs before purging user history") from exc
                raise InstallError(f"Cannot reserve foreground ownership for history purge: {exc}") from exc
            yield
        finally:
            reservation.close()

    def uninstall(self) -> None:
        manifest_path = self.find_manifest()
        expected_scope = "system" if manifest_path.name == "install-system.json" else "user"
        self.scope = expected_scope
        self.dev = manifest_path == self.manifest_path("user", dev=True)
        self.validate_target(manifest_path)
        self.validate_privileged_ancestors(manifest_path)
        if self.privileged(manifest_path):
            manifest_state = self.path(manifest_path).stat()
            if manifest_state.st_uid != 0 or manifest_state.st_mode & 0o022:
                raise InstallError("A privileged installation manifest must be root-owned and not writable by other users")
        try:
            manifest = json.loads(self.path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InstallError(f"Cannot read installation manifest: {exc}") from exc
        if manifest.get("version") != 1 or manifest.get("scope") != expected_scope or manifest.get("mode") not in {"standard", "dev"}:
            raise InstallError("Unsupported installation manifest")
        self.scope = manifest["scope"]
        self.dev = manifest.get("mode") == "dev"
        if self.scope == "user" and not self.stage and os.geteuid() == 0:
            raise InstallError("Remove a user service as its intended non-root login user")
        if self.scope == "user" and not self.stage and manifest.get("user_id") != os.getuid():
            raise InstallError("The selected user installation belongs to a different login user")
        if manifest.get("prefix") != str(self.prefix):
            raise InstallError("Manifest prefix does not match --prefix")
        owner_home = absolute(manifest["user_home"], "manifest user_home")
        source = absolute(manifest["source"], "manifest source")
        allowed = {self.prefix / relative for relative in (
            "bin/burnbag", "bin/burnbag-viewer", "bin/burnbag-viewerctl",
            "bin/burnbag-uninstall", "share/man/man1/burnbag.1",
            "share/man/man1/burnbag-viewer.1", "lib/burnbag/install_services.py",
            "lib/burnbag/burnbag_history.py", "lib/burnbag/burnbag_service.py", "lib/burnbag/burnbag_graph.py",
            "lib/burnbag/burnbag_duration.py", "lib/burnbag/burnbag_viewer_data.py")}
        if self.scope == "user" and self.dev:
            allowed.clear()
        if self.scope == "system":
            allowed.update({self.unit_path(), self.prefix / "lib/sysusers.d/burnbag.conf",
                            Path("/usr/share/polkit-1/rules.d/49-burnbag-delay.rules")})
            if self.prefix not in {Path("/usr"), Path("/usr/local")}:
                allowed.add(Path("/etc/systemd/system/burnbag.service"))
        else:
            owner_config = absolute(manifest.get("user_config", str(owner_home / ".config")), "manifest user_config")
            allowed.add(owner_config / "systemd/user/burnbag.service")
        if self.dev:
            allowed.update({owner_home / ".local/bin/burnbag", source / ".local/bin/burnbag",
                            owner_home / ".local/bin/burnbag-viewer", source / ".local/bin/burnbag-viewer",
                            owner_home / ".local/bin/burnbag-viewerctl", source / ".local/bin/burnbag-viewerctl",
                            source / ".local/share/man/man1/burnbag.1",
                            source / ".local/share/man/man1/burnbag-viewer.1"})
            if self.scope == "user":
                allowed.update({owner_home / ".local/bin/burnbag-uninstall",
                                owner_home / ".local/share/man/man1/burnbag.1",
                                owner_home / ".local/share/man/man1/burnbag-viewer.1"})
        files = manifest.get("files")
        if not isinstance(files, list) or any(not isinstance(item, dict) or Path(item.get("path", "")) not in allowed for item in files):
            raise InstallError("Installation manifest contains an unrecognized artifact path")
        other_owned: set[str] = set()
        history_shared = False
        selected_units = {item["path"] for item in files if item["path"].endswith("/burnbag.service")}
        shared_dir = self.path(self.prefix / "lib/burnbag")
        owner_state = absolute(manifest.get("user_state", str(owner_home / ".local/state")), "manifest user_state")
        other_manifests = set(shared_dir.glob("install-*.json"))
        # A standard --prefix ~/.local installation and a dev user service
        # can share the user manual while keeping manifests in different
        # directories. Account for either removal order.
        user_prefix_manifests = self.path(owner_home / ".local/lib/burnbag")
        other_manifests.update(user_prefix_manifests.glob("install-*.json"))
        private_manifest = self.path(owner_state / "burnbag/install-user.json")
        if private_manifest.is_file():
            other_manifests.add(private_manifest)
        for other in other_manifests:
            if other == self.path(manifest_path):
                continue
            try:
                other_data = json.loads(other.read_text())
                if self.scope == "user" and other_data.get("scope") == "user" and other_data.get("user_state") == str(owner_state):
                    history_shared = True
                for item in other_data["files"]:
                    logical = Path(item["path"])
                    if logical.name == "burnbag.service":
                        if str(logical) not in selected_units:
                            continue
                        # Only the manifest matching the currently published
                        # unit owns its activation. An older mode's replaced
                        # unit must neither stop nor retain the newer unit.
                        current = self.validate_target(logical)
                        if not current.is_file() or digest(current.read_bytes()) != item.get("sha256"):
                            continue
                    other_owned.add(str(logical))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise InstallError(f"Cannot verify shared installation ownership: {other}: {exc}") from exc
        removals: list[Path] = []
        for item in files:
            logical = Path(item["path"])
            target = self.validate_target(logical, allow_link="symlink" in item)
            self.validate_privileged_ancestors(logical)
            if str(logical) in other_owned:
                continue
            if not target.exists() and not target.is_symlink():
                continue
            matches = target.is_symlink() and os.readlink(target) == item["symlink"] if "symlink" in item else not target.is_symlink() and digest(target.read_bytes()) == item.get("sha256")
            if matches:
                removals.append(logical)
            else:
                print(f"[WARNING] Preserving modified or replaced artifact: {target}", file=sys.stderr)
        if self.args.purge_data:
            database = Path("/var/lib/burnbag/history.sqlite3") if self.scope == "system" else absolute(manifest.get("user_state", str(owner_home / ".local/state")), "manifest user_state") / "burnbag/history.sqlite3"
            for suffix in ("", "-wal", "-shm", "-journal"):
                logical = Path(str(database) + suffix)
                target = self.validate_target(logical)
                # Include absent sidecars too: orderly shutdown may create or
                # remove one before the reserved purge executes.
                removals.append(logical)
        unit_shared = any(item["path"].endswith("/burnbag.service") and item["path"] in other_owned for item in files)
        if self.stage:
            registration = Path("/etc/systemd/system/burnbag.service")
            published_unit = registration if self.scope == "system" and self.path(registration).is_file() else self.unit_path()
        else:
            fragment = self.state().get("FragmentPath")
            published_unit = Path(fragment) if fragment else None
        unit_owned = published_unit in removals
        if self.scope == "system" and published_unit is not None and not unit_owned and self.path(published_unit).exists():
            policy = Path("/usr/share/polkit-1/rules.d/49-burnbag-delay.rules")
            removals = [path for path in removals if path != policy]
            print("[INFO] Another published system unit is retained; shared sleep-delay policy preserved.")
        if (unit_shared or history_shared) and self.args.purge_data:
            raise InstallError("Another managed installation still uses this service/history; remove it before purging data")
        if self.args.check:
            print(f"[OK] Would remove {len(removals)} managed artifacts from the {self.scope} installation; no changes made.")
            return
        with self.foreground_purge_guard():
            if not self.stage and self.args.purge_data and not unit_owned:
                if self.state().get("ActiveState") not in {"inactive", "failed"}:
                    raise InstallError("An unowned or replaced service may still record history; stop it explicitly before purging data")
            if not self.stage and unit_owned:
                self.control("stop")
                self.control("disable")
            elif unit_shared:
                print("[INFO] Shared service and artifacts retained for another managed installation.")
            for logical in removals + [manifest_path]:
                self.run(["rm", "-f", "--", str(self.path(logical))], privileged=self.privileged(logical))
            if not self.stage and unit_owned:
                self.reload()
        print(f"[OK] Removed managed {self.scope} installation. History {'purged' if self.args.purge_data else 'preserved'}; configuration, dependencies and service account retained.")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Install/remove burnbag service artifacts; history is preserved unless --purge-data is explicit.")
    parser.add_argument("action", choices=("check", "install", "uninstall"))
    scopes = parser.add_mutually_exclusive_group()
    scopes.add_argument("--user-service", action="store_true")
    scopes.add_argument("--system-service", action="store_true")
    parser.add_argument("--prefix", default="/usr/local")
    parser.add_argument("--destdir")
    parser.add_argument("--user-home")
    parser.add_argument("--source")
    parser.add_argument("--mode", choices=("standard", "dev"), help="Select an installation mode (install default: standard; uninstall default: infer)")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--purge-data", action="store_true")
    args = parser.parse_args(argv)
    try:
        installer = ServiceInstaller(args)
        if args.action == "uninstall":
            installer.uninstall()
        elif args.action == "check" or args.check:
            installer.plan()
            print("[OK] Service installation sources and destinations verified; no changes made.")
        else:
            installer.install()
    except (InstallError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[ERROR] Service {args.action} failed: {exc}. Earlier steps may have completed; resolve the error and rerun.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
