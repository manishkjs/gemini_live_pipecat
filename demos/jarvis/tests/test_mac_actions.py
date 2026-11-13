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
        self.assertEqual(
            mac_actions.normalize_meet_url("abcdefghij"),
            "https://meet.google.com/abc-defg-hij",
        )
        self.assertEqual(
            mac_actions.normalize_meet_url("https://meet.google.com/abc-defg-hij?authuser=0"),
            "https://meet.google.com/abc-defg-hij",
        )

    def test_normalize_meet_url_new_meeting(self):
        for word in ["new", "instant", "start", "New Meeting", "   ", "", None,
                     "meet.google.com/new", "https://meet.google.com/new"]:
            self.assertEqual(
                mac_actions.normalize_meet_url(word), "https://meet.google.com/new", word
            )

    def test_normalize_meet_url_rejects_bogus(self):
        for bad in ["standup", "https://meet.google.com/instant", "https://evil.com/abc-defg-hij"]:
            with self.assertRaises(ValueError, msg=bad):
                mac_actions.normalize_meet_url(bad)

    def test_chrome_open_command(self):
        self.assertEqual(
            mac_actions.chrome_open_command("https://meet.google.com/new"),
            ["open", "-a", "Google Chrome", "https://meet.google.com/new"],
        )

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

    def test_adb_input_text_keeps_letters_and_escapes_shell_chars(self):
        self.assertEqual(mac_actions.adb_input_text("swiggy"), "swiggy")
        self.assertEqual(mac_actions.adb_input_text("masala dosa"), "masala%sdosa")
        self.assertEqual(mac_actions.adb_input_text("rock & roll"), "rock%s\\&%sroll")
        self.assertEqual(mac_actions.adb_input_text("it's"), "it\\'s")

    def test_frontmost_pid_script(self):
        self.assertEqual(
            mac_actions.frontmost_pid_script(4242),
            'tell application "System Events" to set frontmost of '
            "(first process whose unix id is 4242) to true",
        )

    def test_click_uses_each_displays_own_geometry(self):
        desk = mac_actions.MacDesktop()
        desk._geometry = {1: (0.0, 0.0, 1.0), 2: (1710.0, 0.0, 1.25)}
        self.assertEqual(desk.to_global_point(100, 200, 2), (1835.0, 250.0))
        # Follow-up calls without a display stay on display 2.
        self.assertEqual(desk.to_global_point(0, 0), (1710.0, 0.0))
        self.assertEqual(desk.to_global_point(100, 200, 1), (100.0, 200.0))
        with self.assertRaises(ValueError):
            desk.to_global_point(1, 1, 3)

    def test_map_screenshot_point_multi_display(self):
        # Main display at (0, 0)
        self.assertEqual(
            mac_actions.map_screenshot_point(100, 200, 0.0, 0.0, 1.5),
            (150.0, 300.0),
        )
        # Secondary display positioned to the right at (1710, 0)
        self.assertEqual(
            mac_actions.map_screenshot_point(100, 200, 1710.0, 0.0, 1.25),
            (1835.0, 250.0),
        )
        # Secondary display positioned to the left at (-1920, 0)
        self.assertEqual(
            mac_actions.map_screenshot_point(100, 200, -1920.0, 0.0, 1.0),
            (-1820.0, 200.0),
        )


if __name__ == "__main__":
    unittest.main()


class DrawioMailChromeTest(unittest.TestCase):

    CODE = """graph TD
        User[Clients] --> Web[Presentation Layer]
        Web --> App[Application Layer]
        App -->|SQL| DB[(Database Layer)]
        App --> C & D
    """

    def test_parse_mermaid_flowchart(self):
        chart = mac_actions.parse_mermaid_flowchart(self.CODE)
        self.assertEqual(chart.direction, "TD")
        self.assertEqual(chart.nodes["DB"].label, "Database Layer")
        self.assertIn("cylinder", chart.nodes["DB"].style)
        self.assertIn(("App", "DB", "SQL"), chart.edges)
        self.assertIn(("App", "C", ""), chart.edges)
        self.assertIn(("App", "D", ""), chart.edges)
        with self.assertRaises(ValueError):
            mac_actions.parse_mermaid_flowchart("sequenceDiagram\n A->>B: hi")

    def test_drawio_url_round_trips(self):
        import base64
        import urllib.parse
        import zlib

        url = mac_actions.mermaid_to_drawio_url(self.CODE, "3-tier")
        self.assertTrue(url.startswith("https://app.diagrams.net/?splash=0#R"))
        b64 = urllib.parse.unquote(url.split("#R", 1)[1])
        xml = urllib.parse.unquote(zlib.decompress(base64.b64decode(b64), -15).decode())
        self.assertIn('value="Presentation Layer"', xml)
        self.assertEqual(xml.count('edge="1"'), 5)

    def test_gmail_compose_url_keeps_account(self):
        self.assertEqual(
            mac_actions.gmail_compose_url("https://mail.google.com/mail/u/2/#inbox"),
            "https://mail.google.com/mail/u/2/#inbox?compose=new",
        )
        url = mac_actions.gmail_compose_url("", to="a@b.com", subject="Hi there")
        self.assertTrue(url.startswith("https://mail.google.com/mail/u/0/?view=cm"))
        self.assertIn("su=Hi%20there", url)

    def test_pick_user_chrome_pid_skips_jarvis_and_helpers(self):
        bin_ = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        lines = [
            f"97606 {bin_} --user-data-dir=/Users/x/.jarvis-chrome-profile --no-first-run",
            f"97637 {bin_} Helper --type=renderer",
            f"2367 {bin_}",
        ]
        self.assertEqual(
            mac_actions.pick_user_chrome_pid(lines, "/Users/x/.jarvis-chrome-profile"), 2367
        )
        self.assertIsNone(mac_actions.pick_user_chrome_pid(lines[:2], "/Users/x/.jarvis-chrome-profile"))


class ClickTextScoringTest(unittest.TestCase):

    def test_exact_and_role_beat_partial(self):
        s = mac_actions.score_ui_match
        exact = s("Join now", "Join now", "AXButton")
        contains = s("Join now", "Click here to join now please", "AXStaticText")
        self.assertGreater(exact, contains)
        self.assertGreater(s("theo", "Theo - t3.gg", "AXLink"), 0)

    def test_requires_all_words_for_short_queries(self):
        s = mac_actions.score_ui_match
        self.assertEqual(s("Docs home", "Running test find_ui_elements on docs", "AXButton"), 0.0)
        self.assertGreater(s("rust infrastructure", "Why AI Infrastructure Is Moving to Rust", "AXLink"), 0)
        self.assertEqual(s("", "anything", "AXButton"), 0.0)


class ScrollStepsTest(unittest.TestCase):

    def test_notches_and_pixels(self):
        self.assertEqual(sum(mac_actions.scroll_steps(-5)), -500)
        self.assertEqual(sum(mac_actions.scroll_steps(-500)), -500)
        self.assertEqual(sum(mac_actions.scroll_steps(3)), 300)
        self.assertTrue(all(abs(s) <= 60 for s in mac_actions.scroll_steps(-800)))
        self.assertEqual(sum(mac_actions.scroll_steps(-100000)), -6000)
        self.assertEqual(mac_actions.scroll_steps(0), [])


class SiteSearchTest(unittest.TestCase):

    def test_site_search_urls(self):
        self.assertEqual(
            mac_actions.site_search_url("YouTube", "google cloud videos"),
            "https://www.youtube.com/results?search_query=google+cloud+videos",
        )
        self.assertEqual(
            mac_actions.site_search_url("gmail", "from:boss", "https://mail.google.com/mail/u/1/#inbox"),
            "https://mail.google.com/mail/u/1/#search/from%3Aboss",
        )
        with self.assertRaises(ValueError):
            mac_actions.site_search_url("myspace", "x")

    def test_maps_directions_url(self):
        url = mac_actions.maps_directions_url("Raja Ritz Avenue", "Google Kyoto office, Bengaluru", "driving")
        self.assertTrue(url.startswith("https://www.google.com/maps/dir/?api=1&origin=Raja+Ritz+Avenue"))
        self.assertIn("travelmode=driving", url)
