"""App navigation and KYC guidance for Cymbal Lending mobile/web application."""

from __future__ import annotations
from typing import Any, Dict, Optional


def get_kyc_guidance(step_or_doc: Optional[str] = "all") -> Dict[str, Any]:
    """Provide step-by-step guidance for KYC verification on Cymbal Lending app."""
    query = (step_or_doc or "all").lower()
    
    if "pan" in query:
        return {
            "step": "PAN Verification",
            "instructions_hinglish": (
                "Cymbal App open karein -> Profile icon pe click karein -> KYC Verification select karein -> "
                "Apna 10-digit PAN number enter karein aur PAN card ki clear photo upload karein. "
                "Yeh instant verify ho jata hai."
            ),
            "requirements": "Original PAN Card photo, good lighting.",
        }
    
    if "aadhaar" in query or "address" in query:
        return {
            "step": "Aadhaar / Address Verification",
            "instructions_hinglish": (
                "Aadhaar verification ke liye -> Digilocker option select karein -> "
                "Apna 12-digit Aadhaar number daalein aur mobile par aane wala OTP enter karein. "
                "Digilocker se verification securely aur bina document upload kiye complete ho jayegi."
            ),
            "requirements": "Mobile number must be linked with Aadhaar for OTP.",
        }

    if "bank" in query or "account" in query or "penny" in query:
        return {
            "step": "Bank Account Linking",
            "instructions_hinglish": (
                "Bank linking ke liye -> Add Bank Account pe tap karein -> Apna Bank Account Number aur IFSC Code enter karein. "
                "Platform aapke account mein ₹1 transfer karke (Penny drop) naam match karega. "
                "Ensure karein ki bank account aapke hi naam par ho."
            ),
            "requirements": "Bank account name must match PAN card name exactly.",
        }

    return {
        "step": "Complete KYC 3-Step Overview",
        "instructions_hinglish": (
            "Cymbal Lending par KYC complete karne ke 3 simple steps hain: "
            "1. PAN card number enter karke photo upload karein. "
            "2. Digilocker ke through Aadhaar OTP verify karein. "
            "3. Apna bank account number aur IFSC code add karein penny-drop verification ke liye. "
            "Yeh pura process 2 minute mein ho jata hai."
        ),
    }


def get_app_screen_flow(target_flow: Optional[str] = "general") -> Dict[str, Any]:
    """Provide screen guidance for lending, deposits, and auto-invest."""
    flow = (target_flow or "general").lower()

    if "deposit" in flow or "fund" in flow or "add money" in flow or "pay" in flow:
        return {
            "flow_name": "Adding Funds to Cymbal Escrow Wallet",
            "instructions_hinglish": (
                "Funds add karne ke liye: App home screen par 'Add Funds' button pe tap karein -> "
                "Amount enter karein (minimum ₹250 manual ke liye ya ₹25,000 lumpsum ke liye) -> "
                "Payment mode select karein: UPI ya NetBanking -> "
                "Payment complete hone par funds aapke RBI-regulated Escrow account mein instantly reflect ho jayenge."
            ),
        }

    if "lumpsum" in flow or "stl" in flow or "mtl" in flow:
        return {
            "flow_name": "Lumpsum Lending (STL / MTL)",
            "instructions_hinglish": (
                "Lumpsum invest karne ke liye: Home screen par 'Invest' tab pe click karein -> "
                "'Lumpsum Plans' select karein -> STL 5M (3-5 months), STL 7M (4-6 months), ya MTL 14M (12 months) select karein -> "
                "Amount daalein aur 'Confirm & Disburse' karein. Platform automatically aapka paisa 100+ verified borrowers mein diversify kar dega."
            ),
        }

    if "manual" in flow:
        return {
            "flow_name": "Manual Lending Selection",
            "instructions_hinglish": (
                "Manual lending ke liye: 'Invest' tab par jaakar 'Manual Lending' select karein -> "
                "Borrower risk categories (A, AA, AAA) filter karein -> "
                "Per borrower limit (₹250 se ₹4,000) set karein aur 'Lend Now' pe click karein."
            ),
        }

    return {
        "flow_name": "General App Navigation",
        "instructions_hinglish": (
            "Cymbal app mein 3 main sections hain: "
            "1. Dashboard: Jahan aapka total portfolio, monthly returns aur daily interest dikhta hai. "
            "2. Invest: Jahan aap STL, MTL ya Manual plans select kar sakte hain. "
            "3. Portfolio / Statement: Jahan se aap detailed borrower breakdown aur tax reports download kar sakte hain."
        ),
    }
