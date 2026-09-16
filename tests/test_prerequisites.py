"""Distribution package selection without touching the host package manager."""

from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PrerequisiteTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".local/tmp").mkdir(parents=True, exist_ok=True)
        self.workspace = tempfile.TemporaryDirectory(prefix="prerequisite-test.", dir=ROOT / ".local/tmp")
        self.root = Path(self.workspace.name)
        self.addCleanup(self.workspace.cleanup)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for command in ("apt-get", "dnf"):
            self.command(command, 'printf "%s %s\\n" "${0##*/}" "$*" >> "$TEST_CALLS"\n'
                         'if [ "$TEST_PACKAGE_FAIL" = yes ]; then exit 42; fi\n'
                         'touch "$TEST_INSTALLED"\n')
        self.command("sudo", 'exec "$@"\n')

    def command(self, name, body):
        target = self.bin / name
        target.write_text("#!/usr/bin/bash\n" + body)
        target.chmod(0o755)

    def run_check(self, distro, *args, failure=False, installed=False):
        marker = self.root / "installed"
        if installed:
            marker.touch()
        environment = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin",
                           TEST_DISTRO=distro, TEST_CALLS=str(self.root / "calls"),
                           TEST_INSTALLED=str(marker), TEST_PACKAGE_FAIL="yes" if failure else "no")
        return subprocess.run(
            ["/usr/bin/bash", "-c", '''
source "$1"
shift
read_distribution() { printf '%s\\n' "$TEST_DISTRO"; }
check_python() { return 0; }
check_pygobject() { [[ -f "$TEST_INSTALLED" ]]; }
check_gtk4() { [[ -f "$TEST_INSTALLED" ]]; }
main "$@"
''', "prerequisite-test", str(ROOT / "scripts/install_prerequisites.sh"), *args],
            env=environment, text=True, capture_output=True, timeout=10)

    def test_ubuntu_install_uses_apt_even_when_dnf_is_available(self):
        result = self.run_check("ubuntu debian")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "calls").read_text(),
                         "apt-get install -y python3-gi python3-gi-cairo gir1.2-glib-2.0 gir1.2-gtk-4.0\n")

    def test_rhel_derivative_retains_rpm_package(self):
        result = self.run_check("rocky rhel fedora")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "calls").read_text(), "dnf install -y python3-gobject gtk4\n")

    def test_check_does_not_install_and_reports_distribution_hint(self):
        result = self.run_check("ubuntu debian", "--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("sudo apt-get install python3-gi", result.stderr)
        self.assertFalse((self.root / "calls").exists())

    def test_unknown_distribution_does_not_guess_package_manager(self):
        result = self.run_check("unrecognized")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Cannot select packages", result.stderr)
        self.assertFalse((self.root / "calls").exists())

    def test_existing_bindings_need_no_package_operation(self):
        result = self.run_check("unrecognized", "--check", installed=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "calls").exists())

    def test_package_failure_is_actionable_and_nonzero(self):
        result = self.run_check("debian", failure=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("apt-get package installation failed", result.stderr)
        self.assertFalse((self.root / "installed").exists())


if __name__ == "__main__":
    unittest.main()
