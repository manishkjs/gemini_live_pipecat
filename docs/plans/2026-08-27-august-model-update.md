# August 2026 Model Update Implementation Plan

> **For Gemini:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate Gemini 3.5 Transcribe Live (`gemini-3.5-transcribe-live`) as an enterprise real-time streaming STT model across Vertex AI and Google AI Studio endpoints in the STT-LLM-TTS cascading stack, add Gemini 3.7 Flash (`gemini-3.7-flash`) to the LLM model tier, and purge deprecated legacy models (`gemini-2.0-*`, `gemini-3.5-flash`, `gemini-3.6-flash`) while retaining stable `gemini-2.5-flash` and `gemini-2.5-flash-lite`.

**Architecture:** 
Implement `CustomGeminiTranscribeLiveService` (subclassing Pipecat's `STTService`) that manages an asynchronous bidirectional WebSocket session to Gemini Live API (`google.genai.Client` with `response_modalities=["TEXT"]` and `AudioTranscriptionConfig`). Incoming PCM 16kHz audio frames are streamed upstream, and incremental transcriptions from `server_content.input_transcription` are parsed into `InterimTranscriptionFrame` and `TranscriptionFrame` with precise speech offset latency tracking. Update the LLM routing layer in `agent.py` to route `gemini-3.7-flash` to the `global` Vertex AI endpoint with thinking configuration support, and synchronize client UI selectors across `client/index.html`, `client/src/app.ts`, and compiled production bundles.

**Tech Stack:** Python 3.13, FastAPI, WebSockets, Pipecat 1.2.1, `google-genai` SDK (`types.LiveConnectConfig`), TypeScript, Vite.

---

### Task 1: Environment & Dedicated Branch Verification

**Files:**
- Repository: `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat`

**Step 1: Verify current git branch**
Run: `git branch --show-current`
Expected: `august_model_update` (cleanly branched from `main`).

**Step 2: Run baseline test suite**
Run: `./server/venv/bin/python server/test_routes.py`
Expected: 100% PASS (4 tests).

---

### Task 2: Implement `CustomGeminiTranscribeLiveService` for Vertex AI & AI Studio

**Files:**
- Modify: `server/agent.py`
- Test: `server/tests/test_stt_transcribe_live.py`

**Step 1: Write failing unit tests for `CustomGeminiTranscribeLiveService`**

```python
# server/tests/test_stt_transcribe_live.py
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import os
import sys

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from agent import CustomGeminiTranscribeLiveService
from pipecat.transcriptions.language import Language


class TestGeminiTranscribeLiveService(unittest.IsolatedAsyncioTestCase):
    def test_init_vertex_ai(self):
        service = CustomGeminiTranscribeLiveService(
            project_id="deep-clock-339817",
            location="us-central1",
            model="gemini-3.5-transcribe-live",
            languages=[Language("en-US"), Language("hi-IN")],
            is_ai_studio=False,
        )
        self.assertEqual(service.model_name, "gemini-3.5-transcribe-live")
        self.assertFalse(service.is_ai_studio)
        self.assertEqual(service.location, "us-central1")

    def test_init_ai_studio(self):
        service = CustomGeminiTranscribeLiveService(
            api_key="test_api_key",
            model="gemini-3.5-transcribe-live",
            languages=[Language("en-US")],
            is_ai_studio=True,
        )
        self.assertEqual(service.model_name, "models/gemini-3.5-transcribe-live")
        self.assertTrue(service.is_ai_studio)


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**
Run: `./server/venv/bin/python -m unittest server/tests/test_stt_transcribe_live.py`
Expected: FAIL with `ImportError: cannot import name 'CustomGeminiTranscribeLiveService' from 'agent'`

**Step 3: Implement `CustomGeminiTranscribeLiveService` in `server/agent.py`**

```python
class CustomGeminiTranscribeLiveService(STTService):
    """Speech-to-Text streaming service using Gemini 3.5 Transcribe Live.
    
    Supports both Vertex AI (Enterprise) and Google AI Studio endpoints over WebSockets.
    """
    def __init__(
        self,
        *,
        project_id: Optional[str] = None,
        location: str = "us-central1",
        api_key: Optional[str] = None,
        model: str = "gemini-3.5-transcribe-live",
        languages: Optional[List[Language]] = None,
        is_ai_studio: bool = False,
        sample_rate: int = 16000,
        **kwargs
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self.is_ai_studio = is_ai_studio
        self.project_id = project_id
        self.location = location
        self.sample_rate = sample_rate
        self.languages = languages or [Language("en-US"), Language("hi-IN")]
        
        # Clean model naming
        clean_model = model.replace("-aistudio", "").strip()
        if is_ai_studio:
            self.model_name = f"models/{clean_model}" if not clean_model.startswith("models/") else clean_model
            self._client = genai.Client(api_key=api_key)
        else:
            self.model_name = clean_model
            self._client = genai.Client(vertexai=True, project=project_id, location=location)

        self._session = None
        self._send_task = None
        self._receive_task = None
        self._stream_start_wall_time = None
        self._user_started_speaking_time = None
        self._user_stopped_speaking_time = None

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._stream_start_wall_time = time.time()

    async def run_stt(self, audio_generator: AsyncGenerator[AudioRawFrame, None]) -> AsyncGenerator[Frame, None]:
        lang_codes = [language_to_google_stt_language(lang) for lang in self.languages] if self.languages else []
        config = types.LiveConnectConfig(
            response_modalities=["TEXT"],
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=lang_codes
            )
        )
        
        try:
            async with self._client.aio.live.connect(model=self.model_name, config=config) as session:
                self._session = session
                logger.info(f"Gemini 3.5 Transcribe Live session connected ({'AI Studio' if self.is_ai_studio else 'Vertex AI'} - {self.model_name})")

                async def receive_transcripts():
                    async for response in session.receive():
                        server_content = getattr(response, "server_content", None)
                        if not server_content:
                            continue
                        
                        input_transcription = getattr(server_content, "input_transcription", None)
                        if input_transcription and input_transcription.text:
                            transcript_text = input_transcription.text.strip()
                            if transcript_text:
                                now = time.time()
                                stt_latency = None
                                if self._user_stopped_speaking_time:
                                    elapsed = now - self._user_stopped_speaking_time
                                    if 0.05 <= elapsed <= 15.0:
                                        stt_latency = elapsed
                                elif self._user_started_speaking_time:
                                    elapsed = now - self._user_started_speaking_time
                                    if 0.05 <= elapsed <= 15.0:
                                        stt_latency = elapsed
                                
                                if stt_latency is not None:
                                    logger.info(f"STT Latency (Gemini 3.5 Transcribe Live): {stt_latency:.3f}s ({int(stt_latency*1000)}ms)")
                                    await self.push_frame(OutputTransportMessageFrame(message={
                                        "label": "rtvi-ai",
                                        "type": "server-message",
                                        "data": {
                                            'type': 'metrics',
                                            'payload': {'type': 'stt_latency', 'value': stt_latency}
                                        }
                                    }))

                                is_turn_complete = getattr(server_content, "turn_complete", False)
                                if is_turn_complete:
                                    await self.push_frame(TranscriptionFrame(
                                        text=transcript_text,
                                        user_id=self._user_id,
                                        timestamp=time_now_iso8601(),
                                        language=self.languages[0].value if self.languages else "en-US"
                                    ))
                                else:
                                    await self.push_frame(InterimTranscriptionFrame(
                                        text=transcript_text,
                                        user_id=self._user_id,
                                        timestamp=time_now_iso8601(),
                                        language=self.languages[0].value if self.languages else "en-US"
                                    ))

                self._receive_task = asyncio.create_task(receive_transcripts())

                async for audio_frame in audio_generator:
                    if isinstance(audio_frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
                        self._user_started_speaking_time = time.time()
                        self._user_stopped_speaking_time = None
                    elif isinstance(audio_frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
                        self._user_stopped_speaking_time = time.time()
                    
                    if isinstance(audio_frame, AudioRawFrame) and audio_frame.audio:
                        await session.send(
                            input={"data": audio_frame.audio, "mime_type": f"audio/pcm;rate={audio_frame.sample_rate}"},
                            end_of_turn=False
                        )
        except Exception as e:
            logger.error(f"Gemini 3.5 Transcribe Live exception: {e}")
            yield ErrorFrame(error=f"Gemini Transcribe Live error: {str(e)}")
        finally:
            if self._receive_task and not self._receive_task.done():
                self._receive_task.cancel()
```

**Step 4: Run unit tests to verify pass**
Run: `./server/venv/bin/python -m unittest server/tests/test_stt_transcribe_live.py`
Expected: 100% PASS (2 tests).

---

### Task 3: Update Model Routing & Purge Deprecated Models in `server/agent.py` & `server/server.py`

**Files:**
- Modify: `server/agent.py`
- Modify: `server/server.py`
- Test: `server/tests/test_model_routing.py`

**Step 1: Write failing tests for model routing updates**

```python
# server/tests/test_model_routing.py
import unittest
import os
import sys

server_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from agent import validate_stt_model, validate_llm_model


class TestModelRouting(unittest.TestCase):
    def test_stt_model_validation(self):
        # Gemini 3.5 Transcribe Live
        self.assertEqual(validate_stt_model("gemini-3.5-transcribe-live"), "gemini-3.5-transcribe-live")
        self.assertEqual(validate_stt_model("gemini-3.5-transcribe-live-aistudio"), "gemini-3.5-transcribe-live-aistudio")
        # Legacy Cloud Speech v2 models
        self.assertEqual(validate_stt_model("chirp_3"), "chirp_3")
        self.assertEqual(validate_stt_model("chirp_2"), "chirp_2")
        self.assertEqual(validate_stt_model("latest_long"), "latest_long")
        # Fallback for unknown
        self.assertEqual(validate_stt_model("unknown_stt"), "gemini-3.5-transcribe-live")

    def test_llm_model_validation(self):
        # Gemini 3.7 Flash and approved tiers
        self.assertEqual(validate_llm_model("gemini-3.7-flash"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-3.5-flash-lite"), "gemini-3.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-2.5-flash"), "gemini-2.5-flash")
        self.assertEqual(validate_llm_model("gemini-2.5-flash-lite"), "gemini-2.5-flash-lite")
        self.assertEqual(validate_llm_model("gemini-2.5-pro"), "gemini-2.5-pro")
        self.assertEqual(validate_llm_model("gemini-3.5-pro"), "gemini-3.5-pro")
        # Removed models should fallback to gemini-3.7-flash
        self.assertEqual(validate_llm_model("gemini-2.0-flash"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-2.0-flash-lite"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-3.5-flash"), "gemini-3.7-flash")
        self.assertEqual(validate_llm_model("gemini-3.6-flash"), "gemini-3.7-flash")


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it fails**
Run: `./server/venv/bin/python -m unittest server/tests/test_model_routing.py`
Expected: FAIL with `ImportError: cannot import name 'validate_stt_model' from 'agent'`

**Step 3: Update `server/agent.py` and `server/server.py`**
- Implement `validate_stt_model` and `validate_llm_model`.
- In `run_agent()`, dynamically instantiate `CustomGeminiTranscribeLiveService` when `clean_stt_model.startswith("gemini-3.5-transcribe")`, supporting both Vertex AI and AI Studio endpoints (resolving API key via env or Secret Manager).
- Route `gemini-3.7-flash` with `llm_location = "global"` and `thinking_config = GoogleLLMService.ThinkingConfig(thinking_level="minimal")`.
- In `server/server.py`, update default parameters:
  - `llm_model: str = "gemini-3.7-flash"`
  - `stt_model: str = "gemini-3.5-transcribe-live"`

**Step 4: Run test to verify it passes**
Run: `./server/venv/bin/python -m unittest server/tests/test_model_routing.py`
Expected: 100% PASS (2 tests).

---

### Task 4: Update Frontend Model Selectors & Rebuild Client

**Files:**
- Modify: `client/index.html`
- Modify: `client/src/app.ts`
- Modify: `client/src/app.js`
- Build Output: `client/dist/`

**Step 1: Update `client/index.html` STT and LLM Model Dropdowns**
- In `<select id="stt-model-select">`:
  ```html
  <option value="gemini-3.5-transcribe-live" selected>gemini-3.5-transcribe-live (Vertex AI Live STT - US)</option>
  <option value="gemini-3.5-transcribe-live-aistudio">gemini-3.5-transcribe-live-aistudio (AI Studio Live STT)</option>
  <option value="chirp_3">chirp_3 (Cloud Speech v2 Multilingual - US)</option>
  <option value="chirp_2">chirp_2 (Cloud Speech v2 - us-central1)</option>
  <option value="latest_long">latest_long (General Long - US)</option>
  <option value="telephony">telephony (Telephony - US)</option>
  ```
- In `<select id="llm-model-select">`:
  ```html
  <option value="gemini-3.7-flash" selected>gemini-3.7-flash</option>
  <option value="gemini-3.5-flash-lite">gemini-3.5-flash-lite</option>
  <option value="gemini-3.5-pro">gemini-3.5-pro</option>
  <option value="gemini-2.5-flash">gemini-2.5-flash</option>
  <option value="gemini-2.5-flash-lite">gemini-2.5-flash-lite</option>
  <option value="gemini-2.5-pro">gemini-2.5-pro</option>
  ```
- Purge removed options (`gemini-2.0-*`, `gemini-3.5-flash`, `gemini-3.6-flash`, `gemini-3-*-preview`).

**Step 2: Update default fallback values in `client/src/app.ts` and `client/src/app.js`**
- `llmModel = ... || "gemini-3.7-flash"`
- `sttModel = ... || "gemini-3.5-transcribe-live"`

**Step 3: Compile and bundle client application**
Run: `npm run build` in `client/`
Expected: Clean build (`✓ built in ~3s`), updating `client/dist/`.

---

### Task 5: Comprehensive Regression & Integration Testing

**Files:**
- Test: `server/test_routes.py`
- Test: `server/tests/`

**Step 1: Execute test suite**
Run: `./server/venv/bin/python server/test_routes.py`
Run: `./server/venv/bin/python -m unittest discover server/tests`
Expected: 100% PASS across all unit and integration tests.

**Step 2: Run clean git status check**
Run: `git status`
Expected: All modified files staged/committed cleanly without temporary artifact pollution.

---

### Task 6: Documentation & Release Updates

**Files:**
- Modify: `README.md`
- Modify: `PROJECT.md`

**Step 1: Update README.md and documentation**
- Document the new Gemini 3.5 Transcribe Live STT model option (Vertex AI + AI Studio).
- Document Gemini 3.7 Flash in the LLM tier.
- Remove references to deprecated models (`gemini-2.0-*`, `gemini-3.5-flash`, `gemini-3.6-flash`).

**Step 2: Final commit on `august_model_update`**
Run:
```bash
git add .
git commit -m "feat(models): add gemini 3.5 transcribe live STT and gemini 3.7 flash LLM, purge legacy models"
```
