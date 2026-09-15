"""Scoped installation lifecycle tests without touching the host service manager."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("burnbag_install_services", PROJECT_ROOT / "scripts/install_services.py")
assert SPEC is not None and SPEC.loader is not None
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


class ServiceInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = PROJECT_ROOT / ".local/tmp"
        temporary.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="burnbag-service-install.", dir=temporary))
        self.stage = self.root / "stage"
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for command in ("sudo", "systemctl", "systemd-sysusers", "useradd", "groupadd", "loginctl"):
            path = self.bin / command
            path.write_text("#!/usr/bin/bash\nprintf 'FORBIDDEN HOST COMMAND\\n' >&2\nexit 99\n")
            path.chmod(0o755)

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def helper(self, action: str, *options: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PATH"] = f"{self.bin}:/usr/bin:/bin"
        environment["HOME"] = str(self.home)
        environment.pop("XDG_STATE_HOME", None)
        environment.pop("XDG_CONFIG_HOME", None)
        return subprocess.run(
            ["/usr/bin/python3", "-B", str(PROJECT_ROOT / "scripts/install_services.py"), action,
             "--destdir", str(self.stage), "--user-home", str(self.home),
             "--source", str(PROJECT_ROOT), *options],
            env=environment, capture_output=True, text=True, timeout=20, check=False,
        )

    def staged(self, logical: str | Path) -> Path:
        return self.stage / str(logical).lstrip("/")

    def install(self, *options: str) -> None:
        result = self.helper("install", *options)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("FORBIDDEN", result.stderr)

    def assert_current_manual(self, manual: Path) -> None:
        contents = manual.read_bytes()
        self.assertEqual(contents, (PROJECT_ROOT / "burnbag.1").read_bytes())
        self.assertIn(b"\\-\\-last", contents)
        self.assertIn(b"Months and larger units use calendar arithmetic", contents)
        self.assertEqual(manual.stat().st_mode & 0o777, 0o644)
        self.assertFalse(manual.is_symlink())

    def instance(self, *, user: bool = False, dev: bool = False) -> INSTALL.ServiceInstaller:
        args = argparse.Namespace(
            prefix=str(self.home / ".local") if user else "/usr/local", destdir=None,
            source=str(PROJECT_ROOT), user_home=str(self.home), user_service=user,
            system_service=not user, mode="dev" if dev else "standard", check=False,
            purge_data=False,
        )
        return INSTALL.ServiceInstaller(args)

    def test_stage_contains_complete_executable_modules_unit_and_account_declaration(self) -> None:
        self.install("--system-service")
        for relative in ("bin/burnbag", "bin/burnbag-uninstall", "share/man/man1/burnbag.1",
                         "lib/burnbag/burnbag_history.py", "lib/burnbag/burnbag_service.py",
                         "lib/burnbag/burnbag_graph.py", "lib/burnbag/burnbag_duration.py", "lib/burnbag/install_services.py",
                         "lib/sysusers.d/burnbag.conf", "lib/burnbag/install-system.json"):
            self.assertTrue((self.stage / "usr/local" / relative).is_file(), relative)
        unit = (self.stage / "usr/local/lib/systemd/system/burnbag.service").read_text()
        self.assertIn('ExecStart="/usr/local/bin/burnbag" --collector --service-scope system', unit)
        self.assertIn("User=burnbag\nGroup=burnbag", unit)
        self.assertIn("Type=notify", unit)
        self.assertIn("RestartPreventExitStatus=73", unit)
        self.assertNotIn("PrivateNetwork=yes", unit)
        policy = self.stage / "usr/share/polkit-1/rules.d/49-burnbag-delay.rules"
        self.assertTrue(policy.is_file())
        self.assertNotIn("suspend-multiple-sessions", policy.read_text())
        self.assertFalse((self.stage / "etc/passwd").exists())

    def test_staged_executable_imports_installed_support_modules(self) -> None:
        self.install()
        result = subprocess.run([str(self.stage / "usr/local/bin/burnbag"), "--help"],
                                capture_output=True, text=True, timeout=10, check=False,
                                cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout.lower())
        self.assertNotIn("No module named", result.stderr)

    def test_every_installation_mode_copies_the_generated_duration_manual(self) -> None:
        cases = (
            ("standard-system", (), Path("/usr/local/share/man/man1/burnbag.1")),
            ("dev-system", ("--mode", "dev"), Path("/usr/local/share/man/man1/burnbag.1")),
            ("standard-user", ("--user-service",), Path("/usr/local/share/man/man1/burnbag.1")),
            ("dev-user", ("--user-service", "--mode", "dev"), self.home / ".local/share/man/man1/burnbag.1"),
        )
        for name, options, manual in cases:
            with self.subTest(mode=name):
                self.stage = self.root / name
                self.install(*options)
                self.assert_current_manual(self.staged(manual))

    def test_custom_prefix_registers_a_tracked_unit_and_uninstalls_it(self) -> None:
        self.install("--prefix", "/opt/burnbag")
        registration = self.stage / "etc/systemd/system/burnbag.service"
        unit = self.stage / "opt/burnbag/lib/systemd/system/burnbag.service"
        self.assertEqual(registration.read_bytes(), unit.read_bytes())
        self.assertIn('ExecStart="/opt/burnbag/bin/burnbag"', registration.read_text())
        manifest = json.loads((self.stage / "opt/burnbag/lib/burnbag/install-system.json").read_text())
        self.assertIn("/etc/systemd/system/burnbag.service", [item["path"] for item in manifest["files"]])
        result = self.helper("uninstall", "--prefix", "/opt/burnbag")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(registration.exists())
        self.assertFalse(unit.exists())

    def test_custom_prefix_refuses_an_unmanaged_registration_before_writes(self) -> None:
        registration = self.stage / "etc/systemd/system/burnbag.service"
        registration.parent.mkdir(parents=True)
        registration.write_text("operator-owned unit")
        result = self.helper("install", "--prefix", "/opt/burnbag")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unmanaged service", result.stderr)
        self.assertEqual(registration.read_text(), "operator-owned unit")
        self.assertFalse((self.stage / "opt/burnbag/bin/burnbag").exists())

    def test_older_prefix_uninstall_preserves_current_registration_and_policy(self) -> None:
        for old_prefix in ("/usr/local", "/opt/burnbag-old"):
            with self.subTest(old_prefix=old_prefix):
                self.stage = self.root / ("stage-default" if old_prefix == "/usr/local" else "stage-custom")
                self.install("--prefix", old_prefix)
                self.install("--prefix", "/opt/burnbag-new")
                result = self.helper("uninstall", "--system-service", "--prefix", old_prefix)
                self.assertEqual(result.returncode, 0, result.stderr)
                registration = self.stage / "etc/systemd/system/burnbag.service"
                self.assertIn("/opt/burnbag-new/bin/burnbag", registration.read_text())
                self.assertTrue((self.stage / "usr/share/polkit-1/rules.d/49-burnbag-delay.rules").exists())
                self.assertFalse(self.staged(Path(old_prefix) / "bin/burnbag").exists())

    def test_older_prefix_cannot_stop_the_unit_selected_by_systemd(self) -> None:
        self.install()
        self.install("--prefix", "/opt/burnbag-new")
        installer = self.instance()
        mapper = lambda logical: self.stage / str(logical).lstrip("/")
        current = {"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled",
                   "FragmentPath": "/etc/systemd/system/burnbag.service"}
        with patch.object(installer, "path", side_effect=mapper), \
             patch.object(installer, "privileged", return_value=False), \
             patch.object(installer, "state", return_value=current), \
             patch.object(installer, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run, \
             patch.object(installer, "control") as control, patch.object(installer, "reload") as reload:
            installer.uninstall()
        control.assert_not_called()
        reload.assert_not_called()
        removed = [call.args[0][-1] for call in run.call_args_list]
        self.assertNotIn(str(self.stage / "etc/systemd/system/burnbag.service"), removed)
        self.assertNotIn(str(self.stage / "usr/share/polkit-1/rules.d/49-burnbag-delay.rules"), removed)

    def test_custom_prefix_registration_is_published_before_enable_and_start(self) -> None:
        installer = self.instance()
        installer.prefix = Path("/opt/burnbag")
        events = []
        def record_write(path: Path, *_args: object) -> None:
            events.append(str(path))
        with patch.object(installer, "state", side_effect=[{"LoadState": "not-found"}, {"ActiveState": "inactive"}]), \
             patch.object(installer, "write", side_effect=record_write), patch.object(installer, "ensure_account"), \
             patch.object(installer, "reload"), patch.object(installer, "control", side_effect=events.append):
            installer.install()
        self.assertLess(events.index("/etc/systemd/system/burnbag.service"), events.index("enable"))
        self.assertLess(events.index("enable"), events.index("start"))

    def test_check_does_not_create_staging_tree(self) -> None:
        result = self.helper("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.stage.exists())

    def test_support_and_policy_paths_cannot_escape_staging(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        target = self.stage / "usr/local/lib"
        target.parent.mkdir(parents=True)
        target.symlink_to(outside, target_is_directory=True)
        result = self.helper("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("escapes --destdir", result.stderr)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse((self.stage / "usr/local/bin/burnbag").exists())

    def test_user_service_is_scoped_and_lingering_is_never_modified(self) -> None:
        self.install("--user-service")
        unit = self.staged(self.home / ".config/systemd/user/burnbag.service").read_text()
        self.assertIn("--service-scope user", unit)
        self.assertIn("UMask=0077", unit)
        self.assertNotIn("User=burnbag", unit)
        self.assertFalse((self.stage / "usr/local/lib/sysusers.d/burnbag.conf").exists())
        self.assertFalse((self.stage / "usr/local/lib/systemd/system/burnbag.service").exists())

    def test_user_development_unit_executes_checkout_and_has_private_manifest(self) -> None:
        self.install("--user-service", "--mode", "dev")
        unit = self.staged(self.home / ".config/systemd/user/burnbag.service").read_text()
        self.assertIn(str(PROJECT_ROOT / "burnbag.py"), unit)
        self.assertFalse((self.stage / "usr/local/bin/burnbag").exists())
        manifest = self.staged(self.home / ".local/state/burnbag/install-user.json")
        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
        self.assertEqual(manifest.parent.stat().st_mode & 0o777, 0o700)
        manual = self.home / ".local/share/man/man1/burnbag.1"
        self.assert_current_manual(self.staged(manual))
        self.assertEqual(self.staged(manual).stat().st_uid, os.getuid())
        record = next(item for item in json.loads(manifest.read_text())["files"]
                      if item["path"] == str(manual))
        self.assertTrue(record["shared"])
        self.assertEqual(record["sha256"], INSTALL.digest(self.staged(manual).read_bytes()))

    def test_user_manual_remains_until_both_standard_and_dev_owners_are_removed(self) -> None:
        for first, second in (("standard", "dev"), ("dev", "standard")):
            with self.subTest(first_removed=first):
                self.stage = self.root / ("shared-manual-" + first)
                prefix = self.home / ".local"
                self.install("--user-service", "--prefix", str(prefix))
                self.install("--user-service", "--mode", "dev")
                manual = self.staged(prefix / "share/man/man1/burnbag.1")
                for mode in (first, second):
                    options = ["--user-service", "--mode", mode]
                    if mode == "standard":
                        options.extend(("--prefix", str(prefix)))
                    result = self.helper("uninstall", *options)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    if mode == first:
                        self.assert_current_manual(manual)
                    else:
                        self.assertFalse(manual.exists())

    def test_user_dev_uninstall_preserves_a_modified_manual(self) -> None:
        self.install("--user-service", "--mode", "dev")
        manual = self.staged(self.home / ".local/share/man/man1/burnbag.1")
        manual.write_text("operator manual changes")
        result = self.helper("uninstall", "--user-service", "--mode", "dev")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preserving modified", result.stderr)
        self.assertEqual(manual.read_text(), "operator manual changes")

    def test_uninstall_preserves_data_configuration_and_modified_artifacts(self) -> None:
        self.install()
        database = self.stage / "var/lib/burnbag/history.sqlite3"
        database.parent.mkdir(parents=True)
        database.write_text("retained history")
        override = self.stage / "etc/systemd/system/burnbag.service.d/operator.conf"
        override.parent.mkdir(parents=True)
        override.write_text("operator configuration")
        executable = self.stage / "usr/local/bin/burnbag"
        executable.write_text("locally modified executable")
        result = self.helper("uninstall", "--system-service")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Preserving modified", result.stderr)
        self.assertEqual(database.read_text(), "retained history")
        self.assertTrue(override.is_file())
        self.assertEqual(executable.read_text(), "locally modified executable")
        self.assertFalse((self.stage / "usr/local/lib/systemd/system/burnbag.service").exists())
        self.assertFalse((self.stage / "usr/local/lib/burnbag/install-system.json").exists())

    def test_uninstall_check_is_read_only_and_purge_is_scope_limited(self) -> None:
        self.install()
        system_db = self.stage / "var/lib/burnbag/history.sqlite3"
        user_db = self.staged(self.home / ".local/state/burnbag/history.sqlite3")
        for db in (system_db, user_db):
            db.parent.mkdir(parents=True, exist_ok=True)
            db.write_text("data")
        unrelated = system_db.parent / "operator.txt"
        unrelated.write_text("retain")
        result = self.helper("uninstall", "--check", "--purge-data")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(system_db.exists())
        self.assertTrue((self.stage / "usr/local/bin/burnbag").exists())
        result = self.helper("uninstall", "--purge-data")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(system_db.exists())
        self.assertTrue(user_db.exists())
        self.assertTrue(unrelated.exists())

    def test_uninstall_rejects_forged_manifest_and_purge_symlink_before_removing_files(self) -> None:
        self.install()
        manifest_path = self.stage / "usr/local/lib/burnbag/install-system.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"].append({"path": "/etc/passwd", "sha256": "invalid"})
        manifest_path.write_text(json.dumps(manifest))
        result = self.helper("uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrecognized artifact", result.stderr)
        self.assertTrue((self.stage / "usr/local/bin/burnbag").exists())
        self.install()
        db = self.stage / "var/lib/burnbag/history.sqlite3"
        db.parent.mkdir(parents=True)
        db.symlink_to(self.root / "outside")
        result = self.helper("uninstall", "--purge-data")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.stage / "usr/local/bin/burnbag").exists())

    def test_shared_files_survive_removing_one_installed_scope(self) -> None:
        self.install("--system-service")
        self.install("--user-service")
        result = self.helper("uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Multiple managed installations", result.stderr)
        result = self.helper("uninstall", "--system-service")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.stage / "usr/local/bin/burnbag").exists())
        self.assertTrue(self.staged(self.home / ".config/systemd/user/burnbag.service").exists())

    def test_both_user_modes_are_selectable_without_orphaning_the_current_unit(self) -> None:
        self.install("--user-service", "--mode", "standard")
        self.install("--user-service", "--mode", "dev")
        ambiguous = self.helper("uninstall", "--user-service")
        self.assertNotEqual(ambiguous.returncode, 0)
        self.assertIn("--mode standard|dev", ambiguous.stderr)
        purge = self.helper("uninstall", "--user-service", "--mode", "dev", "--purge-data")
        self.assertNotEqual(purge.returncode, 0)
        self.assertIn("Another managed installation", purge.stderr)
        result = self.helper("uninstall", "--user-service", "--mode", "dev")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.staged(self.home / ".local/state/burnbag/install-user.json").exists())
        self.assertFalse(self.staged(self.home / ".config/systemd/user/burnbag.service").exists())
        result = self.helper("uninstall", "--user-service", "--mode", "standard")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.staged(self.home / ".config/systemd/user/burnbag.service").exists())

    def test_removing_older_user_mode_preserves_the_current_mode_unit(self) -> None:
        self.install("--user-service", "--mode", "standard")
        self.install("--user-service", "--mode", "dev")
        unit = self.staged(self.home / ".config/systemd/user/burnbag.service")
        original = unit.read_bytes()
        result = self.helper("uninstall", "--user-service", "--mode", "standard")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(unit.read_bytes(), original)
        result = self.helper("uninstall", "--user-service", "--mode", "dev")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(unit.exists())

    def test_system_dev_uninstall_preserves_launcher_owned_by_private_user_dev_manifest(self) -> None:
        launcher = self.home / ".local/bin/burnbag"
        launcher.parent.mkdir(parents=True)
        contents = '#!/usr/bin/bash\n# burnbag-managed-dev-launcher\nexec "' + str(PROJECT_ROOT / "burnbag.py") + '" "$@"\n'
        launcher.write_text(contents)
        staged_launcher = self.staged(launcher)
        staged_launcher.parent.mkdir(parents=True)
        staged_launcher.write_text(contents)
        self.install("--system-service", "--mode", "dev")
        self.install("--user-service", "--mode", "dev")
        result = self.helper("uninstall", "--system-service")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(staged_launcher.read_text(), contents)
        result = self.helper("uninstall", "--user-service", "--mode", "dev")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(staged_launcher.exists())

    def test_existing_private_user_directories_keep_their_permissions(self) -> None:
        private = [self.staged(self.home / relative) for relative in (
            ".config/systemd/user", ".local/bin", ".local/share/man/man1")]
        for directory in private:
            directory.mkdir(parents=True, mode=0o700)
        self.install("--user-service", "--mode", "dev")
        for directory in private:
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def test_new_install_enables_and_starts_but_stopped_upgrade_preserves_state(self) -> None:
        for before, expected in (
            ({"LoadState": "not-found", "ActiveState": "inactive", "UnitFileState": ""}, ["enable", "start"]),
            ({"LoadState": "loaded", "ActiveState": "inactive", "UnitFileState": "disabled"}, []),
            ({"LoadState": "loaded", "ActiveState": "active", "UnitFileState": "disabled"}, ["restart"]),
            ({"LoadState": "masked", "ActiveState": "inactive", "UnitFileState": "masked"}, []),
        ):
            with self.subTest(before=before):
                installer = self.instance()
                with patch.object(installer, "state", side_effect=[before, {"ActiveState": "inactive"}]), \
                     patch.object(installer, "write") as write, patch.object(installer, "ensure_account"), \
                     patch.object(installer, "reload"), patch.object(installer, "control") as control:
                    installer.install()
                self.assertTrue(write.called)
                self.assertEqual([call.args[0] for call in control.call_args_list], expected)

    def test_peer_running_blocks_install_before_any_writes(self) -> None:
        installer = self.instance()
        with patch.object(installer, "state", side_effect=[{"LoadState": "not-found"}, {"ActiveState": "active"}]), \
             patch.object(installer, "write") as write:
            with self.assertRaisesRegex(INSTALL.InstallError, "other service scope"):
                installer.install()
        write.assert_not_called()

    def test_system_prefix_cannot_execute_from_operator_writable_home(self) -> None:
        installer = self.instance()
        installer.prefix = self.home / "system-daemon"
        with self.assertRaisesRegex(INSTALL.InstallError, "root-owned directories"):
            installer.plan()

    def test_existing_login_account_is_rejected_before_installation(self) -> None:
        installer = self.instance()
        account = SimpleNamespace(pw_uid=1001, pw_gid=1001, pw_shell="/bin/bash")
        with patch.object(INSTALL.pwd, "getpwnam", return_value=account), \
             patch.object(INSTALL.grp, "getgrnam", return_value=SimpleNamespace(gr_gid=1001)), \
             patch.object(installer, "write") as write:
            with self.assertRaisesRegex(INSTALL.InstallError, "non-login service account"):
                installer.install()
        write.assert_not_called()

    def test_privileged_descendants_reject_untrusted_owner_or_write_permissions(self) -> None:
        installer = self.instance()
        unsafe = Path("/usr/local/lib/burnbag")
        original_stat = Path.stat
        for owner, mode in ((1000, 0o755), (0, 0o775)):
            with self.subTest(owner=owner, mode=mode):
                def fake_stat(path: Path, *args: object, **kwargs: object) -> object:
                    if path == unsafe:
                        return SimpleNamespace(st_uid=owner, st_mode=stat.S_IFDIR | mode)
                    return original_stat(path, *args, **kwargs)
                with patch.object(Path, "stat", fake_stat):
                    with self.assertRaisesRegex(INSTALL.InstallError, str(unsafe)):
                        installer.validate_privileged_ancestors(unsafe / "burnbag_service.py")

    def test_privileged_symlink_targets_include_their_resolved_ancestors(self) -> None:
        installer = self.instance()
        parent = Path("/usr/local/lib/burnbag")
        original_resolve = Path.resolve
        def redirected(path: Path, *args: object, **kwargs: object) -> Path:
            return self.home if path == parent else original_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", redirected):
            with self.assertRaisesRegex(INSTALL.InstallError, str(self.home)):
                installer.validate_privileged_ancestors(parent / "burnbag_service.py")

    def test_user_purge_reserves_foreground_ownership_until_completion(self) -> None:
        installer = self.instance(user=True)
        installer.args.purge_data = True
        # Use a fixture-owned abstract address, never the operator's namespace.
        installer.user_id = 2000000000 + os.getpid()
        address = "\0burnbag.foreground.v1.%d" % installer.user_id
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as owner:
            owner.bind(address)
            with self.assertRaisesRegex(INSTALL.InstallError, "Foreground burnbag recording is active"):
                with installer.foreground_purge_guard():
                    self.fail("Busy foreground ownership must prevent deletion")
        with self.assertRaisesRegex(RuntimeError, "injected removal failure"):
            with installer.foreground_purge_guard():
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as contender:
                    with self.assertRaises(OSError):
                        contender.bind(address)
                raise RuntimeError("injected removal failure")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as released:
            released.bind(address)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze unavailable")
    def test_systemd_accepts_rendered_unit_directives(self) -> None:
        for scope in ("system", "user"):
            with self.subTest(scope=scope):
                directory = self.root / scope
                directory.mkdir()
                unit = directory / "burnbag.service"
                contents = (PROJECT_ROOT / f"systemd/burnbag-{scope}.service").read_text()
                unit.write_text(contents.replace("@EXECUTABLE@", '"/usr/bin/python3"'))
                result = subprocess.run(["systemd-analyze", "verify", "--man=no", str(unit)],
                                        capture_output=True, text=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_user_dev_xdg_history_location_is_pinned_for_service_and_purge(self) -> None:
        with patch.dict(os.environ, {"HOME": str(self.home), "XDG_STATE_HOME": str(self.home / "custom-state")}):
            installer = self.instance(user=True, dev=True)
            files = installer.plan()
        unit = next(item["data"].decode() for item in files if item["path"].endswith("burnbag.service"))
        self.assertIn(f'Environment="XDG_STATE_HOME={self.home}/custom-state"', unit)
        self.assertEqual(installer.manifest_path(), self.home / "custom-state/burnbag/install-user.json")


if __name__ == "__main__":
    unittest.main()
