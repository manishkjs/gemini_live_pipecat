import os
import io
import wave
import base64
import asyncio
import logging
import typing
import queue
import time
import audioop
import traceback
import threading
import datetime

import soundfile as sf
import librosa
from google import genai
from google.genai import types
from google.oauth2 import service_account
from google.genai.types import (
    Content,
    LiveConnectConfig,
    Modality,
    Part,
)

from vocode.streaming.agent.base_agent import (
    BaseAgent,
    AgentInput,
    AgentResponseFillerAudio,
    AgentResponseAudioQueue
)
from vocode.streaming.agent.base_agent import B64EncodedChunkAgentInput
from xpertcore.models.agent import (
    GeminiLiveAgentConfig,
    GEMINI_LIVE_API_DEFAULT_LANGUAGE_CODE,
    GEMINI_LIVE_API_DEFAULT_VOICE_NAME,
    GEMINI_LIVE_API_DEFAULT_MEDIA_RESOLUTION
)
from vocode.streaming.utils.post_processing import post_processing_func, post_processing_decl
from vocode.streaming.utils.worker import InterruptibleEvent
from xpertcore.utils.constants import (
    INTERRUPT_SENTINEL,
    END_CONVERSATION_SENTINEL
)
from xpertvad import VoiceActivityDetector
import numpy as np
import noisereduce as nr
from xpertcore.models.audio_encoding import AudioEncoding


class GeminiLiveAgent(BaseAgent[GeminiLiveAgentConfig]):
    def __init__(
            self,
            agent_config: GeminiLiveAgentConfig,
            logger: typing.Optional[logging.Logger] = None,
    ):
        super().__init__(agent_config=agent_config, logger=logger)
        self.logger = logger or logging.getLogger(__name__)
        self._init_config()
        self.concurrent_awake_count = 0

    def _init_config(self):
        self._session_handle: str | None = None
        if self.agent_config.gemini_vertexai_mode:
            creds = service_account.Credentials.from_service_account_info(
                self.agent_config.gemini_vertexai_service_account_json.dict(),
                scopes=self.agent_config.gemini_vertexai_scopes
            )
            self.client = genai.Client(
                vertexai=self.agent_config.gemini_vertexai_mode,
                project=self.agent_config.gemini_vertexai_project_id,
                location=self.agent_config.gemini_vertexai_location,
                credentials=creds
            )
        else:
            self.client = genai.Client(
                api_key=self.agent_config.gemini_api_key or os.environ.get("GEMINI_API_KEY")
            )
        self.model = self.agent_config.model_name
        self.config = types.LiveConnectConfig(
            response_modalities=self.agent_config.gemini_response_modalities,
            media_resolution=GEMINI_LIVE_API_DEFAULT_MEDIA_RESOLUTION,
            system_instruction=self.agent_config.prompt_preamble,
            realtime_input_config=types.RealtimeInputConfig(
                turn_coverage="TURN_COVERAGE_UNSPECIFIED"
            ),
            session_resumption=types.SessionResumptionConfig(
                handle=self._session_handle
            )
        )
        if self.agent_config.gemini_input_audio_transcription:
            self.config.input_audio_transcription = {}
        if self.agent_config.gemini_output_audio_transcription:
            self.config.output_audio_transcription = {}
        if self.agent_config.actions:
            self.functions = self.get_functions()
        self.goodbye_function_name = "end_conversation_with_user_on_goodbye"
        self.tools = [
            {"function_declarations": [{"name": self.goodbye_function_name}, post_processing_decl]},
        ]
        if self.tools:
            self.config.tools = self.tools
        self.speech_config = types.SpeechConfig()
        if self.agent_config.gemini_language_code:
            self.speech_config.language_code = self.agent_config.gemini_language_code
        if self.agent_config.gemini_prebuilt_voice_name:
            self.speech_config.voice_config = types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=self.agent_config.gemini_prebuilt_voice_name
                )
            )
        self.config.speech_config = self.speech_config
        if self.agent_config.gemini_realtime_turn_coverage:
            self.config.realtime_input_config.turn_coverage = self.agent_config.gemini_realtime_turn_coverage
        if self.agent_config.gemini_context_trigger_tokens and self.agent_config.gemini_sliding_window_target_tokens:
            self.config.context_window_compression = types.ContextWindowCompressionConfig(
                trigger_tokens=self.agent_config.gemini_context_trigger_tokens,
                sliding_window=types.SlidingWindow(
                    target_tokens=self.agent_config.gemini_sliding_window_target_tokens
                ),
            )
        else:
            self.config.context_window_compression = types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            )
        if not self.agent_config.gemini_auto_vad_enabled:
            self.config.realtime_input_config.automatic_activity_detection = types.AutomaticActivityDetection(
                disabled=True
            )
        else:
            self.config.realtime_input_config.automatic_activity_detection = types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=self.agent_config.gemini_vad_start_of_speech_sensitivity,
                end_of_speech_sensitivity=self.agent_config.gemini_vad_end_of_speech_sensitivity,
                prefix_padding_ms=self.agent_config.gemini_vad_prefix_padding_ms,
                silence_duration_ms=self.agent_config.gemini_vad_silence_duration_ms
            )
        if self.agent_config.gemini_proactive_audio:
            self.config.proactivity = types.ProactivityConfig(
                proactive_audio=True
            )
        
        self.perform_denoising = False
        if self.agent_config.gemini_denoise_audio:
            self.perform_denoising = True
        
        self._session_ctx = None
        self.session = None
        self.receive_task = None
        # FIXED: Added VAD event monitoring task
        self.vad_events_task = None
        self.call_duration_limiter_task = None
        # FIXED: Use asyncio.Event instead of boolean
        self._ended = asyncio.Event()
        self.audio_response_queue: asyncio.Queue[bytes | None] = None
        self._out_pcm_buffer: bytearray = bytearray()
        self.output_audio_sample_rate = 24000
        self.telephony_output_chunk_size_seconds = 0.04
        self._out_chunk_size: int = int(
            self.output_audio_sample_rate * 2 * self.telephony_output_chunk_size_seconds
        )
        self._audio_input_chunk_idx = 0
        self._sent_initial_message = False
        self._is_next_audio_gen_awake = False
        self.is_muted = False
        self.concurrent_awake_count = 0

        self.xpertvad = None
        self.xpertvad_thread = None
        self.xpertvad_event_type = "voice_activity_ended"
        self.xpertvad_endpointing_ms=self.agent_config.xpertvad_endpointing_default_ms
        self.should_amplify_audio = False
        self.xpertvad_end_default_last_time = datetime.datetime.now(datetime.UTC)

        if self.agent_config.xpertvad_enabled:
            self.vad = VoiceActivityDetector(
                threshold=self.agent_config.xpertvad_probability_threshold,
                endpointing_ms=self.xpertvad_endpointing_ms,
                padding_ms=self.agent_config.xpertvad_padding_ms,
                framerate=16000,
                differential_mode=self.agent_config.xpertvad_differential_mode,
            )
            self.vad_processing_queue = queue.Queue()
            self.vad_event_queue = queue.Queue()
            self.vad_audio_queue = queue.Queue()
            self.vad_thread = threading.Thread(target=self.process_vad, daemon=True)
            self.vad_thread.start()
            if self.vad_thread.is_alive():
                self.logger.info("VAD thread started successfully")
            else:
                self.logger.error("Failed to start VAD thread!")

    async def _init_session(self):
        self.logger.debug("Creating a new session for gemini live api ...")
        self._session_ctx = self.client.aio.live.connect(
            model=self.model, config=self.config
        )
        self.session = await self._session_ctx.__aenter__()
        if not self.receive_task:
            self.receive_task = asyncio.create_task(self._receive_responses())
        # FIXED: Start VAD event monitoring task
        if not self.vad_events_task and self.agent_config.xpertvad_enabled:
            self.vad_events_task = asyncio.create_task(self._process_vad_events())
        if not self.call_duration_limiter_task:
            self.call_duration_limiter_task = asyncio.create_task(self._call_duration_limiter())
        # FIXED: Clear the event
        self._ended.clear()
        self.audio_response_queue = asyncio.Queue()
        self.gemini_events_queue = asyncio.Queue()
        self._out_pcm_buffer.clear()
        self.concurrent_awake_count = 0
        self.receive_response_error_count = 0
    
    async def _call_duration_limiter(self):
        await asyncio.sleep(self.agent_config.gemini_call_duration_hard_limit_seconds)
        self.logger.debug("Call duration limiter triggered, ending call soon...")
        self.handle_go_away_event("10s")

    # FIXED: New task to monitor VAD events independently
    async def _process_vad_events(self):
        """Continuously monitor VAD event queue and send to Gemini"""
        while not self._ended.is_set():
            try:
                try:
                    vad_event = self.vad_event_queue.get_nowait()
                    if vad_event == "voice_activity_detected":
                        self.vad_event_type = "voice_activity_detected"
                        self.speech_reset_on_vad_end_state = True
                        await self.session.send_realtime_input(
                            activity_start=types.ActivityStart()
                        )
                    elif vad_event == "voice_activity_ended":
                        self.vad_event_type = "voice_activity_ended"
                        await self.session.send_realtime_input(
                            activity_end=types.ActivityEnd()
                        )
                except queue.Empty:
                    pass
                await asyncio.sleep(0.01)
            except Exception as e:
                self.logger.error(f"Error in VAD event processing: {e}", exc_info=True)

    async def _receive_responses(self):
        """Collect raw PCM frames from Gemini, buffer them, and emit fixed chunks downstream."""
        response_queue_sent = False
        should_end_conversation = False
        # FIXED: Track if turn was interrupted
        turn_was_interrupted = False
        
        while not self._ended.is_set():
            try:
                async for response in self.session.receive():
                    if not response:
                        self.logger.critical("Received None from gemini, continuing ...")
                        continue
                    if response.go_away:
                        self.time_left = response.go_away.time_left
                        self.logger.warning(f"GO_AWAY: should end the call in {self.time_left}")
                        if self.time_left:
                            self.handle_go_away_event(self.time_left)
                    if response.session_resumption_update:
                        self.logger.debug("Session Resumption Update received from Gemini ... ")
                        update = response.session_resumption_update
                        if update.resumable and update.new_handle:
                            if self._session_handle != update.new_handle:
                                self._session_handle = update.new_handle
                                self.logger.warning(f"Saving new session handle: {self._session_handle}")

                    if hasattr(response, 'session_handle') and response.session_handle:
                        new_handle = response.session_handle
                        if new_handle != self._session_handle:
                            self._session_handle = new_handle
                            self.logger.debug(f"Response has a new session handle: {self._session_handle}")

                    if response.server_content:
                        if response.server_content.model_turn:
                            pass
                        if response.server_content.input_transcription:
                            self.logger.debug(
                                f"Gemini received Audio Transcript: {response.server_content.input_transcription.text}")
                        if response.server_content.output_transcription:
                            self.logger.debug(
                                f"Gemini sent Agent Transcript: {response.server_content.output_transcription.text}")

                        # FIXED: on interruption, clear buffered audio and set flag
                        if response.server_content.interrupted:
                            self.logger.debug(f"Interruption received from Gemini: {response}")
                            self._out_pcm_buffer.clear()
                            should_end_conversation = False
                            # FIXED: Set interruption flag
                            turn_was_interrupted = True
                            self.logger.debug("should_end_conversation CALL END CANCELLED due to user interruption ...")
                            while not self.audio_response_queue.empty():
                                try:
                                    self.audio_response_queue.get_nowait()
                                    self.audio_response_queue.task_done()
                                except asyncio.QueueEmpty:
                                    break
                            interrupt_sentinel = INTERRUPT_SENTINEL()
                            self.audio_response_queue.put_nowait(interrupt_sentinel)
                            # FIXED: Reset response_queue_sent
                            response_queue_sent = False
                    else:
                        self.logger.critical("Server content was None from gemini, passing ...")

                    if response.tool_call:
                        function_responses = []
                        self.logger.debug(f"Function call received from Gemini: {response}")
                        for fc in response.tool_call.function_calls:
                            if fc.name == self.goodbye_function_name:
                                self.logger.debug(
                                    "Goodbye function call received from gemini, setting should_end_conversation to True.")
                                should_end_conversation = True
                                function_response = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response={"result": "ok"}
                                )
                                function_responses.append(function_response)
                            
                            if fc.name == "post_processing_func":
                                args = getattr(fc, "args", {}) or {}
                                disposition1 = args.get("disposition1")

                                result = await post_processing_func(disposition1)
                                self.logger.debug(f"ASS OBJ BEFORE: {self.conversation_state_manager._conversation.conversation_history.associate_obj}")
                                conversation_obj = self.conversation_state_manager._conversation
                                associate_obj = conversation_obj.call_config.conversation_context.get('associateObj', {})
                                associate_obj["contacted"] = result.get("contacted", "Contacted")
                                associate_obj["disposition1"] = result.get("disposition1", "")
                                conversation_obj.call_config.conversation_context['associateObj'] = associate_obj
                                conversation_obj.conversation_history.associate_obj = associate_obj
                                self.logger.debug(f"ASS OBJ AFTER: {self.conversation_state_manager._conversation.conversation_history.associate_obj}")

                                self.logger.debug(f"POST PROCESSING RESULT: {result}")
                                function_response = types.FunctionResponse(
                                    id=fc.id,
                                    name=fc.name,
                                    response=result 
                                )
                                allowed = {
                                    "Third Party Contact - information given",
                                    "Claim Paid", "PTP", "RTP", "Call Back", "Dispute", "User disconnected"
                                }
                                if disposition1 not in allowed:
                                    logging.warning(f"Invalid tool args from model: {args}")

                                function_responses.append(function_response)

                        await self.session.send_tool_response(function_responses=function_responses)
                    
                    # FIXED: accumulate raw PCM, but skip stale audio if interrupted
                    if response.data:
                        # FIXED: Skip stale audio if turn was interrupted
                        if turn_was_interrupted:
                            self.logger.debug("Skipping stale audio chunk from interrupted turn")
                            continue
                        
                        self.logger.debug(f"One chunk of audio data received from gemini with size {len(response.data)} ....")
                        try:
                            if not response_queue_sent:
                                self.produce_interruptible_agent_response_event_nonblocking(
                                    AgentResponseAudioQueue(
                                        audio_queue=self.audio_response_queue,
                                        events_queue=self.gemini_events_queue,
                                        is_awake=self._is_next_audio_gen_awake
                                    ),
                                    is_interruptible=self.agent_config.allow_agent_to_be_cut_off,
                                )
                                response_queue_sent = True
                                self._is_next_audio_gen_awake = False
                                self.logger.debug("Started receiving a new response from Gemini ....")
                            self._out_pcm_buffer.extend(response.data)
                            while len(self._out_pcm_buffer) >= self._out_chunk_size:
                                frame = bytes(self._out_pcm_buffer[:self._out_chunk_size])
                                del self._out_pcm_buffer[:self._out_chunk_size]
                                await self.audio_response_queue.put(frame)
                        except Exception as e:
                            self.logger.critical(f"Error emitted from produce agent response: {e}", exc_info=True)
                
                # FIXED: Only flush buffer if turn was NOT interrupted
                if self._out_pcm_buffer and not turn_was_interrupted:
                    await self.audio_response_queue.put(bytes(self._out_pcm_buffer))
                    self._out_pcm_buffer.clear()
                elif turn_was_interrupted:
                    self._out_pcm_buffer.clear()
                    
                self.logger.debug("One gemini response loop finished ...")
                
                if should_end_conversation:
                    self.logger.debug("should_end_conversation is set to True, ending the call ...")
                    end_conversation_sentinel = END_CONVERSATION_SENTINEL()
                    await self.audio_response_queue.put(end_conversation_sentinel)

                # FIXED: Only send None if turn was NOT interrupted
                if response_queue_sent and not turn_was_interrupted:
                    await self.audio_response_queue.put(None)
                
                # FIXED: Reset all flags for next turn
                response_queue_sent = False
                turn_was_interrupted = False
                self.concurrent_awake_count = 0
                
                self.receive_response_error_count = 0
            except Exception as e:
                self.logger.critical(f"Raised error in _receive_responses loop: {e}", exc_info=True)
                self.receive_response_error_count += 1
                # FIXED: Reduced from 100 to 10
                if self.receive_response_error_count >= 10:
                    self.logger.critical("_receive_responses errored out 10 times, breaking loop ...")
                    break
    
    def get_functions(self):
        assert self.agent_config.actions
        if not self.action_factory:
            return None
        functions = [
            self.action_factory.create_action(action_config, self.logger).get_gemini_live_function()
            for action_config in self.agent_config.actions
        ]
        return functions

    async def process(self, item: InterruptibleEvent[AgentInput]):
        try:
            if self.is_muted:
                self.logger.debug("Agent is muted, skipping processing")
                return
            agent_input = item.payload
            if not isinstance(agent_input, B64EncodedChunkAgentInput):
                raise ValueError("GeminiLiveAgent only accepts B64EncodedChunkAgentInput")
            if self.session is None:
                await self._init_session()
            if not self._sent_initial_message:
                await self.session.send_client_content(
                    turns=Content(role="user", parts=[Part(text="Hello, who is this?")])
                )
                self._sent_initial_message = True
            b64_audio = agent_input.b64_chunk.chunk
            audio_bytes = base64.b64decode(b64_audio)
            # FIXED: perform noise reduction asynchronously
            if self.perform_denoising:
                audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
                reduced_noise = await asyncio.to_thread(nr.reduce_noise, y=audio_np, sr=16000)
                audio_bytes = reduced_noise.astype(np.int16).tobytes()
            await self.session.send_realtime_input(
                audio=types.Blob(data=audio_bytes, mime_type="audio/pcm;rate=16000")
            )
            if self.agent_config.xpertvad_enabled:
                self.vad_processing_queue.put(audio_bytes)
            self._audio_input_chunk_idx += 1
            if self._audio_input_chunk_idx % 100 == 0:
                self.logger.debug(f"Audio input chunk {self._audio_input_chunk_idx} sent to gemini ...")
            # FIXED: Removed VAD event processing from here - it's now in _process_vad_events task
        except Exception as e:
            self.logger.critical(f"Raised error in gemini process loop: {e}", exc_info=True)
    
    def create_awake_response(self, awake_messages: list = [], use_llm: bool = False):
        try:
            self.logger.debug("Create awake response called in Gemini Live Agent ...")
            user_awake_prompt_formatted = self.agent_config.user_awake_prompt.format(
                concurrent_awake_count=self.concurrent_awake_count,
                max_user_awake_count=self.agent_config.max_user_awake_count
            )
            if self.session:
                asyncio.run_coroutine_threadsafe(self.session.send_client_content(
                    turns=Content(
                        role="user",
                        parts=[Part(text=user_awake_prompt_formatted)]
                    )
                ), asyncio.get_event_loop())
            self.concurrent_awake_count += 1
            self._is_next_audio_gen_awake = True
            return ""
        except Exception as e:
            self.logger.critical(f"Raised error in create_awake_response loop: {e}", exc_info=True)

    def handle_go_away_event(self, time_left="30s"):
        try:
            self.logger.debug("Handle go away event called in Gemini Live Agent ...")
            agent_go_away_prompt = "This message is from the call Server: This call will soon end, due to server going away. Try to end this call ASAP. Time left is: {time_left}. Make sure to say the goodbye message, and call the end call tool."
            agent_go_away_prompt_formatted = agent_go_away_prompt.format(time_left=time_left)
            if self.session:
                asyncio.run_coroutine_threadsafe(self.session.send_client_content(
                    turns=Content(
                        role="user",
                        parts=[Part(text=agent_go_away_prompt_formatted)]
                    )
                ), asyncio.get_event_loop())
            self._is_next_audio_gen_awake = True
            return ""
        except Exception as e:
            self.logger.critical(f"Raised error in handle_go_away_event loop: {e}", exc_info=True)
    
    def amplify_pcm16(self, audio_bytes, gain=2.0):
        if len(audio_bytes) % 2 != 0:
            self.logger.debug("Amplification Warning: Audio buffer has odd length, trimming last byte.")
            audio_bytes = audio_bytes[:-1]
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
        amplified_audio = np.clip(audio_array * gain, -32768, 32767).astype(np.int16)
        return amplified_audio.tobytes()

    def amplify_mulaw(self, audio_bytes, gain=2.0):
        pcm_audio = audioop.ulaw2lin(audio_bytes, 2)
        amplified_pcm = self.amplify_pcm16(pcm_audio, gain)
        amplified_mulaw = audioop.lin2ulaw(amplified_pcm, 2)
        return amplified_mulaw
    
    def process_vad(self):
        """Background thread that processes VAD asynchronously."""
        silence_byte: bytes = b'\x00'
        min_append_seconds: int = 0.5
        max_append_seconds: int = 4
        amplify_audio = self.amplify_pcm16
        bytes_per_sec: int = 16000
        activity_detected_at = time.time()
        activity_ended_at = time.time()
        # FIXED: Use Event.is_set() instead of boolean
        while not self._ended.is_set():
            try:
                audio_chunk = self.vad_processing_queue.get(timeout=0.02)
                if audio_chunk:
                    vad_results = self.vad.process_stream(audio_chunk)

                    for event in vad_results:
                        if self.agent_config.use_xpertvad_audio_only and event[
                            "type"
                        ] in (
                            "differential_audio_chunk",
                            "final_audio_chunk",
                        ):
                            content = event.get("content")
                            if content and isinstance(content, bytearray):
                                content = bytes(content)
                                if self.should_amplify_audio:
                                    try:
                                        content = amplify_audio(content)
                                    except Exception as e:
                                        self.logger.debug(f"Error occured in amplification: {str(e)}")
                                self.vad_audio_queue.put(content)
                        elif event.get("type") in (
                            "voice_activity_detected",
                            "voice_activity_ended",
                        ):
                            self.logger.debug(f"VAD detected an event: {event['type']}")
                            if event.get("type") == "voice_activity_detected":
                                activity_detected_at = time.time()
                            if event.get("type") == "voice_activity_ended":
                                activity_ended_at = time.time()
                                vad_activity_diff = max(activity_ended_at - activity_detected_at, 0)
                                voice_activity_diff = max(vad_activity_diff - (self.xpertvad_endpointing_ms / 1000), 0.01)
                                self.logger.info(f"VAD streamed differential seconds : {vad_activity_diff}")
                                self.logger.info(f"Voice activity sustained for sec  : {voice_activity_diff}")
                                if self.agent_config.use_xpertvad_audio_only:
                                    append_reduction = min(voice_activity_diff/0.75, max_append_seconds)
                                    append_seconds = max(min_append_seconds, max_append_seconds - append_reduction) if voice_activity_diff <= 2 else min_append_seconds
                                    appended_audio = bytes(silence_byte * int(bytes_per_sec * append_seconds))
                                    self.vad_audio_queue.put(appended_audio)
                                    self.logger.info(f"Appended silence bytes for sec    : {append_seconds}")
                            self.vad_event_queue.put(event["type"])
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"Error in VAD processing: {e}", exc_info=True)

    async def _aterminate(self):
        if self.audio_response_queue:
            self.audio_response_queue.put_nowait(None)
        if getattr(self, "receive_task", None):
            self.receive_task.cancel()
            try:
                await self.receive_task
            except asyncio.CancelledError:
                self.logger.debug("self.receive_task already cancelled, passing ...")
                pass
        # FIXED: Cancel VAD events task
        if getattr(self, "vad_events_task", None):
            self.vad_events_task.cancel()
            try:
                await self.vad_events_task
            except asyncio.CancelledError:
                self.logger.debug("self.vad_events_task already cancelled, passing ...")
                pass
        if getattr(self, "call_duration_limiter_task", None):
            self.call_duration_limiter_task.cancel()
            try:
                await self.call_duration_limiter_task
            except asyncio.CancelledError:
                self.logger.debug("self.call_duration_limiter_task already cancelled, passing ...")
                pass
        if getattr(self, "_session_ctx", None):
            await self._session_ctx.__aexit__(None, None, None)
        self.session = None
        self._session_ctx = None
        self.receive_task = None
        self.vad_events_task = None
        self.audio_response_queue = None
        # FIXED: End vad thread asynchronously
        if self.vad_thread:
            if self.vad_thread.is_alive():
                await asyncio.to_thread(self.vad_thread.join, timeout=2.0)
        if self.vad:
            if hasattr(self.vad, "vad_model"):
                del self.vad.vad_model
                self.vad.vad_model = None
            del self.vad
            self.vad = None

    async def _reconnect(self):
        """
        Gracefully close the current connection and resume the same session.
        DOES NOT WORK. DO NOT USE THIS METHOD.
        """
        try:
            self.is_muted = True
            await self._aterminate()
            await self._init_session()
            self.is_muted = False
        except Exception as e:
            self.logger.critical(f"EXCEPTION HAPPENED IN RECONNECT: {e}", exc_info=True)

    def terminate(self):
        asyncio.run_coroutine_threadsafe(
            self._aterminate(),
            asyncio.get_event_loop()
        )
        super().terminate()
