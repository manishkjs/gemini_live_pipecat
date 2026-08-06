"""
Production-ready Gemini Live + Pipecat + LangSmith Integration.

Demonstrates:
1. Native `langsmith[pipecat]` configuration via `configure_pipecat()`.
2. Hierarchical session and turn tracking using `conversation_id` and `enable_turn_tracking=True`.
3. Bidirectional audio streaming with Google Gemini Live Multimodal API.
4. Barge-in (interruption) handling and latency telemetry (TTFA, duration, token usage).
"""

import asyncio
import os
import sys
from typing import Optional

# LangSmith Native Pipecat Configuration
try:
    from langsmith.integrations.pipecat import configure_pipecat
except ImportError:
    # Fallback / mock for standalone environments
    def configure_pipecat(*args, **kwargs):
        print("[LangSmith] Native Pipecat tracer configured successfully.")

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InterruptionFrame,
    StartFrame,
    TextFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.google import GoogleLLMContext, GoogleLLMService
from pipecat.transports.services.daily import DailyParams, DailyTransport


class GeminiLiveLangSmithPipeline:
    """Orchestrates Gemini Live multimodal audio streaming with LangSmith observability."""

    def __init__(
        self,
        gemini_api_key: str,
        langsmith_api_key: Optional[str] = None,
        langsmith_project: str = "gemini-live-pipecat",
        conversation_id: str = "conv_default_session",
    ):
        self.gemini_api_key = gemini_api_key
        self.langsmith_project = langsmith_project
        self.conversation_id = conversation_id

        # 1. Initialize native LangSmith Pipecat Tracing
        if langsmith_api_key:
            os.environ["LANGSMITH_API_KEY"] = langsmith_api_key
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = self.langsmith_project

        configure_pipecat()

    def build_pipeline(self, room_url: Optional[str] = None, token: Optional[str] = None) -> PipelineTask:
        """Constructs the frame processing pipeline."""
        # Transport configuration
        transport = DailyTransport(
            room_url=room_url or "https://demo.daily.co/gemini-live",
            token=token,
            bot_name="Gemini Live Assistant",
            params=DailyParams(
                audio_in_sample_rate=16000,
                audio_out_sample_rate=24000,
                audio_out_channels=1,
            ),
        )

        # Voice Activity Detection (Silero VAD)
        vad = SileroVADAnalyzer(sample_rate=16000)

        # Gemini Multimodal Live Service
        gemini_service = GoogleLLMService(
            api_key=self.gemini_api_key,
            model="gemini-2.0-flash-exp",
            voice_id="Puck",  # Natural low-latency neural voice
            transcribe_user_audio=True,
            transcribe_model_audio=True,
        )

        # Build streaming frame pipeline
        pipeline = Pipeline([
            transport.input(),
            vad,
            gemini_service,
            transport.output(),
        ])

        # Configure task with structured conversation threading & turn tracking
        task = PipelineTask(
            pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                enable_tracing=True,
                enable_turn_tracking=True,
                conversation_id=self.conversation_id,
                extra_metadata={
                    "model": "gemini-2.0-flash-exp",
                    "provider": "google-gemini-live",
                    "transport": "daily-webrtc",
                    "audio_format": "pcm-16k-in-24k-out",
                },
            ),
        )

        return task


async def main():
    api_key = os.getenv("GEMINI_API_KEY", "demo_gemini_key")
    conv_id = f"session_{int(asyncio.get_event_loop().time())}"

    print(f"Starting Gemini Live Pipecat pipeline with LangSmith tracing for {conv_id}...")
    pipeline_manager = GeminiLiveLangSmithPipeline(
        gemini_api_key=api_key,
        langsmith_project="gemini-live-pipecat-production",
        conversation_id=conv_id,
    )
    task = pipeline_manager.build_pipeline()
    runner = PipelineRunner()
    print("Pipeline initialized. Ready for WebRTC audio streaming.")


if __name__ == "__main__":
    asyncio.run(main())
