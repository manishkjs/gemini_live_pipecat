"""Provider-request accounting regressions; no credentials or network calls."""
import ast
import asyncio
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cascade_pricing import CascadeCostLedger, quote, rate_card
from cascade_metering import billed_duration, observe_tokens


def record(model="gemini-3.5-flash-lite", **extra):
    return dict(stage="llm", model=model, provider="vertex", region="global", complete=True,
                input_mode="text", usage=dict(prompt_token_count=1000, candidates_token_count=200,
                thoughts_token_count=100, cached_content_token_count=400, total_token_count=1300), **extra)


def test_llm_cache_is_subtracted_and_thinking_is_charged():
    value, issue, _ = quote(record())
    assert issue is None
    assert value == Decimal("0.000942")  # 600*.30 + 400*.03 + 300*2.50, per million.


def test_exact_model_provider_and_promotion_dates():
    assert rate_card("llm", "gemini-3.5-flash-lite-unknown", "vertex") is None
    assert rate_card("llm", "gemini-3.5-flash-lite", "other") is None
    assert rate_card("llm", "gemini-3.7-flash", "vertex", at="2026-12-31")["text_in"] == "0.75"
    assert rate_card("llm", "gemini-3.7-flash", "vertex", at="2027-01-01")["text_out"] == "7.50"
    assert Decimal(rate_card("llm", "gemini-3.5-flash-lite", "vertex", "us-central1")["text_in"]) == Decimal(".33")


def test_invalid_and_unreconciled_usage_stays_unknown():
    for mutation in ({"prompt_token_count": -1}, {"thoughts_token_count": True},
                     {"total_token_count": 9999}, {"cached_content_token_count": 1001},
                     {"traffic_type": "PROVISIONED_THROUGHPUT"}):
        r = record()
        r["usage"].update(mutation)
        assert quote(r)[0] is None


def test_audio_and_cache_modalities_for_skip_stt():
    r = record("gemini-2.5-flash")
    r["input_mode"] = "audio"
    assert quote(r)[0] is None
    r["usage"].update(prompt_tokens_details=[{"modality": "TEXT", "token_count": 600}, {"modality": "AUDIO", "token_count": 400}],
                      cache_tokens_details=[{"modality": "TEXT", "token_count": 200}, {"modality": "AUDIO", "token_count": 200}])
    assert quote(r)[0] == Decimal("0.001096")


def test_named_and_cloned_chirp_use_different_skus_and_unicode_characters():
    r = dict(stage="tts", provider="cloud-tts", complete=True, usage={"characters": len("नमस्ते 👋\n")})
    named = quote(dict(r, model="chirp3-hd"))[0]
    cloned = quote(dict(r, model="chirp3-instant-custom-voice"))[0]
    assert cloned == named * 2
    assert named == Decimal(len("नमस्ते 👋\n")) * Decimal(".00003")


def test_gemini_tts_charges_input_and_audio_output():
    r = dict(stage="tts", model="gemini-3.1-flash-tts-preview", provider="vertex", complete=True,
             usage={"prompt_token_count": 100, "candidates_token_count": 250, "total_token_count": 350})
    assert quote(r)[0] == Decimal(".0051")
    assert quote(dict(r, model="gemini-2.5-pro-preview-tts"))[0] == Decimal(".0051")
    # Gemini 3.8 Flash TTS ($0.50/1M in, $9.00/1M audio out) on AI Studio (provider="gemini"):
    # 100 * 0.50/1M + 250 * 9.00/1M = 0.00005 + 0.00225 = 0.00230
    r38 = dict(stage="tts", model="gemini-3.8-flash-tts", provider="gemini", complete=True,
               usage={"prompt_token_count": 100, "candidates_token_count": 250, "total_token_count": 350})
    assert quote(r38)[0] == Decimal(".0023")
    # Gemini 3.8 Flash Lite TTS ($0.50/1M in, $6.00/1M audio out) on AI Studio (provider="gemini"):
    # 100 * 0.50/1M + 250 * 6.00/1M = 0.00005 + 0.00150 = 0.00155
    r38_lite = dict(stage="tts", model="gemini-3.8-flash-lite-tts", provider="gemini", complete=True,
                    usage={"prompt_token_count": 100, "candidates_token_count": 250, "total_token_count": 350})
    assert quote(r38_lite)[0] == Decimal(".00155")


def test_transcribe_rate_is_token_based_but_unverified_scope_is_not_billed():
    r = dict(stage="stt", model="gemini-3.5-transcribe-live", provider="gemini", complete=True,
             usage={"prompt_token_count": 1500, "response_token_count": 175, "total_token_count": 1675})
    assert quote(r)[0] is None
    assert quote(dict(r, scope_verified=True))[0] == Decimal(".008925")
    assert rate_card("stt", "gemini-3.5-transcribe-live-preview", "vertex")["audio_in"] == "3.50"


def test_cloud_speech_billed_duration_and_missing_field():
    assert billed_duration(None) is None
    assert billed_duration(SimpleNamespace(_pb=SimpleNamespace(HasField=lambda _: False), total_billed_duration=timedelta())) is None
    assert billed_duration(SimpleNamespace(total_billed_duration=timedelta(seconds=61))) == 61
    r = dict(stage="stt", model="chirp_3", provider="cloud-speech-v2", complete=True, usage={"billed_seconds": 61})
    assert quote(r)[0] == Decimal(61) * Decimal(".016") / 60


def test_stream_revisions_replace_and_distinct_requests_add():
    ledger = CascadeCostLedger("call", skip_stt=True)
    a = ledger.begin("llm", "gemini-3.5-flash-lite", "vertex")
    ledger.update(a, **record())
    ledger.update(a, **record())
    b = ledger.begin("llm", "gemini-3.5-flash-lite", "vertex")
    ledger.update(b, **record())
    snapshot = ledger.snapshot()
    assert snapshot["known_usd"] == "0.001884"
    assert snapshot["complete"] is False  # TTS has not reported; not a free stage.
    assert snapshot["stages"][0]["disabled"] is True
    assert snapshot["stages"][1]["requests"] == 2
    assert CascadeCostLedger("another").snapshot()["known_usd"] == "0"


def test_failed_or_interrupted_requests_are_explicitly_partial():
    ledger = CascadeCostLedger("call")
    key = ledger.begin("tts", "chirp3-hd", "cloud-tts")
    ledger.update(key, complete=False, usage={"characters": 500}, issue="interrupted")
    stage = ledger.snapshot()["stages"][2]
    assert stage["known_usd"] == "0"
    assert stage["issues"] == ["interrupted"]


def test_actual_llm_stream_keeps_last_metadata_and_meter_is_optional():
    source = ast.parse((Path(__file__).parents[1] / "agent.py").read_text())
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "CustomGoogleVertexLLMService")
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_stream_content")
    class FakeBase:
        async def _stream_content(self, context):
            async def chunks():
                for p in (5, 1000):
                    yield SimpleNamespace(usage_metadata={"prompt_token_count": p, "candidates_token_count": 200, "total_token_count": p + 200})
            return chunks()
    ns = dict(FakeBase=FakeBase, observe_tokens=observe_tokens, publish_cost=AsyncMock())
    extracted = ast.ClassDef(name="Metered", bases=[ast.Name(id="FakeBase", ctx=ast.Load())], keywords=[], body=[method], decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[extracted], type_ignores=[])), "actual_llm_method", "exec"), ns)
    async def run():
        service = ns["Metered"]()
        service._settings = SimpleNamespace(model="gemini-3.5-flash-lite")
        service._location = "global"
        assert len([x async for x in await service._stream_content(None)]) == 2
        service._cascade_meter = CascadeCostLedger("call")
        assert len([x async for x in await service._stream_content(None)]) == 2
        assert len(service._cascade_meter.records) == 1
        assert service._cascade_meter.snapshot()["stages"][1]["known_usd"] == "0.0008"
    asyncio.run(run())


def extracted_method(class_name, method_name, base, namespace, filename="agent.py"):
    source = ast.parse((Path(__file__).parents[1] / filename).read_text())
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == method_name)
    node = ast.ClassDef(name="Subject", bases=[ast.Name(id="Base", ctx=ast.Load())], keywords=[], body=[method], decorator_list=[])
    namespace["Base"] = base
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "actual_provider_method", "exec"), namespace)
    return namespace["Subject"]


def test_gemini_tts_reads_usage_only_chunk_and_interruption_is_partial():
    from google.genai import types
    class FakeBase:
        async def start_ttfb_metrics(self): pass
        async def stop_ttfb_metrics(self): pass
    frames = lambda *args, **kwargs: SimpleNamespace(args=args, kwargs=kwargs)
    ns = dict(types=types, observe_tokens=observe_tokens, publish_cost=AsyncMock(),
              logger=SimpleNamespace(debug=lambda *a: None, exception=lambda *a: None),
              TTSAudioRawFrame=frames, TTSStoppedFrame=frames, ErrorFrame=frames)
    cls = extracted_method("CustomVertexGeminiTTSService", "run_tts", FakeBase, ns)
    async def run():
        async def chunks():
            yield SimpleNamespace(usage_metadata=None, candidates=[SimpleNamespace(content=SimpleNamespace(parts=[SimpleNamespace(inline_data=SimpleNamespace(data=b'\0' * 32))]))])
            yield SimpleNamespace(candidates=None, usage_metadata={"prompt_token_count": 100, "candidates_token_count": 250, "total_token_count": 350})
        async def generate(**kwargs): return chunks()
        service = cls()
        service._settings = SimpleNamespace(model="gemini-3.1-flash-tts-preview", voice="Aoede")
        service._voice_prompt = None
        service._language_code = "hi-IN"
        service._cost_region = "global"
        service.sample_rate, service.chunk_size = 24000, 32
        service._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate)))
        service._cascade_meter = CascadeCostLedger("call")
        assert len([f async for f in service.run_tts("नमस्ते", "context")]) == 2
        assert service._cascade_meter.snapshot()["stages"][2]["known_usd"] == "0.0051"
        interrupted = service.run_tts("Next sentence", "context")
        await anext(interrupted)
        await interrupted.aclose()
        stage = service._cascade_meter.snapshot()["stages"][2]
        assert stage["requests"] == 2 and not stage["complete"]
        assert stage["known_usd"] == "0.0051"  # Previously measured audio is retained.
    asyncio.run(run())


def test_chirp_character_count_is_recorded_after_stream_finishes():
    class FakeBase:
        async def _stream_tts(self, *args): yield "audio"
    ns = dict(publish_cost=AsyncMock())
    cls = extracted_method("CustomGoogleTTSService", "_stream_tts", FakeBase, ns)
    async def run():
        service = cls()
        service._voice_cloning_key = "DUMMY_ONLY"
        service._settings = SimpleNamespace(voice="en-US-Chirp3-HD-Aoede")
        service._cascade_meter = CascadeCostLedger("call")
        text = "नमस्ते 👋\n"
        assert [f async for f in service._stream_tts(None, text, "ctx")] == ["audio"]
        stage = service._cascade_meter.snapshot()["stages"][2]
        assert stage["complete"]
        assert Decimal(stage["known_usd"]) == Decimal(len(text)) * Decimal(".00006")
        service._voice_cloning_key = None
        service._settings.voice = "en-US-Journey-F"
        assert [f async for f in service._stream_tts(None, text, "ctx")] == ["audio"]
        stage = service._cascade_meter.snapshot()["stages"][2]
        assert not stage["complete"]  # An unverified voice SKU is not priced as Chirp.
    asyncio.run(run())


def test_all_persona_declarations_survive_actual_sdk_conversion():
    from google.genai.types import GenerateContentConfig
    from persona_registry import get_persona_architecture
    for persona in ("lamborghini-concierge", "car-negotiator", "ananya-advisor", "kavya-glass-buddy"):
        arch = get_persona_architecture(persona)
        for engine in ("live", "cascade"):
            schemas = arch.get_tool_schemas(engine=engine)
            declarations = [s.to_default_dict() for s in schemas]
            config = GenerateContentConfig(tools=[{"function_declarations": declarations}])
            names = [f.name for t in config.tools for f in t.function_declarations]
            assert names == [s.name for s in schemas]
            if engine == "cascade": assert "switch_phase" not in names


def test_normal_cascade_tts_setup_works_with_and_without_stt():
    import voice_profiles
    from pipecat.transcriptions.language import Language
    source = ast.parse((Path(__file__).parents[1] / "agent.py").read_text())
    fn = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_agent")
    start = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "is_clone")
    end = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "turn_tracker")
    code = compile(ast.Module(body=fn.body[start:end], type_ignores=[]), "actual_tts_setup", "exec")
    for skip in (False, True):
        calls = []
        ns = dict(clean_tts_model="gemini-3.1-flash-tts-preview", tts_voice="Aoede", custom_voice_key=None,
                  stt_language="hi-IN", project_id="dummy", location="us-central1", tts_voice_prompt=None,
                  voice_profiles=voice_profiles, MarkdownTextFilter=lambda: None,
                  CustomVertexGeminiTTSService=lambda **kwargs: calls.append(kwargs))
        if not skip: ns["stt_languages"] = [Language.HI_IN]
        exec(code, ns)
        assert len(calls) == 1 and calls[0]["language_code"] == "hi-IN"


def test_active_cloud_stream_keeps_reported_subtotal_but_not_complete_total():
    meter = CascadeCostLedger("call")
    key = meter.begin("stt", "chirp_3", "cloud-speech-v2", in_flight=True)
    meter.update(key, complete=True, usage={"billed_seconds": 60})
    stage = meter.snapshot()["stages"][0]
    assert stage["known_usd"] == "0.016" and not stage["complete"]


def test_background_transcript_counts_even_with_skip_stt_and_empty_results(monkeypatch):
    import sys
    from types import ModuleType
    cloud_types = ModuleType("google.cloud.speech_v2.types")
    decoding = lambda **kwargs: SimpleNamespace(**kwargs)
    decoding.AudioEncoding = SimpleNamespace(LINEAR16=1)
    cloud_types.cloud_speech = SimpleNamespace(
        RecognitionConfig=decoding, ExplicitDecodingConfig=decoding, RecognizeRequest=decoding)
    monkeypatch.setitem(sys.modules, "google.cloud.speech_v2.types", cloud_types)
    ns = dict(asyncio=asyncio, billed_duration=billed_duration, publish_cost=AsyncMock(),
              logger=SimpleNamespace(debug=lambda *a: None, info=lambda *a: None,
                                     warning=lambda *a: None, error=lambda *a: None))
    cls = extracted_method("AudioAccumulator", "_run_parallel_stt", object, ns, "processors/audio_accumulator.py")

    async def run():
        for duration, cancelled in ((timedelta(seconds=2), False), (None, False), (None, True)):
            async def recognize(**kwargs):
                if cancelled:
                    raise asyncio.CancelledError()
                return SimpleNamespace(results=[], metadata=SimpleNamespace(total_billed_duration=duration))
            service = cls()
            service._cascade_meter = CascadeCostLedger("call", skip_stt=True)
            service._project_id, service._stt_languages = "dummy", ["hi-IN"]
            service._get_stt_client = AsyncMock(return_value=SimpleNamespace(recognize=recognize))
            await service._run_parallel_stt(b"audio")
            stage = service._cascade_meter.snapshot()["stages"][0]
            assert stage["requests"] == 1 and not stage["disabled"]
            assert stage["complete"] is (duration is not None)
            if duration is not None:
                assert Decimal(stage["known_usd"]) == Decimal(2) * Decimal(".016") / 60
            else:
                assert stage["issues"]
    asyncio.run(run())
