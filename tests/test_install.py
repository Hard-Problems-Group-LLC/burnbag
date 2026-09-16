"""Installer regression tests for development command resolution."""

from __future__ import annotations

import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import subprocess
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_TMP = PROJECT_ROOT / ".local" / "tmp"


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        LOCAL_TMP.mkdir(parents=True, exist_ok=True)
        self.run_root = Path(
            tempfile.mkdtemp(prefix="burnbag-install-test.", dir=LOCAL_TMP)
        )
        self.checkout = self.run_root / "checkout"
        self.user_home = self.run_root / "home"
        self.system_bin = self.run_root / "system-bin"
        (self.checkout / "scripts").mkdir(parents=True)
        self.user_home.mkdir()
        self.system_bin.mkdir()

        for relative_path in ("install.sh", "uninstall.sh", "burnbag.py", "burnbag.1", "burnbag_viewer.py", "burnbag_viewer_data.py", "burnbag_viewerctl.py", "burnbag-viewer.1", "burnbag_history.py", "burnbag_service.py", "burnbag_graph.py", "burnbag_duration.py"):
            shutil.copy2(PROJECT_ROOT / relative_path, self.checkout / relative_path)
        shutil.copytree(PROJECT_ROOT / "systemd", self.checkout / "systemd")
        shutil.copy2(PROJECT_ROOT / "scripts/install_services.py", self.checkout / "scripts/install_services_real.py")
        # These launcher tests exercise the real service helper only in an
        # isolated staging tree. Live service lifecycle is covered separately
        # with a controlled command boundary in test_service_install.py.
        (self.checkout / "scripts/install_services.py").write_text(
            "import runpy, sys\nfrom pathlib import Path\n"
            "if '--destdir' in sys.argv:\n"
            "    runpy.run_path(str(Path(__file__).with_name('install_services_real.py')), run_name='__main__')\n",
            encoding="utf-8",
        )
        shutil.copy2(
            PROJECT_ROOT / "scripts" / "install_prerequisites.sh",
            self.checkout / "scripts" / "install_prerequisites.sh",
        )

        self.system_burnbag = self.system_bin / "burnbag"
        self.system_burnbag.write_text(
            "#!/usr/bin/bash\nprintf 'system burnbag\\n'\n", encoding="utf-8"
        )
        self.system_burnbag.chmod(0o755)
        for command in ("burnbag-viewer", "burnbag-viewerctl"):
            self.write_command(command, "printf 'system " + command + "\\n'")
        # Plain dev now also deploys a system daemon. Never allow this fixture
        # to write /usr/local or manage the host service.
        self.write_command("sudo", "exit 0")

    def tearDown(self) -> None:
        shutil.rmtree(self.run_root)

    def environment(self, *, user_bin_first: bool = True) -> dict[str, str]:
        environment = os.environ.copy()
        for key in ("BURNBAG_DEV_LAUNCHER_MODE", "XDG_STATE_HOME", "XDG_CONFIG_HOME",
                    "SUDO_USER", "SUDO_UID", "SUDO_GID"):
            environment.pop(key, None)
        user_bin = self.user_home / ".local" / "bin"
        ordered_bins = (
            (user_bin, self.system_bin)
            if user_bin_first
            else (self.system_bin, user_bin)
        )
        environment["HOME"] = str(self.user_home)
        environment["PATH"] = ":".join(
            [*(str(path) for path in ordered_bins), "/usr/bin", "/bin"]
        )
        return environment

    def run_installer(
        self,
        *arguments: str,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.checkout / "install.sh"), *arguments],
            cwd=self.checkout,
            env=environment or self.environment(),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def write_command(self, name: str, body: str) -> Path:
        """Substitute an external tool in this fixture's isolated PATH."""
        command = self.system_bin / name
        command.write_text("#!/usr/bin/bash\n" + body + "\n", encoding="utf-8")
        command.chmod(0o755)
        return command

    def existing_managed_launcher(self) -> tuple[Path, str]:
        launcher = self.user_home / ".local" / "bin" / "burnbag"
        launcher.parent.mkdir(parents=True, exist_ok=True)
        contents = "#!/usr/bin/bash\n# burnbag-managed-dev-launcher\nprintf 'existing checkout\\n'\n"
        launcher.write_text(contents, encoding="utf-8")
        launcher.chmod(0o755)
        return launcher, contents

    def resolve_burnbag(self, environment: dict[str, str]) -> str:
        result = subprocess.run(
            ["/usr/bin/bash", "-c", "command -v burnbag"],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def test_default_dev_selection_controls_all_bare_commands(self) -> None:
        environment = self.environment()
        launcher = self.user_home / ".local" / "bin" / "burnbag"

        local_result = self.run_installer(
            "--mode",
            "dev",
            "--skip-prerequisites",
            "--user-home",
            str(self.user_home),
            environment=environment,
        )

        self.assertEqual(local_result.returncode, 0, local_result.stderr)
        self.assertIn("burnbag-managed-dev-launcher", launcher.read_text())
        self.assertEqual(self.resolve_burnbag(environment), str(launcher))
        help_result = subprocess.run(
            ["/usr/bin/bash", "-c", "burnbag --help"],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--ignore-lid", help_result.stdout)
        for command in ("burnbag-viewer", "burnbag-viewerctl"):
            user_command = self.user_home / ".local/bin" / command
            self.assertTrue(user_command.is_file())
            result = subprocess.run(["/usr/bin/bash", "-c", "command -v " + command + "; " + command + " --help"],
                                    env=environment, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith(str(user_command)))
            if command == "burnbag-viewer":
                self.assertIn("--last", result.stdout)
                self.assertIn("--only", result.stdout)
        development_manual = self.checkout / ".local/share/man/man1/burnbag.1"
        self.assertTrue(development_manual.is_symlink())
        self.assertEqual(development_manual.resolve(), self.checkout / "burnbag.1")
        self.assertIn("Months and larger units use calendar arithmetic", development_manual.read_text())
        for relative, target in (
            (".local/bin/burnbag-viewer", "burnbag_viewer.py"),
            (".local/bin/burnbag-viewerctl", "burnbag_viewerctl.py"),
            (".local/share/man/man1/burnbag-viewer.1", "burnbag-viewer.1"),
        ):
            link = self.checkout / relative
            self.assertTrue(link.is_symlink(), relative)
            self.assertEqual(link.resolve(), self.checkout / target)

    def test_unmanaged_viewer_launcher_is_preserved_before_replacing_family(self):
        directory = self.user_home / ".local/bin"
        directory.mkdir(parents=True)
        viewer = directory / "burnbag-viewer"
        viewer.write_text("unmanaged")
        result = self.run_installer("--mode", "dev", "--skip-prerequisites",
                                    "--user-home", str(self.user_home))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(viewer.read_text(), "unmanaged")
        self.assertFalse((directory / "burnbag").exists())

    def test_mode_roundtrip_switches_all_commands_and_service_without_checkout_dependency(self):
        # Keep the real helper and file publication. Substitute only login
        # identity and the external service manager in this private fixture.
        (self.checkout / "scripts/install_services.py").write_text(
            "import os, runpy\nfrom pathlib import Path\nfrom types import SimpleNamespace\n"
            "module = runpy.run_path(str(Path(__file__).with_name('install_services_real.py')))\n"
            "module['pwd'].getpwuid = lambda uid: SimpleNamespace(pw_dir=os.environ['HOME'])\n"
            "raise SystemExit(module['main']())\n")
        self.write_command("systemctl", "printf 'LoadState=not-found\\nActiveState=inactive\\nUnitFileState=disabled\\n'")
        self.write_command("mandb", "exit 0")
        environment = self.environment()
        prefix = self.user_home / "installed"
        environment["PATH"] = ":".join((str(self.user_home / ".local/bin"),
            str(prefix / "bin"), str(self.checkout / ".local/bin"), str(self.system_bin), "/usr/bin", "/bin"))
        options = ("--install-user-service", "--skip-prerequisites")
        dev = self.run_installer("--mode", "dev", *options, environment=environment)
        self.assertEqual(dev.returncode, 0, dev.stderr)
        unit = self.user_home / ".config/systemd/user/burnbag.service"
        self.assertIn(str(self.checkout / "burnbag.py"), unit.read_text())
        viewer = self.checkout / "burnbag_viewer.py"
        viewer.write_text(viewer.read_text().replace("GTK 4 desktop browser", "CHECKOUT-EDIT desktop browser"))
        result = subprocess.run(["burnbag-viewer", "--help"], env=environment, text=True,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CHECKOUT-EDIT", result.stdout)
        # No --mode: standard must become authoritative, even with legacy env.
        environment["BURNBAG_DEV_LAUNCHER_MODE"] = "local"
        standard = self.run_installer("--prefix", str(prefix), *options, environment=environment)
        self.assertEqual(standard.returncode, 0, standard.stderr)
        self.assertIn(str(prefix / "bin/burnbag"), unit.read_text())
        self.assertNotIn(str(self.checkout), unit.read_text())
        for command in ("burnbag", "burnbag-viewer", "burnbag-viewerctl"):
            self.assertFalse((self.user_home / ".local/bin" / command).exists())
            self.assertFalse((self.checkout / ".local/bin" / command).exists())
        moved = self.checkout.with_name("checkout-away")
        self.checkout.rename(moved)
        try:
            for command in ("burnbag", "burnbag-viewer", "burnbag-viewerctl"):
                result = subprocess.run(["/usr/bin/bash", "-c", "command -v " + command + "; " + command + " --help"],
                                        cwd=self.user_home, env=environment, text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith(str(prefix / "bin" / command)))
            result = subprocess.run(["/usr/bin/python3", "-B", "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); import burnbag_history, burnbag_service; print(burnbag_service.__file__)",
                str(prefix / "lib/burnbag")], cwd=self.user_home, env=environment,
                text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(prefix / "lib/burnbag"), result.stdout)
        finally:
            moved.rename(self.checkout)
        dev_again = self.run_installer("--mode", "dev", *options, environment=environment)
        self.assertEqual(dev_again.returncode, 0, dev_again.stderr)
        self.assertIn(str(self.checkout / "burnbag.py"), unit.read_text())
        for command in ("burnbag", "burnbag-viewer", "burnbag-viewerctl"):
            self.assertTrue((self.user_home / ".local/bin" / command).is_file())

    def test_standard_refuses_unmanaged_shadowing_before_installation(self):
        prefix = self.user_home / "installed"
        environment = self.environment()
        environment["PATH"] = str(self.user_home / ".local/bin") + ":" + str(prefix / "bin") + ":" + environment["PATH"]
        shadow = self.user_home / ".local/bin/burnbag-viewer"
        shadow.parent.mkdir(parents=True)
        shadow.write_text("#!/bin/sh\necho operator-owned\n")
        shadow.chmod(0o755)
        result = self.run_installer("--prefix", str(prefix), "--install-user-service",
                                    "--skip-prerequisites", environment=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("would override the standard command", result.stderr)
        self.assertIn("operator-owned", shadow.read_text())
        self.assertFalse(prefix.exists())

    def privileged_fixture(self) -> tuple[Path, dict[str, str]]:
        """Exercise root branches without granting the test process privileges.

        Substitute only Bash's immutable identity, the account lookup, and the
        helper's deployment root. Real file publication stays in our private
        stage; the helper's staged mode cannot touch host accounts/services.
        """
        installer = self.checkout / "install.sh"
        installer.write_text(installer.read_text().replace("${EUID}", "0"))
        for command in ("burnbag", "burnbag-viewer", "burnbag-viewerctl"):
            (self.system_bin / command).unlink()
        prefix = self.run_root / "stage/usr/local"
        (self.checkout / "scripts/install_services.py").write_text(
            "import runpy, sys\nfrom pathlib import Path\n"
            "root = Path(__file__).resolve().parents[2]\n"
            "index = sys.argv.index('--prefix') + 1\n"
            "assert sys.argv[index] == str(root / 'stage/usr/local')\n"
            "sys.argv[index] = '/usr/local'\n"
            "sys.argv.extend(['--destdir', str(root / 'stage')])\n"
            "runpy.run_path(str(Path(__file__).with_name('install_services_real.py')), run_name='__main__')\n"
        )
        self.write_command("getent", "[[ $1 == passwd && $2 == 12345 ]] || exit 2\n"
                           + "printf '%s\\n' " + shlex.quote(
                               f"operator:x:12345:12345:Test Operator:{self.user_home}:/bin/bash"))
        self.write_command("mandb", "exit 0")
        root_home = self.run_root / "root-home"
        root_home.mkdir()
        environment = self.environment()
        environment.update(HOME=str(root_home), SUDO_UID="12345", SUDO_USER="operator",
                           PATH=f"{self.system_bin}:/usr/sbin:/usr/bin:/sbin:/bin")
        return prefix, environment

    def test_sudo_restricted_path_installs_independent_commands_and_retires_callers_launchers(self):
        launcher, _ = self.existing_managed_launcher()
        for command, source in (("burnbag", "burnbag.py"),
                                ("burnbag-viewer", "burnbag_viewer.py"),
                                ("burnbag-viewerctl", "burnbag_viewerctl.py")):
            (launcher.parent / command).write_text(launcher.read_text())
            link = self.checkout / ".local/bin" / command
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(self.checkout / source)
        prefix, environment = self.privileged_fixture()
        # Even a competing command on root's PATH says nothing about the
        # operator's shell; verification must use the installed absolute path.
        self.write_command("burnbag", "exit 99")
        root_launcher = Path(environment["HOME"]) / ".local/bin/burnbag"
        root_launcher.parent.mkdir(parents=True)
        root_launcher.write_text(launcher.read_text())
        result = self.run_installer("--prefix", str(prefix), "--skip-prerequisites", environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Verified installed command", result.stdout)
        self.assertIn("caller shell's PATH", result.stdout)
        self.assertNotIn("Bare burnbag selects", result.stdout)
        self.assertTrue(root_launcher.exists())
        moved = self.checkout.with_name("checkout-away")
        self.checkout.rename(moved)
        for command in ("burnbag", "burnbag-viewer", "burnbag-viewerctl"):
            self.assertFalse((launcher.parent / command).exists())
            self.assertFalse((moved / ".local/bin" / command).is_symlink())
            result = subprocess.run([str(prefix / "bin" / command), "--help"],
                                    env=environment, cwd=self.user_home, text=True,
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_sudo_check_is_read_only_and_preserves_launchers(self):
        launcher, contents = self.existing_managed_launcher()
        prefix, environment = self.privileged_fixture()
        result = self.run_installer("--check", "--prefix", str(prefix), "--skip-prerequisites",
                                    environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(prefix.parent.exists())
        self.assertEqual(launcher.read_text(), contents)
        self.assertNotIn("Verified installed command", result.stdout)

    def test_sudo_invalid_identity_fails_before_writes(self):
        prefix, environment = self.privileged_fixture()
        for uid, name in (("not-a-uid", "operator"), ("12345", "someone-else"),
                          ("12345", ""), ("", "operator"), ("54321", "operator")):
            with self.subTest(uid=uid, name=name):
                environment.update(SUDO_UID=uid, SUDO_USER=name)
                result = self.run_installer("--prefix", str(prefix), "--skip-prerequisites",
                                            environment=environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("sudo caller", result.stderr)
                self.assertFalse(prefix.parent.exists())

    def test_sudo_explicit_home_overrides_account_lookup_and_preserves_unmanaged_launcher(self):
        prefix, environment = self.privileged_fixture()
        environment["SUDO_UID"] = "invalid"
        self.write_command("getent", "exit 99")
        shadow = self.user_home / ".local/bin/burnbag-viewer"
        shadow.parent.mkdir(parents=True)
        shadow.write_text("operator-owned\n")
        result = self.run_installer("--prefix", str(prefix), "--skip-prerequisites",
                                    "--user-home", str(self.user_home), environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(shadow.read_text(), "operator-owned\n")
        self.assertIn("Preserved unmanaged launcher", result.stderr)

    def test_direct_root_uses_home_without_requiring_prefix_on_path(self):
        prefix, environment = self.privileged_fixture()
        del environment["SUDO_UID"], environment["SUDO_USER"]
        self.write_command("getent", "exit 99")
        result = self.run_installer("--check", "--prefix", str(prefix), "--skip-prerequisites",
                                    environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(prefix.parent.exists())

    def test_root_dev_and_user_service_are_rejected_before_writes(self):
        prefix, environment = self.privileged_fixture()
        for arguments in (("--mode", "dev"), ("--install-user-service", "--prefix", str(prefix))):
            for check in ((), ("--check",)):
                with self.subTest(arguments=arguments, check=check):
                    result = self.run_installer(*arguments, *check, "--skip-prerequisites",
                                                environment=environment)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("non-root", result.stderr)
                    self.assertFalse(prefix.parent.exists())

    def test_sudo_missing_installed_command_fails_before_retiring_launchers(self):
        launcher, contents = self.existing_managed_launcher()
        prefix, environment = self.privileged_fixture()
        (self.checkout / "scripts/install_services.py").write_text("# Simulate incomplete publication.\n")
        result = self.run_installer("--prefix", str(prefix), "--skip-prerequisites", environment=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Installed command is not a regular executable", result.stderr)
        self.assertEqual(launcher.read_text(), contents)
        self.assertNotIn("[OK] Installed burnbag", result.stdout)

    def test_nonroot_ignores_sudo_metadata_and_keeps_path_guard(self):
        environment = self.environment()
        environment.update(SUDO_UID="invalid", SUDO_USER="nobody")
        result = self.run_installer("--mode", "dev", "--check", "--skip-prerequisites",
                                    environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        environment["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
        result = self.run_installer("--check", "--skip-prerequisites", environment=environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Standard command directory is not on PATH", result.stderr)

    def test_dev_install_preserves_private_existing_launcher_directory(self) -> None:
        user_bin = self.user_home / ".local/bin"
        user_bin.mkdir(parents=True, mode=0o700)
        result = self.run_installer("--mode", "dev", "--dev-command", "local", "--skip-prerequisites",
                                    "--user-home", str(self.user_home))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(user_bin.stat().st_mode & 0o777, 0o700)

    def test_obsolete_environment_policy_cannot_override_development_mode(self) -> None:
        environment = self.environment()
        environment["BURNBAG_DEV_LAUNCHER_MODE"] = "system"
        launcher, _ = self.existing_managed_launcher()

        result = self.run_installer(
            "--mode",
            "dev",
            "--skip-prerequisites",
            "--user-home",
            str(self.user_home),
            environment=environment,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(launcher.exists())
        self.assertEqual(self.resolve_burnbag(environment), str(launcher))
        self.assertIn("BURNBAG_DEV_LAUNCHER_MODE is ignored", result.stderr)

    def test_default_updates_existing_managed_launcher_to_this_checkout(self) -> None:
        launcher, original = self.existing_managed_launcher()
        result = self.run_installer("--mode", "dev", "--skip-prerequisites")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(launcher.read_text(), original)
        self.assertIn(str(self.checkout / "burnbag.py"), launcher.read_text())

    def test_legacy_conflicting_command_options_fail_before_writes(self) -> None:
        for mode, selection in (("dev", "system"), ("dev", "prompt"), ("standard", "local")):
            with self.subTest(mode=mode, selection=selection):
                result = self.run_installer("--mode", mode, "--dev-command", selection,
                                            "--skip-prerequisites")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("--mode determines commands and services", result.stderr)
                self.assertFalse((self.checkout / ".local").exists())

    def test_dev_check_preserves_existing_launcher_without_creating_checkout_links(self) -> None:
        launcher, original = self.existing_managed_launcher()
        result = self.run_installer("--mode", "dev", "--check", "--skip-prerequisites")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(launcher.read_text(), original)
        self.assertFalse((self.checkout / ".local").exists())

    def test_interactive_default_selects_checkout_without_prompt_or_input(self) -> None:
        master, slave = pty.openpty()
        process = subprocess.Popen(
            [str(self.checkout / "install.sh"), "--mode", "dev", "--skip-prerequisites"],
            cwd=self.checkout, env=self.environment(), stdin=slave, stdout=slave, stderr=slave,
        )
        os.close(slave)
        output = b""
        try:
            process.wait(timeout=10)
            while select.select([master], [], [], 0)[0]:
                try:
                    output += os.read(master, 4096)
                except OSError:
                    break
            self.assertEqual(process.returncode, 0, output.decode())
            self.assertNotIn(b"[y/N]", output)
            for command in ("burnbag", "burnbag-viewer", "burnbag-viewerctl"):
                self.assertTrue((self.user_home / ".local/bin" / command).is_file())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)

    def test_invalid_input_is_rejected_before_prerequisite_invocation(self) -> None:
        marker = self.run_root / "prerequisites-ran"
        prerequisite = self.checkout / "scripts" / "install_prerequisites.sh"
        prerequisite.write_text(
            "#!/usr/bin/bash\ntouch " + shlex.quote(str(marker)) + "\n", encoding="utf-8"
        )
        prerequisite.chmod(0o755)
        cases = [
            ("--mode", "dev", "--dev-command", "invalid"),
            ("--mode", "dev", "--dev-command", "invalid", "--check"),
            ("--mode", "dev", "--user-home", ""),
            ("--destdir", ""),
            ("--destdir", "/tmp/.."),
            ("--destdir", "//"),
            ("--destdir", str(self.run_root / "stage"), "--prefix", "/../escape"),
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                result = self.run_installer(*arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("[ERROR]", result.stderr)
                self.assertFalse(marker.exists())
                self.assertFalse((self.checkout / ".local").exists())

    def test_staging_rejects_symlink_escape_before_writing(self) -> None:
        stage = self.run_root / "stage"
        outside = self.run_root / "outside"
        stage.mkdir()
        outside.mkdir()
        (stage / "usr").symlink_to(outside, target_is_directory=True)
        result = self.run_installer("--destdir", str(stage), "--skip-prerequisites")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("escapes --destdir", result.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_staged_install_delivers_files_and_modes_without_privilege_or_mandb(self) -> None:
        stage = self.run_root / "stage"
        self.write_command("sudo", "exit 92")
        self.write_command("mandb", "exit 93")
        result = self.run_installer("--destdir", str(stage), "--skip-prerequisites")
        self.assertEqual(result.returncode, 0, result.stderr)
        for relative, source, mode in [
            ("usr/local/bin/burnbag", "burnbag.py", 0o755),
            ("usr/local/share/man/man1/burnbag.1", "burnbag.1", 0o644),
            ("usr/local/bin/burnbag-viewer", "burnbag_viewer.py", 0o755),
            ("usr/local/bin/burnbag-viewerctl", "burnbag_viewerctl.py", 0o755),
            ("usr/local/share/man/man1/burnbag-viewer.1", "burnbag-viewer.1", 0o644),
        ]:
            target = stage / relative
            self.assertEqual(target.read_bytes(), (self.checkout / source).read_bytes())
            self.assertEqual(target.stat().st_mode & 0o777, mode)
        manual = (stage / "usr/local/share/man/man1/burnbag.1").read_text()
        self.assertIn("\\-\\-last", manual)
        self.assertIn("Months and larger units use calendar arithmetic", manual)

    def test_staging_only_checks_prerequisites_and_stops_before_writes_on_failure(self) -> None:
        stage = self.run_root / "stage"
        marker = self.run_root / "prerequisite-arguments"
        prerequisite = self.checkout / "scripts" / "install_prerequisites.sh"
        prerequisite.write_text(
            '#!/usr/bin/bash\nprintf "%s\\n" "$@" > ' + shlex.quote(str(marker))
            + '\nprintf "[ERROR] Required Python bindings are unavailable.\\n" >&2\nexit 42\n',
            encoding="utf-8",
        )
        prerequisite.chmod(0o755)
        result = self.run_installer("--destdir", str(stage))
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(marker.read_text(), "--check\n")
        self.assertIn("Required Python bindings are unavailable", result.stderr)
        self.assertFalse(stage.exists())
        self.assertNotIn("[OK] Installed burnbag", result.stdout)

    def test_standard_install_refuses_directory_or_symlink_file_targets(self) -> None:
        stage = self.run_root / "stage"
        target = stage / "usr/local/bin/burnbag"
        target.parent.mkdir(parents=True)
        original = self.run_root / "operator-file"
        original.write_text("operator data", encoding="utf-8")
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    target.symlink_to(original)
                else:
                    target.mkdir()
                result = self.run_installer("--destdir", str(stage), "--skip-prerequisites")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("must not be a directory or symlink", result.stderr)
                self.assertEqual(original.read_text(), "operator data")
                if symlink:
                    target.unlink()
                else:
                    self.assertEqual(list(target.iterdir()), [])
                    target.rmdir()

    def test_launcher_directory_and_symlink_directory_are_refused_even_with_force(self) -> None:
        launcher = self.user_home / ".local" / "bin" / "burnbag"
        launcher.parent.mkdir(parents=True)
        directory = self.run_root / "operator-directory"
        directory.mkdir()
        sentinel = directory / "preserve"
        sentinel.write_text("operator data", encoding="utf-8")
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    launcher.symlink_to(directory, target_is_directory=True)
                else:
                    launcher.mkdir()
                result = self.run_installer(
                    "--mode", "dev", "--dev-command", "local", "--force", "--skip-prerequisites"
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("launcher directory", result.stderr)
                self.assertEqual(sentinel.read_text(), "operator data")
                self.assertEqual(list(launcher.parent.glob(".burnbag-launcher.*")), [])
                if symlink:
                    launcher.unlink()
                else:
                    self.assertEqual(list(launcher.iterdir()), [])
                    launcher.rmdir()

    def test_failed_launcher_publication_cleans_temporary_file_and_preserves_original(self) -> None:
        launcher, original = self.existing_managed_launcher()
        failures = {
            "write": ("mktemp", 'created=$(/usr/bin/mktemp "$@") || exit\n/usr/bin/chmod 0400 "$created"\nprintf "%s\\n" "$created"'),
            "chmod": ("chmod", "exit 73"),
            "rename": ("mv", "exit 74"),
        }
        for boundary, (name, body) in failures.items():
            with self.subTest(boundary=boundary):
                command = self.write_command(name, body)
                try:
                    result = self.run_installer(
                        "--mode", "dev", "--dev-command", "local", "--skip-prerequisites"
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("writing the managed user launcher", result.stderr)
                    self.assertEqual(launcher.read_text(), original)
                    self.assertEqual(list(launcher.parent.glob(".burnbag-launcher.*")), [])
                    self.assertNotIn("now select the development checkout", result.stdout)
                finally:
                    command.unlink()

    def test_partial_standard_install_failure_reports_context_without_success(self) -> None:
        stage = self.run_root / "stage"
        self.write_command(
            "install",
            'for arg in "$@"; do\n  case "$arg" in */burnbag.1) exit 75 ;; esac\ndone\nexec /usr/bin/install "$@"',
        )
        result = self.run_installer("--destdir", str(stage), "--skip-prerequisites")
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn("installing the executable and manual page", result.stderr)
        self.assertIn("Earlier steps may have completed", result.stderr)
        self.assertTrue((stage / "usr/local/bin/burnbag").is_file())
        self.assertFalse((stage / "usr/local/share/man/man1/burnbag.1").exists())
        self.assertNotIn("[OK] Installed burnbag", result.stdout)

    def test_local_selection_refuses_unmanaged_user_launcher(self) -> None:
        environment = self.environment()
        launcher = self.user_home / ".local" / "bin" / "burnbag"
        launcher.parent.mkdir(parents=True)
        original_contents = "#!/usr/bin/bash\nprintf 'operator launcher\\n'\n"
        launcher.write_text(original_contents, encoding="utf-8")
        launcher.chmod(0o755)

        result = self.run_installer(
            "--mode",
            "dev",
            "--dev-command",
            "local",
            "--skip-prerequisites",
            "--user-home",
            str(self.user_home),
            environment=environment,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Refusing to replace unmanaged launcher", result.stderr)
        self.assertEqual(launcher.read_text(), original_contents)

    def test_local_selection_fails_before_writing_when_user_bin_loses(self) -> None:
        environment = self.environment(user_bin_first=False)
        launcher = self.user_home / ".local" / "bin" / "burnbag"

        result = self.run_installer(
            "--mode",
            "dev",
            "--dev-command",
            "local",
            "--skip-prerequisites",
            "--user-home",
            str(self.user_home),
            environment=environment,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not precede the current burnbag command", result.stderr)
        self.assertFalse(launcher.exists())

    def test_isolated_assistant_home_requires_explicit_user_home(self) -> None:
        assistant_home = self.run_root / ".codex-home"
        assistant_home.mkdir()
        environment = self.environment()
        environment["HOME"] = str(assistant_home)

        result = self.run_installer(
            "--mode",
            "dev",
            "--skip-prerequisites",
            environment=environment,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("isolated assistant environment", result.stderr)
        self.assertIn("--user-home", result.stderr)

    def test_modern_isolated_homes_require_explicit_override(self) -> None:
        for relative_home in (".local/codex-home", ".local/claude-home", ".local/runtime/home"):
            with self.subTest(home=relative_home):
                assistant_home = self.checkout / relative_home
                assistant_home.mkdir(parents=True)
                environment = self.environment()
                environment["HOME"] = str(assistant_home)
                rejected = self.run_installer(
                    "--mode", "dev", "--skip-prerequisites",
                    environment=environment,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("isolated assistant environment", rejected.stderr)
                accepted = self.run_installer(
                    "--mode", "dev", "--skip-prerequisites",
                    "--user-home", str(self.user_home), environment=environment,
                )
                self.assertEqual(accepted.returncode, 0, accepted.stderr)
                self.assertFalse((assistant_home / ".local").exists())


if __name__ == "__main__":
    unittest.main()
