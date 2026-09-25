import asyncio
import collections
import inspect
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    LLMContextFrame,
    OutputTransportMessageUrgentFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from loguru import logger
from cascade_metering import billed_duration, publish_cost


class AudioAccumulator(FrameProcessor):
    def __init__(self, context, *, project_id, stt_languages=None, cost_meter=None, **kwargs):
        super().__init__(**kwargs)
        self._context = context
        self._audio_frames = []
        self._preroll_frames = collections.deque(maxlen=15)
        self._accumulating = False
        self._project_id = project_id
        self._stt_languages = stt_languages or ["en-US"]
        self._stt_client = None
        self._stt_task = None
        self._cascade_meter = cost_meter
        self._push_lock = asyncio.Lock()
        logger.info(f"AudioAccumulator initialized with parallel STT (languages={self._stt_languages})")

    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        async with self._push_lock:
            await super().push_frame(frame, direction)

    async def _get_stt_client(self):
        if self._stt_client is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud.speech_v2 import SpeechAsyncClient
            self._stt_client = SpeechAsyncClient(
                client_options=ClientOptions(api_endpoint="us-speech.googleapis.com")
            )
        return self._stt_client

    async def _run_parallel_stt(self, audio_data: bytes):
        meter = self._cascade_meter
        cost_key = None
        received = False
        try:
            from google.cloud.speech_v2.types import cloud_speech

            client = await self._get_stt_client()
            config = cloud_speech.RecognitionConfig(
                explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
                    encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=16000,
                    audio_channel_count=1,
                ),
                language_codes=self._stt_languages,
                model="chirp_3",
            )
            request = cloud_speech.RecognizeRequest(
                recognizer=f"projects/{self._project_id}/locations/us/recognizers/_",
                config=config,
                content=audio_data,
            )

            if meter:
                cost_key = meter.begin("stt", "chirp_3", "cloud-speech-v2", "us")
                await publish_cost(self)
            response = await client.recognize(request=request)
            received = True
            if meter:
                seconds = billed_duration(getattr(response, "metadata", None))
                meter.update(cost_key, complete=True, usage={"billed_seconds": seconds})
                await publish_cost(self)

            transcription = ""
            for result in response.results:
                if result.alternatives:
                    transcription += result.alternatives[0].transcript

            if transcription.strip():
                logger.info(f"Parallel STT result: {transcription.strip()}")
                await self.push_frame(OutputTransportMessageUrgentFrame(message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        'type': 'transcription_replace',
                        'participant': 'User',
                        'text': transcription.strip()
                    }
                }))
            else:
                logger.warning("Parallel STT returned empty transcription")
        except asyncio.CancelledError:
            logger.debug("Parallel STT task cancelled")
        except Exception as e:
            logger.error(f"Parallel STT error: {e}")
        finally:
            if meter and cost_key and not received:
                meter.update(cost_key, issue="Background transcript request ended without billed duration")
                await publish_cost(self)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, VADUserStartedSpeakingFrame):
            logger.info("AudioAccumulator: VAD User Started (broadcasting interruption)")
            if self._stt_task and not self._stt_task.done():
                self._stt_task.cancel()
            self._audio_frames = list(self._preroll_frames)
            self._preroll_frames.clear()
            self._accumulating = True

            # Interrupt any in-flight LLM/TTS generation on the server
            await self.broadcast_interruption()
            await self.push_frame(UserStartedSpeakingFrame())

            # Flush client WebAudio playback queue and show immediate VAD listening indicator
            await self.push_frame(OutputTransportMessageUrgentFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    "type": "metrics",
                    "payload": {"type": "interruption", "count": 1},
                },
            }))
            await self.push_frame(OutputTransportMessageUrgentFrame(message={
                "label": "rtvi-ai",
                "type": "server-message",
                "data": {
                    "type": "interim_transcription",
                    "participant": "User",
                    "text": "🎤 Listening...",
                },
            }))
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            logger.info(f"AudioAccumulator: VAD User Stopped (accumulated {len(self._audio_frames)} frames)")
            self._accumulating = False
            await self.push_frame(UserStoppedSpeakingFrame())
            if self._audio_frames:
                logger.info(f"AudioAccumulator: Sending {len(self._audio_frames)} audio frames to LLM")

                audio_data = b''.join([f.audio for f in self._audio_frames])

                maybe_coro = self._context.add_audio_frames_message(
                    audio_frames=self._audio_frames,
                    text="The user is speaking. Here is the audio:"
                )
                if inspect.iscoroutine(maybe_coro):
                    await maybe_coro
                self._audio_frames = []

                # Emit User transcription frame FIRST so pipecat-session.ts creates the User bubble
                # and resets turnStarted=false before the Bot's first LLM text chunk arrives.
                await self.push_frame(OutputTransportMessageUrgentFrame(message={
                    "label": "rtvi-ai",
                    "type": "server-message",
                    "data": {
                        'type': 'transcription',
                        'participant': 'User',
                        'text': '🎤 Audio Message'
                    }
                }))

                await self.push_frame(LLMContextFrame(self._context))

                self._stt_task = asyncio.create_task(
                    self._run_parallel_stt(audio_data)
                )
        elif isinstance(frame, AudioRawFrame):
            if self._accumulating:
                self._audio_frames.append(frame)
            else:
                self._preroll_frames.append(frame)

        await self.push_frame(frame, direction)
