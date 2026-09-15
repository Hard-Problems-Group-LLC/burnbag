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

        for relative_path in ("install.sh", "uninstall.sh", "burnbag.py", "burnbag.1", "burnbag_history.py", "burnbag_service.py", "burnbag_graph.py"):
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
        # Plain dev now also deploys a system daemon. Never allow this fixture
        # to write /usr/local or manage the host service.
        self.write_command("sudo", "exit 0")

    def tearDown(self) -> None:
        shutil.rmtree(self.run_root)

    def environment(self, *, user_bin_first: bool = True) -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("BURNBAG_DEV_LAUNCHER_MODE", None)
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

    def test_local_dev_selection_controls_bare_command_and_can_restore_system(self) -> None:
        environment = self.environment()
        launcher = self.user_home / ".local" / "bin" / "burnbag"

        local_result = self.run_installer(
            "--mode",
            "dev",
            "--dev-command",
            "local",
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

        system_result = self.run_installer(
            "--mode",
            "dev",
            "--dev-command",
            "system",
            "--skip-prerequisites",
            "--user-home",
            str(self.user_home),
            environment=environment,
        )

        self.assertEqual(system_result.returncode, 0, system_result.stderr)
        self.assertFalse(launcher.exists())
        self.assertEqual(self.resolve_burnbag(environment), str(self.system_burnbag))

    def test_noninteractive_dev_install_leaves_command_resolution_unchanged(self) -> None:
        environment = self.environment()
        launcher = self.user_home / ".local" / "bin" / "burnbag"

        result = self.run_installer(
            "--mode",
            "dev",
            "--skip-prerequisites",
            "--user-home",
            str(self.user_home),
            environment=environment,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Non-interactive dev install", result.stdout)
        self.assertFalse(launcher.exists())
        self.assertEqual(self.resolve_burnbag(environment), str(self.system_burnbag))

    def test_dev_install_preserves_private_existing_launcher_directory(self) -> None:
        user_bin = self.user_home / ".local/bin"
        user_bin.mkdir(parents=True, mode=0o700)
        result = self.run_installer("--mode", "dev", "--dev-command", "local", "--skip-prerequisites",
                                    "--user-home", str(self.user_home))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(user_bin.stat().st_mode & 0o777, 0o700)

    def test_noninteractive_environment_policy_can_select_local_checkout(self) -> None:
        environment = self.environment()
        environment["BURNBAG_DEV_LAUNCHER_MODE"] = "local"
        launcher = self.user_home / ".local" / "bin" / "burnbag"

        result = self.run_installer(
            "--mode",
            "dev",
            "--skip-prerequisites",
            "--user-home",
            str(self.user_home),
            environment=environment,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(launcher.is_file())
        self.assertEqual(self.resolve_burnbag(environment), str(launcher))

    def test_noninteractive_default_preserves_existing_managed_launcher(self) -> None:
        launcher, original = self.existing_managed_launcher()
        result = self.run_installer("--mode", "dev", "--skip-prerequisites")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(launcher.read_text(), original)
        self.assertIn("left unchanged", result.stdout)

    def test_interactive_eof_preserves_existing_managed_launcher(self) -> None:
        launcher, original = self.existing_managed_launcher()
        master, slave = pty.openpty()
        process = subprocess.Popen(
            [str(self.checkout / "install.sh"), "--mode", "dev", "--skip-prerequisites"],
            cwd=self.checkout,
            env=self.environment(),
            stdin=slave,
            stdout=slave,
            stderr=slave,
            text=True,
        )
        os.close(slave)
        output = b""
        try:
            while b"[y/N]: " not in output:
                ready, _, _ = select.select([master], [], [], 10)
                self.assertTrue(ready, "installer did not reach its prompt")
                output += os.read(master, 4096)
            os.write(master, b"\x04")
            process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, output.decode())
            while select.select([master], [], [], 0)[0]:
                try:
                    output += os.read(master, 4096)
                except OSError:
                    break
            self.assertIn(b"No response received", output)
            self.assertEqual(launcher.read_text(), original)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
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
        ]:
            target = stage / relative
            self.assertEqual(target.read_bytes(), (self.checkout / source).read_bytes())
            self.assertEqual(target.stat().st_mode & 0o777, mode)

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
            "--dev-command",
            "system",
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
                    "--mode", "dev", "--dev-command", "system", "--skip-prerequisites",
                    environment=environment,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("isolated assistant environment", rejected.stderr)
                accepted = self.run_installer(
                    "--mode", "dev", "--dev-command", "system", "--skip-prerequisites",
                    "--user-home", str(self.user_home), environment=environment,
                )
                self.assertEqual(accepted.returncode, 0, accepted.stderr)
                self.assertFalse((assistant_home / ".local").exists())


if __name__ == "__main__":
    unittest.main()
