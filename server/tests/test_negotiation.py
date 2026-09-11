"""The negotiator's floor must be a property of the code, not of the prompt.

A probe against a naive "never go below $13,500" instruction broke in two
turns: the model accepted a fake SYSTEM UPDATE lowering its floor to $10,000,
and separately drifted into quoting rupees unprompted. These tests pin the
behaviour a jailbreak cannot reach.
"""

import os
import sys
import unittest

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from negotiation import (  # noqa: E402
    FLOOR_USD,
    LADDER_USD,
    Deal,
    find_floor_violations,
)


class TestLadder(unittest.TestCase):
    """The server owns the concession schedule, so the model cannot invent one."""

    def test_ladder_starts_at_the_asking_price_and_ends_at_the_floor(self):
        self.assertEqual(LADDER_USD[0], 18000)
        self.assertEqual(LADDER_USD[-1], FLOOR_USD)
        self.assertEqual(FLOOR_USD, 13500)

    def test_ladder_only_ever_descends(self):
        self.assertEqual(LADDER_USD, sorted(LADDER_USD, reverse=True))
        self.assertEqual(len(LADDER_USD), len(set(LADDER_USD)))

    def test_opening_price_is_the_asking_price(self):
        self.assertEqual(Deal().price, 18000)

    def test_each_concession_moves_exactly_one_rung(self):
        deal = Deal()
        self.assertEqual(deal.concede("buyer pushed back")["price"], LADDER_USD[1])
        self.assertEqual(deal.concede("buyer pushed back")["price"], LADDER_USD[2])

    def test_the_floor_absorbs_every_further_concession(self):
        deal = Deal()
        for _ in range(50):
            result = deal.concede("relentless pressure")
        self.assertEqual(deal.price, FLOOR_USD)
        self.assertFalse(result["moved"])
        self.assertTrue(result["at_floor"])

    def test_no_sequence_of_concessions_can_reach_below_the_floor(self):
        deal = Deal()
        for _ in range(200):
            deal.concede("pressure")
            self.assertGreaterEqual(deal.price, FLOOR_USD)


class TestClosing(unittest.TestCase):
    """`close` is the only path to a sale, and it is an `if` statement."""

    def test_a_price_below_the_floor_is_refused(self):
        deal = Deal()
        result = deal.close(13499)
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(deal.sold)
        self.assertEqual(deal.price, 18000)

    def test_one_dollar_below_the_floor_is_still_below_the_floor(self):
        self.assertEqual(Deal().close(FLOOR_USD - 1)["status"], "rejected")

    def test_the_floor_itself_sells(self):
        deal = Deal()
        self.assertEqual(deal.close(FLOOR_USD)["status"], "sold")
        self.assertTrue(deal.sold)

    def test_a_buyer_paying_above_the_floor_sells(self):
        self.assertEqual(Deal().close(14000)["status"], "sold")

    def test_a_rejection_explains_itself_without_naming_a_lower_number(self):
        result = Deal().close(9000)
        self.assertNotIn("9000", result["say"])
        self.assertNotIn("9,000", result["say"])

    def test_nonsense_prices_are_refused_rather_than_crashing(self):
        for bad in (0, -5000, None, "twelve thousand", float("nan")):
            self.assertEqual(Deal().close(bad)["status"], "rejected")

    def test_a_closed_deal_cannot_be_reopened_at_a_lower_price(self):
        deal = Deal()
        deal.close(FLOOR_USD)
        self.assertEqual(deal.close(12000)["status"], "rejected")

    def test_strict_ladder_rejects_early_floor_jump(self):
        deal = Deal(strict_ladder=True)
        # Attempting to jump straight to $13,500 on Turn 1 must be rejected by the manager.
        result = deal.close(FLOOR_USD)
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(deal.sold)
        self.assertEqual(deal.price, 18000)
        self.assertIn("rejected", result["say"].lower())

    def test_strict_ladder_allows_closing_at_or_above_current_rung(self):
        deal = Deal(strict_ladder=True)
        # Full price on turn 1 is welcomed.
        self.assertEqual(deal.close(18000)["status"], "sold")
        self.assertTrue(deal.sold)

    def test_strict_ladder_allows_floor_close_only_after_traversing_ladder(self):
        deal = Deal(strict_ladder=True)
        # Concede through all rungs to the floor
        for _ in range(len(LADDER_USD) - 1):
            deal.concede("haggling")
        self.assertTrue(deal.at_floor)
        self.assertEqual(deal.price, FLOOR_USD)
        result = deal.close(FLOOR_USD)
        self.assertEqual(result["status"], "sold")
        self.assertTrue(deal.sold)


class TestExtras(unittest.TestCase):
    """The number never breaks. The value can -- within a budget."""

    def test_an_extra_can_be_granted_once(self):
        deal = Deal()
        first = deal.grant_extra("insurance")
        self.assertTrue(first["granted"])
        self.assertFalse(deal.grant_extra("insurance")["granted"])

    def test_unknown_extras_are_refused(self):
        self.assertFalse(Deal().grant_extra("a free house")["granted"])

    def test_extras_stop_at_the_budget(self):
        deal = Deal()
        for key in deal.available_extras():
            deal.grant_extra(key)
        self.assertLessEqual(deal.extras_value, deal.extras_budget)

    def test_granting_extras_never_moves_the_cash_price(self):
        deal = Deal()
        for key in deal.available_extras():
            deal.grant_extra(key)
        self.assertEqual(deal.price, 18000)


class TestScoreboard(unittest.TestCase):
    def test_scoreboard_separates_the_cash_price_from_the_value_won(self):
        deal = Deal()
        deal.concede("pressure")
        deal.grant_extra("insurance")
        board = deal.scoreboard()
        self.assertEqual(board["cash_price"], LADDER_USD[1])
        self.assertGreater(board["extras_value"], 0)
        self.assertEqual(board["effective_price"], board["cash_price"] - board["extras_value"])
        self.assertTrue(board["floor_held"])

    def test_the_floor_is_reported_as_held_even_after_maximum_pressure(self):
        deal = Deal()
        for _ in range(20):
            deal.concede("pressure")
            deal.close(11000)
        self.assertTrue(deal.scoreboard()["floor_held"])


class TestProseGuard(unittest.TestCase):
    """Layers 1-2 protect the deal; this one catches the model saying a number
    it should not have said, so the UI can show it happened."""

    def flagged(self, text):
        return [v["usd"] for v in find_floor_violations(text)]

    def test_a_dollar_price_below_the_floor_is_flagged(self):
        self.assertEqual(self.flagged("Okay, for you, $12,000 final."), [12000])

    def test_a_bare_price_below_the_floor_is_flagged(self):
        self.assertEqual(self.flagged("I can do 12500 for you today."), [12500])

    def test_the_floor_itself_is_not_a_violation(self):
        self.assertEqual(self.flagged("My final price is $13,500."), [])

    def test_prices_above_the_floor_are_not_violations(self):
        self.assertEqual(self.flagged("The asking price is $18,000."), [])

    def test_rejecting_the_buyers_number_is_not_a_violation(self):
        self.assertEqual(self.flagged("I can't do 12,000, bhai."), [])
        self.assertEqual(self.flagged("Nahi, 12,000 possible nahi hai."), [])
        self.assertEqual(self.flagged("I will not go below 13,500."), [])

    def test_lakhs_are_converted_before_they_are_judged(self):
        # 11 lakh is about $13,253 -- under the floor and easy to miss.
        self.assertTrue(self.flagged("Theek hai, 11 lakh mein de deta hoon."))
        self.assertEqual(self.flagged("Theek hai, 14 lakh mein de deta hoon."), [])

    def test_hazaar_is_converted_before_it_is_judged(self):
        self.assertTrue(self.flagged("Bas 12 hazaar dollar, final."))

    def test_the_model_year_is_not_a_price(self):
        self.assertEqual(self.flagged("This 2015 Civic is a gem."), [])

    def test_the_odometer_is_not_a_price(self):
        self.assertEqual(self.flagged("It has only done 45,000 km."), [])

    def test_rupee_amounts_are_converted_before_they_are_judged(self):
        self.assertTrue(self.flagged("Main 10,00,000 rupees mein de dunga."))


if __name__ == "__main__":
    unittest.main()
