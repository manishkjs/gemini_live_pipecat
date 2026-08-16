"""Continuous Watcher Brain (Gemini 3.5 Flash Lite Sidecar Co-Pilot)

Runs asynchronously in the background on every user dialogue turn.
Silently analyzes customer sentiment, objections, strategic opportunities, and compliance boundaries.
Selectively injects structured whispers (<copilot_hint>) directly into Gemini Live's WebSocket session
as dynamic system role turns without interrupting live audio streaming.
"""

import os
import json
import asyncio
import logging
from typing import List, Dict, Any, Optional

from google.genai import Client
from google.genai.types import GenerateContentConfig, Content, Part
from system_prompt import WATCHER_SYSTEM_PROMPT

logger = logging.getLogger("watcher_brain")
logger.setLevel(logging.INFO)


class WatcherBrain:
    """Continuous Watcher Brain sidecar powered by Gemini 3.5 Flash-Lite."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "cymbal-lending")
        self.location = location or os.getenv("WATCHER_LOCATION", "global")
        self.model = model or os.getenv("WATCHER_MODEL", "gemini-3.5-flash-lite")
        self.client: Optional[Client] = None
        self._last_injected_hint: Optional[str] = None
        self._last_injected_turn_count: int = 0
        self._min_turn_interval: int = 4  # Strict cooldown: at least 4 turns between any intervention
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initializes the GenAI SDK client for Vertex AI."""
        try:
            self.client = Client(
                project=self.project_id,
                location=self.location,
                vertexai=True,
            )
            logger.info(
                f"👁️ [WatcherBrain] Initialized Gemini 3.5 Flash-Lite watcher "
                f"(model={self.model}, location={self.location}, project={self.project_id})"
            )
        except Exception as e:
            logger.error(f"[WatcherBrain] Failed to initialize client: {e}")
            self.client = None

    async def analyze_dialogue(
        self,
        transcript_history: List[Dict[str, str]],
        user_profile: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Analyzes dialogue history asynchronously using Gemini 3.5 Flash-Lite."""
        if not self.client or not transcript_history:
            return None

        # Filter recent dialogue (last 6 turns for rapid inference)
        recent_history = transcript_history[-6:]
        dialogue_text = "\n".join(
            f"{turn.get('role', 'speaker').upper()}: {turn.get('text', '')}"
            for turn in recent_history
        )

        user_context_str = ""
        if user_profile:
            facts = user_profile.get("facts", {})
            mems = user_profile.get("episodic_memories", []) or user_profile.get("recent_memories", [])
            user_context_str = (
                f"\n[Known User Facts]: {json.dumps(facts, ensure_ascii=False)}\n"
                f"[Past Memories]: {'; '.join(str(m) for m in mems[:2])}\n"
            )

        prompt = (
            f"<current_dialogue>\n{dialogue_text}\n</current_dialogue>\n"
            f"{user_context_str}\n"
            f"Analyze if Pragya needs a strategic whisper for the very next turn."
        )

        config = GenerateContentConfig(
            system_instruction=WATCHER_SYSTEM_PROMPT,
            response_mime_type="application/json",
        )

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                ),
            )

            if response and response.text:
                result = json.loads(response.text.strip())
                return result
        except Exception as e:
            logger.warning(f"[WatcherBrain:InferenceError] {e}")
            return None

        return None

    async def maybe_whisper_to_live(
        self,
        session: Any,
        transcript_history: List[Dict[str, str]],
        user_id: str = "default_user",
        user_profile: Optional[Dict[str, Any]] = None,
        phase_tracker: Optional[Any] = None,
    ) -> bool:
        """Evaluates dialogue turn in background and injects hint into Gemini Live session if justified."""
        if not session or not transcript_history:
            return False

        current_turn_count = len(transcript_history)

        # Debounce check: don't inject hints if recently injected within cooldown interval
        if self._last_injected_turn_count > 0 and (current_turn_count - self._last_injected_turn_count) < self._min_turn_interval:
            return False

        # Fast skip on 1-word user fillers
        last_turn = transcript_history[-1] if transcript_history else {}
        last_text = last_turn.get("text", "").strip()
        filler_words = {"haan", "ji", "ok", "okay", "yes", "theek", "achha", "accha", "haanji", "हाँ", "जी", "ठीक", "अच्छा", "हाँजी"}
        if last_turn.get("role") == "user" and len(last_text.split()) <= 1 and last_text.lower() in filler_words:
            return False

        result = await self.analyze_dialogue(transcript_history, user_profile)
        if not result or not isinstance(result, dict):
            return False

        should_inject = result.get("should_inject_hint", False)
        hint_type = result.get("hint_type", "strategy")
        hint_text = result.get("hint_text")
        reasoning = result.get("reasoning", "")

        if should_inject and hint_text:
            # Prevent duplicate consecutive identical whispers
            if hint_text == self._last_injected_hint:
                return False

            hint_payload = (
                f'<copilot_hint type="{hint_type}">\n'
                f"[DIRECTOR WHISPER]: {hint_text}\n"
                f"</copilot_hint>"
            )

            logger.info(
                f"👁️⚡ [WatcherBrain:Whisper] Injected {hint_type} hint for '{user_id}':\n"
                f"   ├─ Text: {hint_text}\n"
                f"   └─ Reason: {reasoning}"
            )

            # Safely dispatch via phase tracker (buffers when bot is actively speaking)
            if phase_tracker and hasattr(phase_tracker, "yield_copilot_hint"):
                success = await phase_tracker.yield_copilot_hint(hint_payload)
                if success:
                    self._last_injected_hint = hint_text
                    self._last_injected_turn_count = current_turn_count
                    return True

            if hasattr(session, "send_client_content"):
                try:
                    await session.send_client_content(
                        turns=[
                            Content(
                                role="system",
                                parts=[Part(text=hint_payload)],
                            )
                        ],
                        turn_complete=False,
                    )
                    self._last_injected_hint = hint_text
                    self._last_injected_turn_count = current_turn_count
                    return True
                except Exception as e:
                    logger.warning(f"[WatcherBrain] Failed to send whisper via WebSocket: {e}")

        return False
