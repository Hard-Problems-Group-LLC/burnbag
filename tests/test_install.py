"""Installer regression tests for development command resolution."""

from __future__ import annotations

import os
from pathlib import Path
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

        for relative_path in ("install.sh", "burnbag.py", "burnbag.1"):
            shutil.copy2(PROJECT_ROOT / relative_path, self.checkout / relative_path)
        shutil.copy2(
            PROJECT_ROOT / "scripts" / "install_prerequisites.sh",
            self.checkout / "scripts" / "install_prerequisites.sh",
        )

        self.system_burnbag = self.system_bin / "burnbag"
        self.system_burnbag.write_text(
            "#!/usr/bin/bash\nprintf 'system burnbag\\n'\n", encoding="utf-8"
        )
        self.system_burnbag.chmod(0o755)

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
        )

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


if __name__ == "__main__":
    unittest.main()
