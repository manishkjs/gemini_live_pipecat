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
        new = "F3" if old != "F3" else "F4"
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

    def test_card_eight_can_still_change_a_flight(self):
        self.assertIn("SearchTool", TOOL_GROUP_BY_CARD[8])
        self.assertIn("SearchTool", TARA_CARD_BY_NUMBER[8].directive)


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
