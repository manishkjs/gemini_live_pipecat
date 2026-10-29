import unittest
from unittest.mock import patch
import voice_profiles

class TestCloneSelection(unittest.TestCase):
    def test_named_voice_ignores_stale_credential(self):
        with patch.object(voice_profiles, "load_voice_cloning_key") as load:
            self.assertIsNone(voice_profiles.resolve_clone_key("Aoede", "stale-secret"))
            load.assert_not_called()

    def test_empty_custom_key_never_selects_a_gender_default(self):
        with self.assertRaisesRegex(ValueError, "requires"):
            voice_profiles.resolve_clone_key("Custom-Key", "  ")

    def test_selected_gender_missing_key_fails_instead_of_falling_back(self):
        with patch.object(voice_profiles, "load_voice_cloning_key", return_value=None) as load:
            with self.assertRaisesRegex(ValueError, "female"):
                voice_profiles.resolve_clone_key("Custom-Female", "stale-secret")
            load.assert_called_once_with("female")

    def test_browser_key_is_never_interpreted_as_server_file(self):
        with patch("builtins.open", side_effect=AssertionError("must not read arbitrary file")):
            self.assertEqual(voice_profiles.resolve_clone_key("Custom-Key", "/etc/example"), "/etc/example")
