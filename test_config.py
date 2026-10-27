import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from config import Settings
import server


class ConfigTests(unittest.TestCase):
    def test_production_cannot_enable_test_login(self):
        with self.assertRaisesRegex(ValueError, 'forbidden'):
            Settings.load({'MOMIQ_ENV': 'production', 'MOMIQ_DATA_DIR': str(Path.cwd()),
                           'MOMIQ_ALLOW_TEST_LOGIN': '1'}, Path.cwd())

    def test_hosted_settings_are_explicit_and_fail_closed(self):
        for mode in ('staging', 'production'):
            with self.assertRaisesRegex(ValueError, 'explicit'):
                Settings.load({'MOMIQ_ENV': mode}, Path.cwd())
            config = Settings.load({'MOMIQ_ENV': mode, 'MOMIQ_DATA_DIR': str(Path.cwd())}, Path.cwd())
            self.assertFalse(config.test_login)
        with self.assertRaises(ValueError):
            Settings.load({'MOMIQ_ENV': 'prodution'}, Path.cwd())

    def test_default_admin_sibling_and_port_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'backend'
            (Path(tmp) / 'momiq_admin').mkdir()
            self.assertEqual(Settings.load({}, root).admin, Path(tmp) / 'momiq_admin')
            with self.assertRaises(ValueError):
                Settings.load({'MOMIQ_PORT': '0'}, root)

    def test_database_cannot_cross_environments(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(server, 'DATA', Path(tmp)):
            with patch.object(server, 'ENVIRONMENT', 'local'):
                server.setup()
                server.setup()
            with patch.object(server, 'ENVIRONMENT', 'production'):
                with self.assertRaisesRegex(ValueError, 'different environment'):
                    server.setup()

    def test_production_default_has_no_login_even_if_local_defaults_enable_it(self):
        self.assertTrue(Settings.load({}, Path.cwd()).test_login)
        self.assertFalse(Settings.load({'MOMIQ_ENV': 'production',
                         'MOMIQ_DATA_DIR': str(Path.cwd())}, Path.cwd()).test_login)
