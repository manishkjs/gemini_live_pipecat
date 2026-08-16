"""Asynchronous Post-Session Memory Downcar Extraction Service.

Extracts structured financial facts and episodic conversation summaries from
multi-turn voice session transcripts using Gemini 2.5 Flash Lite with JSON schema
enforcement and deterministic offline fallback.

Key Responsibilities:
1. Role-tagged transcript formatting (`format_transcript_for_downcar`).
2. Structured JSON response parsing with markdown code-fence stripping (`parse_downcar_response`).
3. 8 Canonical Fact parsing (`amount`, `tenure_months`, `risk_preference`, `timeline`,
   `goal`, `occupation`, `city`, `experience`).
4. MD5 content hash calculation from formatted transcript for idempotent deduplication.
5. Updating `FactStore` and persisting episodic memories to `MemoryBank`.
6. Safe execution resilience against API errors, quota exhaustion, and malformed outputs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

try:
    from memory_bank import CANONICAL_FACT_KEYS, MemoryBank, normalize_lexical_user_id
except ImportError:
    try:
        from .memory_bank import CANONICAL_FACT_KEYS, MemoryBank, normalize_lexical_user_id
    except Exception:
        CANONICAL_FACT_KEYS = {
            "amount",
            "tenure_months",
            "risk_preference",
            "timeline",
            "goal",
            "occupation",
            "city",
            "experience",
        }
        MemoryBank = None
        normalize_lexical_user_id = lambda name: f"user_{str(name).lower().replace(' ', '_')}" if name else "user_anonymous"


# ═══════════════════════════════════════════════════════════════════════
# 1. TRANSCRIPT FORMATTING & LLM RESPONSE PARSING
# ═══════════════════════════════════════════════════════════════════════

def format_transcript_for_downcar(transcript_history: List[Dict[str, str]]) -> str:
    """Formats multi-turn transcript into role-tagged plain text.

    Args:
        transcript_history: List of utterance dictionaries containing 'role' and 'text' / 'content'.

    Returns:
        New-line separated string formatted as "Role: Utterance text".
    """
    lines: List[str] = []
    if not transcript_history or not isinstance(transcript_history, list):
        return ""

    for turn in transcript_history:
        if not isinstance(turn, dict):
            continue
        role_raw = turn.get("role") or turn.get("participant") or "speaker"
        role = str(role_raw).strip().capitalize()
        text = str(turn.get("text") or turn.get("content") or "").strip()
        if text:
            lines.append(f"{role}: {text}")

    return "\n".join(lines)


def parse_downcar_response(raw_text: str) -> Dict[str, Any]:
    """Parses LLM extraction response, stripping markdown code fences if present.

    Handles ```json ... ``` fences, raw JSON objects, and malformed responses.

    Args:
        raw_text: Raw string response from Gemini 2.5 Flash Lite.

    Returns:
        Dictionary containing extracted 'facts' dict and 'summary' string.
    """
    if not raw_text or not isinstance(raw_text, str):
        return {"facts": {}, "summary": ""}

    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # Normalize facts subdict
            facts = data.get("facts")
            if not isinstance(facts, dict):
                # If facts were placed at root level alongside summary
                facts = {k: v for k, v in data.items() if k in CANONICAL_FACT_KEYS}
            summary = str(data.get("summary") or data.get("episodic_summary") or "").strip()
            return {
                "facts": facts or {},
                "summary": summary or text,
            }
        return {"facts": {}, "summary": text}
    except Exception:
        # Fallback for plain text response without valid JSON syntax
        return {
            "facts": {},
            "summary": raw_text.strip(),
            "parse_error": True,
        }


# ═══════════════════════════════════════════════════════════════════════
# 2. OFFLINE HEURISTIC EXTRACTION ENGINE (HERMETIC FALLBACK)
# ═══════════════════════════════════════════════════════════════════════

def extract_facts_and_summary_offline(
    transcript_text: str,
    user_id: str,
    session_id: str,
) -> Tuple[Dict[str, Any], str]:
    """Heuristic extraction for hermetic offline execution and fallback.

    Extracts canonical financial parameters and generates an episodic summary.
    """
    extracted_facts: Dict[str, Any] = {}
    lower_text = transcript_text.lower()

    # 1. Amount Extraction (Lakhs, Crores, numbers)
    # Check lakh patterns first
    lakh_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|lac|lacs)\b", lower_text)
    if lakh_match:
        extracted_facts["amount"] = float(lakh_match.group(1)) * 100000.0
    elif "24,00,000" in lower_text or "2400000" in lower_text:
        extracted_facts["amount"] = 2400000.0
    elif "2,00,000" in lower_text or "200000" in lower_text:
        extracted_facts["amount"] = 200000.0
    elif "5,00,000" in lower_text or "500000" in lower_text:
        extracted_facts["amount"] = 500000.0
    elif "1,00,000" in lower_text or "100000" in lower_text:
        extracted_facts["amount"] = 100000.0
    elif "50,000" in lower_text or "50000" in lower_text:
        extracted_facts["amount"] = 50000.0
    elif "25,000" in lower_text or "25000" in lower_text:
        extracted_facts["amount"] = 25000.0
    else:
        num_match = re.search(r"(?:₹|rs\.?|inr)?\s*(\d{4,8})\b", lower_text)
        if num_match:
            try:
                amt = float(num_match.group(1))
                if 250.0 <= amt <= 5000000.0:
                    extracted_facts["amount"] = amt
            except ValueError:
                pass

    # 2. Tenure Extraction (ignoring product codes like MTL 14M, STL 5M, STL 7M)
    cleaned_tenure_text = re.sub(r"\b(?:stl|mtl)\s*\d+m\b", " ", lower_text)
    tenure_match = re.search(r"\b(\d{1,2})\s*(?:month|months|mahine|mahina)\b", cleaned_tenure_text)
    if tenure_match:
        try:
            extracted_facts["tenure_months"] = int(tenure_match.group(1))
        except ValueError:
            pass
    elif "1 saal" in cleaned_tenure_text or "1 year" in cleaned_tenure_text or "12 month" in cleaned_tenure_text:
        extracted_facts["tenure_months"] = 12
    elif "6 month" in cleaned_tenure_text or "6 mahine" in cleaned_tenure_text:
        extracted_facts["tenure_months"] = 6
    elif "5 month" in cleaned_tenure_text or "5 mahine" in cleaned_tenure_text:
        extracted_facts["tenure_months"] = 5
    elif "4 month" in cleaned_tenure_text or "4 mahine" in cleaned_tenure_text:
        extracted_facts["tenure_months"] = 4
    elif "3 month" in cleaned_tenure_text or "3 mahine" in cleaned_tenure_text:
        extracted_facts["tenure_months"] = 3
    elif "2 month" in cleaned_tenure_text or "2 mahine" in cleaned_tenure_text:
        extracted_facts["tenure_months"] = 2

    # 3. Risk Preference
    if "low risk" in lower_text or "conservative" in lower_text or "safe" in lower_text or "surakshit" in lower_text:
        extracted_facts["risk_preference"] = "low"
    elif "high risk" in lower_text or "aggressive" in lower_text:
        extracted_facts["risk_preference"] = "high"
    elif "medium risk" in lower_text or "moderate" in lower_text:
        extracted_facts["risk_preference"] = "moderate"

    # 4. Financial Goal
    if "wealth growth" in lower_text or "wealth" in lower_text or "growth" in lower_text or "capital appreciation" in lower_text:
        extracted_facts["goal"] = "wealth growth"
    elif "daily" in lower_text or "edi" in lower_text or "daily liquidity" in lower_text:
        extracted_facts["goal"] = "daily liquidity"
    elif "monthly income" in lower_text or "monthly emi" in lower_text or "regular income" in lower_text or "income" in lower_text:
        extracted_facts["goal"] = "monthly income"
    elif "retirement" in lower_text:
        extracted_facts["goal"] = "retirement"
    elif "child education" in lower_text or "education" in lower_text:
        extracted_facts["goal"] = "child education"

    # 5. City
    cities = ["Bengaluru", "Bangalore", "Mumbai", "Delhi", "Pune", "Hyderabad", "Chennai", "Kolkata", "Ahmedabad", "Jaipur"]
    for c in cities:
        if c.lower() in lower_text:
            extracted_facts["city"] = c
            break

    # 6. Occupation
    occupations = [
        ("software engineer", "software engineer"),
        ("engineer", "software engineer"),
        ("doctor", "doctor"),
        ("chartered accountant", "chartered accountant"),
        ("ca", "chartered accountant"),
        ("business", "business owner"),
        ("salaried", "salaried professional"),
        ("consultant", "consultant"),
    ]
    for pattern, occ in occupations:
        if re.search(r"\b" + re.escape(pattern) + r"\b", lower_text):
            extracted_facts["occupation"] = occ
            break

    # 7. Experience
    if "first time" in lower_text or "pehli baar" in lower_text or "beginner" in lower_text or "new to p2p" in lower_text:
        extracted_facts["experience"] = "beginner"
    elif "experienced" in lower_text or "investing for years" in lower_text:
        extracted_facts["experience"] = "experienced"

    # Episodic Summary Construction
    parts = []
    if "amount" in extracted_facts:
        amt = extracted_facts["amount"]
        amt_raw = int(amt) if float(amt).is_integer() else amt
        parts.append(f"investment {amt_raw} (₹{amt:,.0f})")
    if "tenure_months" in extracted_facts:
        parts.append(f"for {extracted_facts['tenure_months']} months")
    if "goal" in extracted_facts:
        parts.append(f"with goal '{extracted_facts['goal']}'")
    if "risk_preference" in extracted_facts:
        parts.append(f"with {extracted_facts['risk_preference']} risk")

    param_summary = " ".join(parts) if parts else "investment options"
    name_display = user_id.replace("user_", "").replace("_", " ").title() if str(user_id).startswith("user_") else str(user_id)
    summary = f"Customer {name_display} in session {session_id} explored {param_summary}."
    if "STL 7M" in transcript_text or "stl 7m" in lower_text:
        summary += " Discussed STL 7M plan."
    elif "MTL 14M" in transcript_text or "mtl 14m" in lower_text:
        summary += " Discussed MTL 14M plan."
    elif "STL 5M" in transcript_text or "stl 5m" in lower_text:
        summary += " Discussed STL 5M plan."

    return extracted_facts, summary


# ═══════════════════════════════════════════════════════════════════════
# 3. ASYNCHRONOUS POST-SESSION DOWNCAR WORKER
# ═══════════════════════════════════════════════════════════════════════

async def run_post_session_downcar(
    session_id: str,
    user_id: str,
    transcript_history: List[Dict[str, str]],
    memory_bank: Any,
    genai_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Asynchronous background downcar extraction worker.

    Parses the session transcript, extracts structured canonical facts and episodic
    summaries, computes deterministic MD5 content hash for idempotency, updates the
    user's FactStore, and persists the memory into the Agent Memory Bank.

    Args:
        session_id: Unique voice session identifier.
        user_id: Customer spoken name or normalized user key.
        transcript_history: Multi-turn transcript turn list.
        memory_bank: MemoryBank instance.
        genai_client: Optional Google GenAI Client (mocked or live).

    Returns:
        Result dictionary containing status, facts, summary, and content_hash.
    """
    # 1. Validate transcript history presence
    if not transcript_history or not isinstance(transcript_history, list):
        logger.info(f"[Downcar] Session {session_id}: Skipped due to empty transcript.")
        return {
            "status": "skipped",
            "session_id": session_id,
            "user_id": user_id,
            "reason": "empty_transcript",
        }

    try:
        # 2. Normalize Lexical User ID
        uid = normalize_lexical_user_id(user_id)

        # 3. Format Transcript to Plain Text
        transcript_text = format_transcript_for_downcar(transcript_history)
        if not transcript_text.strip():
            logger.info(f"[Downcar] Session {session_id}: Skipped due to empty transcript text.")
            return {
                "status": "skipped",
                "session_id": session_id,
                "user_id": uid,
                "reason": "empty_transcript_text",
            }

        # 4. Deterministic MD5 Content Hash Calculation
        content_hash = hashlib.md5(transcript_text.encode("utf-8")).hexdigest()

        # 5. Idempotency Check
        if hasattr(memory_bank, "_hash_index") and content_hash in memory_bank._hash_index.get(uid, {}):
            logger.info(f"[Downcar] Session {session_id}: Duplicate transcript detected (hash: {content_hash}). Skipping duplicate write.")
            return {
                "status": "duplicate",
                "session_id": session_id,
                "user_id": uid,
                "content_hash": content_hash,
                "message": "Transcript already processed and stored.",
            }

        extracted_facts: Dict[str, Any] = {}
        summary: str = ""

        # 6. Structured Extraction Execution
        downcar_model = os.getenv("MEMORY_DOWNCAR_MODEL", "gemini-3.5-flash-lite")
        downcar_location = os.getenv("MEMORY_DOWNCAR_LOCATION", "global")
        project = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "deep-clock-339817"

        if genai_client is not None:
            extraction_prompt = (
                "You are an expert financial memory extractor for Cymbal Lending.\n"
                "Analyze the following conversation transcript and extract:\n"
                "1. Structured facts (only include canonical keys: amount, tenure_months, risk_preference, timeline, goal, occupation, city, experience).\n"
                "2. A concise 2-sentence episodic summary of the customer's intent, discussion, and KYC status.\n\n"
                "Return ONLY a valid JSON object with the following schema:\n"
                "{\n"
                '  "facts": {"amount": float, "tenure_months": int, "risk_preference": string, ...},\n'
                '  "summary": string\n'
                "}\n\n"
                f"Transcript:\n{transcript_text}"
            )
            response = await genai_client.models.generate_content(
                model=downcar_model,
                contents=[
                    {"role": "user", "parts": [{"text": extraction_prompt}]}
                ],
            )
            raw_text = response.text if hasattr(response, "text") else str(response)
            parsed = parse_downcar_response(raw_text)
            extracted_facts = parsed.get("facts", {}) or {}
            summary = parsed.get("summary", "") or ""
        else:
            # Initialize live Vertex AI Client with ADC at global location
            live_client = None
            if not os.getenv("HERMETIC_TEST_MODE"):
                try:
                    from google.genai import Client
                    live_client = Client(project=project, location=downcar_location, vertexai=True)
                except Exception as client_err:
                    logger.debug(f"[Downcar] GenAI Client init notice: {client_err}")

            if live_client is not None:
                try:
                    extraction_prompt = (
                        "Extract structured financial facts (amount, tenure_months, risk_preference, timeline, goal, occupation, city, experience) "
                        "and episodic summary from this transcript as JSON:\n\n"
                        f"{transcript_text}"
                    )
                    response = await live_client.aio.models.generate_content(
                        model=downcar_model,
                        contents=extraction_prompt,
                        config={"response_mime_type": "application/json"},
                    )
                    raw_text = response.text if hasattr(response, "text") else str(response)
                    parsed = parse_downcar_response(raw_text)
                    extracted_facts = parsed.get("facts", {}) or {}
                    summary = parsed.get("summary", "") or ""
                except Exception as live_err:
                    logger.warning(f"[Downcar] Live API call fallback to heuristic: {live_err}")
                    extracted_facts, summary = extract_facts_and_summary_offline(transcript_text, uid, session_id)
            else:
                # Heuristic offline extraction
                extracted_facts, summary = extract_facts_and_summary_offline(transcript_text, uid, session_id)

        # 7. Filter Facts to Canonical Keys & Normalize Types
        valid_facts: Dict[str, Any] = {}
        for k, v in extracted_facts.items():
            if k in CANONICAL_FACT_KEYS and v is not None:
                if k == "amount":
                    try:
                        valid_facts[k] = float(v)
                    except (ValueError, TypeError):
                        pass
                elif k == "tenure_months":
                    try:
                        valid_facts[k] = int(v)
                    except (ValueError, TypeError):
                        pass
                else:
                    valid_facts[k] = v

        # 8. Persist Facts to FactStore
        if valid_facts and hasattr(memory_bank, "get_fact_store"):
            fact_store = memory_bank.get_fact_store(uid)
            turn_idx = len(transcript_history)
            for k, v in valid_facts.items():
                try:
                    fact_store.set_fact(k, v, turn_id=turn_idx, is_hypothetical=False)
                except ValueError as err:
                    logger.debug(f"[Downcar] FactStore ignored key '{k}': {err}")

        # 9. Persist Episodic Summary into MemoryBank
        memory_added = False
        if summary and hasattr(memory_bank, "add_memory"):
            memory_added = memory_bank.add_memory(
                user_id=uid,
                content=summary,
                metadata={
                    "session_id": session_id,
                    "downcar_processed": True,
                    "facts": valid_facts,
                },
                content_hash=content_hash,
            )

        logger.info(
            f"[Downcar] Successfully processed session {session_id} for {uid}: "
            f"{len(valid_facts)} facts extracted, memory_added={memory_added}"
        )

        return {
            "status": "success",
            "session_id": session_id,
            "user_id": uid,
            "facts": valid_facts,
            "summary": summary,
            "content_hash": content_hash,
            "memory_added": memory_added,
        }

    except Exception as e:
        logger.error(f"[Downcar] Error in run_post_session_downcar for session {session_id}: {e}")
        return {
            "status": "error",
            "session_id": session_id,
            "user_id": user_id,
            "error": str(e),
        }


__all__ = [
    "format_transcript_for_downcar",
    "parse_downcar_response",
    "extract_facts_and_summary_offline",
    "run_post_session_downcar",
]
