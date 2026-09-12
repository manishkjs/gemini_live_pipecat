"""Explicit model phase selection and structured booking argument validation."""
import unittest
from supercar_phases import (
    CallSlots, PragyaPhaseTracker, SOP_01_OPENING, SOP_02_DISCOVERY,
    SOP_03_PINCODE, SOP_04_BOOKED, resolves_to_a_day, resolves_to_a_time,
)


class TestPhaseSelection(unittest.TestCase):
    def test_current_topic_can_return_while_progress_is_retained(self):
        tracker = PragyaPhaseTracker()
        self.assertEqual(tracker.current_phase, SOP_01_OPENING)
        tracker.select_phase(SOP_03_PINCODE)
        tracker.select_phase(SOP_02_DISCOVERY)
        self.assertEqual(tracker.current_index, 1)
        self.assertEqual(tracker.furthest_phase, SOP_03_PINCODE)

    def test_booked_requires_tool_evidence(self):
        tracker = PragyaPhaseTracker()
        with self.assertRaises(ValueError):
            tracker.select_phase(SOP_04_BOOKED)
        self.assertEqual(tracker.current_phase, SOP_01_OPENING)
        tracker.booking_confirmed = True
        tracker.select_phase(SOP_04_BOOKED)
        tracker.select_phase(SOP_02_DISCOVERY)
        self.assertTrue(tracker.booking_confirmed)
        self.assertEqual(tracker.furthest_phase, SOP_04_BOOKED)


class TestStructuredSlots(unittest.TestCase):
    def test_pin_is_an_exact_structured_field_not_a_speech_match(self):
        for pin in ("PIN 560048", "5600489999", "5 6 0 0 4 8", "५६००४८", "012345", "Mumbai", 560048):
            slots = CallSlots()
            self.assertEqual(slots.propose(pincode=pin), ["pincode"])
            self.assertIsNone(slots.get("pincode"))
        self.assertEqual(slots.propose(pincode="560048"), [])
        self.assertEqual(slots.get("pincode"), "560048")

    def test_blank_optional_fields_retain_collected_values(self):
        slots = CallSlots()
        slots.propose(pincode="560048", visit_date="Tomorrow", visit_time="3 PM")
        slots.propose(pincode="", visit_date=None, car_choice="")
        self.assertTrue(slots.is_bookable())
        self.assertIsNone(slots.get("car_choice"))

    def test_invalid_fields_are_reported_and_cannot_replace_valid_values(self):
        slots = CallSlots()
        slots.propose(visit_date="Saturday", visit_time="15:30")
        self.assertEqual(slots.propose(visit_date="Next week", visit_time="morning"), ["visit_date", "visit_time"])
        self.assertEqual(slots.get("visit_date"), "Saturday")
        self.assertEqual(slots.get("visit_time"), "15:30")

    def test_day_validation_does_not_search_sentences(self):
        for day in ("Tomorrow", "Day after tomorrow", "Saturday", "2026-09-19"):
            self.assertTrue(resolves_to_a_day(day), day)
        for day in ("", "next week", "not tomorrow", "2026-02-30", "20260919", "Saturday or Sunday"):
            self.assertFalse(resolves_to_a_day(day), day)

    def test_clock_validation_requires_a_concrete_time(self):
        for time in ("15:30", "11:00 AM", "3 PM", "3pm"):
            self.assertTrue(resolves_to_a_time(time), time)
        for time in ("", "morning", "sometime at 3 PM", "25:00", "13 PM", "3 PM or 4 PM"):
            self.assertFalse(resolves_to_a_time(time), time)

    def test_model_cannot_claim_booking_or_lounge_ownership(self):
        slots = CallSlots()
        slots.propose(booking_status="confirmed", booking_ref="fake", lounge_name="fake")
        self.assertEqual(slots.as_dict(), {"booking_status": "not_started"})
        slots.set_tool(booking_status="confirmed", booking_ref="LAMBO-123")
        slots.set_server(lounge_name="Demo Lounge")
        slots.propose(pincode="110037")
        self.assertIsNone(slots.get("lounge_name"))
        self.assertEqual(slots.get("booking_ref"), "LAMBO-123")
