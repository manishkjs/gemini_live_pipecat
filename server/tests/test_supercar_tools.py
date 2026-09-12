"""Unit tests for Lamborghini Experience Lounge lookup and appointment booking tools."""

import unittest

from supercar_tools import (
    get_exp_center,
    create_appointment_booking,
    SUPERCAR_TOOL_SCHEMAS,
)


class TestSupercarTools(unittest.TestCase):
    def test_get_exp_center_by_city(self):
        mumbai = get_exp_center("Mumbai")
        self.assertEqual(len(mumbai["centers"]), 1)
        self.assertEqual(mumbai["centers"][0]["center_id"], "LAMBO_MUM_BKC")
        self.assertIn("Maker Maxity", mumbai["centers"][0]["address"])

        delhi = get_exp_center("Delhi")
        self.assertEqual(len(delhi["centers"]), 1)
        self.assertEqual(delhi["centers"][0]["center_id"], "LAMBO_DEL_AERO")
        self.assertIn("Aerocity", delhi["centers"][0]["address"])

        blr = get_exp_center("Bengaluru")
        self.assertEqual(len(blr["centers"]), 1)
        self.assertEqual(blr["centers"][0]["center_id"], "LAMBO_BLR_LAV")
        self.assertIn("Lavelle Road", blr["centers"][0]["address"])

    def test_get_exp_center_by_pincode(self):
        res = get_exp_center("400051")
        self.assertEqual(res["centers"][0]["center_id"], "LAMBO_MUM_BKC")

        res_del = get_exp_center("110037")
        self.assertEqual(res_del["centers"][0]["center_id"], "LAMBO_DEL_AERO")

    def test_get_exp_center_fallback_returns_all(self):
        res = get_exp_center("Kolkata")
        self.assertEqual(len(res["centers"]), 3)
        self.assertTrue(res["is_fallback"])

    def test_create_appointment_booking_success(self):
        booking = create_appointment_booking(
            center_id="LAMBO_MUM_BKC",
            date="Tomorrow",
            time="3:00 PM",
            customer_phone="+919876543210",
            vehicle_variant="Lamborghini Aventador",
        )
        self.assertEqual(booking["status"], "confirmed")
        self.assertTrue(booking["booking_id"].startswith("LAMBO-"))
        self.assertEqual(booking["center_name"], "Lamborghini Mumbai Atelier (BKC)")
        self.assertEqual(booking["vehicle_variant"], "Lamborghini Aventador")
        self.assertIn("confirmed", booking["confirmation_message"].lower())

    def test_create_appointment_booking_by_pincode(self):
        booking = create_appointment_booking(
            pincode="110037",
            date="Saturday",
            time="4:00 PM",
            vehicle_variant="Revuelto",
        )
        self.assertEqual(booking["status"], "confirmed")
        self.assertEqual(booking["center_id"], "LAMBO_DEL_AERO")
        self.assertIn("Aerocity", booking["address"])

    def test_model_phase_and_booking_tools_registered(self):
        schema_names = [s.name for s in SUPERCAR_TOOL_SCHEMAS]
        self.assertEqual(schema_names, ["switch_phase", "create_appointment_booking"])


if __name__ == "__main__":
    unittest.main()
