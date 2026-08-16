import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Scripts')))

import settings


class TestSettingsModule(unittest.TestCase):
    def test_str2bool_conversion(self):
        self.assertTrue(settings.str2bool("true"))
        self.assertTrue(settings.str2bool("True"))
        self.assertTrue(settings.str2bool("1"))
        self.assertTrue(settings.str2bool("yes"))
        self.assertFalse(settings.str2bool("false"))
        self.assertFalse(settings.str2bool("0"))
        self.assertFalse(settings.str2bool("no"))

    def test_default_settings_loaded(self):
        self.assertIsNotNone(settings.versionNumber)
        self.assertIsInstance(settings.DEBUG_MODE, bool)
        self.assertIsInstance(settings.AUDIO_ENABLED, bool)
        self.assertIsInstance(settings.MULTI_USER, bool)
        self.assertIsInstance(settings.TASK_FREQUENCY, int)


if __name__ == "__main__":
    unittest.main()
