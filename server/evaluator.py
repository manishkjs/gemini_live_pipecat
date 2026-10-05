import time
from loguru import logger
from typing import Optional, Dict, Any

from pipecat.frames.frames import (
    Frame,
    OutputTransportMessageFrame,
    MetricsFrame
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

class VoiceEvaluatorProcessor(FrameProcessor):
    """
    A processor that calculates and logs Time-To-First-Byte (TTFB) 
    and other voice evaluation metrics like turn-by-turn LLM-as-a-judge context.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._user_finished_speaking_time: Optional[float] = None
        self._last_ttfb: Optional[float] = None
        self._user_utterance = ""
        self._bot_utterance = ""
        self._interaction_count = 0
        self._metrics: list[Dict[str, Any]] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if direction == FrameDirection.DOWNSTREAM:
            if isinstance(frame, OutputTransportMessageFrame):
                data = frame.message.get("data", {})
                
                # Detect user transcription
                if data.get("type") == "transcription" and data.get("participant") == "User":
                    self._user_utterance = data.get("text", "")
                    self._user_finished_speaking_time = time.time()
                    self._bot_utterance = "" # reset bot utterance for next turn
                    self._last_ttfb = None
                    logger.debug(f"[Evaluator] User speaking registered at {self._user_finished_speaking_time}")
                
                # Detect bot transcription (First byte indicator for text/audio correlation)
                if data.get("type") == "transcription" and data.get("participant") == "Bot":
                    if self._user_finished_speaking_time and self._last_ttfb is None:
                        ttfb = time.time() - self._user_finished_speaking_time
                        self._last_ttfb = ttfb
                        self._log_ttfb(ttfb)
                    self._bot_utterance += " " + data.get("text", "")
                
                # Detect Turn Complete
                if data.get("type") == "metrics" and data.get("payload", {}).get("type") == "turn_complete":
                     self._evaluate_turn()
                     # Reset for next turn
                     self._user_finished_speaking_time = None
                     self._last_ttfb = None
                     self._user_utterance = ""
                     self._bot_utterance = ""

        await self.push_frame(frame, direction)

    def _log_ttfb(self, ttfb: float):
        logger.info(f"====== EVALUATION METRIC ======")
        logger.info(f"TTFB (Time to First Byte): {ttfb:.3f} seconds")
        logger.info(f"===============================")

    def _evaluate_turn(self):
        if not self._user_utterance and not self._bot_utterance.strip():
            return
            
        self._interaction_count += 1
        logger.info(f"====== TURN {self._interaction_count} EVALUATION ======")
        logger.info(f"User Utterance: {self._user_utterance}")
        logger.info(f"Bot Utterance: {self._bot_utterance.strip()}")
        logger.info(f"TTFB: {self._last_ttfb:.3f}s" if self._last_ttfb else "TTFB: N/A")
        
        # Stub for LLM-as-a-judge
        logger.info("Grade: Pending LLM-as-a-judge integration (Requires secondary LLM call)")
        logger.info(f"=======================================")
        
        self._metrics.append({
            "turn": self._interaction_count,
            "user_text": self._user_utterance,
            "bot_text": self._bot_utterance.strip(),
            "ttfb": self._last_ttfb
        })

    def get_metrics(self) -> list[Dict[str, Any]]:
        return self._metrics
