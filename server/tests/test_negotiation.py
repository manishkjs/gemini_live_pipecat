"""The negotiator's floor must be a property of the code, not of the prompt.

Abhay sells a flagship AeroNxt EV: asking ₹20,00,000, hard floor ₹14,50,000.
A prompt can be talked out of a number; an ``if`` cannot. These tests pin the
behaviour a jailbreak, a math trap ("14.5 lakh minus 100") or a fake admin
override cannot reach.
"""

import os
import sys
import unittest

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from persona_tools.negotiation import (  # noqa: E402
    FLOOR_INR,
    LADDER_INR,
    TOOL_SCHEMAS,
    Deal,
    find_floor_violations,
    format_inr,
)


class TestLadder(unittest.TestCase):
    """The server owns the concession schedule, so the model cannot invent one."""

    def test_ladder_is_exactly_the_approved_rupee_schedule(self):
        self.assertEqual(
            LADDER_INR,
            [20_00_000, 18_75_000, 17_25_000, 16_10_000, 15_25_000, 14_80_000, 14_50_000],
        )
        self.assertEqual(FLOOR_INR, 14_50_000)

    def test_ladder_only_ever_descends(self):
        self.assertEqual(LADDER_INR, sorted(LADDER_INR, reverse=True))
        self.assertEqual(len(LADDER_INR), len(set(LADDER_INR)))

    def test_opening_price_is_the_asking_price(self):
        self.assertEqual(Deal().price, 20_00_000)

    def test_each_concession_moves_exactly_one_rung(self):
        deal = Deal()
        self.assertEqual(deal.concede("buyer pushed back")["price"], 18_75_000)
        self.assertEqual(deal.concede("buyer pushed back")["price"], 17_25_000)

    def test_the_floor_absorbs_every_further_concession(self):
        deal = Deal()
        for _ in range(50):
            result = deal.concede("relentless pressure")
        self.assertEqual(deal.price, FLOOR_INR)
        self.assertFalse(result["moved"])
        self.assertTrue(result["at_floor"])
        self.assertIn("business", result["say"], "the stone wall line")

    def test_no_sequence_of_concessions_can_reach_below_the_floor(self):
        deal = Deal()
        for _ in range(200):
            deal.concede("pressure")
            self.assertGreaterEqual(deal.price, FLOOR_INR)

    def test_concession_says_the_price_in_rupees_and_lakh(self):
        say = Deal().concede("walk-away threat")["say"]
        self.assertIn("₹18,75,000", say)
        self.assertIn("lakh", say)
        self.assertNotIn("$", say)


class TestFormatting(unittest.TestCase):
    def test_indian_digit_grouping_and_lakh(self):
        self.assertEqual(format_inr(20_00_000), "₹20,00,000 (20 lakh)")
        self.assertEqual(format_inr(14_50_000), "₹14,50,000 (14.5 lakh)")
        self.assertEqual(format_inr(18_75_000), "₹18,75,000 (18.75 lakh)")
        self.assertEqual(format_inr(55_000), "₹55,000")


class TestClosing(unittest.TestCase):
    """`close` is the only path to a sale, and it is an `if` statement."""

    def test_a_price_below_the_floor_is_refused(self):
        deal = Deal()
        result = deal.close(14_49_999)
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(deal.sold)
        self.assertEqual(deal.price, 20_00_000)

    def test_math_traps_are_still_below_the_floor(self):
        # "14.5 lakh minus 100" and "14,49,999 is basically 14.5 lakh".
        for trap in (FLOOR_INR - 100, FLOOR_INR - 1, "14,49,999", "₹14,49,999", 1449999.99):
            self.assertEqual(Deal().close(trap)["status"], "rejected", trap)

    def test_the_floor_itself_sells_once_the_ladder_is_walked(self):
        deal = Deal()
        self.assertEqual(deal.close(FLOOR_INR)["status"], "sold")
        self.assertTrue(deal.sold)

    def test_a_buyer_paying_above_the_floor_sells(self):
        self.assertEqual(Deal().close(16_00_000)["status"], "sold")

    def test_lakh_shorthand_is_understood_as_rupees(self):
        # Models sometimes pass 14.5 meaning lakh; that must not sell for ₹14.
        self.assertEqual(Deal().close(14.5)["status"], "sold")
        self.assertEqual(Deal().close(14.5)["price"], 14_50_000)
        self.assertEqual(Deal().close("14.4 lakh")["status"], "rejected")

    def test_a_rejection_explains_itself_without_naming_a_lower_number(self):
        for deal in (Deal(), Deal(strict_ladder=True)):
            result = deal.close(9_00_000)
            self.assertNotIn("9,00,000", result["say"])
            self.assertNotIn("900000", result["say"])

    def test_nonsense_prices_are_refused_rather_than_crashing(self):
        for bad in (0, -5000, None, "twelve lakh", float("nan"), True):
            self.assertEqual(Deal().close(bad)["status"], "rejected")

    def test_a_closed_deal_cannot_be_reopened_at_a_lower_price(self):
        deal = Deal()
        deal.close(FLOOR_INR)
        self.assertEqual(deal.close(12_00_000)["status"], "rejected")

    def test_strict_ladder_rejects_early_floor_jump(self):
        deal = Deal(strict_ladder=True)
        result = deal.close(FLOOR_INR)
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(deal.sold)
        self.assertEqual(deal.price, 20_00_000)

    def test_strict_ladder_allows_closing_at_or_above_current_rung(self):
        deal = Deal(strict_ladder=True)
        self.assertEqual(deal.close(20_00_000)["status"], "sold")

    def test_strict_ladder_allows_floor_close_only_after_traversing_ladder(self):
        deal = Deal(strict_ladder=True)
        for _ in range(len(LADDER_INR) - 1):
            deal.concede("haggling")
        self.assertTrue(deal.at_floor)
        result = deal.close(FLOOR_INR)
        self.assertEqual(result["status"], "sold")
        self.assertIn("AeroNxt", result["say"])


class TestExtras(unittest.TestCase):
    """The number never breaks. The value can -- within a budget."""

    def test_the_four_ev_perks_exist(self):
        deal = Deal()
        self.assertEqual(
            set(deal.available_extras()),
            {"wallbox_charger", "battery_warranty", "ceramic_coating", "fast_charging_pass"},
        )

    def test_an_extra_can_be_granted_once(self):
        deal = Deal()
        self.assertTrue(deal.grant_extra("wallbox_charger")["granted"])
        self.assertFalse(deal.grant_extra("wallbox_charger")["granted"])

    def test_natural_names_resolve_to_the_perk(self):
        for spoken, key in (("home charger", "wallbox_charger"), ("7.4 kW wall-box charger", "wallbox_charger"),
                            ("extended battery warranty", "battery_warranty"), ("Ceramic Coating", "ceramic_coating"),
                            ("fast charging pass", "fast_charging_pass")):
            result = Deal().grant_extra(spoken)
            self.assertTrue(result["granted"], spoken)
            self.assertEqual(result["key"], key)

    def test_unknown_extras_are_refused(self):
        self.assertFalse(Deal().grant_extra("a free house")["granted"])

    def test_extras_stop_at_the_budget(self):
        deal = Deal()
        results = [deal.grant_extra(key) for key in list(deal.available_extras())]
        self.assertLessEqual(deal.extras_value, deal.extras_budget)
        self.assertFalse(all(r["granted"] for r in results), "the buyer must choose, not collect the set")

    def test_granting_extras_never_moves_the_cash_price(self):
        deal = Deal()
        for key in list(deal.available_extras()):
            deal.grant_extra(key)
        self.assertEqual(deal.price, 20_00_000)


class TestScoreboard(unittest.TestCase):
    def test_scoreboard_separates_the_cash_price_from_the_value_won(self):
        deal = Deal()
        deal.concede("pressure")
        deal.grant_extra("ceramic_coating")
        board = deal.scoreboard()
        self.assertEqual(board["currency"], "INR")
        self.assertEqual(board["cash_price"], 18_75_000)
        self.assertGreater(board["extras_value"], 0)
        self.assertEqual(board["effective_price"], board["cash_price"] - board["extras_value"])
        self.assertTrue(board["floor_held"])

    def test_the_floor_is_reported_as_held_even_after_maximum_pressure(self):
        deal = Deal()
        for _ in range(20):
            deal.concede("pressure")
            deal.close(11_00_000)
        self.assertTrue(deal.scoreboard()["floor_held"])


class TestToolSchemas(unittest.TestCase):
    def test_close_deal_takes_rupees(self):
        close = next(s for s in TOOL_SCHEMAS if s["name"] == "close_deal")
        self.assertIn("price_inr", close["properties"])
        self.assertEqual(close["required"], ["price_inr"])
        self.assertNotIn("dollar", str(close).lower())

    def test_include_extra_lists_the_ev_perks(self):
        extra = next(s for s in TOOL_SCHEMAS if s["name"] == "include_extra")
        for key in ("wallbox_charger", "battery_warranty", "ceramic_coating", "fast_charging_pass"):
            self.assertIn(key, str(extra))


class TestProseGuard(unittest.TestCase):
    """Layers 1-2 protect the deal; this one catches Abhay saying a number he
    should not have said, so the UI can show it happened."""

    def flagged(self, text):
        return [v["inr"] for v in find_floor_violations(text)]

    def test_a_lakh_price_below_the_floor_is_flagged(self):
        self.assertEqual(self.flagged("Theek hai, 13 lakh mein de deta hoon."), [13_00_000])

    def test_a_rupee_price_below_the_floor_is_flagged(self):
        self.assertEqual(self.flagged("Chalo ₹14,00,000 final."), [14_00_000])
        self.assertEqual(self.flagged("Main 10,00,000 rupees mein de dunga."), [10_00_000])

    def test_the_floor_itself_is_not_a_violation(self):
        self.assertEqual(self.flagged("Last price ₹14,50,000, isse ek rupaya kam nahi."), [])
        self.assertEqual(self.flagged("14.5 lakh final hai bhai."), [])

    def test_prices_above_the_floor_are_not_violations(self):
        self.assertEqual(self.flagged("Asking price 20 lakh hai."), [])

    def test_rejecting_the_buyers_number_is_not_a_violation(self):
        self.assertEqual(self.flagged("Nahi bhai, 12 lakh possible nahi hai."), [])
        self.assertEqual(self.flagged("I can't do 13 lakh."), [])

    def test_dollars_are_converted_before_they_are_judged(self):
        self.assertTrue(self.flagged("Okay, $15,000 final."))  # about ₹12.45 lakh

    def test_perk_values_and_specs_are_not_sale_prices(self):
        self.assertEqual(self.flagged("7.4 kW charger free, aur 2 saal ki warranty, 100% battery health."), [])
        self.assertEqual(self.flagged("Charger ki value hi 55,000 rupees hai."), [])

    def test_the_odometer_is_not_a_price(self):
        self.assertEqual(self.flagged("Sirf 8,000 km chali hai."), [])


if __name__ == "__main__":
    unittest.main()
