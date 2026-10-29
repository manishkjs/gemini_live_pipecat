"""Public USD API estimates, independently metered for each Cascade stage.

Prices researched 2026-09-13. No transcript token guesses, monthly free-tier
allocation, account discounts, or inferred Live Transcribe counter semantics.
The ledger replaces request snapshots; it never sums streaming revisions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
import math

REVIEWED_AT = "2026-10-29"
SOURCES = {
    "vertex": "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing",
    "vertex_maas": "https://docs.cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing",
    "gemini": "https://ai.google.dev/gemini-api/docs/pricing",
    "speech": "https://cloud.google.com/speech-to-text/pricing",
    "tts": "https://cloud.google.com/text-to-speech/pricing",
}
MILLION = Decimal(1_000_000)


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 2**53 - 1 else None


def metadata_dict(value):
    """Retain numeric provider usage only; never text, credentials or audio."""
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    return dict(value) if isinstance(value, dict) else {}


def rate_card(stage, model, provider, region="global", at=None):
    """Exact allowlist; region/date are the actual request configuration."""
    at = at or datetime.now(timezone.utc).date().isoformat()
    card = {"model": model, "provider": provider, "region": region, "reviewed_at": REVIEWED_AT}
    if stage == "llm" and model == "gemma-4-26b-a4b-it-maas":
        if provider != "vertex" or region != "global":
            return None
        card.update(
            text_in="0.15",
            text_out="0.60",
            cached_text_in="0.015",
            source=SOURCES["vertex_maas"],
        )
    elif stage == "llm" and provider in ("vertex", "gemini"):
        clean_model = model.replace("-aistudio", "")
        prices = {
            "gemini-3.5-flash-lite": ("0.30", "0.30", "2.50", "0.03", "0.03"),
            "gemini-3.8-flash": (("0.75", "0.75", "3.75", "0.075", "0.075")
                                  if at <= "2026-12-31" else ("1.50", "1.50", "7.50", "0.15", "0.15")),
            "gemini-3.7-flash": (("0.75", "0.75", "3.75", "0.075", "0.075")
                                  if at <= "2026-12-31" else ("1.50", "1.50", "7.50", "0.15", "0.15")),
            "gemini-2.5-flash": ("0.30", "1.00", "2.50", "0.03", "0.10"),
            "gemini-2.5-flash-lite": ("0.10", "0.30", "0.40", "0.01", "0.03"),
        }
        if clean_model not in prices:
            return None
        values = prices[clean_model]
        if provider == "vertex" and clean_model.startswith("gemini-3") and region != "global":
            values = tuple(str(Decimal(v) * Decimal("1.1")) for v in values)
        card.update(dict(zip(("text_in", "audio_in", "text_out", "cached_text_in", "cached_audio_in"), values)))
        card["source"] = SOURCES[provider]
    elif stage == "stt" and model in ("gemini-3.5-transcribe-live", "gemini-3.5-transcribe-live-preview") and provider in ("vertex", "gemini"):
        card.update(audio_in="3.50", text_out="21.00", source=SOURCES[provider])
    elif stage == "stt" and provider == "cloud-speech-v2" and model in ("chirp_3", "chirp_2", "latest_long", "latest_short", "telephony"):
        # Standard recognition, first monthly tier. Invoice tiers are account-wide.
        card.update(audio_minute="0.016", source=SOURCES["speech"])
    elif stage == "tts" and model.replace("-aistudio", "") in ("gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts") and provider in ("gemini", "vertex"):
        clean_tts_model = model.replace("-aistudio", "")
        card.update(
            text_in="0.50",
            audio_out="9.00" if clean_tts_model == "gemini-3.8-flash-tts" else "6.00",
            source=SOURCES["gemini"],
        )
    elif stage == "tts" and provider == "vertex" and model in (
        "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-lite-preview-tts", "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts",
    ):
        higher_rate = model in ("gemini-3.1-flash-tts-preview", "gemini-2.5-pro-preview-tts")
        card.update(text_in="1.00" if higher_rate else "0.50",
                    audio_out="20.00" if higher_rate else "10.00", source=SOURCES["tts"])
    elif stage == "tts" and provider == "cloud-tts" and model in ("chirp3-hd", "chirp3-instant-custom-voice"):
        card.update(characters="60.00" if model == "chirp3-instant-custom-voice" else "30.00", source=SOURCES["tts"])
    else:
        return None
    return card


def modality_counts(details):
    result = {}
    for item in details or []:
        if not isinstance(item, dict) or count(item.get("token_count")) is None:
            return None
        name = str(item.get("modality", "")).lower().removeprefix("modality.")
        result[name] = result.get(name, 0) + item["token_count"]
    return result


# Transcribe Live returns no usage_metadata (probed 2026-09-24), so its cost is estimated:
# Google's published audio tokenization (25 tokens / second of streamed audio) and ~3
# transcript characters per output token (Devanagari/Latin mix). Shown as "~" in the UI.
TRANSCRIBE_AUDIO_TOKENS_PER_SEC = Decimal(25)
TRANSCRIBE_CHARS_PER_TOKEN = 3


def estimate_transcribe_live(usage, card):
    seconds, chars = usage.get("audio_seconds"), usage.get("transcript_chars", 0)
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
        return None, "Missing streamed audio duration", card
    if count(chars) is None:
        return None, "Invalid transcript length", card
    audio_tokens = math.ceil(Decimal(str(seconds)) * TRANSCRIBE_AUDIO_TOKENS_PER_SEC)
    text_tokens = math.ceil(chars / TRANSCRIBE_CHARS_PER_TOKEN)
    return (Decimal(audio_tokens) * Decimal(card["audio_in"]) + Decimal(text_tokens) * Decimal(card["text_out"])) / MILLION, None, card


def quote(record):
    """Return a price only when all required units for this request reconcile."""
    card = rate_card(record["stage"], record["model"], record["provider"], record.get("region", "global"), record.get("date"))
    if not card:
        return None, "No verified rate for this model/provider", None
    if record.get("estimated") and record["stage"] == "stt" and "audio_in" in card:
        return estimate_transcribe_live(record.get("usage", {}), card)
    if record.get("issue"):
        return None, record["issue"], card
    if not record.get("complete"):
        return None, "Awaiting final provider usage", card
    u = record.get("usage", {})
    if "characters" in card:
        chars = count(u.get("characters"))
        return ((Decimal(chars) * Decimal(card["characters"]) / MILLION, None, card) if chars is not None
                else (None, "Missing synthesized character count", card))
    if "audio_minute" in card:
        seconds = u.get("billed_seconds")
        if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not math.isfinite(seconds) or seconds < 0:
            return None, "Missing provider-billed audio duration", card
        return Decimal(str(seconds)) * Decimal(card["audio_minute"]) / Decimal(60), None, card
    p = count(u.get("prompt_token_count"))
    raw_out = u.get("candidates_token_count", u.get("response_token_count"))
    output = count(0 if (raw_out is None and record["stage"] == "llm") else raw_out)
    raw_thinking = u.get("thoughts_token_count")
    thinking = count(0 if raw_thinking is None else raw_thinking)
    raw_cache = u.get("cached_content_token_count")
    cache = count(0 if raw_cache is None else raw_cache)
    raw_tool_prompt = u.get("tool_use_prompt_token_count")
    tool_prompt = count(0 if raw_tool_prompt is None else raw_tool_prompt)
    total = count(u.get("total_token_count"))
    if None in (p, output, thinking, cache, tool_prompt):
        return None, "Missing or invalid token counters", card
    input_total = p + tool_prompt
    if cache > input_total:
        return None, "Missing or invalid token counters", card
    if total == input_total + output + thinking:
        output_to_charge = output + thinking
    elif total == input_total + output and output >= thinking:
        output_to_charge = output
    else:
        return None, "Provider token totals do not reconcile", card
    if u.get("traffic_type") not in (None, "ON_DEMAND", "TRAFFIC_TYPE_UNSPECIFIED"):
        return None, "Usage is not standard pay-as-you-go", card
    if record["stage"] == "stt" and not record.get("scope_verified"):
        return None, "Transcribe Live usage scope needs runtime verification", card
    if record["stage"] == "tts":
        if cache or thinking:
            return None, "Unexpected cached/thinking usage for TTS", card
        return (Decimal(input_total) * Decimal(card["text_in"]) + Decimal(output) * Decimal(card["audio_out"])) / MILLION, None, card
    if record["stage"] == "stt":
        if cache or thinking:
            return None, "Unexpected cached/thinking usage for STT", card
        return (Decimal(input_total) * Decimal(card["audio_in"]) + Decimal(output) * Decimal(card["text_out"])) / MILLION, None, card
    # LLM: output includes thinking; cached input (cached_content_token_count) is billed
    # at cached_text_in / cached_audio_in, and remaining uncached input at text_in / audio_in.
    details = modality_counts(u.get("prompt_tokens_details"))
    cached = modality_counts(u.get("cache_tokens_details"))
    if details is None or cached is None:
        return None, "Invalid modality counters", card
    if "audio_in" not in card:
        if record.get("input_mode") == "audio" or details.get("audio", 0) > 0 or cached.get("audio", 0) > 0:
            return None, "Model rate card does not list audio input rates", card
        value = Decimal(input_total - cache) * Decimal(card["text_in"]) + Decimal(cache) * Decimal(card["cached_text_in"])
        value += Decimal(output_to_charge) * Decimal(card["text_out"])
        return value / MILLION, None, card
    same_rate = (
        card["text_in"] == card["audio_in"]
        and card.get("cached_text_in") == card.get("cached_audio_in")
    )
    if record.get("input_mode") == "text" or same_rate:
        value = Decimal(input_total - cache) * Decimal(card["text_in"]) + Decimal(cache) * Decimal(card["cached_text_in"])
    else:
        if set(details) - {"text", "audio"} or sum(details.values()) != input_total:
            return None, "Missing audio/text or cache modality breakdown", card
        if cache > 0 and not cached:
            # Implicit prefix caching caches leading system/history text first before trailing audio.
            cached_text = min(cache, details.get("text", 0))
            cached = {"text": cached_text, "audio": cache - cached_text}
        if sum(cached.values()) != cache:
            return None, "Missing audio/text or cache modality breakdown", card
        value = Decimal(0)
        for kind in ("text", "audio"):
            tokens, cached_tokens = details.get(kind, 0), cached.get(kind, 0)
            if cached_tokens > tokens:
                return None, "Cached tokens exceed modality total", card
            value += Decimal(tokens - cached_tokens) * Decimal(card[kind + "_in"])
            value += Decimal(cached_tokens) * Decimal(card["cached_" + kind + "_in"])
    value += Decimal(output_to_charge) * Decimal(card["text_out"])
    return value / MILLION, None, card


def _llm_stage_usage_summary(records):
    prompt_tokens = 0
    cached_tokens = 0
    output_tokens = 0
    thoughts_tokens = 0
    for r in records:
        u = r.get("usage") or {}
        p = count(u.get("prompt_token_count"))
        if p is None:
            continue
        raw_tp = u.get("tool_use_prompt_token_count")
        tp = count(0 if raw_tp is None else raw_tp) or 0
        raw_c = u.get("cached_content_token_count")
        c = count(0 if raw_c is None else raw_c) or 0
        raw_out = u.get("candidates_token_count", u.get("response_token_count"))
        out = count(0 if raw_out is None else raw_out) or 0
        raw_th = u.get("thoughts_token_count")
        th = count(0 if raw_th is None else raw_th) or 0
        tot = count(u.get("total_token_count"))
        in_tot = p + tp
        billed_out = out + th if tot == in_tot + out + th else out
        prompt_tokens += in_tot
        cached_tokens += min(c, in_tot)
        output_tokens += billed_out
        thoughts_tokens += th
    uncached_tokens = max(0, prompt_tokens - cached_tokens)
    hit_rate = round(cached_tokens / prompt_tokens, 4) if prompt_tokens > 0 else 0.0
    return {
        "prompt_tokens": prompt_tokens,
        "cached_tokens": cached_tokens,
        "uncached_prompt_tokens": uncached_tokens,
        "output_tokens": output_tokens,
        "thoughts_tokens": thoughts_tokens,
        "cache_hit_rate": hit_rate,
    }


def _is_estimated_cache_split(record) -> bool:
    if record.get("stage") != "llm" or not record.get("complete") or record.get("input_mode") == "text":
        return False
    card = rate_card("llm", record.get("model"), record.get("provider"), record.get("region"), record.get("date"))
    if not card or "audio_in" not in card:
        return False
    if card["text_in"] == card["audio_in"] and card.get("cached_text_in") == card.get("cached_audio_in"):
        return False
    u = record.get("usage") or {}
    raw_c = u.get("cached_content_token_count")
    cache = count(0 if raw_c is None else raw_c) or 0
    if cache <= 0 or modality_counts(u.get("cache_tokens_details")):
        return False
    details = modality_counts(u.get("prompt_tokens_details")) or {}
    return details.get("text", 0) > 0 and details.get("audio", 0) > 0


class CascadeCostLedger:
    """One ledger per call; all updates replace a stable provider request id."""
    def __init__(self, session_id, *, skip_stt=False):
        self.session_id = session_id or str(uuid4())
        self.skip_stt = skip_stt
        self.records = {}
        self.revision = 0

    def begin(self, stage, model, provider, region="global", **extra):
        key = str(uuid4())
        self.update(key, **{"stage": stage, "model": model, "provider": provider, "region": region,
                            "date": datetime.now(timezone.utc).date().isoformat(),
                            "complete": False, "usage": {}, **extra})
        return key

    def update(self, key, **values):
        self.records[key] = {**self.records.get(key, {}), **values}
        self.revision += 1

    def snapshot(self):
        stages = []
        for stage in ("stt", "llm", "tts"):
            disabled = stage == "stt" and self.skip_stt
            records = [] if disabled else [r for r in self.records.values() if r.get("stage") == stage]
            amount, missing, rates = Decimal(0), set(), {}
            if not records and not disabled:
                missing.add("No final usage received")
            for record in records:
                value, reason, card = quote(record)
                if value is None:
                    missing.add(reason)
                else:
                    amount += value
                if record.get("in_flight"):
                    missing.add("Recognition stream active; final billed duration pending")
                if record.get("pending_reason"):
                    missing.add(record["pending_reason"])
                if card:
                    rates[(card["model"], card["provider"], card["region"])] = card
            stage_entry = {"stage": stage, "known_usd": str(amount), "complete": not missing,
                           "disabled": disabled, "requests": len(records), "issues": sorted(missing),
                           "estimated": any(r.get("estimated") or _is_estimated_cache_split(r) for r in records),
                           "rates": list(rates.values())}
            if stage == "llm":
                stage_entry.update(_llm_stage_usage_summary(records))
            stages.append(stage_entry)
        return {"type": "cascade_cost", "session_id": self.session_id, "revision": self.revision,
                "currency": "USD", "basis": "public-list-price", "reviewed_at": REVIEWED_AT,
                "known_usd": str(sum((Decimal(s["known_usd"]) for s in stages), Decimal(0))),
                "complete": all(s["complete"] for s in stages), "stages": stages}

