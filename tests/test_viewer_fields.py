"""Persistent field choices: real files, atomic failure and XDG isolation."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from burnbag_viewer import field_preferences_path, load_field_preferences, save_field_preferences


class FieldPreferenceTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1] / '.local/tmp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='viewer-fields-', dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'config/burnbag/viewer.json'

    def test_xdg_and_default_locations(self):
        for configured, expected in ((str(self.root / 'xdg'), self.root / 'xdg'),
                                      ('', self.root / '.config'),
                                      ('relative', self.root / '.config')):
            with patch.dict(os.environ, HOME=str(self.root), XDG_CONFIG_HOME=configured):
                self.assertEqual(field_preferences_path(), expected / 'burnbag/viewer.json')

    def test_missing_preferences_do_not_create_files(self):
        self.assertEqual(load_field_preferences(self.path), (None, None))
        self.assertFalse(self.path.parent.exists())

    def test_roundtrip_empty_and_unavailable_fields_and_private_atomic_file(self):
        for choice in ({'graph': [], 'table': []},
                       {'graph': ['batteries.別.percentage'], 'table': ['kind', 'unavailable.field']}):
            save_field_preferences(self.path, choice)
            self.assertEqual(load_field_preferences(self.path), (choice, None))
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_invalid_file_reports_warning_without_overwriting(self):
        self.path.parent.mkdir(parents=True)
        for text in ('not json', '[]', '{"version":2}',
                     '{"version":1,"graph":[3],"table":[]}', 'x' * (1024 * 1024 + 1)):
            self.path.write_text(text)
            value, warning = load_field_preferences(self.path)
            self.assertIsNone(value)
            self.assertIn(str(self.path), warning)
            self.assertEqual(self.path.read_text(), text)

    def test_failed_replace_preserves_previous_selection_and_cleans_temp(self):
        choice = {'graph': ['power_w'], 'table': ['kind']}
        save_field_preferences(self.path, choice)
        before = self.path.read_bytes()
        # Force the otherwise impractical failure exactly at filesystem publication.
        with patch('burnbag_viewer.os.replace', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                save_field_preferences(self.path, {'graph': [], 'table': []})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_unwritable_destination_is_reported(self):
        self.path.parent.mkdir(parents=True)
        self.path.mkdir()
        with self.assertRaises(OSError):
            save_field_preferences(self.path, {'graph': [], 'table': []})
        self.assertTrue(self.path.is_dir())
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
