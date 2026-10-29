"""Tara (Book My Trip): engine contract, card delivery, context_update tool swaps, wiring."""
import asyncio
import datetime as dt
import json
import re
import unittest

from persona_prompt_cards.tara_cards import (
    RESEND_AFTER_TRIM,
    RESEND_NEW_SESSION,
    TARA_CARD_BY_NUMBER,
    TARA_PHASE_IDS,
    get_tara_monolithic_system_instruction,
    get_tara_root_system_instruction,
)
from persona_tools.travel_booking import (
    CALLING_NUMBER,
    TOOL_DECLARATIONS,
    TOOL_GROUP_BY_CARD,
    TOOL_NAMES,
    TravelBookingEngine,
    function_schemas,
    rupees,
    wire_declaration,
    wire_declarations,
)
from live_tool_swapper import LiveToolSwapper, context_update_frame, supports_context_update

TODAY = dt.date(2026, 10, 3)
FRI = "2026-10-09"
MON = "2026-10-12"


def engine() -> TravelBookingEngine:
    return TravelBookingEngine(today=TODAY)


def to_card(e: TravelBookingEngine, number: int, trip_type: str = "OW", on_result=None) -> None:
    """Drive a fresh engine to the given card with the happy path."""
    plan = [
        ("SelectLanguageTool", {"language": "Hindi"}),
        ("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                        "depart_date": FRI, **({"trip_type": "RT", "return_date": MON} if trip_type == "RT" else {})}),
        ("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1"}),
    ]
    if trip_type == "RT":
        plan += [("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "trip_type": "OW", "origin": "Mumbai",
                                 "destination": "Delhi", "depart_date": MON}),
                 ("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "R1"})]
    plan += [
        ("TravellerDetailsTool", {"passenger_count": 1}),
        ("TravellerDetailsTool", {"passenger_index": 1, "first_name_letters": list("RAHUL"),
                                  "last_name_letters": list("SHARMA"), "spelling_source": "model_guess",
                                  "age": 34, "gender": "male"}),
        ("TravellerDetailsTool", {"name_confirmed": True}),
        ("TravellerDetailsTool", {"phone_choice": "same"}),
        ("TravellerDetailsTool", {"email": "rahul.sharma@gmail.com"}),
        ("TravellerDetailsTool", {"email_confirmed": True}),
        ("TravellerDetailsTool", {"details_confirmed": True}),
    ]
    for name, args in plan:
        if e.active_card >= number:
            return
        result = e.handle(name, args)
        if on_result is not None:
            on_result(name, result)
    assert e.active_card >= number, e.active_card


class TestDeclarationsAndGroups(unittest.TestCase):
    def test_six_lean_tools_verbatim_and_blocking_on_the_wire(self):
        self.assertEqual(TOOL_NAMES, ["SelectLanguageTool", "CheckAirportTool", "SearchTool",
                                      "FlightActionTool", "TravellerDetailsTool", "PaymentTool"])
        for decl in TOOL_DECLARATIONS:
            self.assertIn("behavior", decl)  # kept in the source of truth
            self.assertNotIn("behavior", wire_declaration(decl["name"]))  # 3.x Live: all blocking
        # The legacy user_language parameter is gone from every tool.
        self.assertNotIn("user_language", json.dumps(TOOL_DECLARATIONS))

    def test_pipecat_schemas_use_json_schema_types(self):
        schemas = {s.name: s for s in function_schemas()}
        self.assertEqual(set(schemas), set(TOOL_NAMES))
        search = schemas["SearchTool"].properties
        self.assertEqual(search["filters"]["type"], "object")
        self.assertEqual(search["filters"]["properties"]["stops_count"]["type"], "integer")
        self.assertNotIn("OBJECT", json.dumps([s.properties for s in schemas.values()]))

    def test_every_card_group_covers_the_tools_its_card_names(self):
        for number, card in TARA_CARD_BY_NUMBER.items():
            line = next(l for l in card.directive.splitlines() if l.startswith("Tools for this step"))
            named = set(re.findall(r"[A-Z][A-Za-z]+Tool", line))
            with self.subTest(card=number):
                self.assertTrue(named <= set(TOOL_GROUP_BY_CARD[number]), named - set(TOOL_GROUP_BY_CARD[number]))
                self.assertIn("SelectLanguageTool", TOOL_GROUP_BY_CARD[number])

    def test_each_card_registers_exactly_the_tools_it_names(self):
        # SelectLanguageTool rides on every card: the base SI allows a language switch at any time.
        for number, card in TARA_CARD_BY_NUMBER.items():
            line = next(l for l in card.directive.splitlines() if l.startswith("Tools for this step"))
            named = set(re.findall(r"[A-Z][A-Za-z]+Tool", line)) | {"SelectLanguageTool"}
            with self.subTest(card=number):
                self.assertEqual(set(TOOL_GROUP_BY_CARD[number]), named)

    def test_next_only_names_tools_the_active_card_registered(self):
        for trip in ("OW", "RT"):
            e = engine()

            def check(name, result, e=e, trip=trip):
                group = set(TOOL_GROUP_BY_CARD[e.active_card])
                for entry in result.get("next") or []:
                    with self.subTest(trip=trip, after=name, card=e.active_card):
                        self.assertIn(entry["tool"], group)
                named = set(re.findall(r"[A-Z][A-Za-z]+Tool", result.get("instruction", "")))
                with self.subTest(trip=trip, after=name, card=e.active_card, instruction=True):
                    self.assertTrue(named <= group, named - group)

            to_card(e, 8, trip_type=trip, on_result=check)


class TestCardsAndPrompt(unittest.TestCase):
    def test_root_si_is_book_my_trip_tara_and_female(self):
        si = get_tara_root_system_instruction()
        self.assertIn("You are Tara, a female Indian voice assistant for Book My Trip", si)
        self.assertIn('Say "Book My Trip" as three words', si)
        self.assertNotIn("{", si)
        for banned in ("Make My Trip", "MakeMyTrip", "MMT", "Myra"):
            self.assertNotIn(banned, si)
        self.assertNotIn("Prompt card", si)  # Live: cards arrive just in time

    def test_cascade_si_carries_card_one(self):
        self.assertIn("Prompt card 1 of 8: Language", get_tara_monolithic_system_instruction())

    def test_opening_card_has_card_state_and_footer_in_order(self):
        text = engine().opening_card()
        card_at = text.index("Prompt card 1 of 8")
        state_at = text.index("Session state:")
        footer_at = text.index("Before you speak: Only Indian English.")
        self.assertLess(card_at, state_at)
        self.assertLess(state_at, footer_at)
        self.assertIn("language: not given yet", text)
        self.assertIn("today: Saturday, 3 October 2026", text)

    def test_phase_ids_are_the_eight_bmt_cards(self):
        self.assertEqual([TARA_CARD_BY_NUMBER[n].phase_id for n in range(1, 9)], TARA_PHASE_IDS)


class TestBookingFlow(unittest.TestCase):
    def test_one_way_happy_path_walks_all_eight_cards(self):
        e = engine()
        seen, cards = [1], []
        steps = [
            ("SelectLanguageTool", {"language": "Hindi"}),
            ("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai", "depart_date": FRI}),
            ("FlightActionTool", {"action": "SELECT_FLIGHT", "reference": "FIRST"}),
            ("TravellerDetailsTool", {"passenger_count": 2}),
            ("TravellerDetailsTool", {"includes_children": False}),
            ("TravellerDetailsTool", {"passenger_count_confirmed": True}),
            ("TravellerDetailsTool", {"passenger_index": 1, "first_name_letters": list("RAHUL"), "last_name_letters": list("SHARMA"),
                                      "spelling_source": "model_guess", "age": 34, "gender": "male"}),
            ("TravellerDetailsTool", {"name_confirmed": True}),
            ("TravellerDetailsTool", {"passenger_index": 2, "first_name_letters": list("PRIYA"), "last_name_letters": list("SHARMA"),
                                      "spelling_source": "model_guess", "age": 31, "gender": "female"}),
            ("TravellerDetailsTool", {"name_confirmed": True}),
            ("TravellerDetailsTool", {"phone_choice": "same"}),
            ("TravellerDetailsTool", {"email": "rahul.sharma at gmail dot com"}),
            ("TravellerDetailsTool", {"email_confirmed": True}),
            ("TravellerDetailsTool", {"details_confirmed": True}),
            ("PaymentTool", {"action": "PROCEED"}),
        ]
        for name, args in steps:
            before = e.active_card
            r = e.handle(name, args)
            self.assertIn("call_state", r)
            self.assertIn("instruction", r)
            self.assertNotIn("error", r, (name, r))
            if e.active_card != before:
                self.assertIn("prompt_card", r, name)
                self.assertIn(f"Prompt card {e.active_card} of 8", r["prompt_card"])
                seen.append(e.active_card)
                cards.append(r["prompt_card"])
            else:
                self.assertNotIn("prompt_card", r, name)
        self.assertEqual(seen, [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(r["status"], "link_sent")
        self.assertRegex(r["data"]["booking_ref"], r"^BMT\d{7}$")
        total = e.state.outbound.fare * 2
        self.assertEqual(r["data"]["amount_say"], rupees(total))
        # Later cards render the state the server holds, so nothing has to be remembered.
        self.assertIn("language: Hindi", cards[-1])
        self.assertIn("Only Hindi, everyday Hinglish.", cards[-1])
        self.assertIn("Passenger 2: Priya Sharma, 31, female, name confirmed", cards[-1])

    def test_round_trip_split_returns_exact_return_leg_arguments(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "English"})
        r = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "DEL", "destination": "bombay",
                                    "trip_type": "RT", "depart_date": FRI, "return_date": MON})
        self.assertTrue(all(f["flight_id"].startswith("F") for f in r["data"]["flights"]))
        r = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F2"})
        self.assertEqual(r["status"], "selected")
        self.assertEqual(e.active_card, 3)
        follow = r["next"][0]
        self.assertEqual(follow["tool"], "SearchTool")
        r = e.handle("SearchTool", follow["arguments"])
        self.assertTrue(all(f["flight_id"].startswith("R") for f in r["data"]["flights"]))
        self.assertIn("outbound_selected_say", r["data"])
        r = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "reference": "CHEAPEST"})
        self.assertEqual(e.active_card, 4)
        self.assertIn("combined fare for both flights", r["data"]["facts"])
        self.assertIn(rupees(e.state.outbound.fare + e.state.ret.fare), r["data"]["facts"])

    def test_follow_up_search_with_only_the_missing_field(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        r = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "trip_type": "RT"})
        self.assertEqual(r["status"], "needs_info")
        self.assertEqual(r["missing"][0], "destination city")
        r = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "destination": "Goa", "depart_date": FRI})
        self.assertEqual(r["missing"], ["return date"])
        r = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "return_date": MON})
        self.assertEqual(r["status"], "ok")
        self.assertEqual((e.state.origin, e.state.destination, e.state.trip_type), ("Delhi", "Goa", "RT"))

    def test_refine_keeps_filters_and_more_skips_shown(self):
        e = engine()
        to_card(e, 3)
        r = e.handle("SearchTool", {"query_sub_type": "REFINE_RESULTS", "refine_intent": "FILTER",
                                    "filters": {"stops_count": 0}})
        self.assertTrue(all(f["stops_say"] == "non-stop" for f in r["data"]["flights"]))
        shown = {f["flight_id"] for f in r["data"]["flights"]}
        r = e.handle("SearchTool", {"query_sub_type": "REFINE_RESULTS", "refine_intent": "MORE"})
        self.assertTrue(all(f["stops_say"] == "non-stop" for f in r["data"]["flights"]))
        if r["data"].get("note_say") is None:
            self.assertFalse(shown & {f["flight_id"] for f in r["data"]["flights"]})
        r = e.handle("SearchTool", {"query_sub_type": "REFINE_RESULTS", "clear_filters": ["stops"]})
        self.assertEqual(r["data"]["results_count"], 6)

    def test_flight_change_after_selection_keeps_the_step(self):
        e = engine()
        to_card(e, 5)
        old = e.state.outbound.flight_id
        new = next(f for f in e.offered["outbound"] if f != old)  # cards 4-7 change only to an offered flight
        r = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": new})
        self.assertEqual(r["status"], "changed")
        self.assertIn("The new total is", r["change"])
        self.assertEqual(e.active_card, 5)
        self.assertNotIn("prompt_card", r)
        self.assertEqual(e.state.outbound.flight_id, new)
        self.assertTrue(r["instruction"].startswith("Say change exactly as given, then"))

    def test_new_route_after_selection_returns_to_card_three(self):
        e = engine()
        to_card(e, 5)
        r = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Goa", "depart_date": FRI})
        self.assertEqual(e.active_card, 3)
        self.assertIn("prompt_card", r)
        self.assertIsNone(e.state.outbound)

    def test_mid_call_language_switch_resends_current_card(self):
        e = engine()
        to_card(e, 3)
        r = e.handle("SelectLanguageTool", {"language": "Tamil"})
        self.assertEqual(e.active_card, 3)
        self.assertIn("Prompt card 3 of 8", r["prompt_card"])
        self.assertIn("Only Tamil, everyday spoken Tamil.", r["prompt_card"])

    def test_phone_confirmed_at_phone_choice_means_same_number(self):
        e = engine()
        to_card(e, 6)
        self.assertEqual(e.state.step, "phone_choice")
        r = e.handle("TravellerDetailsTool", {"phone_confirmed": True})
        self.assertEqual(r["data"]["step"], "email")
        self.assertEqual(e.state.whatsapp, CALLING_NUMBER)

    def test_incomplete_email_is_reported_not_dropped(self):
        e = engine()
        to_card(e, 6)
        e.handle("TravellerDetailsTool", {"phone_choice": "same"})
        r = e.handle("TravellerDetailsTool", {"email": "rahul at gmail"})
        self.assertEqual(r["data"]["step"], "email")
        self.assertIn("domain is incomplete", r["error"])
        r = e.handle("TravellerDetailsTool", {"email": "rahulsharma"})
        self.assertIn("needs a name, an @", r["error"])

    def test_whatsapp_failure_offers_retry_then_another_number(self):
        e = engine()
        to_card(e, 6)
        e.handle("TravellerDetailsTool", {"phone_choice": "new"})
        r = e.handle("TravellerDetailsTool", {"phone_number": "98765 40000"})
        self.assertEqual(r["data"]["step"], "confirm_phone")
        e.handle("TravellerDetailsTool", {"phone_confirmed": True})
        e.handle("TravellerDetailsTool", {"email": "a.b@example.com"})
        r = e.handle("TravellerDetailsTool", {"email_confirmed": True})
        self.assertEqual(r["data"]["step"], "retry_traveller_whatsapp")
        self.assertEqual(e.active_card, 7)
        r = e.handle("TravellerDetailsTool", {"phone_number": "9123456789"})
        self.assertEqual(r["data"]["step"], "confirm_phone")
        e.handle("TravellerDetailsTool", {"phone_confirmed": True})
        self.assertEqual(e.state.step, "review_details")

    def test_children_need_count_and_date_of_birth(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 3})
        r = e.handle("TravellerDetailsTool", {"includes_children": True})
        self.assertEqual(r["data"]["step"], "child_count")
        r = e.handle("TravellerDetailsTool", {"child_count": 1})
        self.assertEqual(r["data"]["step"], "child_date_of_birth")
        r = e.handle("TravellerDetailsTool", {"date_of_birth": "2020-05-01"})
        self.assertEqual(r["data"]["step"], "confirm_passenger_count")
        self.assertIn("2 adults and 1 child", r["ask_say"])

    # The next three reproduce live Vertex 3.8 runs where the model ran ahead of the count step and the
    # engine silently dropped every later detail, so payment never unlocked.
    def test_all_adults_answer_sent_as_count_confirmation_settles_the_mix(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        self.assertEqual(e.state.step, "passenger_mix")
        r = e.handle("TravellerDetailsTool", {"passenger_count_confirmed": True})
        self.assertEqual(r["data"]["step"], "confirm_passenger_count")
        self.assertIn("2 adults", r["ask_say"])
        r = e.handle("TravellerDetailsTool", {"passenger_count_confirmed": True})
        self.assertEqual(r["data"]["step"], "passenger_details")
        self.assertEqual(e.active_card, 5)

    def test_details_given_before_the_count_is_confirmed_are_kept_and_read_back_later(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        r = e.handle("TravellerDetailsTool", {"passenger_index": 1, "first_name_letters": list("RAHUL"),
                                              "last_name_letters": list("SHARMA"), "spelling_source": "model_guess",
                                              "age": 34, "gender": "male"})
        self.assertEqual(r["data"]["step"], "passenger_mix")  # the open step still comes first
        self.assertIn("passenger 1", r["saved"])
        self.assertEqual(r["status"], "step_open")  # not a bland "ok": the model must finish this step first
        self.assertTrue(r["instruction"].startswith("First finish this step"))
        e.handle("TravellerDetailsTool", {"includes_children": False})
        r = e.handle("TravellerDetailsTool", {"passenger_count_confirmed": True})
        self.assertEqual(r["data"]["step"], "confirm_name")  # nothing re-asked: straight to the readback
        self.assertEqual(r["name_spell"]["first_spell"], "R A H U L")
        self.assertEqual(e.state.travellers[0].age, 34)

    def test_names_after_the_total_was_read_imply_the_yes(self):
        # Live: the caller said "haan" to the total, the model skipped the tool and asked for names.
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        r = e.handle("TravellerDetailsTool", {"includes_children": False})
        self.assertEqual(r["data"]["step"], "confirm_passenger_count")
        r = e.handle("TravellerDetailsTool", {"passenger_index": 1, "first_name_letters": list("RAHUL"),
                                              "last_name_letters": list("SHARMA"), "spelling_source": "model_guess",
                                              "age": 34, "gender": "male"})
        self.assertEqual(r["data"]["step"], "confirm_name")
        self.assertEqual(e.active_card, 5)
        self.assertTrue(e.state.count_confirmed)

    def test_same_number_choice_given_early_is_not_dropped(self):
        e = engine()
        to_card(e, 5)
        self.assertEqual(e.state.step, "passenger_details")
        e.handle("TravellerDetailsTool", {"phone_choice": "same"})
        self.assertEqual(e.state.whatsapp, CALLING_NUMBER)
        e.handle("TravellerDetailsTool", {"passenger_index": 1, "first_name_letters": list("RAHUL"),
                                          "last_name_letters": list("SHARMA"), "spelling_source": "model_guess",
                                          "age": 34, "gender": "male"})
        r = e.handle("TravellerDetailsTool", {"name_confirmed": True})
        self.assertEqual(r["data"]["step"], "email")  # phone_choice already answered

    def test_caller_spelled_correction_spells_only_the_corrected_part(self):
        e = engine()
        to_card(e, 5)
        e.handle("TravellerDetailsTool", {"passenger_index": 1, "first_name_letters": list("RAHUL"),
                                          "last_name_letters": list("SARMA"), "spelling_source": "model_guess",
                                          "age": 34, "gender": "male"})
        r = e.handle("TravellerDetailsTool", {"last_name_letters": list("SHARMA"), "spelling_source": "caller_spelled",
                                              "name_confirmed": False})
        self.assertEqual(r["name_spell"]["first_spell"], "")
        self.assertEqual(r["name_spell"]["last_spell"], "S H A R M A")
        self.assertTrue(r["spelling_changed"])

    def test_payment_is_gated_until_details_are_complete(self):
        e = engine()
        to_card(e, 5)
        r = e.handle("PaymentTool", {"action": "PROCEED"})
        self.assertIn("error", r)
        self.assertIsNone(e.state.booking_ref)

    def test_scope_and_airport_checks(self):
        e = engine()
        r = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Dubai", "depart_date": FRI})
        self.assertEqual(r["status"], "out_of_scope")
        r = e.handle("CheckAirportTool", {"place": "Rishikesh"})
        self.assertFalse(r["has_airport"])
        self.assertEqual(r["nearby"][0]["city"], "Dehradun")
        r = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai", "depart_date": "2026-09-01"})
        self.assertIn("in the past", r["error"])

    def test_unknown_tool_and_bad_args_are_errors_with_instruction(self):
        e = engine()
        self.assertIn("error", e.handle("NopeTool", {}))
        self.assertIn("error", e.handle("SearchTool", {}))
        self.assertIn("error", e.handle("SelectLanguageTool", {"language": "Klingon"}))
        self.assertIn("error", e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1"}))


def name_args(first="RAHUL", last="SHARMA", **extra):
    return {"first_name_letters": list(first), "last_name_letters": list(last), "spelling_source": "model_guess", **extra}


def two_adults_at(e: TravelBookingEngine, step: str) -> None:
    """Round trip, two adults, driven to the given traveller step."""
    to_card(e, 4, trip_type="RT")
    for args in (
        {"passenger_count": 2},
        {"includes_children": False},
        {"passenger_count_confirmed": True},
        name_args(passenger_index=1, age=34, gender="male"),
        {"name_confirmed": True},
        name_args("PRIYA", passenger_index=2, age=31, gender="female"),
        {"name_confirmed": True},
        {"phone_choice": "same"},
        {"email": "rahul.sharma@gmail.com"},
        {"email_confirmed": True},
        {"details_confirmed": True},
    ):
        if e.state.step == step:
            return
        e.handle("TravellerDetailsTool", args)
    assert e.state.step == step, e.state.step


class TestRoundOneBlockers(unittest.TestCase):
    """Gauntlet round 1 (Opus, Fable, Argon): each test reproduces a probed failure."""

    def test_engine_exception_still_answers_the_blocking_call(self):
        from persona_registry import get_persona_architecture
        arch = get_persona_architecture("travel-concierge")
        arch.engine.handle = lambda name, args: 1 / 0
        r = run(arch.run_tool("SearchTool", {}))
        self.assertEqual(r["status"], "error")
        self.assertIn("instruction", r)

    def test_bad_refine_filters_are_rejected_not_saved(self):
        e = engine()
        to_card(e, 3)
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai", "depart_date": FRI})
        for filters in ({"time_of_day": "late night"}, "non-stop", {"max_fare": "cheap"}):
            r = e.handle("SearchTool", {"query_sub_type": "REFINE_RESULTS", "filters": filters})
            self.assertEqual(r["status"], "error", filters)
        r = e.handle("SearchTool", {"query_sub_type": "REFINE_RESULTS", "filters": {"max_fare": "7000"}})
        self.assertEqual(r["status"], "ok")  # numeric strings are coerced
        self.assertTrue(all(f["fare"] <= 7000 for f in r["data"]["flights"]))

    def test_flight_change_and_side_questions_resume_the_open_step(self):
        e = engine()
        to_card(e, 5)
        e.handle("FlightActionTool", {"action": "FLIGHT_DETAILS", "flight_id": "F1"})
        e.handle("CheckAirportTool", {"place": "Goa"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai", "depart_date": FRI})
        r = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F2"})
        self.assertEqual(r["status"], "changed")
        self.assertEqual(r["data"]["step"], "passenger_details")
        self.assertIn("full name as on Aadhaar", r["instruction"])
        self.assertEqual(r["next"][0]["tool"], "TravellerDetailsTool")
        r = e.handle("SelectLanguageTool", {"language": "Tamil"})
        self.assertNotIn("Say change", r["instruction"])

    def test_confirmation_sent_with_a_new_count_reads_the_new_total_first(self):
        e = engine()
        two_adults_at(e, "confirm_passenger_count")
        r = e.handle("TravellerDetailsTool", {"passenger_count": 3, "passenger_count_confirmed": True})
        self.assertFalse(e.state.count_confirmed)
        self.assertIn(r["data"]["step"], ("passenger_mix", "confirm_passenger_count"))

    def test_changed_mix_with_a_name_is_not_an_implicit_yes(self):
        e = engine()
        two_adults_at(e, "confirm_passenger_count")
        r = e.handle("TravellerDetailsTool", {"child_count": 1, **name_args(passenger_index=1, age=34, gender="male")})
        self.assertFalse(e.state.count_confirmed)
        self.assertEqual(r["data"]["step"], "child_date_of_birth")

    def test_names_and_emails_are_always_read_back_before_they_count(self):
        e = engine()
        to_card(e, 5)
        r = e.handle("TravellerDetailsTool", name_args(passenger_index=1, age=34, gender="male", name_confirmed=True))
        self.assertEqual(r["data"]["step"], "confirm_name")  # a first mention is never confirmed unread
        e.handle("TravellerDetailsTool", {"name_confirmed": True})
        e.handle("TravellerDetailsTool", {"phone_choice": "same"})
        r = e.handle("TravellerDetailsTool", {"email": "a.b@gmail.com", "email_confirmed": True})
        self.assertEqual(r["data"]["step"], "confirm_email")
        self.assertFalse(e.state.email_confirmed)
        r = e.handle("TravellerDetailsTool", {"email": "c.d@gmail.com", "email_confirmed": False})
        self.assertEqual(e.state.email, "c.d@gmail.com")  # the correction is kept, not thrown away
        self.assertEqual(r["data"]["step"], "confirm_email")

    def test_session_state_never_hides_what_the_server_knows(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai"})
        self.assertIn("Delhi", e.state.snapshot()["trip"] or "")
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "depart_date": FRI})
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1"})
        self.assertIn("per adult", e.state.snapshot()["total_fare"])
        e.handle("TravellerDetailsTool", {"passenger_count": 3})
        self.assertNotIn("3 adults", e.state.snapshot()["travellers"])  # mix not known yet

    def test_count_given_with_the_search_is_not_asked_again(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": FRI, "passenger_count": 2})
        r = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1"})
        self.assertEqual(r["data"]["step"], "passenger_mix")
        self.assertNotIn("How many", r["ask_say"])

    def test_child_date_of_birth_is_asked_once(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 1})
        e.handle("TravellerDetailsTool", {"date_of_birth": "2020-05-01"})
        e.handle("TravellerDetailsTool", {"passenger_count_confirmed": True})
        e.handle("TravellerDetailsTool", name_args(passenger_index=1, age=34, gender="male"))
        e.handle("TravellerDetailsTool", {"name_confirmed": True})
        e.handle("TravellerDetailsTool", name_args("ANYA", passenger_index=2, age=6, gender="female"))
        r = e.handle("TravellerDetailsTool", {"name_confirmed": True})
        self.assertEqual(r["data"]["step"], "phone_choice")
        self.assertEqual(e.state.travellers[1].date_of_birth, "2020-05-01")

    def test_whatsapp_retry_never_swaps_the_number_silently(self):
        e = engine()
        to_card(e, 6)
        e.handle("TravellerDetailsTool", {"phone_choice": "new"})
        e.handle("TravellerDetailsTool", {"phone_number": "98765 40000"})
        e.handle("TravellerDetailsTool", {"phone_confirmed": True})
        e.handle("TravellerDetailsTool", {"email": "a.b@example.com"})
        e.handle("TravellerDetailsTool", {"email_confirmed": True})
        r = e.handle("TravellerDetailsTool", {"retry_whatsapp": True})
        self.assertEqual(r["data"]["step"], "retry_traveller_whatsapp")  # the mock number fails again
        self.assertEqual(e.state.whatsapp, "9876540000")
        r = e.handle("TravellerDetailsTool", {"phone_choice": "same"})
        self.assertEqual(e.state.whatsapp, CALLING_NUMBER)
        self.assertEqual(r["data"]["step"], "review_details")

    def test_caller_can_go_back_to_the_calling_number(self):
        e = engine()
        to_card(e, 6)
        e.handle("TravellerDetailsTool", {"phone_choice": "new"})
        e.handle("TravellerDetailsTool", {"phone_number": "9123456789"})
        e.handle("TravellerDetailsTool", {"phone_confirmed": True})
        e.handle("TravellerDetailsTool", {"phone_choice": "same"})
        self.assertEqual(e.state.whatsapp, CALLING_NUMBER)

    def test_new_route_after_review_needs_the_total_and_the_review_again(self):
        e = engine()
        two_adults_at(e, "complete")
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "trip_type": "OW", "origin": "Delhi",
                                "destination": "Goa", "depart_date": FRI})
        r = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1"})
        self.assertEqual(r["data"]["step"], "confirm_passenger_count")
        self.assertFalse(e.state.details_confirmed)
        self.assertIn("error", e.handle("PaymentTool", {"action": "PROCEED"}))

    def test_flight_change_after_the_link_issues_a_new_link_after_review(self):
        e = engine()
        two_adults_at(e, "complete")
        first = e.handle("PaymentTool", {"action": "PROCEED"})["data"]["booking_ref"]
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai", "depart_date": FRI})
        r = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F2"})
        self.assertEqual(r["data"]["step"], "review_details")
        e.handle("TravellerDetailsTool", {"details_confirmed": True})
        r = e.handle("PaymentTool", {"action": "PROCEED"})
        self.assertEqual(r["status"], "link_sent")
        self.assertNotEqual(r["data"]["booking_ref"], first)

    def test_a_yes_sent_as_another_confirmation_answers_the_count_readback(self):
        e = engine()
        two_adults_at(e, "confirm_passenger_count")
        r = e.handle("TravellerDetailsTool", {"details_confirmed": True})
        self.assertTrue(e.state.count_confirmed)
        self.assertEqual(r["data"]["step"], "passenger_details")

    def test_email_yes_counts_for_the_address_read_back_even_after_the_step_moved(self):
        e = engine()
        to_card(e, 6)
        e.handle("TravellerDetailsTool", {"phone_choice": "same"})
        r = e.handle("TravellerDetailsTool", {"email": "a.b@gmail.com"})
        self.assertEqual(r["data"]["step"], "confirm_email")  # read back here
        e.handle("TravellerDetailsTool", {"phone_number": "9123456789"})  # the step moves to confirm_phone
        e.handle("TravellerDetailsTool", {"email_confirmed": True})
        self.assertTrue(e.state.email_confirmed)

    def test_email_yes_before_any_readback_does_not_count(self):
        e = engine()
        to_card(e, 5)
        e.handle("TravellerDetailsTool", {"email": "a.b@gmail.com"})
        e.handle("TravellerDetailsTool", {"email_confirmed": True})
        self.assertFalse(e.state.email_confirmed)

    def test_return_search_without_cities_is_the_return_leg(self):
        e = engine()
        to_card(e, 3, trip_type="RT")
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1"})
        r = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "depart_date": MON})
        self.assertEqual(r["data"]["leg"], "return")
        self.assertIsNotNone(e.state.outbound)

    def test_email_without_a_name_says_so(self):
        e = engine()
        to_card(e, 6)
        e.handle("TravellerDetailsTool", {"phone_choice": "same"})
        r = e.handle("TravellerDetailsTool", {"email": "@gmail.com"})
        self.assertIn("name before the @", r["error"])

    def test_card_four_asks_the_model_to_send_answers_it_already_heard(self):
        self.assertIn("already answered", TARA_CARD_BY_NUMBER[4].directive)

    def test_a_card_drops_the_tools_whose_job_is_done(self):
        # context_update replaces the whole tool list: a card sends only what it still needs.
        lang = "SelectLanguageTool"
        self.assertEqual(set(TOOL_GROUP_BY_CARD[3]), {lang, "SearchTool", "FlightActionTool"})
        for card in (4, 5, 6, 7):  # the trip is built: no search; a change picks an offered flight
            self.assertEqual(set(TOOL_GROUP_BY_CARD[card]), {lang, "TravellerDetailsTool", "FlightActionTool"})
        self.assertEqual(set(TOOL_GROUP_BY_CARD[8]), {lang, "PaymentTool"})  # details confirmed at review
        for card in range(4, 9):
            self.assertNotIn("SearchTool", TARA_CARD_BY_NUMBER[card].directive)
            self.assertNotIn("CheckAirportTool", TARA_CARD_BY_NUMBER[card].directive)


class _FakeWS:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send(self, text):
        if self.fail:
            raise ConnectionError("closed")
        self.sent.append(json.loads(text))


class _FakeLLM:
    def __init__(self, fail=False):
        self._session = type("S", (), {"_ws": _FakeWS(fail)})()
        self._disconnecting = False
        self._bot_is_responding = False
        self._mixin_bot_responding = False
        self.directives = []
        self.registered = {}

    async def inject_directive(self, text, tag="Directive", speak_now=True, at_tool_boundary=False):
        self.directives.append((text, tag, speak_now))
        return True

    def register_function(self, name, handler):
        self.registered[name] = handler


def run(coro):
    return asyncio.run(coro)


class TestRoundTwoBlockers(unittest.TestCase):
    def _tools_named(self, result):
        return set(re.findall(r"[A-Z][A-Za-z]+Tool", result.get("instruction", "")))

    def test_a_name_yes_needs_a_readback_the_caller_heard(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})  # passenger_mix is open
        e.handle("TravellerDetailsTool", name_args(passenger_index=1, age=34, gender="male"))  # saved, not read back
        e.handle("TravellerDetailsTool", {"name_confirmed": True, "passenger_index": 1})
        self.assertFalse(any(t.name_confirmed for t in e.state.travellers))
        e.handle("TravellerDetailsTool", {"includes_children": False})
        r = e.handle("TravellerDetailsTool", {"passenger_count_confirmed": True, "name_confirmed": True})
        self.assertFalse(any(t.name_confirmed for t in e.state.travellers))
        self.assertEqual(r["data"]["step"], "confirm_name")  # now the caller hears it
        r = e.handle("TravellerDetailsTool", {"name_confirmed": True, "passenger_index": 1})
        self.assertTrue(e.state.travellers[0].name_confirmed)

    def test_city_errors_on_every_card_name_only_registered_tools(self):
        for card in range(2, 9):
            for place in ("Shimla", "Rishikesh", "Atlantis"):
                e = engine()
                to_card(e, card)
                r = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi",
                                            "destination": place, "depart_date": FRI})
                with self.subTest(card=card, place=place):
                    group = set(TOOL_GROUP_BY_CARD[e.active_card])
                    self.assertTrue(self._tools_named(r) <= group, self._tools_named(r) - group)
                    if place == "Rishikesh":
                        self.assertEqual(r["nearby"][0]["city"], "Dehradun")
                        self.assertIn("Dehradun", r["facts"])

    def test_a_refine_with_no_match_during_a_change_keeps_the_step(self):
        e = engine()
        to_card(e, 5)
        resume = e._current_instruction
        r = e.handle("SearchTool", {"query_sub_type": "REFINE_RESULTS", "filters": {"max_fare": 1}})
        self.assertEqual(r["status"], "no_flights")
        self.assertEqual(e._current_instruction, resume)
        self.assertEqual(e.state.step, "passenger_details")

    def test_count_step_child_dates_are_matched_by_age(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 3})
        e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 2})
        e.handle("TravellerDetailsTool", {"date_of_birth": "2018-01-01"})  # age 8
        e.handle("TravellerDetailsTool", {"date_of_birth": "2021-02-02"})  # age 5
        e.handle("TravellerDetailsTool", {"passenger_count_confirmed": True})
        e.handle("TravellerDetailsTool", name_args(passenger_index=1, age=34, gender="male"))
        e.handle("TravellerDetailsTool", {"name_confirmed": True})
        e.handle("TravellerDetailsTool", name_args("ANYA", passenger_index=2, age=5, gender="female"))
        self.assertEqual(e.state.travellers[1].date_of_birth, "2021-02-02")
        e.handle("TravellerDetailsTool", {"name_confirmed": True})
        e.handle("TravellerDetailsTool", name_args("VIR", passenger_index=3, age=11, gender="male"))
        self.assertIsNone(e.state.travellers[2].date_of_birth)  # 2018-01-01 is age 8: ask instead

    def test_close_child_ages_get_the_exact_date(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 3})
        e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 2})
        e.handle("TravellerDetailsTool", {"date_of_birth": "2023-08-24"})  # age 3
        e.handle("TravellerDetailsTool", {"date_of_birth": "2024-08-24"})  # age 2
        e.handle("TravellerDetailsTool", {"passenger_count_confirmed": True})
        e.handle("TravellerDetailsTool", name_args(passenger_index=1, age=34, gender="male"))
        e.handle("TravellerDetailsTool", {"name_confirmed": True})
        e.handle("TravellerDetailsTool", name_args("ANYA", passenger_index=2, age=2, gender="female"))
        self.assertEqual(e.state.travellers[1].date_of_birth, "2024-08-24")
        e.handle("TravellerDetailsTool", {"name_confirmed": True})
        e.handle("TravellerDetailsTool", name_args("VIR", passenger_index=3, age=3, gender="male"))
        self.assertEqual(e.state.travellers[2].date_of_birth, "2023-08-24")

    def test_a_rejected_name_is_not_confirmed_by_a_later_bare_yes(self):
        e = engine()
        to_card(e, 5)
        e.handle("TravellerDetailsTool", name_args(passenger_index=1, age=34, gender="male"))  # readback served
        r = e.handle("TravellerDetailsTool", {"name_confirmed": False})  # "no": asks for spelling
        self.assertNotIn("name_spell", r)
        e.handle("TravellerDetailsTool", {"name_confirmed": True})  # "haan" to "please spell it"
        self.assertFalse(e.state.travellers[0].name_confirmed)

    def test_a_shrinking_count_drops_names_beyond_it(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        e.handle("TravellerDetailsTool", {"includes_children": False})
        e.handle("TravellerDetailsTool", {"passenger_count_confirmed": True})
        e.handle("TravellerDetailsTool", name_args("PRIYA", passenger_index=2, age=30, gender="female"))
        e.handle("TravellerDetailsTool", {"passenger_count": 1})
        self.assertNotIn(2, e._pending_name)
        self.assertNotIn(2, e._name_read_back)

    def test_a_corrected_age_drops_an_auto_matched_date(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 1})
        e.handle("TravellerDetailsTool", {"date_of_birth": "2021-02-02"})  # age 5
        e.handle("TravellerDetailsTool", {"passenger_count_confirmed": True})
        e.handle("TravellerDetailsTool", name_args(passenger_index=1, age=34, gender="male"))
        e.handle("TravellerDetailsTool", {"name_confirmed": True})
        e.handle("TravellerDetailsTool", name_args("ANYA", passenger_index=2, age=5, gender="female"))
        self.assertEqual(e.state.travellers[1].date_of_birth, "2021-02-02")
        e.handle("TravellerDetailsTool", {"passenger_index": 2, "age": 9})  # "sorry, she is 9"
        self.assertIsNone(e.state.travellers[1].date_of_birth)

    def test_a_growing_count_asks_the_mix_again(self):
        e = engine()
        to_card(e, 5)  # one traveller, so the mix was settled without asking
        r = e.handle("TravellerDetailsTool", {"additional_passengers": 1})
        self.assertEqual(r["data"]["step"], "passenger_mix")

    def test_a_yes_with_a_stale_index_confirms_the_name_that_was_read_back(self):
        # Live e2e 2026-10-04: confirming passenger 2, the model sent passenger_index 1
        # (already confirmed) six times; each yes re-read passenger 2's spelling.
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        e.handle("TravellerDetailsTool", {"includes_children": False})
        e.handle("TravellerDetailsTool", {"passenger_count_confirmed": True})
        e.handle("TravellerDetailsTool", name_args(passenger_index=1, age=34, gender="male"))
        e.handle("TravellerDetailsTool", {"name_confirmed": True, "passenger_index": 1})
        r = e.handle("TravellerDetailsTool", name_args("PRIYA", passenger_index=2, age=31, gender="female"))
        self.assertEqual(r["data"]["step"], "confirm_name")
        e.handle("TravellerDetailsTool", {"name_confirmed": True, "passenger_index": 1})
        self.assertTrue(e.state.travellers[1].name_confirmed)
        self.assertNotEqual(e.state.step, "confirm_name")

    def test_the_mix_question_names_the_arguments_that_carry_the_answer(self):
        from persona_prompt_cards.tara_cards import STEP_INSTRUCTIONS
        self.assertIn("includes_children false", STEP_INSTRUCTIONS["passenger_mix"])
        self.assertIn("includes_children false", TARA_CARD_BY_NUMBER[4].directive)


class TestLiveToolSwapper(unittest.TestCase):
    def test_only_vertex_gemini_38_live_swaps(self):
        self.assertTrue(supports_context_update("gemini-3.8-live", vertex=True))
        self.assertTrue(supports_context_update("google/gemini-3.8-live", vertex=True))
        for model, vertex in [("gemini-3.8-live", False), ("gemini-3.5-flash-live-preview", True),
                              ("gemini-3.5-live-preview", True), ("gemini-live-2.5-flash-native-audio", True),
                              ("gemini-3.8-live-extended-thinking-preview", True), ("", True), (None, True)]:
            self.assertFalse(supports_context_update(model, vertex), model)

    def test_frame_shape_matches_the_verified_wire_format(self):
        frame = context_update_frame(wire_declarations(["PaymentTool"]))
        decl = frame["context_update"]["tools"]["tools"][0]["functionDeclarations"][0]
        self.assertEqual(decl["name"], "PaymentTool")
        self.assertEqual(decl["parameters"]["type"], "OBJECT")
        self.assertNotIn("behavior", decl)

    def test_register_sends_at_once_even_after_the_model_spoke(self):
        # The model is blocked on the tool response, so "responding" flags left over from a
        # "one moment" line before the call must not hold the swap back.
        llm = _FakeLLM()
        llm._bot_is_responding = llm._mixin_bot_responding = True
        s = LiveToolSwapper(wire_declarations, TOOL_GROUP_BY_CARD[1])
        same = run(s.register(llm, TOOL_GROUP_BY_CARD[1]))
        self.assertEqual(same.status, "unchanged")
        self.assertEqual(llm._session._ws.sent, [])
        swap = run(s.register(llm, TOOL_GROUP_BY_CARD[2]))
        self.assertEqual((swap.status, swap.via), ("sent", "context_update"))
        self.assertEqual(set(swap.added), {"SearchTool", "CheckAirportTool"})
        self.assertEqual(swap.removed, ())
        self.assertEqual(swap.declared, TOOL_GROUP_BY_CARD[2])
        names = [d["name"] for d in llm._session._ws.sent[0]["context_update"]["tools"]["tools"][0]["functionDeclarations"]]
        self.assertEqual(set(names), set(TOOL_GROUP_BY_CARD[2]))
        self.assertEqual((s.active, s.swaps), (TOOL_GROUP_BY_CARD[2], 1))
        back = run(s.register(llm, TOOL_GROUP_BY_CARD[1]))
        self.assertEqual(set(back.removed), {"SearchTool", "CheckAirportTool"})

    def test_failed_send_stays_pending_retries_at_turn_complete(self):
        llm = _FakeLLM(fail=True)
        s = LiveToolSwapper(wire_declarations, TOOL_GROUP_BY_CARD[1])
        self.assertEqual(run(s.register(llm, TOOL_GROUP_BY_CARD[4])).status, "pending")
        self.assertEqual(s.pending, TOOL_GROUP_BY_CARD[4])
        self.assertFalse(run(s.flush(llm)))
        llm._session._ws.fail = False
        self.assertTrue(run(s.flush(llm)))
        self.assertEqual((s.active, s.pending), (TOOL_GROUP_BY_CARD[4], None))

    def test_failed_send_lands_with_the_next_setup(self):
        s = LiveToolSwapper(wire_declarations, TOOL_GROUP_BY_CARD[1])
        run(s.register(_FakeLLM(fail=True), TOOL_GROUP_BY_CARD[4]))
        self.assertEqual(s.setup_tools(), TOOL_GROUP_BY_CARD[4])
        self.assertIsNone(s.pending)


class TestInstructionInContext(unittest.TestCase):
    """A sliding-window compaction keeps only the system instruction. Measured live: with the
    card in the history only, 6 of 7 replies after a compaction replayed the card-1 greeting;
    with the card in a context_update system instruction, 0 of 7 did."""

    def test_frame_carries_tools_instruction_or_both(self):
        si_only = context_update_frame(system_instruction="SI")
        self.assertEqual(si_only, {"context_update": {"systemInstruction": {"parts": [{"text": "SI"}]}}})
        both = context_update_frame(wire_declarations(["PaymentTool"]), system_instruction="SI")
        self.assertEqual(set(both["context_update"]), {"tools", "systemInstruction"})
        self.assertEqual(set(context_update_frame(wire_declarations(["PaymentTool"]))["context_update"]), {"tools"})

    def test_instruction_rides_with_the_tools_and_is_sent_only_when_it_changes(self):
        llm = _FakeLLM()
        s = LiveToolSwapper(wire_declarations, TOOL_GROUP_BY_CARD[1])
        r = run(s.register(llm, TOOL_GROUP_BY_CARD[2], system_instruction="card 2"))
        self.assertEqual(r.status, "sent")
        self.assertEqual(set(llm._session._ws.sent[0]["context_update"]), {"tools", "systemInstruction"})
        r = run(s.register(llm, TOOL_GROUP_BY_CARD[2], system_instruction="card 2, origin Delhi"))
        self.assertEqual(r.status, "unchanged")  # the tools did not change, so no tool toast
        self.assertEqual(llm._session._ws.sent[1], {"context_update": {"systemInstruction": {
            "parts": [{"text": "card 2, origin Delhi"}]}}})
        run(s.register(llm, TOOL_GROUP_BY_CARD[2], system_instruction="card 2, origin Delhi"))
        self.assertEqual(len(llm._session._ws.sent), 2)
        self.assertEqual(s.instruction, "card 2, origin Delhi")

    def test_a_failed_instruction_send_is_retried_at_turn_complete(self):
        llm = _FakeLLM(fail=True)
        s = LiveToolSwapper(wire_declarations, TOOL_GROUP_BY_CARD[2])
        run(s.register(llm, TOOL_GROUP_BY_CARD[2], system_instruction="card 2"))
        self.assertEqual(s.pending_instruction, "card 2")
        llm._session._ws.fail = False
        self.assertTrue(run(s.flush(llm)))
        self.assertEqual((s.instruction, s.pending_instruction), ("card 2", None))
        self.assertIn("systemInstruction", llm._session._ws.sent[0]["context_update"])

    def test_a_lost_session_forgets_the_instruction_it_had(self):
        llm = _FakeLLM()
        s = LiveToolSwapper(wire_declarations, TOOL_GROUP_BY_CARD[1])
        run(s.register(llm, TOOL_GROUP_BY_CARD[2], system_instruction="card 2"))
        s.session_lost()  # the new setup carried the base SI again
        run(s.register(llm, TOOL_GROUP_BY_CARD[2], system_instruction="card 2"))
        self.assertEqual(len(llm._session._ws.sent), 2)

    def test_live_instruction_drops_the_greeting_and_holds_card_and_state(self):
        from persona_prompt_cards.tara_cards import get_tara_live_system_instruction
        e = engine()
        to_card(e, 5)
        si = get_tara_live_system_instruction(e.build_card())
        self.assertNotIn("Which language would you like", si)
        self.assertIn("Never greet again", si)
        self.assertIn("Prompt card 5 of 8", si)
        self.assertIn("Session state:", si)
        self.assertIn("ROLE", si)  # the base rules stay


class TestTaraArchitecture(unittest.TestCase):
    def setUp(self):
        from persona_registry import get_persona_architecture
        self.arch = get_persona_architecture("travel-concierge")
        self.arch._engine = engine()

    def test_registry_alias_and_lock(self):
        from persona_registry import ArchitecturePattern, is_persona_ui_editable, resolve_persona_architecture
        self.assertIs(resolve_persona_architecture("tara"), ArchitecturePattern.JIT_TRAVEL_CARDS)
        self.assertFalse(is_persona_ui_editable("travel-concierge"))
        self.assertTrue(self.arch.owns_language_policy)
        self.assertTrue(self.arch.has_exclusive_tools())
        self.assertEqual(self.arch.compose_system_prompt("ignored client text"), get_tara_root_system_instruction())
        self.assertIn("Prompt card 1", self.arch.compose_system_prompt(None, engine="cascade"))

    def test_setup_tools_follow_the_model(self):
        self.assertFalse(self.arch.bind_live_model("gemini-3.8-live", vertex=False))
        self.assertEqual(len(self.arch.get_tool_schemas()), 6)
        self.assertTrue(self.arch.bind_live_model("gemini-3.8-live", vertex=True))
        self.assertEqual({s.name for s in self.arch.get_tool_schemas()}, set(TOOL_GROUP_BY_CARD[1]))
        self.assertEqual(len(self.arch.get_tool_schemas(engine="cascade")), 6)

    def _call(self, llm, tool, arguments, results):
        class Params:
            pass
        Params.arguments = arguments

        async def result_callback(result):
            results.append(("result", result))
        Params.result_callback = staticmethod(result_callback)
        run(llm.registered[tool](Params))

    def test_card_change_registers_its_tools_before_the_card_is_returned(self):
        order, events, llm = [], [], _FakeLLM()
        ws = llm._session._ws
        real_send = ws.send

        async def send(text):
            await real_send(text)
            order.append(("frame", json.loads(text)))
        ws.send = send

        async def broadcast(payload):
            events.append(payload)

        self.arch.bind_live_model("gemini-3.8-live", vertex=True)
        self.assertEqual(set(self.arch.register_handlers(llm, broadcast=broadcast)), set(TOOL_NAMES))
        llm._bot_is_responding = True  # the model said "one moment" before calling
        self._call(llm, "SelectLanguageTool", {"language": "Hindi"}, order)
        self.assertEqual([kind for kind, _ in order], ["frame", "result"])
        self.assertIn("Prompt card 2 of 8", order[1][1]["prompt_card"])
        declared = order[0][1]["context_update"]["tools"]["tools"][0]["functionDeclarations"]
        self.assertEqual({d["name"] for d in declared}, set(TOOL_GROUP_BY_CARD[2]))
        transition = events[-1]
        self.assertEqual((transition["type"], transition["phase_id"]), ("phase_transition", "BMT_02_TRIP_SEARCH"))
        self.assertTrue(transition["card_pushed"])
        self.assertEqual(transition["tools"], {
            "card": 2, "declared": list(TOOL_GROUP_BY_CARD[2]), "added": ["SearchTool", "CheckAirportTool"],
            "removed": [], "via": "context_update", "status": "sent"})

    def test_static_models_report_the_full_tool_set_on_each_card(self):
        events, llm = [], _FakeLLM()

        async def broadcast(payload):
            events.append(payload)

        self.arch.bind_live_model("gemini-3.5-flash-live-preview", vertex=True)
        self.arch.register_handlers(llm, broadcast=broadcast)
        self._call(llm, "SelectLanguageTool", {"language": "Hindi"}, [])
        self.assertEqual(llm._session._ws.sent, [])
        self.assertEqual(events[-1]["tools"], {
            "card": 2, "declared": list(TOOL_NAMES), "added": [], "removed": [], "via": "static", "status": "sent"})

    def test_first_session_reports_the_card_one_tools_the_setup_declared(self):
        events, llm = [], _FakeLLM()

        async def broadcast(payload):
            events.append(payload)

        self.arch.bind_live_model("gemini-3.8-live", vertex=True)
        self.arch.register_handlers(llm, broadcast=broadcast)
        run(self.arch.on_session_ready(llm, resumed=False))
        self.assertEqual(events[-1]["phase_id"], "BMT_01_LANGUAGE")
        self.assertEqual(events[-1]["tools"], {
            "card": 1, "declared": list(TOOL_GROUP_BY_CARD[1]), "added": list(TOOL_GROUP_BY_CARD[1]),
            "removed": [], "via": "setup", "status": "sent"})
        run(self.arch.on_session_ready(llm, resumed=True))  # a reconnect is not a new card
        self.assertEqual(len([e for e in events if e.get("tools")]), 1)

    def test_resends_after_trim_and_after_a_lost_session_only(self):
        llm = _FakeLLM()
        to_card(self.arch.engine, 3)
        self.assertTrue(run(self.arch.on_context_compressed(llm)))
        self.assertTrue(llm.directives[-1][0].startswith(RESEND_AFTER_TRIM))
        self.assertFalse(llm.directives[-1][2])  # quiet: never "respond now"
        run(self.arch.on_session_ready(llm, resumed=False))  # first connect
        run(self.arch.on_session_ready(llm, resumed=True))  # resumed: server kept context
        self.assertEqual(len(llm.directives), 1)
        run(self.arch.on_session_ready(llm, resumed=False))  # context lost
        self.assertTrue(llm.directives[-1][0].startswith(RESEND_NEW_SESSION))
        self.assertIn("Prompt card 3 of 8", llm.directives[-1][0])

    def _live(self):
        frames, order, llm = [], [], _FakeLLM()
        ws = llm._session._ws
        real_send = ws.send

        async def send(text):
            await real_send(text)
            frames.append(json.loads(text)["context_update"])
            order.append("frame")
        ws.send = send
        self.arch.bind_live_model("gemini-3.8-live", vertex=True)
        self.arch.register_handlers(llm)
        return llm, frames, order

    @staticmethod
    def _si(frame):
        return frame["systemInstruction"]["parts"][0]["text"]

    def test_every_tool_call_refreshes_the_live_instruction_before_its_result(self):
        llm, frames, order = self._live()
        self._call(llm, "SelectLanguageTool", {"language": "Hindi"}, order)
        kinds = lambda: [o if isinstance(o, str) else o[0] for o in order]
        self.assertEqual(kinds(), ["frame", "result"])
        self.assertEqual(set(frames[0]), {"tools", "systemInstruction"})
        self.assertIn("Prompt card 2 of 8", self._si(frames[0]))
        self.assertIn("language: Hindi", self._si(frames[0]))
        self.assertNotIn("Which language would you like", self._si(frames[0]))
        self._call(llm, "SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi",
                                       "destination": "Mumbai", "depart_date": FRI}, order)
        self.assertEqual(kinds()[2:], ["frame", "result"])
        card_changed = self.arch.engine.active_card != 2
        self.assertEqual("tools" in frames[1], card_changed)  # tools travel only with a new card
        self.assertIn("Delhi", self._si(frames[1]))  # the live session state is in the SI
        self._call(llm, "FlightActionTool", {"action": "GET_DETAILS", "flight_id": "F1"}, order)
        later = frames[2:]
        self.assertTrue(all("tools" not in f for f in later if self.arch.engine.active_card == 3))

    def test_the_result_points_at_the_card_instead_of_repeating_it(self):
        # The card already rides in the system instruction; a full copy in the result only
        # grows the history (~550-680 tokens per card change).
        llm, frames, order = self._live()
        self._call(llm, "SelectLanguageTool", {"language": "Hindi"}, order)
        result = order[-1][1]
        self.assertIn("Prompt card 2 of 8", result["prompt_card"])
        self.assertIn("system instruction", result["prompt_card"])
        self.assertLess(len(result["prompt_card"]) // 4, 40)
        self.assertIn("Session state:", self._si(frames[0]))  # the full card is in the SI

    def test_static_models_still_get_the_full_card_in_the_result(self):
        llm = _FakeLLM()
        self.arch.bind_live_model("gemini-3.5-flash-live-preview", vertex=True)
        self.arch.register_handlers(llm)
        out = []
        self._call(llm, "SelectLanguageTool", {"language": "Hindi"}, out)
        self.assertIn("Session state:", out[-1][1]["prompt_card"])

    def test_card_one_keeps_the_setup_instruction(self):
        llm, frames, order = self._live()
        self._call(llm, "SearchTool", {"origin": "Delhi"}, order)  # off-card call on card 1
        self.assertFalse(any("systemInstruction" in f for f in frames))

    def test_compaction_needs_no_history_resend_once_the_instruction_holds_the_card(self):
        llm, frames, order = self._live()
        self._call(llm, "SelectLanguageTool", {"language": "Hindi"}, order)
        self.assertTrue(run(self.arch.on_context_compressed(llm)))
        self.assertEqual(llm.directives, [])  # nothing appended to the history

    def test_a_lost_session_gets_the_live_instruction_back(self):
        llm, frames, order = self._live()
        run(self.arch.on_session_ready(llm, resumed=False))
        self._call(llm, "SelectLanguageTool", {"language": "Hindi"}, order)
        sent = len(frames)
        run(self.arch.on_session_ready(llm, resumed=True))  # the server kept the context
        self.assertEqual(len(frames), sent)
        run(self.arch.on_session_ready(llm, resumed=False))  # setup carried the base SI again
        self.assertEqual(set(frames[-1]), {"systemInstruction"})
        self.assertIn("Prompt card 2 of 8", self._si(frames[-1]))
        self.assertEqual(llm.directives, [])

    def test_opening_messages_seed_card_one(self):
        messages = self.arch.opening_messages()
        self.assertEqual(messages[0]["role"], "user")
        self.assertIn("Prompt card 1 of 8: Language", messages[0]["content"])


class TestAgentLiveHooks(unittest.TestCase):
    def test_language_directive_is_skipped_for_tara(self):
        from agent_live import compose_live_system_prompt
        si = get_tara_root_system_instruction()
        self.assertNotIn("IMPORTANT: You must converse in",
                         compose_live_system_prompt(si, "female", "en-IN", "Sulafat", language_directive=False))
        self.assertIn("IMPORTANT: You must converse in en-IN",
                      compose_live_system_prompt(si, "female", "en-IN", "Sulafat"))

    def test_start_trigger_sends_opening_card_before_hello(self):
        from pipecat.frames.frames import InputTransportMessageFrame, LLMMessagesAppendFrame
        from pipecat.processors.frame_processor import FrameDirection
        from agent_live import StartTriggerProcessor
        processor = StartTriggerProcessor(language="en-IN")
        processor.opening_messages = [{"role": "user", "content": "CARD 1"}]
        pushed = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            pushed.append(frame)

        processor.push_frame = capture
        run(processor.process_frame(InputTransportMessageFrame(message={"type": "start_trigger"}), FrameDirection.DOWNSTREAM))
        append = [f for f in pushed if isinstance(f, LLMMessagesAppendFrame)][0]
        self.assertEqual(append.messages, [{"role": "user", "content": "CARD 1"}, {"role": "user", "content": "Hello!"}])


if __name__ == "__main__":
    unittest.main()


class TestTaraTrace(unittest.TestCase):
    def test_state_diff_names_each_changed_field_old_to_new(self):
        from persona_tools import tara_trace as trace
        from persona_prompt_cards.tara_cards import render_session_state
        e = engine()
        before = trace.state_lines(render_session_state(e.state.snapshot()))
        to_card(e, 4)
        after = trace.state_lines(render_session_state(e.state.snapshot()))
        changes = {label: (old, new) for label, old, new in trace.state_changes(before, after)}
        self.assertEqual(changes["language"][0], "not given yet")
        self.assertNotIn("agent name", changes)

    def test_context_update_prints_the_dynamic_part_exactly(self):
        from persona_tools import tara_trace as trace
        from persona_prompt_cards.tara_cards import get_tara_live_system_instruction
        e = engine()
        to_card(e, 5)
        card = e.build_card()
        si = get_tara_live_system_instruction(card)
        new_card = trace.context_update(3, {"declared": ["A"], "added": ["A"], "removed": []}, si, card, True)
        self.assertIn("Prompt card 5 of 8", new_card)
        self.assertIn("(+['A'] -[])", new_card)
        same_card = trace.context_update(4, None, si, card, False)
        self.assertIn("tools: unchanged", same_card)
        self.assertIn("waiting for:", same_card)
        self.assertNotIn("Goal:", same_card)  # the directive is printed once per card
        result = trace.tool_result("X", {"status": "ok", "prompt_card": card})
        self.assertIn("<System update for agent. Prompt card 5 of 8", result)
        self.assertIn("tokens", result)


class TestToolPreview(unittest.TestCase):
    """The studio's tool panel must show what the session declares for the card it is on."""

    def test_preview_lists_the_card_group_on_gemini_38_vertex(self):
        from persona_registry import get_persona_architecture
        arch = get_persona_architecture("travel-concierge")
        names = lambda phase, **kw: {s.name for s in arch.preview_tool_schemas(phase, **kw)}
        self.assertEqual(names("BMT_01_LANGUAGE"), {"SelectLanguageTool"})
        self.assertEqual(names(None), {"SelectLanguageTool"})  # no phase yet: the opening card
        self.assertEqual(names("BMT_08_PAYMENT"), set(TOOL_GROUP_BY_CARD[8]))
        self.assertEqual(names("BMT_01_LANGUAGE", model="gemini-3.5-flash-live-preview"), set(TOOL_NAMES))
        self.assertEqual(names("BMT_01_LANGUAGE", vertex=False), set(TOOL_NAMES))

    def test_persona_prompt_route_reports_one_tool_on_card_one(self):
        from fastapi.testclient import TestClient
        import server as server_module
        client = TestClient(server_module.app)
        body = client.get("/persona-prompt/travel-concierge?engine=live&phase=BMT_01_LANGUAGE").json()
        self.assertEqual([t["name"] for t in body["tools"]], ["SelectLanguageTool"])
        body = client.get("/persona-prompt/travel-concierge?engine=live&phase=BMT_05_NAME").json()
        self.assertEqual({t["name"] for t in body["tools"]}, set(TOOL_GROUP_BY_CARD[5]))


class TestGauntletEngineBugs(unittest.TestCase):
    """Bugs found by the 3-model gauntlet review (round 1)."""

    def test_round_trip_change_by_reference_needs_and_honours_the_leg(self):
        e = engine()
        to_card(e, 5, trip_type="RT")
        outbound_before, return_before = e.state.outbound.flight_id, e.state.ret.flight_id
        ambiguous = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "reference": "CHEAPEST"})
        self.assertEqual(ambiguous["status"], "error")
        self.assertEqual((e.state.outbound.flight_id, e.state.ret.flight_id), (outbound_before, return_before))
        cheapest_out = min(e.results["outbound"], key=lambda f: (f.fare, f.depart_minutes))
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "reference": "CHEAPEST", "leg": "OUTBOUND"})
        self.assertEqual(e.state.outbound.flight_id, cheapest_out.flight_id)
        self.assertEqual(e.state.ret.flight_id, return_before)

    def test_child_date_of_birth_at_the_count_step_is_a_child_date(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 3})
        result = e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 1,
                                                  "date_of_birth": "2018-05-01"})
        self.assertEqual(e._child_dobs, ["2018-05-01"])
        self.assertTrue(all(t.date_of_birth is None for t in e.state.travellers))
        self.assertEqual(result["data"]["step"], "confirm_passenger_count")

    def test_phone_said_with_the_name_is_kept(self):
        e = engine()
        to_card(e, 5)
        result = e.handle("TravellerDetailsTool", {
            "passenger_index": 1, "first_name_letters": list("RAHUL"), "last_name_letters": list("SHARMA"),
            "spelling_source": "model_guess", "age": 34, "gender": "male", "phone_choice": "same"})
        self.assertEqual(result["data"]["step"], "confirm_name")
        self.assertEqual(e.state.whatsapp, CALLING_NUMBER)
        self.assertTrue(e.state.whatsapp_confirmed)

    def test_adding_travellers_keeps_the_name_said_in_the_same_turn(self):
        e = engine()
        to_card(e, 5)
        result = e.handle("TravellerDetailsTool", {
            "add_more_passengers": True, "passenger_index": 1, "first_name_letters": list("RAHUL"),
            "last_name_letters": list("SHARMA"), "spelling_source": "model_guess", "age": 34, "gender": "male"})
        self.assertEqual(result["data"]["step"], "passenger_count")
        self.assertIn(1, e._pending_name)
        self.assertEqual(e.state.travellers[0].age, 34)

    def test_children_without_a_count_keep_the_person_fields(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        result = e.handle("TravellerDetailsTool", {"includes_children": True, "passenger_index": 1, "age": 34,
                                                  "gender": "male"})
        self.assertEqual(result["data"]["step"], "child_count")
        self.assertEqual(e.state.travellers[0].age, 34)

    def test_a_count_raised_with_a_selection_asks_the_mix_again(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": FRI, "passenger_count": 2})
        e.state.mix_known = True  # e.g. "all adults" heard earlier for two travellers
        result = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1", "passenger_count": 3})
        self.assertEqual(result["data"]["step"], "passenger_mix")

    def test_flight_errors_after_card_three_never_point_at_search(self):
        e = engine()
        to_card(e, 5)
        result = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F99"})
        self.assertEqual(result["status"], "error")
        self.assertNotIn("SearchTool", result["instruction"])

    def test_reselecting_the_same_flight_keeps_the_link_and_the_review(self):
        e = engine()
        to_card(e, 7)
        e.state.details_confirmed = True
        e.state.booking_ref = "BMT0000001"
        e._payment_link_sent = True
        result = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": e.state.outbound.flight_id})
        self.assertTrue(e.state.details_confirmed)
        self.assertEqual(e.state.booking_ref, "BMT0000001")
        self.assertTrue(e._payment_link_sent)
        self.assertIn("already selected", result["change"])

    def test_change_trip_goes_back_to_search_and_keeps_the_travellers(self):
        e = engine()
        to_card(e, 6)
        travellers = [t.name for t in e.state.travellers]
        result = e.handle("FlightActionTool", {"action": "CHANGE_TRIP"})
        self.assertEqual(e.active_card, 2)
        self.assertIn("SearchTool", TOOL_GROUP_BY_CARD[e.active_card])
        self.assertIsNone(e.state.outbound)
        self.assertEqual(result["data"]["step"], "trip_details")
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": MON})
        after = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F2"})
        self.assertEqual([t.name for t in e.state.travellers], travellers)
        self.assertGreaterEqual(e.active_card, 4)
        self.assertNotEqual(after["data"]["step"], "passenger_count")

    def test_every_tool_a_result_names_is_declared_on_the_card_it_lands_on(self):
        """Every tool named in a result's next/instruction is in that card's group (one-way and round trip)."""
        for trip in ("OW", "RT"):
            e = engine()
            seen = []

            def check(name, result, e=e):
                group = set(TOOL_GROUP_BY_CARD[e.active_card])
                named = {n["tool"] for n in result.get("next", [])}
                named |= {t for t in TOOL_NAMES if t in result.get("instruction", "")}
                seen.append((name, e.active_card, named - group))

            to_card(e, 8, trip_type=trip, on_result=check)
            check("PaymentTool", e.handle("PaymentTool", {"action": "PROCEED"}))
            bad = [s for s in seen if s[2]]
            self.assertEqual(bad, [], trip)


class TestGauntletSearchAndPaymentBugs(unittest.TestCase):
    """Round-trip searches, language, child count and payment link (gauntlet round 1)."""

    def _rt_outbound_chosen(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": FRI, "trip_type": "RT", "return_date": MON})
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1"})
        return e

    def test_reversed_route_with_a_new_date_moves_the_return_and_keeps_the_trip(self):
        e = self._rt_outbound_chosen()
        result = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "trip_type": "OW", "origin": "Mumbai",
                                         "destination": "Delhi", "depart_date": "2026-10-14"})
        self.assertEqual(e.state.trip_type, "RT")
        self.assertEqual((e.state.origin, e.state.destination), ("Delhi", "Mumbai"))
        self.assertEqual(e.state.outbound.flight_id, "F1")
        self.assertEqual(e.state.return_date, dt.date(2026, 10, 14))
        self.assertEqual(result["data"]["leg"], "return")

    def test_return_date_alone_moves_the_return(self):
        e = self._rt_outbound_chosen()
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "R1"})
        result = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "return_date": "2026-10-14"})
        self.assertEqual(e.state.return_date, dt.date(2026, 10, 14))
        self.assertIsNone(e.state.ret)  # the old return flight was for the old date
        self.assertEqual(e.state.outbound.flight_id, "F1")
        self.assertEqual(result["data"]["leg"], "return")

    def test_repeated_outbound_search_while_the_return_is_open_keeps_the_outbound(self):
        e = self._rt_outbound_chosen()
        result = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                         "depart_date": FRI})
        self.assertEqual(e.state.outbound.flight_id, "F1")
        self.assertEqual(result["data"]["leg"], "return")
        bare = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE"})
        self.assertEqual(e.state.outbound.flight_id, "F1")
        self.assertEqual(bare["data"]["leg"], "return")

    def test_explicit_one_way_on_the_same_route_is_a_new_trip(self):
        e = self._rt_outbound_chosen()
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "trip_type": "OW", "origin": "Delhi",
                                "destination": "Mumbai", "depart_date": FRI})
        self.assertEqual(e.state.trip_type, "OW")
        self.assertIsNone(e.state.outbound)

    def test_new_outbound_date_is_still_a_new_trip(self):
        e = self._rt_outbound_chosen()
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "depart_date": "2026-10-10"})
        self.assertEqual(e.state.depart_date, dt.date(2026, 10, 10))
        self.assertIsNone(e.state.outbound)

    def test_language_chosen_late_keeps_the_current_step(self):
        e = engine()
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": FRI})  # a static model can search before the language
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1"})
        card, step = e.active_card, e.state.step
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        self.assertEqual((e.active_card, e.state.step), (card, step))
        self.assertEqual(e.state.language, "Hindi")

    def test_impossible_child_count_is_an_error(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        result = e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 2})
        self.assertIn("error", result)
        self.assertEqual(result["data"]["step"], "child_count")
        self.assertEqual(e.state.child_count, 0)

    def test_link_is_reissued_when_the_booking_changed_after_it_was_sent(self):
        e = engine()
        to_card(e, 8)
        first = e.handle("PaymentTool", {"action": "PROCEED"})
        again = e.handle("PaymentTool", {"action": "PROCEED"})
        self.assertEqual(again["status"], "already_sent")
        self.assertEqual(again["data"]["booking_ref"], first["data"]["booking_ref"])
        e.state.email = "rahul.new@gmail.com"  # e.g. changed on a static model after the link went out
        changed = e.handle("PaymentTool", {"action": "PROCEED"})
        self.assertEqual(changed["status"], "link_sent")
        self.assertNotEqual(changed["data"]["booking_ref"], first["data"]["booking_ref"])

    def test_return_flight_and_names_change_the_booking_reference(self):
        refs = set()
        for ret, name in (("R1", "RAHUL"), ("R2", "RAHUL"), ("R1", "ROHAN")):
            e = engine()
            to_card(e, 5, trip_type="RT")
            e.state.ret = next(f for f in e.results["return"] if f.flight_id == ret)
            e.state.travellers[0].first_name = name.capitalize()
            refs.add(e._booking_fingerprint())
        self.assertEqual(len(refs), 3)

    def test_card_eight_never_asks_for_a_second_proceed(self):
        card = TARA_CARD_BY_NUMBER[8]
        text = card.body if hasattr(card, "body") else str(card)
        self.assertIn("never call PROCEED again", text)
        self.assertNotIn("last result's next", text)

    def test_live_si_names_only_tools_of_the_current_card(self):
        from persona_prompt_cards.tara_cards import get_tara_live_system_instruction
        for number in range(1, 9):
            e = engine()
            if number > 1:
                to_card(e, number)
            si = get_tara_live_system_instruction(e.build_card(number))
            named = {t for t in TOOL_NAMES if t in si}
            self.assertLessEqual(named, set(TOOL_GROUP_BY_CARD[number]), (number, named - set(TOOL_GROUP_BY_CARD[number])))


class TestGauntletArchitectureBugs(unittest.TestCase):
    """Reconnects, flush ordering and the studio panel's model awareness."""

    def setUp(self):
        from persona_registry import get_persona_architecture
        self.arch = get_persona_architecture("travel-concierge")
        self.arch._engine = engine()

    def _live(self):
        frames, llm = [], _FakeLLM()
        ws = llm._session._ws
        real_send = ws.send

        async def send(text):
            await real_send(text)
            frames.append(json.loads(text)["context_update"])
        ws.send = send
        self.arch.bind_live_model("gemini-3.8-live", vertex=True)
        self.arch.register_handlers(llm)
        return llm, frames

    def test_setup_on_card_one_greets_with_card_one_in_the_instruction(self):
        self._live()
        si = self.arch.setup_system_instruction()
        self.assertIn("Which language would you like", si)
        self.assertIn("Prompt card 1 of 8: Language", si)
        self.assertNotIn("Never greet again", si)
        self.assertEqual(self.arch.opening_messages(), [])  # card 1 is not repeated in the history

    def test_card_one_is_never_refreshed_mid_call(self):
        self._live()  # a refresh would put the greeting line back after it was spoken
        self.assertIsNone(self.arch._live_instruction())

    def test_static_models_still_send_card_one_ahead_of_the_greeting(self):
        self.arch.bind_live_model("gemini-3.5-flash-live-preview", vertex=True)
        self.assertIn("Prompt card 1 of 8", self.arch.opening_messages()[0]["content"])

    def test_reconnect_setup_carries_the_live_instruction(self):
        self._live()
        to_card(self.arch.engine, 5)
        si = self.arch.setup_system_instruction()
        self.assertIn("Prompt card 5 of 8", si)
        self.assertIn("Session state:", si)
        self.assertEqual(self.arch.swapper.instruction, si)
        self.assertIsNone(self.arch.swapper.pending_instruction)

    def test_static_models_never_override_the_setup_instruction(self):
        self.arch.bind_live_model("gemini-3.5-flash-live-preview", vertex=True)
        to_card(self.arch.engine, 5)
        self.assertIsNone(self.arch.setup_system_instruction())

    def test_reconnect_after_a_live_setup_sends_nothing_resumed_or_not(self):
        llm, frames = self._live()
        run(self.arch.on_session_ready(llm, resumed=False))  # first connect
        to_card(self.arch.engine, 5)
        for resumed in (True, False):
            self.arch.setup_system_instruction()
            sent = len(frames)
            run(self.arch.on_session_ready(llm, resumed=resumed))
            self.assertEqual(len(frames), sent, resumed)
            self.assertEqual(llm.directives, [], resumed)

    def test_flush_waits_for_a_running_tool_call(self):
        llm, frames = self._live()
        seen = []

        async def flush(_llm):
            seen.append(self.arch._lock.locked())
        self.arch.swapper.flush = flush

        async def scenario():
            await self.arch._lock.acquire()
            task = asyncio.ensure_future(self.arch.flush_pending_card())
            await asyncio.sleep(0)
            self.assertEqual(seen, [])  # blocked behind the tool call
            self.arch._lock.release()
            await task
        run(scenario())
        self.assertEqual(seen, [True])

    def test_persona_prompt_route_follows_the_selected_model(self):
        from fastapi.testclient import TestClient
        import server as server_module
        client = TestClient(server_module.app)
        url = "/persona-prompt/travel-concierge?engine=live&phase=BMT_01_LANGUAGE&model="
        static = client.get(url + "gemini-3.5-flash-live-preview").json()
        self.assertEqual({t["name"] for t in static["tools"]}, set(TOOL_NAMES))
        live = client.get(url + "gemini-3.8-live").json()
        self.assertEqual([t["name"] for t in live["tools"]], ["SelectLanguageTool"])


class TestGauntletRoundTwoBugs(unittest.TestCase):
    """Opus round 2: child DOB via early returns, recycled refs, bare date on the return leg."""

    def test_child_dob_on_the_children_question_never_lands_on_adult_one(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 3})
        result = e.handle("TravellerDetailsTool", {"includes_children": True, "date_of_birth": "2018-05-01"})
        self.assertEqual(result["data"]["step"], "child_count")
        self.assertTrue(all(t.date_of_birth is None for t in e.state.travellers))
        self.assertEqual(e._child_dobs, ["2018-05-01"])

    def test_child_dob_with_an_impossible_count_never_lands_on_adult_one(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        result = e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 2,
                                                  "date_of_birth": "2018-05-01"})
        self.assertIn("error", result)
        self.assertTrue(all(t.date_of_birth is None for t in e.state.travellers))

    def test_a_voided_reference_is_never_issued_again(self):
        e = engine()
        to_card(e, 8)
        first = e.handle("PaymentTool", {"action": "PROCEED"})["data"]["booking_ref"]
        original = e.state.outbound
        e.state.outbound = next(f for f in e.results["outbound"] if f.flight_id != original.flight_id)
        second = e.handle("PaymentTool", {"action": "PROCEED"})["data"]["booking_ref"]
        e.state.outbound = original  # back to the first itinerary
        third = e.handle("PaymentTool", {"action": "PROCEED"})
        self.assertEqual(third["status"], "link_sent")
        self.assertEqual(len({first, second, third["data"]["booking_ref"]}), 3)
        self.assertEqual(e.handle("PaymentTool", {"action": "PROCEED"})["status"], "already_sent")

    def test_the_return_offer_says_where_a_new_return_date_goes(self):
        # depart_date keeps one meaning (the outbound date, see test_new_outbound_date_is_still_a_new_trip);
        # the return offer tells the model to send a new return date as return_date alone.
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": FRI, "trip_type": "RT", "return_date": MON})
        chosen = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1"})
        offer = e.handle("SearchTool", chosen["next"][0]["arguments"])
        self.assertEqual(e.state.step, "flight_choice_return")
        self.assertIn("only return_date", offer["instruction"])
        moved = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "return_date": "2026-10-14"})
        self.assertEqual((e.state.return_date, e.state.outbound.flight_id), (dt.date(2026, 10, 14), "F1"))
        self.assertEqual(moved["data"]["leg"], "return")

    def test_change_trip_forgets_the_half_heard_search(self):
        e = engine()
        to_card(e, 6)
        e._draft = {"depart": dt.date(2026, 10, 27)}
        e.handle("FlightActionTool", {"action": "CHANGE_TRIP"})
        self.assertEqual(e._draft, {})

    def test_from_card_four_only_offered_flights_can_be_selected(self):
        e = engine()
        to_card(e, 5)
        offered = e.offered["outbound"]
        unheard = next(f.flight_id for f in e.results["outbound"] if f.flight_id not in offered)
        result = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": unheard})
        self.assertEqual(result["status"], "error")
        self.assertIn("not offered", result["error"] if "error" in result else result["instruction"])
        self.assertNotEqual(e.state.outbound.flight_id, unheard)


class TestGauntletRoundTwoFableBugs(unittest.TestCase):
    """Fable round 2: a half-heard outbound date, reverse round trips, re-select after the link."""

    def _rt_outbound_chosen(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": FRI, "trip_type": "RT", "return_date": MON})
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F1"})
        return e

    def test_an_outbound_date_after_the_return_survives_the_return_date_answer(self):
        e = self._rt_outbound_chosen()
        first = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "depart_date": "2026-10-14"})
        self.assertIn("return date", first.get("error", "") + first.get("instruction", ""))
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "return_date": "2026-10-16"})
        self.assertEqual((e.state.depart_date, e.state.return_date), (dt.date(2026, 10, 14), dt.date(2026, 10, 16)))
        self.assertIsNone(e.state.outbound)  # a new trip: the old outbound was for the 9th

    def test_reversed_route_as_a_round_trip_is_a_new_trip(self):
        e = self._rt_outbound_chosen()
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Mumbai", "destination": "Delhi",
                                "trip_type": "RT", "depart_date": "2026-10-20", "return_date": "2026-10-25"})
        self.assertEqual((e.state.origin, e.state.destination), ("Mumbai", "Delhi"))
        self.assertEqual((e.state.depart_date, e.state.return_date), (dt.date(2026, 10, 20), dt.date(2026, 10, 25)))

    def test_reselecting_after_the_link_keeps_the_payment_step(self):
        e = engine()
        to_card(e, 8)
        e.handle("PaymentTool", {"action": "PROCEED"})
        held = e.state.outbound.flight_id
        e.active_card = 7  # static models keep FlightActionTool declared; pretend the model calls it here
        result = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": held})
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(e.state.step, "payment_sent")
        self.assertNotIn("PROCEED", json.dumps(result.get("next", [])))

    def test_a_stalled_socket_leaves_the_update_pending(self):
        import live_tool_swapper
        llm = _FakeLLM()

        async def stall(_text):
            await asyncio.sleep(5)
        llm._session._ws.send = stall
        swapper = live_tool_swapper.LiveToolSwapper(lambda names: [{"name": n} for n in names], TOOL_GROUP_BY_CARD[1], label="t")
        old, live_tool_swapper.SEND_TIMEOUT_S = live_tool_swapper.SEND_TIMEOUT_S, 0.05
        try:
            run(swapper.register(llm, TOOL_GROUP_BY_CARD[2]))
        finally:
            live_tool_swapper.SEND_TIMEOUT_S = old
        self.assertEqual(tuple(swapper.pending), tuple(TOOL_GROUP_BY_CARD[2]))


class TestGauntletRoundThreeBugs(unittest.TestCase):
    """Round 3 (Opus A/B/C, Fable R3-1..3 + backlog): sticky draft, heard flights, payment_sent re-select."""

    def _rt_outbound_chosen(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": "2026-10-20", "trip_type": "RT", "return_date": "2026-10-25"})
        chosen = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F2"})
        return e, chosen["next"][0]["arguments"]

    def _failed_new_outbound(self):
        e, return_args = self._rt_outbound_chosen()
        bad = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "depart_date": "2026-10-27"})
        self.assertEqual(bad["status"], "error")
        return e, return_args

    def test_after_a_failed_outbound_date_the_return_arguments_still_offer_the_return(self):
        e, return_args = self._failed_new_outbound()
        result = e.handle("SearchTool", return_args)
        self.assertEqual((e.state.trip_type, e.state.outbound.flight_id), ("RT", "F2"))
        self.assertEqual(result["data"]["leg"], "return")
        self.assertEqual(e._draft, {})

    def test_keeping_the_stored_return_after_a_failed_outbound_date_is_not_a_loop(self):
        e, _ = self._failed_new_outbound()
        result = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "return_date": "2026-10-25"})
        self.assertNotEqual(result["status"], "error")
        self.assertEqual((e.state.depart_date, e.state.outbound.flight_id), (dt.date(2026, 10, 20), "F2"))

    def test_keeping_the_stored_outbound_date_keeps_the_chosen_flight(self):
        e, _ = self._failed_new_outbound()
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "depart_date": "2026-10-20"})
        self.assertEqual(e.state.outbound.flight_id, "F2")

    def test_a_flight_heard_before_refine_more_can_still_be_chosen(self):
        e = engine()
        to_card(e, 5)
        first_two = list(e.offered["outbound"])
        e.handle("SearchTool", {"query_sub_type": "REFINE_RESULTS", "refinement": "MORE"})
        other = next(f for f in first_two if f != e.state.outbound.flight_id)
        result = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": other})
        self.assertEqual(result["status"], "changed")

    def test_a_no_match_filter_does_not_switch_the_heard_guard_off(self):
        e = engine()
        to_card(e, 5)
        heard = set(e._heard_ids["outbound"])
        e.offered["outbound"] = []  # what a no_flights refine leaves behind
        unheard = next(f.flight_id for f in e.results["outbound"] if f.flight_id not in heard)
        self.assertEqual(e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": unheard})["status"], "error")

    def test_the_payment_step_points_at_information_with_a_heads_up(self):
        e = engine()
        to_card(e, 8)
        e.handle("PaymentTool", {"action": "PROCEED"})
        e.active_card = 7
        result = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": e.state.outbound.flight_id})
        self.assertEqual(result["data"]["step"], "payment_sent")
        self.assertTrue(result.get("heads_up"))
        self.assertEqual([(n["tool"], n.get("arguments", {}).get("action")) for n in result["next"]],
                         [("PaymentTool", "INFORMATION")])

    def test_the_alternatives_search_clears_the_draft(self):
        e, return_args = self._rt_outbound_chosen()
        e.handle("SearchTool", return_args)
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "R1"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": "2026-10-20"})
        self.assertEqual(e._draft, {})

    def test_adding_a_return_to_a_one_way_is_not_an_outbound_change(self):
        e = engine()
        to_card(e, 5)  # one way
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": e.state.origin, "destination": e.state.destination,
                                "depart_date": e.state.depart_date.isoformat(), "trip_type": "RT", "return_date": "2026-10-16"})
        self.assertEqual((e.state.trip_type, e.state.return_date), ("RT", dt.date(2026, 10, 16)))


class TestGauntletRoundFourBugs(unittest.TestCase):
    """Round 4 (Opus calendar draft, Fable OW-shaped alternatives) + Argon round 3 leftovers."""

    def _rt_outbound_chosen(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": "2026-10-20", "trip_type": "RT", "return_date": "2026-10-25"})
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F2"})
        return e

    def test_browsing_a_calendar_is_not_a_chosen_departure(self):
        e = self._rt_outbound_chosen()
        e.handle("SearchTool", {"query_sub_type": "DATE_RANGE", "depart_date": "2026-10-21", "depart_date_end": "2026-10-23"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "return_date": "2026-10-27"})
        self.assertEqual((e.state.depart_date, e.state.return_date), (dt.date(2026, 10, 20), dt.date(2026, 10, 27)))
        self.assertEqual(e.state.outbound.flight_id, "F2")

    def test_ow_shaped_alternatives_keep_the_round_trip(self):
        e = engine()
        to_card(e, 5, trip_type="RT")
        ret = e.state.ret.flight_id
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "trip_type": "OW", "origin": e.state.origin,
                                "destination": e.state.destination, "depart_date": e.state.depart_date.isoformat()})
        self.assertEqual((e.state.trip_type, e.state.ret.flight_id), ("RT", ret))
        self.assertGreaterEqual(e.active_card, 4)

    def test_a_child_date_resent_with_a_corrected_count_never_lands_on_adult_one(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 2})
        e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 2, "date_of_birth": "2018-05-01"})
        e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 1, "date_of_birth": "2018-05-01"})
        self.assertTrue(all(t.date_of_birth is None for t in e.state.travellers))
        self.assertEqual(e._child_dobs, ["2018-05-01"])

    def test_more_twice_reaches_flights_not_heard_yet(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai", "depart_date": FRI})
        e.handle("SearchTool", {"query_sub_type": "REFINE_RESULTS", "refinement": "MORE"})
        e.handle("SearchTool", {"query_sub_type": "REFINE_RESULTS", "refinement": "MORE"})
        self.assertEqual(len(e._heard_ids["outbound"]), min(6, len(e.results["outbound"])))

    def test_cheapest_after_card_three_picks_among_heard_flights(self):
        e = engine()
        to_card(e, 5)
        heard = set(e._heard_ids["outbound"])
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "reference": "CHEAPEST", "leg": "OUTBOUND"})
        self.assertIn(e.state.outbound.flight_id, heard)

    def test_a_route_change_answered_with_a_return_date_is_the_new_trip(self):
        e = self._rt_outbound_chosen()
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "destination": "Bengaluru", "return_date": "2026-10-08"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "return_date": "2026-10-24"})
        self.assertEqual(e.state.destination, "Bengaluru")
        self.assertEqual(e.state.return_date, dt.date(2026, 10, 24))


class TestGauntletRoundFiveBugs(unittest.TestCase):
    """Round 5 (Opus): browsed calendars, echoed child dates vs twins, bare one-way switch."""

    def _rt_outbound_chosen(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": "2026-10-20", "trip_type": "RT", "return_date": "2026-10-25"})
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F2"})
        return e

    def _goa_calendar(self, e):
        e.handle("SearchTool", {"query_sub_type": "DATE_RANGE", "origin": "Delhi", "destination": "Goa",
                                "depart_date": "2026-10-21", "depart_date_end": "2026-10-23"})

    def test_a_calendar_for_another_route_is_only_browsing(self):
        e = self._rt_outbound_chosen()
        self._goa_calendar(e)
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "return_date": "2026-10-27"})
        self.assertEqual((e.state.destination, e.state.outbound.flight_id), ("Mumbai", "F2"))
        self.assertEqual(e.state.return_date, dt.date(2026, 10, 27))

    def test_calendar_cheapest_books_the_browsed_route(self):
        e = self._rt_outbound_chosen()
        self._goa_calendar(e)
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "date_reference": "CALENDAR_CHEAPEST"})
        self.assertEqual((e.state.destination, e.state.depart_date), ("Goa", e.calendar_cheapest))

    def test_calendar_cheapest_on_card_two(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "DATE_RANGE", "origin": "Delhi", "destination": "Goa",
                                "depart_date": "2026-10-21", "depart_date_end": "2026-10-23"})
        result = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "date_reference": "CALENDAR_CHEAPEST"})
        self.assertEqual((e.state.origin, e.state.destination, e.state.depart_date), ("Delhi", "Goa", e.calendar_cheapest))
        self.assertTrue(result["data"].get("flights"))

    def test_a_date_echoed_with_the_count_is_not_a_twin(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 3})
        e.handle("TravellerDetailsTool", {"includes_children": True, "date_of_birth": "2018-05-01"})
        result = e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 2, "date_of_birth": "2018-05-01"})
        self.assertEqual(e._child_dobs, ["2018-05-01"])
        self.assertEqual(result["data"]["step"], "child_date_of_birth")

    def test_twins_share_a_date_of_birth(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 3})
        first = e.handle("TravellerDetailsTool", {"includes_children": True, "child_count": 2})
        self.assertEqual(first["data"]["step"], "child_date_of_birth")
        e.handle("TravellerDetailsTool", {"date_of_birth": "2018-05-01"})
        e.handle("TravellerDetailsTool", {"date_of_birth": "2018-05-01"})
        self.assertEqual(e._child_dobs, ["2018-05-01", "2018-05-01"])

    def test_a_bare_one_way_switch_after_both_legs_is_a_one_way_trip(self):
        e = engine()
        to_card(e, 5, trip_type="RT")
        outbound = e.state.outbound.flight_id
        result = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "trip_type": "OW"})
        self.assertEqual((e.state.trip_type, e.state.ret, e.state.return_date), ("OW", None, None))
        self.assertEqual(e.state.outbound.flight_id, outbound)  # only the return was dropped
        self.assertNotIn(result["data"]["step"], ("flight_choice", "flight_choice_outbound"))
        self.assertIn("one way", result["change"])


class TestGauntletRoundSixBugs(unittest.TestCase):
    """Round 6 (Opus R6, Fable R5): the calendar is one-shot context; one-way keeps the outbound."""

    def _rt_outbound_chosen(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": "2026-10-20", "trip_type": "RT", "return_date": "2026-10-25"})
        chosen = e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F2"})
        return e, chosen["next"][0]["arguments"]

    def test_same_route_calendar_then_the_stored_return_day_offers_the_return(self):
        e, _ = self._rt_outbound_chosen()
        e.handle("SearchTool", {"query_sub_type": "DATE_RANGE", "depart_date": "2026-10-19", "depart_date_end": "2026-10-25"})
        result = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "depart_date": "2026-10-25"})
        self.assertEqual((e.state.outbound.flight_id, e.state.depart_date), ("F2", dt.date(2026, 10, 20)))
        self.assertEqual(result["data"]["leg"], "return")

    def test_a_dismissed_calendar_never_reroutes_a_later_date(self):
        e, return_args = self._rt_outbound_chosen()
        e.handle("SearchTool", {"query_sub_type": "DATE_RANGE", "origin": "Delhi", "destination": "Goa",
                                "depart_date": "2026-10-21", "depart_date_end": "2026-10-23"})
        e.handle("SearchTool", return_args)
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "R2"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "depart_date": "2026-10-22"})
        self.assertEqual(e.state.destination, "Mumbai")

    def test_a_day_right_after_a_calendar_takes_its_route_even_outside_the_range(self):
        e, _ = self._rt_outbound_chosen()
        e.handle("SearchTool", {"query_sub_type": "DATE_RANGE", "origin": "Delhi", "destination": "Goa",
                                "depart_date": "2026-10-21", "depart_date_end": "2026-10-23"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "depart_date": "2026-10-22"})
        self.assertEqual((e.state.destination, e.state.depart_date), ("Goa", dt.date(2026, 10, 22)))

    def test_a_failed_calendar_leaves_the_draft_alone(self):
        e, _ = self._rt_outbound_chosen()
        bad = e.handle("SearchTool", {"query_sub_type": "DATE_RANGE", "origin": "Delhi", "destination": "Goa",
                                      "depart_date": "2026-09-01", "depart_date_end": "2026-09-03"})
        self.assertEqual(bad["status"], "error")
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "return_date": "2026-10-27"})
        self.assertEqual((e.state.destination, e.state.outbound.flight_id), ("Mumbai", "F2"))
        self.assertEqual(e.state.return_date, dt.date(2026, 10, 27))

    def test_one_way_at_the_return_step_keeps_the_outbound(self):
        e, _ = self._rt_outbound_chosen()
        result = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "trip_type": "OW"})
        self.assertEqual((e.state.trip_type, e.state.outbound.flight_id), ("OW", "F2"))
        self.assertGreaterEqual(e.active_card, 4)
        self.assertNotIn("return", e.results)



class TestSystemInstructionRevamp(unittest.TestCase):
    """context_update replaces the whole instruction, so each one is complete and says each rule once."""

    @staticmethod
    def _live_si(number):
        from persona_prompt_cards.tara_cards import get_tara_live_system_instruction
        e = engine()
        if number > 1:
            to_card(e, number)
        return get_tara_live_system_instruction(e.build_card(number, for_instruction=True), greeting=number == 1)

    def test_every_live_instruction_says_each_line_once_and_ends_with_the_reminder(self):
        for number in range(1, 9):
            si = self._live_si(number)
            lines = [line for line in si.splitlines() if line.strip()]
            with self.subTest(card=number):
                self.assertEqual(len(lines), len(set(lines)))
                self.assertEqual(si.count("Before you speak:"), 1)
                self.assertTrue(lines[-1].startswith("Before you speak:"))
                self.assertNotIn("System update for agent", si)
                self.assertNotIn("You are Tara, a woman", si)  # the base already says who she is
                self.assertNotIn("ALWAYS", si)

    def test_live_instruction_describes_its_own_transport(self):
        si = self._live_si(4)
        self.assertIn("CURRENT STEP AND SESSION STATE", si)
        self.assertNotIn("prompt_card field of a tool result", si)

    def test_base_rules_are_at_most_1250_tokens(self):
        from persona_prompt_cards.tara_cards import STEP_MARKER
        base = self._live_si(5).partition(STEP_MARKER)[0]
        self.assertLess(len(base) / 4, 1250)

    def test_card_specific_rules_live_on_their_cards(self):
        from persona_prompt_cards.tara_cards import STEP_MARKER
        base = self._live_si(5).partition(STEP_MARKER)[0]
        self.assertNotIn("returns no flights", base)
        self.assertNotIn("FIRST or CHEAPEST", base)
        self.assertIn("returns no flights", TARA_CARD_BY_NUMBER[2].directive)
        self.assertIn("returns no flights", TARA_CARD_BY_NUMBER[3].directive)
        for number in range(4, 8):
            self.assertIn("never use FIRST or CHEAPEST", TARA_CARD_BY_NUMBER[number].directive)

    def test_message_transport_keeps_the_system_update_contract(self):
        root = get_tara_root_system_instruction()
        self.assertIn("System update for agent", root)
        self.assertEqual(root.count("Before you speak:"), 1)
        card = engine().build_card(1)
        self.assertTrue(card.startswith("System update for agent. Prompt card 1 of 8"))
        self.assertIn("You are Tara, a woman", card)


class TestGauntletRoundSevenBugs(unittest.TestCase):
    """Round 7 (Opus R7): the cheapest calendar day is one-shot too; one-way drops the stale draft."""

    def _rt_outbound_chosen(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                "depart_date": "2026-10-20", "trip_type": "RT", "return_date": "2026-10-25"})
        e.handle("FlightActionTool", {"action": "SELECT_FLIGHT", "flight_id": "F2"})
        return e

    def test_calendar_cheapest_after_an_intervening_call_asks_instead_of_rebooking(self):
        for between in (("FlightActionTool", {"action": "FLIGHT_DETAILS", "flight_id": "F2"}),
                        ("SelectLanguageTool", {"language": "English"})):
            e = self._rt_outbound_chosen()
            e.handle("SearchTool", {"query_sub_type": "DATE_RANGE", "origin": "Delhi", "destination": "Goa",
                                    "depart_date": "2026-10-21", "depart_date_end": "2026-10-23"})
            e.handle(*between)
            result = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "date_reference": "CALENDAR_CHEAPEST"})
            with self.subTest(between=between[0]):
                self.assertEqual(result["status"], "error")
                self.assertEqual((e.state.destination, e.state.outbound.flight_id), ("Mumbai", "F2"))

    def test_calendar_cheapest_right_after_the_calendar_still_books_its_route(self):
        e = self._rt_outbound_chosen()
        cal = e.handle("SearchTool", {"query_sub_type": "DATE_RANGE", "origin": "Delhi", "destination": "Goa",
                                      "depart_date": "2026-10-21", "depart_date_end": "2026-10-23"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "date_reference": "CALENDAR_CHEAPEST"})
        self.assertEqual((e.state.destination, e.state.depart_date.isoformat()),
                         ("Goa", cal["data"]["cheapest"]["date"]))

    def test_one_way_switch_clears_the_stale_round_trip_draft(self):
        e = self._rt_outbound_chosen()
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "depart_date": "2026-10-27"})
        e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "trip_type": "OW"})
        self.assertEqual((e.state.trip_type, e.state.outbound.flight_id), ("OW", "F2"))
        self.assertEqual(e._draft, {})
        self.assertIsNone(e.state.heard)


class TestLiveSessionFindings(unittest.TestCase):
    """Findings from the live session s_6fe39282 (2026-10-04)."""

    def test_tara_greeting_trigger_is_not_caller_speech_in_any_language(self):
        # F1: on hi-IN the injected "नमस्ते!" read as the caller choosing Hindi; Tara never introduced herself.
        from persona_registry import get_persona_architecture
        arch = get_persona_architecture("travel-concierge")
        self.assertNotIn("नमस्ते", arch.greeting_text)
        self.assertIn("not spoken", arch.greeting_text)
        self.assertIn("not the caller", get_tara_root_system_instruction())

    def test_start_trigger_uses_the_persona_greeting_text(self):
        from pipecat.frames.frames import InputTransportMessageFrame, LLMMessagesAppendFrame
        from pipecat.processors.frame_processor import FrameDirection
        from agent_live import StartTriggerProcessor
        processor = StartTriggerProcessor(language="hi-IN")
        processor.greeting_text = "(call connected)"
        pushed = []

        async def capture(frame, direction=FrameDirection.DOWNSTREAM):
            pushed.append(frame)

        processor.push_frame = capture
        run(processor.process_frame(InputTransportMessageFrame(message={"type": "start_trigger"}), FrameDirection.DOWNSTREAM))
        append = [f for f in pushed if isinstance(f, LLMMessagesAppendFrame)][0]
        self.assertEqual(append.messages[-1], {"role": "user", "content": "(call connected)"})

    def test_cards_four_and_five_tell_the_model_to_send_a_volunteered_number(self):
        # F2: "7738035517" said with the name was never sent; the calling number was offered instead.
        for number in (4, 5):
            self.assertIn("phone_number", TARA_CARD_BY_NUMBER[number].directive)

    def test_a_number_said_with_the_count_is_read_back_instead_of_the_calling_number(self):
        e = engine()
        to_card(e, 4)
        e.handle("TravellerDetailsTool", {"passenger_count": 1, "includes_children": False, "phone_number": "7738035517"})
        e.handle("TravellerDetailsTool", {"first_name_letters": list("MANISH"), "last_name_letters": list("KUMAR"),
                                          "spelling_source": "caller_spelled", "age": 39, "gender": "male"})
        result = e.handle("TravellerDetailsTool", {"name_confirmed": True})
        self.assertEqual(result["data"]["step"], "confirm_phone")
        self.assertEqual(result["phone_digits"], " ".join("7738035517"))


class TestGauntletRoundEightBugs(unittest.TestCase):
    """Round 8 (Opus R8): two prompt rules the revamp dropped, the calendar route check, cascade footer."""

    def test_search_cards_forbid_a_checking_line_of_its_own(self):
        for number in (2, 3):
            self.assertIn("without your own checking line", TARA_CARD_BY_NUMBER[number].directive)

    def test_flight_change_cards_carry_the_barge_in_rule(self):
        for number in range(4, 8):
            self.assertIn("ye wala", TARA_CARD_BY_NUMBER[number].directive)

    def test_calendar_cheapest_for_another_route_than_the_calendar_errors(self):
        e = engine()
        e.handle("SelectLanguageTool", {"language": "Hindi"})
        e.handle("SearchTool", {"query_sub_type": "DATE_RANGE", "origin": "Delhi", "destination": "Goa",
                                "depart_date": "2026-10-21", "depart_date_end": "2026-10-23"})
        result = e.handle("SearchTool", {"query_sub_type": "SPECIFIC_DATE", "origin": "Delhi", "destination": "Mumbai",
                                         "date_reference": "CALENDAR_CHEAPEST"})
        self.assertEqual(result["status"], "error")
        self.assertIsNone(e.state.destination)

    def test_cascade_prompt_ends_with_the_reminder(self):
        si = get_tara_monolithic_system_instruction()
        self.assertTrue(si.rstrip().splitlines()[-1].startswith("Before you speak:"))
        self.assertEqual(si.count("Before you speak:"), 1)
        self.assertIn("Prompt card 1 of 8: Language", si)


class TestGauntletRoundNineBugs(unittest.TestCase):
    """Round 9 (Opus, Fable, Argon): cascade greeting, volunteered phone on cards 4-5, START wording."""

    def test_cascade_greeting_uses_the_persona_stub(self):
        from agent import cascade_greeting_text
        from persona_registry import get_persona_architecture
        arch = get_persona_architecture("travel-concierge")
        self.assertEqual(cascade_greeting_text(arch, "hi-IN"), arch.greeting_text)
        self.assertEqual(cascade_greeting_text(None, "hi-IN"), "नमस्ते!")
        self.assertEqual(cascade_greeting_text(None, "en-IN"), "Hello!")

    def test_start_quotes_the_exact_stub(self):
        from persona_prompt_cards.tara_cards import GREETING_STUB
        from persona_registry import get_persona_architecture
        self.assertEqual(get_persona_architecture("travel-concierge").greeting_text, GREETING_STUB)
        self.assertIn(GREETING_STUB, get_tara_root_system_instruction())
        self.assertNotIn("The first message", get_tara_root_system_instruction())

    def test_cascade_prompt_carries_the_opening_session_state(self):
        si = get_tara_monolithic_system_instruction()
        self.assertIn("Session state:", si)
        self.assertIn("language: not given yet", si)

    def test_a_clipped_number_on_card_four_never_jumps_to_the_contact_step(self):
        e = engine()
        to_card(e, 4)
        result = e.handle("TravellerDetailsTool", {"passenger_count": 2, "phone_number": "773803551"})
        self.assertEqual((e.active_card, e.state.step), (4, "passenger_mix"))
        self.assertNotIn("error", result)
        self.assertIsNone(e.state.whatsapp)

    def test_a_bare_short_number_on_card_five_stays_on_names(self):
        e = engine()
        to_card(e, 5)
        e.handle("TravellerDetailsTool", {"phone_number": "98765"})
        self.assertEqual(e.active_card, 5)

    def test_a_number_said_with_the_name_shows_in_the_next_card_state(self):
        e = engine()
        to_card(e, 4)
        result = e.handle("TravellerDetailsTool", {
            "passenger_count": 1, "first_name_letters": list("MANISH"), "last_name_letters": list("KUMAR"),
            "spelling_source": "model_guess", "age": 39, "gender": "male", "phone_number": "7738035517"})
        self.assertNotIn("WhatsApp: not given yet", result.get("prompt_card", ""))
        self.assertEqual(e.state.whatsapp, "7738035517")


class TestVocalToneAnchor(unittest.TestCase):
    """vocal_tone rides in every tool result so the accent rule sits next to the decode point."""

    def test_engine_default_sends_no_vocal_tone(self):
        result = engine().handle("SelectLanguageTool", {"language": "Hindi"})
        self.assertNotIn("vocal_tone", result)

    def test_every_result_carries_the_anchor_when_set(self):
        from persona_prompt_cards.tara_cards import VOCAL_TONE
        e = TravelBookingEngine(today=TODAY, vocal_tone=VOCAL_TONE)
        ok = e.handle("SelectLanguageTool", {"language": "Hindi"})
        self.assertEqual(ok["vocal_tone"], VOCAL_TONE)
        self.assertIn("call_state", ok)
        failed = e.failure("SearchTool")
        self.assertEqual(failed["vocal_tone"], VOCAL_TONE)
        self.assertIn("error", failed)

    def test_anchor_is_short(self):
        from persona_prompt_cards.tara_cards import VOCAL_TONE
        self.assertLess(len(VOCAL_TONE) // 4, 25)  # ~4 chars per token: a one-line reminder

    def test_base_si_never_speaks_the_anchor(self):
        from persona_prompt_cards.tara_cards import get_tara_live_system_instruction
        for si in (get_tara_root_system_instruction(), get_tara_live_system_instruction("x", greeting=True)):
            self.assertIn("Never speak instruction, prompt_card, call_state or vocal_tone.", si)

    def test_registry_engine_sends_the_anchor(self):
        from persona_prompt_cards.tara_cards import VOCAL_TONE
        from persona_registry import get_persona_architecture
        arch = get_persona_architecture("travel-concierge")
        arch._engine = None
        try:
            self.assertEqual(arch.engine.vocal_tone, VOCAL_TONE)
        finally:
            arch._engine = None

    def test_pointer_keeps_the_anchor(self):
        from persona_prompt_cards.tara_cards import VOCAL_TONE
        from persona_registry import get_persona_architecture
        arch = get_persona_architecture("travel-concierge")
        pointed = arch._point_at_instruction(
            {"instruction": "Ask for the route.", "prompt_card": "<full card>", "call_state": "Language: Hindi",
             "vocal_tone": VOCAL_TONE}, 2)
        self.assertEqual(pointed["vocal_tone"], VOCAL_TONE)
        self.assertIn("Prompt card 2 of 8", pointed["prompt_card"])
        self.assertEqual(set(pointed), {"instruction", "prompt_card", "call_state", "vocal_tone"})

    def test_empty_declarations_send_the_clear_all_wrapper(self):
        # proto: a set-but-empty Tools wrapper clears every tool; an absent key keeps them.
        self.assertEqual(context_update_frame([])["context_update"], {"tools": {}})
        self.assertNotIn("tools", context_update_frame(system_instruction="SI")["context_update"])

    def test_whitelist_lets_spelled_fields_be_spoken(self):
        si = get_tara_root_system_instruction()
        self.assertIn("any field ending in _say or _spell (exactly as given)", si)
        self.assertNotIn("say nothing and wait", si)
