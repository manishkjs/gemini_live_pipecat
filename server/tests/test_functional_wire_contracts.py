"""End-to-end functional mock and wire-contract test suite.

Exercises the real service classes (`CustomVertexGeminiTTSService`,
`CustomGeminiTranscribeLiveService`, `CustomGeminiLiveLLMService`,
`CustomGeminiLiveVertexLLMService`, `_MeteredGeminiLLMMixin`, and
`AudioEmotionObserver`) with real `google.genai.Client` instances and real SDK
request serializers (`_GenerateContentParameters_to_mldev`,
`_LiveConnectParameters_to_mldev`), intercepting only at the network boundary
(`BaseApiClient._async_request` and `google.genai.live.ws_connect`).

Why this suite exists:
Unit tests that mock `genai.Client` (`return_value=None`) cannot catch SDK
wire-protocol regressions such as `google-genai 3.3.0` flipping
`GOOGLE_AI_API_DEFAULT_VERSION` from `'v1beta'` to `'v1'` (which caused
`generativelanguage.googleapis.com/v1` to reject `speechConfig` and
`speechMetadata` with `400 Bad Request`). This suite enforces the real `v1` vs
`v1beta` protobuf schema rules at the wire boundary and runs across all
personas, languages, and both architectures (Cascade STT/LLM/TTS and Gemini 3.8
Live).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import sys
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, patch

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from google.genai._api_client import BaseApiClient, HttpRequest
from pipecat.frames.frames import (
    ErrorFrame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TTSAudioRawFrame,
    TranscriptionFrame,
)
from pipecat.services.google.tts import GeminiTTSService
from pipecat.transcriptions.language import Language

import agent
import agent_live
from persona_registry import get_persona_architecture
from processors.emotion_perception import AudioEmotionObserver, GoogleDecisionsClassifier


# Fields that exist only in the AI Studio `v1beta` / `v1alpha` REST schema and
# are rejected with `400 INVALID_ARGUMENT` by `generativelanguage.googleapis.com/v1`.
_V1_FORBIDDEN_GENERATION_CONFIG_KEYS = frozenset({
    "speechConfig",
    "thinkingConfig",
})
_V1_FORBIDDEN_TOP_LEVEL_KEYS = frozenset({
    "systemInstruction",
    "cachedContent",
    "toolConfig",
})
_V1_FORBIDDEN_PART_KEYS = frozenset({
    "speechMetadata",
})


def _validate_aistudio_rest_wire_request(http_request: HttpRequest) -> None:
    """Enforce `generativelanguage.googleapis.com` v1 vs v1beta field rules on wire dicts."""
    url = http_request.url or ""
    data = http_request.data if isinstance(http_request.data, dict) else {}

    # Detect `/v1/models/...` (as opposed to `/v1beta/models/...` or `/v1alpha/models/...`).
    is_v1_endpoint = "/v1/models/" in url or url.rstrip("/").endswith("/v1")
    if not is_v1_endpoint:
        return

    violations: list[dict[str, str]] = []
    for top_key in _V1_FORBIDDEN_TOP_LEVEL_KEYS:
        if top_key in data:
            violations.append({
                "field": top_key,
                "description": (
                    f'Invalid JSON payload received. Unknown name "{top_key}": '
                    "Cannot find field."
                ),
            })

    gen_cfg = data.get("generationConfig")
    if isinstance(gen_cfg, dict):
        for cfg_key in _V1_FORBIDDEN_GENERATION_CONFIG_KEYS:
            if cfg_key in gen_cfg:
                violations.append({
                    "field": "generation_config",
                    "description": (
                        f'Invalid JSON payload received. Unknown name "{cfg_key}" '
                        "at 'generation_config': Cannot find field."
                    ),
                })

    contents = data.get("contents")
    if isinstance(contents, list):
        for c_idx, content in enumerate(contents):
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list):
                for p_idx, part in enumerate(parts):
                    if isinstance(part, dict):
                        for part_key in _V1_FORBIDDEN_PART_KEYS:
                            if part_key in part:
                                violations.append({
                                    "field": f"contents[{c_idx}].parts[{p_idx}]",
                                    "description": (
                                        f'Invalid JSON payload received. Unknown name "{part_key}" '
                                        f"at 'contents[{c_idx}].parts[{p_idx}]': Cannot find field."
                                    ),
                                })

    if violations:
        msg = "\n".join(v["description"] for v in violations)
        err_payload = {
            "error": {
                "code": 400,
                "message": msg,
                "status": "INVALID_ARGUMENT",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.BadRequest",
                        "fieldViolations": violations,
                    }
                ],
            }
        }
        raise genai_errors.ClientError(400, err_payload, response=None)


class _FakeSseStreamResponse:
    """Minimal async-iterable HTTP stream response compatible with `BaseApiClient.async_request_streamed`."""

    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.headers = {"content-type": "application/json"}
        self._items = list(chunks)

    def __aiter__(self) -> "_FakeSseStreamResponse":
        return self

    async def __anext__(self) -> dict[str, Any]:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


class TestWireLevelGenAIGate(unittest.IsolatedAsyncioTestCase):
    """Verifies real `google.genai.Client` REST wire requests hit `/v1beta/` with valid payloads."""

    def setUp(self) -> None:
        self.captured_requests: list[HttpRequest] = []
        self._pcm_b64 = base64.b64encode(b"\x10\x00" * 480).decode("ascii")

        async def _wire_interceptor(
            api_client_self: BaseApiClient,
            http_request: HttpRequest,
            http_options: Any = None,
            stream: bool = False,
        ) -> Any:
            self.captured_requests.append(http_request)
            _validate_aistudio_rest_wire_request(http_request)

            data = http_request.data if isinstance(http_request.data, dict) else {}
            gen_cfg = data.get("generationConfig") or {}
            modalities = gen_cfg.get("responseModalities") or []

            if "AUDIO" in modalities:
                chunk = {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "audio/pcm;rate=24000",
                                            "data": self._pcm_b64,
                                        }
                                    }
                                ],
                            }
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 14,
                        "candidatesTokenCount": 42,
                        "totalTokenCount": 56,
                    },
                }
            else:
                chunk = {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": "Hello from Gemini wire harness."}],
                            }
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 10,
                        "candidatesTokenCount": 6,
                        "totalTokenCount": 16,
                    },
                }
            return _FakeSseStreamResponse([chunk])

        self._req_patch = patch.object(BaseApiClient, "_async_request", _wire_interceptor)
        self._key_patch = patch("agent._resolve_gemini_api_key", return_value="fake-ai-studio-key")
        self._base_client_patch = patch.object(GeminiTTSService, "_create_client", return_value=None)
        self._req_patch.start()
        self._key_patch.start()
        self._base_client_patch.start()
        self.addCleanup(self._req_patch.stop)
        self.addCleanup(self._key_patch.stop)
        self.addCleanup(self._base_client_patch.stop)

    async def test_tts_38_flash_lite_aistudio_wire_request_hits_v1beta_and_streams_24khz_pcm(self) -> None:
        svc = agent.CustomVertexGeminiTTSService(
            project_id="test-proj",
            location="global",
            voice_id="Aoede",
            model="gemini-3.8-flash-lite-tts",
            language_code="hi-IN",
        )
        frames = [
            f
            async for f in svc.run_tts(
                "Arre, kuch toh problem lag rahi hai... Main portfolio details dobara check kar leti hoon.",
                "ctx-lite-1",
            )
        ]

        self.assertEqual(len(self.captured_requests), 1)
        req = self.captured_requests[0]
        self.assertIn("/v1beta/models/gemini-3.8-flash-lite-tts:streamGenerateContent", req.url)
        self.assertNotIn("/v1/models/", req.url)

        payload = req.data
        self.assertEqual(payload["generationConfig"]["responseModalities"], ["AUDIO"])
        self.assertEqual(
            payload["generationConfig"]["speechConfig"]["voice_config"]["prebuilt_voice_config"]["voice_name"],
            "Aoede",
        )
        part0 = payload["contents"][0]["parts"][0]
        self.assertEqual(part0["speechMetadata"]["style"], "calm, conversational")

        audio_frames = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
        error_frames = [f for f in frames if isinstance(f, ErrorFrame)]
        self.assertEqual(len(error_frames), 0)
        self.assertEqual(len(audio_frames), 1)
        self.assertEqual(audio_frames[0].sample_rate, 24000)

    async def test_tts_38_flash_full_aistudio_wire_request_hits_v1beta_with_library_voice(self) -> None:
        svc = agent.CustomVertexGeminiTTSService(
            project_id="test-proj",
            location="global",
            voice_id="en-in-csagent-3",
            model="gemini-3.8-flash-tts",
            language_code="en-IN",
        )
        frames = [
            f
            async for f in svc.run_tts(
                "Hello, welcome to mutual fund advisory desk.",
                "ctx-full-1",
            )
        ]

        self.assertEqual(len(self.captured_requests), 1)
        req = self.captured_requests[0]
        self.assertIn("/v1beta/models/gemini-3.8-flash-tts:streamGenerateContent", req.url)
        payload = req.data
        self.assertEqual(
            payload["generationConfig"]["speechConfig"]["voice_config"]["voice"],
            "en-in-csagent-3",
        )
        self.assertNotIn("speechMetadata", payload["contents"][0]["parts"][0])
        self.assertEqual([type(f) for f in frames], [TTSAudioRawFrame])

    async def test_tts_38_cloned_voicekey_wire_request_and_404_fallback_to_puck(self) -> None:
        call_count = {"n": 0}
        pcm_b64 = self._pcm_b64

        async def _flaky_voicekey_interceptor(
            api_client_self: BaseApiClient,
            http_request: HttpRequest,
            http_options: Any = None,
            stream: bool = False,
        ) -> Any:
            call_count["n"] += 1
            self.captured_requests.append(http_request)
            _validate_aistudio_rest_wire_request(http_request)
            if call_count["n"] == 1:
                raise genai_errors.ClientError(
                    404,
                    {
                        "error": {
                            "code": 404,
                            "message": "The voice was not found or the caller does not have permission to access it.",
                            "status": "NOT_FOUND",
                        }
                    },
                    response=None,
                )
            return _FakeSseStreamResponse([
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "audio/pcm;rate=24000",
                                            "data": pcm_b64,
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                }
            ])

        with patch.object(BaseApiClient, "_async_request", _flaky_voicekey_interceptor), \
             patch("voice_profiles.load_gemini_voice_key", return_value=None):
            svc = agent.CustomVertexGeminiTTSService(
                project_id="test-proj",
                location="global",
                voice_id="Gemini-Clone-Manish",
                model="gemini-3.8-flash-lite-tts",
                language_code="en-US",
                voice_key="voicekey_fake_12345",
            )
            svc.push_frame = AsyncMock()
            frames = [f async for f in svc.run_tts("Testing voice key fallback.", "ctx-clone")]

        self.assertEqual(call_count["n"], 2)
        first_voice_cfg = self.captured_requests[0].data["generationConfig"]["speechConfig"]["voice_config"]
        second_voice_cfg = self.captured_requests[1].data["generationConfig"]["speechConfig"]["voice_config"]
        self.assertEqual(first_voice_cfg["voice"], "voicekey_fake_12345")
        self.assertEqual(second_voice_cfg["prebuilt_voice_config"]["voice_name"], "Puck")
        self.assertEqual([type(f) for f in frames], [TTSAudioRawFrame])

    async def test_tts_v1_endpoint_regression_trap_raises_400_and_clears_ttfb_start(self) -> None:
        """Proves the wire validator catches any client accidentally configured with `api_version='v1'`."""
        svc = agent.CustomVertexGeminiTTSService(
            project_id="test-proj",
            location="global",
            voice_id="Aoede",
            model="gemini-3.8-flash-lite-tts",
            language_code="hi-IN",
        )
        # Deliberately overwrite with an unversioned `genai.Client(api_key=...)` (which defaults to `v1` in google-genai 3.3+).
        svc._client = genai.Client(api_key="fake-ai-studio-key")

        frames = [f async for f in svc.run_tts("Should fail on v1 endpoint.", "ctx-v1-trap")]
        error_frames = [f for f in frames if isinstance(f, ErrorFrame)]
        self.assertEqual(len(error_frames), 1)
        self.assertIn("speechConfig", error_frames[0].error)
        self.assertIn("speechMetadata", error_frames[0].error)
        self.assertIsNone(svc._my_ttfb_start)

    async def test_gemma_aistudio_fallback_wire_request_hits_v1beta(self) -> None:
        class _DummyLLM(agent._MeteredGeminiLLMMixin):
            def __init__(self) -> None:
                self._settings = SimpleNamespace(
                    system_instruction="You are a concise voice assistant.",
                    max_tokens=256,
                    temperature=0.7,
                    top_p=None,
                    top_k=None,
                    seed=None,
                    frequency_penalty=None,
                    presence_penalty=None,
                    extra=None,
                )
                self._project_id = "test-proj"
                self._my_ttfb_start = None

            def _build_generation_params(self, **kwargs: Any) -> dict[str, Any]:
                return {"max_output_tokens": 256, "temperature": 0.7}

            async def start_ttfb_metrics(self) -> None:
                pass

            def get_llm_adapter(self) -> Any:
                return SimpleNamespace(
                    get_llm_invocation_params=lambda ctx, system_instruction=None: {
                        "messages": [
                            types.Content(
                                role="user",
                                parts=[types.Part.from_text(text="Hello Gemma")],
                            )
                        ],
                        "system_instruction": system_instruction,
                        "tools": [],
                    }
                )

        dummy = _DummyLLM()
        stream = await dummy._open_gemma_aistudio_fallback(SimpleNamespace())
        chunks = [c async for c in stream]
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(self.captured_requests), 1)
        self.assertIn("/v1beta/models/gemma-4-26b-a4b-it:streamGenerateContent", self.captured_requests[0].url)

    def test_google_decisions_emotion_classifier_wire_client_is_v1beta(self) -> None:
        classifier = GoogleDecisionsClassifier(api_key="fake-decision-key")
        self.assertEqual(classifier.client._genai._api_client._http_options.api_version, "v1beta")
        observer = AudioEmotionObserver(enabled=True, session_id="s-1", api_key="fake-decision-key")
        self.assertIsNotNone(observer._classifier)
        self.assertEqual(
            observer._classifier.client._genai._api_client._http_options.api_version,
            "v1beta",
        )


class _FakeLiveWebSocket:
    """Wire-level mock WebSocket for `google.genai.live.ws_connect`."""

    def __init__(self, uri: str, headers: dict[str, str] | None) -> None:
        self.uri = uri
        self.headers = headers or {}
        self.sent_messages: list[dict[str, Any]] = []
        self._incoming: asyncio.Queue[bytes] = asyncio.Queue()
        self._incoming.put_nowait(
            json.dumps({"setupComplete": {"sessionId": "wire-live-session-1"}}).encode("utf-8")
        )

    async def send(self, data: str | bytes) -> None:
        raw = data.decode("utf-8") if isinstance(data, bytes) else data
        msg = json.loads(raw)
        self.sent_messages.append(msg)
        if "realtime_input" in msg or "realtimeInput" in msg:
            await self._incoming.put(
                json.dumps({
                    "serverContent": {
                        "inputTranscription": {"text": "Hello in US English."},
                        "turnComplete": True,
                    }
                }).encode("utf-8")
            )

    async def recv(self, decode: bool = False) -> bytes | str:
        item = await self._incoming.get()
        return item.decode("utf-8") if decode else item


class TestLiveWebSocketWireContracts(unittest.IsolatedAsyncioTestCase):
    """Verifies real `google.genai.Client.aio.live.connect` WebSocket URLs and setup frames."""

    async def test_transcribe_live_aistudio_websocket_wire_contract_and_audio_roundtrip(self) -> None:
        captured_sockets: list[_FakeLiveWebSocket] = []

        @contextlib.asynccontextmanager
        async def _fake_ws_connect(uri: str, additional_headers: Any = None, **kwargs: Any):
            if ".v1.GenerativeService" in uri:
                raise RuntimeError(f"Invalid v1 WebSocket URI for Transcribe Live: {uri}")
            ws = _FakeLiveWebSocket(uri, additional_headers)
            captured_sockets.append(ws)
            yield ws

        with patch("google.genai.live.ws_connect", _fake_ws_connect):
            svc = agent.CustomGeminiTranscribeLiveService(
                project_id="test-proj",
                location="global",
                api_key="fake-ai-studio-key",
                model="gemini-3.5-transcribe-live-aistudio",
                languages=[Language.EN_US],
                is_ai_studio=True,
            )
            emitted_frames: list[Any] = []

            async def _capture_push(frame: Any, direction: Any = None) -> None:
                emitted_frames.append(frame)

            svc.push_frame = _capture_push
            svc._handle_transcription = AsyncMock()
            svc.stop_processing_metrics = AsyncMock()

            worker = asyncio.create_task(svc._streaming_worker())
            await svc._audio_queue.put(
                InputAudioRawFrame(audio=b"\x01\x02" * 320, sample_rate=16000, num_channels=1)
            )
            await asyncio.sleep(0.12)
            svc._stopping = True
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

        self.assertEqual(len(captured_sockets), 1)
        ws = captured_sockets[0]
        self.assertIn("v1beta.GenerativeService.BidiGenerateContent", ws.uri)
        self.assertGreaterEqual(len(ws.sent_messages), 2)

        setup_msg = ws.sent_messages[0]["setup"]
        self.assertEqual(setup_msg["model"], "models/gemini-3.5-transcribe-live")
        self.assertEqual(setup_msg["generationConfig"]["responseModalities"], ["TEXT"])
        self.assertIn("inputAudioTranscription", setup_msg)

        finals = [f.text for f in emitted_frames if isinstance(f, TranscriptionFrame)]
        self.assertEqual(finals, ["Hello in US English."])

    def test_gemini_live_aistudio_client_uses_v1beta_by_default_and_preserves_v1alpha(self) -> None:
        svc_default = object.__new__(agent_live.CustomGeminiLiveLLMService)
        svc_default._api_key = "fake-live-key"
        svc_default._http_options = None
        svc_default.create_client()
        self.assertEqual(svc_default._client._api_client._http_options.api_version, "v1beta")

        svc_alpha = object.__new__(agent_live.CustomGeminiLiveLLMService)
        svc_alpha._api_key = "fake-live-key"
        svc_alpha._http_options = types.HttpOptions(api_version="v1alpha")
        svc_alpha.create_client()
        self.assertEqual(svc_alpha._client._api_client._http_options.api_version, "v1alpha")

    async def test_vertex_gemini_38_live_connection_task_handler_wire_contract(self) -> None:
        from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

        captured_sockets: list[_FakeLiveWebSocket] = []

        @contextlib.asynccontextmanager
        async def _fake_ws_connect(uri: str, additional_headers: Any = None, **kwargs: Any):
            ws = _FakeLiveWebSocket(uri, additional_headers)
            captured_sockets.append(ws)
            yield ws

        fake_creds = SimpleNamespace(token="fake-bearer-token", valid=True, quota_project_id="test-proj")
        svc = object.__new__(agent_live.CustomGeminiLiveVertexLLMService)
        svc._language_code = "en-US"
        svc._transcription_language_code = "en-US"
        svc.persona_architecture = get_persona_architecture("pragya")
        svc._avatar_enabled = False
        svc._replicated_voice_sample = None
        svc._fallback_voice_name = "Aoede"
        svc._client = genai.Client(
            vertexai=True,
            project="test-proj",
            location="us-central1",
            credentials=fake_creds,
        )

        async def _fake_super_handler(parent_self: Any, config: types.LiveConnectConfig) -> None:
            async with parent_self._client.aio.live.connect(
                model="google/gemini-3.8-live",
                config=config,
            ):
                return

        cfg = types.LiveConnectConfig(
            speech_config=types.SpeechConfig(
                language_code="en-US",
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Aoede")
                ),
            ),
            response_modalities=[types.Modality.AUDIO],
        )

        with patch("google.genai.live.ws_connect", _fake_ws_connect), \
             patch.object(GeminiLiveLLMService, "_connection_task_handler", _fake_super_handler):
            await svc._connection_task_handler(cfg)

        self.assertEqual(len(captured_sockets), 1)
        ws = captured_sockets[0]
        self.assertIn("LlmBidiService/BidiGenerateContent", ws.uri)
        setup_msg = ws.sent_messages[0]["setup"]
        self.assertEqual(
            setup_msg["model"],
            "projects/test-proj/locations/us-central1/publishers/google/models/gemini-3.8-live",
        )
        self.assertEqual(
            setup_msg["generationConfig"]["speechConfig"]["languageCode"],
            "en-US",
        )
        self.assertEqual(
            setup_msg["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voice_name"],
            "Aoede",
        )
        self.assertIn("en-US", setup_msg["inputAudioTranscription"]["language_codes"])
        self.assertIn("en-US", setup_msg["outputAudioTranscription"]["language_codes"])


class TestPersonaLanguageMatrixFunctional(unittest.IsolatedAsyncioTestCase):
    """End-to-end functional matrix across all personas, languages, and both engine modes."""

    PERSONAS = (
        ("groww-advisor", "en-IN", "en-IN"),
        ("pragya", "en-IN", "en-IN"),
        ("car-negotiator", "en-IN", "en-IN"),
        ("tara-travel", "en-US", "en-US"),
        ("lenskart-buddy", "en-US", "en-US"),
        ("ola-bazaar", "en-US", "en-US"),
        (None, "en-US", "en-US"),
    )

    EXPLICIT_LANGUAGES = ("en-US", "en-IN", "hi-IN", "ta-IN", "te-IN")

    def test_live_and_cascade_respect_explicit_language_across_all_personas(self) -> None:
        for persona_id, expected_speech_default, expected_tx_default in self.PERSONAS:
            arch = get_persona_architecture(persona_id)

            # 1. Omitted language falls back to the persona's default speech/transcription language.
            self.assertEqual(
                agent_live.resolve_speech_language_code(None, arch),
                expected_speech_default,
                f"Default speech language mismatch for persona={persona_id}",
            )
            self.assertEqual(
                agent_live.resolve_transcription_language_code(None, arch),
                expected_tx_default,
                f"Default transcription language mismatch for persona={persona_id}",
            )

            # 2. Every explicit language selection (especially en-US) is respected verbatim.
            for explicit_lang in self.EXPLICIT_LANGUAGES:
                with self.subTest(persona_id=persona_id, explicit_lang=explicit_lang):
                    speech_lang = agent_live.resolve_speech_language_code(explicit_lang, arch)
                    tx_lang = agent_live.resolve_transcription_language_code(explicit_lang, arch)
                    self.assertEqual(speech_lang, explicit_lang)
                    self.assertEqual(tx_lang, explicit_lang)

                    _, pipecat_lang = agent_live.resolve_tts_voice_and_language(
                        explicit_lang, "Aoede", arch
                    )
                    self.assertEqual(
                        pipecat_lang,
                        agent_live.LIVE_LANGUAGE_MAP[explicit_lang],
                    )

                    live_greeting = agent_live.default_greeting_text(explicit_lang)
                    cascade_greeting = agent.cascade_greeting_text(arch, explicit_lang)
                    if explicit_lang == "en-US":
                        self.assertEqual(live_greeting, "Hello!")
                        if persona_id != "tara-travel":
                            self.assertEqual(cascade_greeting, "Hello!")
                            self.assertNotIn("Namaste", cascade_greeting)

    async def test_all_personas_synthesize_cascade_greeting_over_v1beta_tts_without_errors(self) -> None:
        pcm_b64 = base64.b64encode(b"\x08\x00" * 320).decode("ascii")
        captured_urls: list[str] = []

        async def _wire_interceptor(
            api_client_self: BaseApiClient,
            http_request: HttpRequest,
            http_options: Any = None,
            stream: bool = False,
        ) -> Any:
            captured_urls.append(http_request.url)
            _validate_aistudio_rest_wire_request(http_request)
            return _FakeSseStreamResponse([
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "audio/pcm;rate=24000",
                                            "data": pcm_b64,
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                }
            ])

        with patch.object(BaseApiClient, "_async_request", _wire_interceptor), \
             patch("agent._resolve_gemini_api_key", return_value="fake-ai-studio-key"), \
             patch.object(GeminiTTSService, "_create_client", return_value=None):
            for persona_id, _, _ in self.PERSONAS:
                for tts_model in ("gemini-3.8-flash-lite-tts", "gemini-3.8-flash-tts"):
                    with self.subTest(persona_id=persona_id, tts_model=tts_model):
                        arch = get_persona_architecture(persona_id)
                        greeting = agent.cascade_greeting_text(arch, "en-US")
                        svc = agent.CustomVertexGeminiTTSService(
                            project_id="test-proj",
                            location="global",
                            voice_id="Aoede",
                            model=tts_model,
                            language_code="en-US",
                        )
                        frames = [f async for f in svc.run_tts(greeting, f"ctx-{persona_id}-{tts_model}")]
                        error_frames = [f for f in frames if isinstance(f, ErrorFrame)]
                        audio_frames = [f for f in frames if isinstance(f, TTSAudioRawFrame)]
                        self.assertEqual(error_frames, [])
                        self.assertEqual(len(audio_frames), 1)

        self.assertTrue(all("/v1beta/models/" in u for u in captured_urls))


if __name__ == "__main__":
    unittest.main()
