"""Unit tests for the pure-Python parts of mac_actions (run on any OS)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mac_actions  # noqa: E402


class AssessTextTest(unittest.TestCase):

    def test_flags_destructive_commands(self):
        for cmd in (
            "rm -rf /var/data",
            "rm -fr build",
            "DROP TABLE users;",
            "drop database prod",
            "DELETE FROM orders",
            "terraform destroy -auto-approve",
            "kubectl delete deployment checkout",
            "gcloud sql instances delete prod-db",
            "git push --force origin main",
            "git reset --hard HEAD~3",
        ):
            with self.subTest(cmd=cmd):
                self.assertTrue(mac_actions.assess_text(cmd).risky)

    def test_allows_everyday_commands(self):
        for cmd in (
            "kubectl get pods",
            "git status",
            "gcloud run services list",
            "DELETE FROM orders WHERE id = 7",
            "hello from jarvis",
        ):
            with self.subTest(cmd=cmd):
                self.assertFalse(mac_actions.assess_text(cmd).risky)


class AssessClickTest(unittest.TestCase):

    def test_flags_consequential_buttons(self):
        self.assertTrue(mac_actions.assess_click("Deploy to production button").risky)
        self.assertTrue(mac_actions.assess_click("Delete database").risky)
        self.assertTrue(mac_actions.assess_click("Pay now").risky)
        self.assertTrue(mac_actions.assess_click("Place order on Swiggy").risky)

    def test_allows_navigation(self):
        self.assertFalse(mac_actions.assess_click("Logs tab").risky)
        self.assertFalse(mac_actions.assess_click("search box").risky)

    def test_reason_names_the_trigger_word(self):
        self.assertIn("delete", mac_actions.assess_click("Delete database").reason)


class KeyComboTest(unittest.TestCase):

    def test_plain_letter_with_modifiers(self):
        self.assertEqual(
            mac_actions.key_combo_to_applescript("cmd+shift+t"),
            'tell application "System Events" to keystroke "t" using {command down, shift down}',
        )

    def test_named_key_uses_key_code(self):
        self.assertEqual(
            mac_actions.key_combo_to_applescript("enter"),
            'tell application "System Events" to key code 36',
        )

    def test_rejects_unknown_key_and_modifier(self):
        with self.assertRaises(ValueError):
            mac_actions.key_combo_to_applescript("cmd+f13x")
        with self.assertRaises(ValueError):
            mac_actions.key_combo_to_applescript("hyper+a")
        with self.assertRaises(ValueError):
            mac_actions.key_combo_to_applescript("")

    def test_escapes_quotes(self):
        self.assertIn('keystroke "\\""', mac_actions.key_combo_to_applescript('"'))


class MeetAndMobileHelpersTest(unittest.TestCase):

    def test_normalize_meet_url(self):
        self.assertEqual(
            mac_actions.normalize_meet_url("abc-defg-hij"),
            "https://meet.google.com/abc-defg-hij",
        )
        self.assertEqual(
            mac_actions.normalize_meet_url("meet.google.com/abc-defg-hij"),
            "https://meet.google.com/abc-defg-hij",
        )
        self.assertEqual(
            mac_actions.normalize_meet_url("https://meet.google.com/abc-defg-hij"),
            "https://meet.google.com/abc-defg-hij",
        )
        with self.assertRaises(ValueError):
            mac_actions.normalize_meet_url("   ")

    def test_chrome_profile_command_and_drawio_url(self):
        cmd = mac_actions.chrome_profile_command("https://meet.google.com/x", "/tmp/p")
        self.assertIn("--user-data-dir=/tmp/p", cmd)
        self.assertEqual(cmd[-1], "https://meet.google.com/x")
        self.assertEqual(mac_actions.drawio_url(), "https://app.diagrams.net/?splash=0")

    def test_resolve_audio_device_index(self):
        devices = [
            {"name": "MacBook Pro Microphone", "maxInputChannels": 1, "maxOutputChannels": 0},
            {"name": "BlackHole 2ch", "maxInputChannels": 2, "maxOutputChannels": 2},
            {"name": "BlackHole 16ch", "maxInputChannels": 16, "maxOutputChannels": 16},
        ]
        self.assertIsNone(mac_actions.resolve_audio_device_index(None, devices, "input"))
        self.assertEqual(mac_actions.resolve_audio_device_index("1", devices, "input"), 1)
        self.assertEqual(
            mac_actions.resolve_audio_device_index("blackhole 16ch", devices, "output"), 2
        )
        with self.assertRaises(ValueError):
            mac_actions.resolve_audio_device_index("0", devices, "output")
        with self.assertRaises(ValueError):
            mac_actions.resolve_audio_device_index("missing", devices, "input")

    def test_adb_helpers(self):
        out = "List of devices attached\nemulator-5554\tdevice\n"
        self.assertEqual(mac_actions.adb_device_serial(out), "emulator-5554")
        self.assertIsNone(mac_actions.adb_device_serial("List of devices attached\n"))
        self.assertEqual(mac_actions.resolve_android_package("Swiggy"), "in.swiggy.android")
        self.assertEqual(
            mac_actions.resolve_android_package("com.example.app"), "com.example.app"
        )


if __name__ == "__main__":
    unittest.main()
