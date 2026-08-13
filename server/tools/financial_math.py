"""Deterministic financial calculation engine for Cymbal Lending P2P.

Pure Python arithmetic — zero LLM guesswork.
Handles:
  1. STL (Short Term Lumpsum) 5M & 7M calculations
  2. MTL (Medium Term Lumpsum) 14M Monthly & Daily EDI calculations
  3. Manual Lending Standard (18% XIRR for <=6m, 24% XIRR for 12m)
  4. Manual Lending Custom Portfolio (Rule 4 Steps A-G: NPA loss, fee deduction 1-6%, net profit, annualized XIRR)
  5. Product validation & eligibility checking
  6. SIP compounding calculations
"""

from __future__ import annotations
from typing import Any, Dict, Optional


def calculate_stl_returns(amount: float, tenure_months: Optional[int] = None) -> Dict[str, Any]:
    """Calculate returns for Short Term Lumpsum (STL) products.
    
    STL 5M: 3, 4, 5 months (default/average: 4 months) @ 12%-15% p.a. XIRR
    STL 7M: 4, 5, 6 months (default/average: 5 months) @ 15%-18% p.a. XIRR
    Repayment: Monthly EMI
    Min Amount: ₹25,000 | Max Amount: ₹25,00,000
    """
    if amount < 25000:
        return {
            "error": "Minimum investment amount for Lumpsum (STL) is ₹25,000.",
            "min_amount": 25000,
        }
    if amount > 2500000:
        return {
            "error": "Maximum investment amount for STL is ₹25,00,000.",
            "max_amount": 2500000,
        }

    # If tenure not specified, default to STL 7M average (5 months)
    if tenure_months is None:
        product_code = "STL 7M"
        tenure = 5
        xirr_rate = 18.0  # Upper bound of 15%-18%
    elif tenure_months in (3, 4, 5):
        product_code = "STL 5M"
        tenure = tenure_months
        xirr_rate = 15.0  # Upper bound of 12%-15%
    elif tenure_months == 6:
        product_code = "STL 7M"
        tenure = 6
        xirr_rate = 18.0  # Upper bound of 15%-18%
    else:
        return {
            "error": f"Invalid tenure {tenure_months} months for STL. Available tenures: 3, 4, 5, 6 months.",
            "available_tenures": [3, 4, 5, 6],
        }

    profit = amount * (xirr_rate / 100.0) * (tenure / 12.0)
    final_amount = amount + profit
    monthly_payout = final_amount / tenure

    return {
        "product_name": product_code,
        "principal": amount,
        "tenure_months": tenure,
        "annualized_xirr_pct": xirr_rate,
        "profit_rupees": round(profit, 2),
        "final_maturity_amount": round(final_amount, 2),
        "monthly_emi_payout": round(monthly_payout, 2),
        "repayment_type": "Monthly EMI (Principal + Interest)",
        "summary_hinglish": (
            f"{int(amount):,} rupaye {tenure} mahine ke liye {product_code} mein lagane par "
            f"lagbhag {xirr_rate}% annualized return ke hisaab se "
            f"{int(round(profit)):,} rupaye ka profit hoga, aur total maturity amount "
            f"{int(round(final_amount)):,} rupaye milega. Har mahine lagbhag "
            f"{int(round(monthly_payout)):,} rupaye EMI payout aayega."
        ),
    }


def calculate_mtl_returns(amount: float, repayment_type: Optional[str] = "monthly") -> Dict[str, Any]:
    """Calculate returns for Medium Term Lumpsum (MTL 14M) products.
    
    MTL 14M Monthly: 12 months @ 21%-24% p.a. XIRR (Monthly EMI, AA Medium Risk)
    MTL 14M Daily: 12 months @ 16%-18% p.a. XIRR (Daily EDI, AAA Low Risk)
    Min Amount: ₹1,00,000 | Max Amount: ₹10,00,000 (Monthly) / ₹25,00,000 (Daily)
    """
    if amount < 100000:
        return {
            "error": "Minimum investment amount for MTL 14M is ₹1,00,000.",
            "min_amount": 100000,
        }

    tenure = 12
    rep_str = (repayment_type or "monthly").lower()
    is_daily = "daily" in rep_str or "edi" in rep_str

    if is_daily:
        product_code = "MTL 14M Daily (EDI)"
        xirr_rate = 18.0  # 16%-18% upper bound
        risk_tier = "AAA (Low Risk)"
        rep_desc = "Daily EDI (Principal + Interest credited daily)"
        if amount > 2500000:
            return {"error": "Maximum investment for MTL Daily is ₹25,00,000."}
    else:
        product_code = "MTL 14M Monthly (EMI)"
        xirr_rate = 24.0  # 21%-24% upper bound
        risk_tier = "AA (Medium Risk)"
        rep_desc = "Monthly EMI (Principal + Interest credited monthly)"
        if amount > 1000000:
            return {"error": "Maximum investment for MTL Monthly is ₹10,00,000."}

    profit = amount * (xirr_rate / 100.0) * (tenure / 12.0)
    final_amount = amount + profit
    payout_rate = final_amount / (365 if is_daily else 12)

    return {
        "product_name": product_code,
        "principal": amount,
        "tenure_months": tenure,
        "risk_category": risk_tier,
        "annualized_xirr_pct": xirr_rate,
        "profit_rupees": round(profit, 2),
        "final_maturity_amount": round(final_amount, 2),
        "payout_amount": round(payout_rate, 2),
        "repayment_type": rep_desc,
        "summary_hinglish": (
            f"{int(amount):,} rupaye 1 saal (12 mahine) ke liye {product_code} mein invest karne par "
            f"{xirr_rate}% annualized XIRR ke hisaab se lagbhag {int(round(profit)):,} rupaye profit banta hai. "
            f"Total maturity value {int(round(final_amount)):,} rupaye hogi. "
            f"{'Har din lagbhag ' + str(int(round(payout_rate))) + ' rupaye account mein aayenge' if is_daily else 'Har mahine lagbhag ' + str(int(round(payout_rate))) + ' rupaye EMI aayegi'}."
        ),
    }


def calculate_manual_lending(
    amount: float,
    tenure_months: int = 12,
    custom_borrower_rate_pct: Optional[float] = None,
    custom_npa_rate_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Calculate returns for Manual Lending.
    
    Standard Mode (No custom rate):
      - Tenure 2-6 months: 18% annualized XIRR (already NPA/fee adjusted)
      - Tenure 12 months: 24% annualized XIRR (already NPA/fee adjusted)
      
    Custom Portfolio Mode (Rule 4 Steps A-G):
      - Step A: Principal
      - Step B: NPA Loss = Principal * NPA%
      - Step C: Performing Principal = Principal - NPA Loss
      - Step D: Gross Interest = Performing Principal * Borrower Rate * (Tenure/12)
      - Step E: Platform Fee = Principal * Fee% (1% for 2-3m, 4% for 4-5m, 3% for 6m, 6% for 12m)
      - Step F: Net Profit = Gross Interest - Platform Fee - NPA Loss
      - Step G: Net ROI = (Net Profit / Principal) * (12 / Tenure) * 100
    """
    if amount < 250:
        return {"error": "Minimum manual lending amount is ₹250."}
    if amount > 5000000:
        return {"error": "Maximum platform lending limit is ₹50,00,000 (50 Lakhs)."}
    if tenure_months <= 0:
        return {"error": f"Invalid tenure {tenure_months} months. Tenure must be a positive integer (e.g. 2, 3, 4, 5, 6, or 12 months)."}
    if tenure_months == 9:
        return {"error": "9-month tenure is strictly not available on Cymbal Lending for new loans. Available tenures are 2, 3, 4, 5, 6, or 12 months."}
    if tenure_months not in (2, 3, 4, 5, 6, 12):
        return {"error": f"Invalid tenure {tenure_months} months for Manual Lending. Available tenures are 2, 3, 4, 5, 6, or 12 months."}

    # Fee lookup table by tenure
    fee_map = {2: 1.0, 3: 1.0, 4: 4.0, 5: 4.0, 6: 3.0, 12: 6.0}
    fee_pct = fee_map.get(tenure_months, 6.0)

    # If standard calculation (no custom borrower rate provided)
    if custom_borrower_rate_pct is None:
        xirr_rate = 24.0 if tenure_months >= 12 else 18.0
        profit = amount * (xirr_rate / 100.0) * (tenure_months / 12.0)
        final_amount = amount + profit
        return {
            "mode": "Standard Manual Lending",
            "principal": amount,
            "tenure_months": tenure_months,
            "annualized_xirr_pct": xirr_rate,
            "profit_rupees": round(profit, 2),
            "final_amount": round(final_amount, 2),
            "summary_hinglish": (
                f"Manual Lending mein {int(amount):,} rupaye {tenure_months} mahine ke liye "
                f"{xirr_rate}% annualized XIRR par lagane se lagbhag {int(round(profit)):,} rupaye profit hoga, "
                f"aur total {int(round(final_amount)):,} rupaye milenge. Yeh returns already NPA aur fees adjust karke hain."
            ),
        }

    # Custom Portfolio Breakdown (Rule 4 Steps A-G)
    borrower_rate = float(custom_borrower_rate_pct)
    if borrower_rate < 0:
        return {"error": "Borrower interest rate percentage cannot be negative."}

    npa_rate = float(custom_npa_rate_pct if custom_npa_rate_pct is not None else 3.5)
    if npa_rate < 0 or npa_rate > 100:
        return {"error": "NPA rate percentage must be between 0% and 100%."}

    step_a_principal = amount
    step_b_npa_loss = step_a_principal * (npa_rate / 100.0)
    step_c_performing = step_a_principal - step_b_npa_loss
    step_d_gross_interest = step_c_performing * (borrower_rate / 100.0) * (tenure_months / 12.0)
    step_e_platform_fee = step_a_principal * (fee_pct / 100.0)
    step_f_net_profit = step_d_gross_interest - step_e_platform_fee - step_b_npa_loss
    step_g_net_roi_pct = (step_f_net_profit / step_a_principal) * (12.0 / tenure_months) * 100.0
    final_amount = step_a_principal + step_f_net_profit

    return {
        "mode": "Custom Portfolio Step-by-Step Breakdown (Rule 4)",
        "step_a_principal": round(step_a_principal, 2),
        "step_b_npa_loss_rupees": round(step_b_npa_loss, 2),
        "npa_rate_pct": npa_rate,
        "step_c_performing_principal": round(step_c_performing, 2),
        "borrower_rate_pct": borrower_rate,
        "step_d_gross_interest": round(step_d_gross_interest, 2),
        "platform_fee_pct": fee_pct,
        "step_e_platform_fee_rupees": round(step_e_platform_fee, 2),
        "step_f_net_profit_rupees": round(step_f_net_profit, 2),
        "step_g_net_annualized_roi_pct": round(step_g_net_roi_pct, 2),
        "final_total_amount": round(final_amount, 2),
        "summary_hinglish": (
            f"Step-by-step breakdown {int(amount):,} rupaye ke liye ({tenure_months} mahine, {borrower_rate}% borrower rate):\n"
            f"1. NPA Loss ({npa_rate}%): lagbhag {int(round(step_b_npa_loss)):,} rupaye default reserve.\n"
            f"2. Performing Principal: {int(round(step_c_performing)):,} rupaye.\n"
            f"3. Gross Interest Earned: {int(round(step_d_gross_interest)):,} rupaye.\n"
            f"4. Platform Fee ({fee_pct}%): {int(round(step_e_platform_fee)):,} rupaye.\n"
            f"5. Net Profit: {int(round(step_f_net_profit)):,} rupaye.\n"
            f"6. Net Annualized ROI: {round(step_g_net_roi_pct, 1)}% p.a. Total final return: {int(round(final_amount)):,} rupaye."
        ),
    }


def calculate_sip_returns(monthly_amount: float, annual_rate: float, years: int) -> Dict[str, Any]:
    """Calculate Systematic Investment Plan (SIP) maturity value."""
    if monthly_amount <= 0:
        return {"error": "Monthly SIP amount must be greater than 0."}
    if years <= 0:
        return {"error": "SIP duration in years must be greater than 0."}
    if annual_rate < 0:
        return {"error": "Annual return rate percentage cannot be negative."}

    n = years * 12
    if annual_rate == 0:
        maturity = monthly_amount * n
    else:
        r = annual_rate / (12 * 100)
        maturity = monthly_amount * (((1 + r) ** n - 1) / r) * (1 + r)
    total_invested = monthly_amount * n
    wealth_gained = maturity - total_invested
    return {
        "monthly_investment": monthly_amount,
        "annual_interest_rate_pct": annual_rate,
        "duration_years": years,
        "total_invested_rupees": round(total_invested, 2),
        "wealth_gained_rupees": round(wealth_gained, 2),
        "maturity_value_rupees": round(maturity, 2),
        "summary_hinglish": (
            f"Har mahine {int(monthly_amount):,} rupaye {years} saal ke liye {annual_rate}% return par lagane se "
            f"total investment {int(round(total_invested)):,} rupaye hoga aur maturity value {int(round(maturity)):,} rupaye milegi "
            f"(profit: {int(round(wealth_gained)):,} rupaye)."
        ),
    }


def get_product_recommendation(
    amount: float,
    risk_appetite: Optional[str] = "medium",
    tenure_months: Optional[int] = None,
) -> Dict[str, Any]:
    """Validate investment parameters and recommend the best Cymbal Lending product."""
    risk = (risk_appetite or "medium").lower()
    
    if amount < 250:
        return {
            "is_valid": False,
            "error": "Minimum platform investment/lending amount is ₹250.",
        }
    if amount > 5000000:
        return {
            "is_valid": False,
            "error": "Maximum platform lending limit is ₹50,00,000 (50 Lakhs).",
        }
    
    if tenure_months == 9:
        return {
            "is_valid": False,
            "error": "9-month tenures are strictly not available on Cymbal Lending for new loans.",
            "suggestion": "We recommend 6-month STL 7M or 12-month MTL 14M instead.",
        }

    if amount < 25000:
        return {
            "is_valid": True,
            "recommended_product": "Manual Lending",
            "eligible_tenures": [2, 3, 4, 5, 6, 12],
            "expected_xirr": "18% - 24% p.a.",
            "note": "For investments below ₹25,000, Manual Lending is available starting from ₹250.",
        }

    if tenure_months == 12 or risk in ("low", "conservative"):
        if "low" in risk:
            return {
                "is_valid": True,
                "recommended_product": "MTL 14M Daily (EDI)",
                "risk_tier": "AAA (Low Risk)",
                "tenure_months": 12,
                "expected_xirr": "16% - 18% p.a.",
                "payout": "Daily principal + interest credit",
            }
        return {
            "is_valid": True,
            "recommended_product": "MTL 14M Monthly (EMI)",
            "risk_tier": "AA (Medium Risk)",
            "tenure_months": 12,
            "expected_xirr": "21% - 24% p.a.",
            "payout": "Monthly EMI payout",
        }

    # Short term (3 - 6 months)
    if tenure_months in (3, 4, 5):
        return {
            "is_valid": True,
            "recommended_product": "STL 5M",
            "risk_tier": "A (High / Moderate Risk)",
            "tenure_months": tenure_months,
            "expected_xirr": "12% - 15% p.a.",
            "payout": "Monthly EMI payout",
        }

    # Default recommendation: STL 7M
    return {
        "is_valid": True,
        "recommended_product": "STL 7M",
        "risk_tier": "A (High / Moderate Risk)",
        "tenure_months": tenure_months or 6,
        "expected_xirr": "15% - 18% p.a.",
        "payout": "Monthly EMI payout",
    }
