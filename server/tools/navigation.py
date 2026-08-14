from __future__ import annotations
from typing import Any, Dict, Optional


def get_onboarding_guide(topic: Optional[str] = "all") -> Dict[str, Any]:
    """Unified onboarding guide for KYC (PAN/Aadhaar/Bank) or App deposit/navigation flows."""
    t = (topic or "all").lower().strip()
    if any(k in t for k in ["pan", "aadhaar", "aadhar", "bank", "penny", "kyc"]):
        return get_kyc_guidance(step_or_doc=t)
    return get_app_screen_flow(target_flow=t)



def get_kyc_guidance(step_or_doc: Optional[str] = "all") -> Dict[str, Any]:
    """Provide step-by-step guidance for KYC verification on Cymbal Lending app."""
    query = (step_or_doc or "all").lower().strip()
    
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
    
    if "aadhaar" in query or "aadhar" in query or "address" in query:
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
        "requirements": "Original PAN Card, Aadhaar linked to mobile, Active Bank Account.",
    }


def get_app_screen_flow(target_flow: Optional[str] = "general") -> Dict[str, Any]:
    """Provide screen guidance for lending, deposits, and auto-invest."""
    flow = (target_flow or "general").lower().strip()

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

    if "filter" in flow or "loan filter" in flow or "borrower filter" in flow:
        return {
            "flow_name": "App Loan Filter Options",
            "available_filters": [
                "1. Loan Tenure (2, 3, 4, 5, 6, 12 months)",
                "2. Repayment Type (Monthly EMI vs Daily EDI)",
                "3. Risk Category (AAA Low Risk, AA Medium Risk, A High Return, B, C)",
                "4. Borrower Type (Salaried, Self-Employed, Business Owner)",
                "5. Borrower Monthly Income Bracket (e.g. ₹25,000+, ₹50,000+, ₹1,00,000+)",
                "6. Total Loan Amount Requested",
                "7. Remaining Amount to be funded",
                "8. Borrower Age Group (e.g. 21-35, 36-50, 50+)"
            ],
            "instructions_hinglish": (
                "Cymbal App mein loan filter karne ke liye 8 exact options available hain: "
                "1. Loan Tenure (2 se 12 mahine), "
                "2. Repayment Type (Monthly EMI ya Daily EDI), "
                "3. Risk Category (AAA se C rating), "
                "4. Borrower Type (Salaried ya Self-Employed), "
                "5. Monthly Income, "
                "6. Loan Amount, "
                "7. Remaining Amount (jo abhi fund hona baki hai), aur "
                "8. Borrower Age. "
                "Aap in filters ko combine karke specific borrowers choose kar sakte hain."
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


def get_consultative_guidance(phase_or_topic: Optional[str] = "overview") -> Dict[str, Any]:
    """Retrieve on-demand consultative sales talk-tracks, phase directives, or objection scripts."""
    topic = (phase_or_topic or "overview").lower().strip()

    if "fd" in topic or "bank" in topic:
        return {
            "topic": "Bank FD Comparison",
            "key_points_hinglish": (
                "Bank FDs mein sirf 6.5% se 7.5% return milta hai jo post-tax inflation ko barely beat karta hai. "
                "Cymbal Lending P2P par 12% se 24% returns milte hain monthly EMI ya daily payouts (EDI) ke saath, "
                "jo regular cash flow aur 2x-3x higher wealth create karte hain."
            ),
        }
    if "npa" in topic or "risk" in topic or "default" in topic:
        return {
            "topic": "Risk & Default Mitigation",
            "key_points_hinglish": (
                "Platform par risk control karne ke liye ₹50,000 ka investment 100+ vetted borrowers mein automatically diversify hota hai. "
                "Quoted returns (12%-24% XIRR) historical NPA provisions deduct karne ke baad net bataye jaate hain."
            ),
        }
    if "rbi" in topic or "trust" in topic or "legal" in topic or "escrow" in topic:
        return {
            "topic": "Platform Legitimacy & RBI Trust",
            "key_points_hinglish": (
                "Cymbal Lending ek RBI-registered NBFC-P2P platform hai. "
                "Lender aur borrower ka saara paisa independent RBI-regulated ICICI/IDBI Trustee Escrow account ke through operate hota hai."
            ),
        }
    if "liquidity" in topic or "withdraw" in topic:
        return {
            "topic": "Liquidity & Repayment Mechanics",
            "key_points_hinglish": (
                "Plans mein monthly EMIs ya daily EDI credits ke through continuously principal + interest return hota rehta hai, "
                "jisse aapko maturity tak wait kiye bina regular cash liquidity milti hai."
            ),
        }
    return {
        "topic": "Consultative Sales Journey",
        "phases": "Phases 1-9: Time Check -> Discovery -> Education -> RBI Trust -> Diversification -> Readiness -> Product Recommendation -> KYC Navigation -> Commitment.",
        "rule": "Always respect customer time and use deterministic tools for exact numbers."
    }

