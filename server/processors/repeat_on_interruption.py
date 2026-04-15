from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame,
    TextFrame,
    InterruptionFrame,
    StartInterruptionFrame,
    LLMMessagesAppendFrame,
    LLMFullResponseEndFrame,
    TranscriptionFrame,
)


class RepeatOnInterruptionProcessor(FrameProcessor):
    """Handles interruptions with two-tier logic for Gemini Live native audio.

    When the bot is interrupted:
    - Short filler (≤2 words like "uh huh", "okay", "acha"):
      Automatically tells the LLM to resume what it was saying.
    - Genuine interruption (3+ words): Injects a system note so
      the LLM can repeat if the user explicitly asks later.

    IMPORTANT: Interruption detection runs BEFORE super().process_frame()
    because the base class cancels the processor's task queue on
    InterruptionFrame, which would prevent our logic from executing.

    Pipeline placement: between LLM and TTS/transport output.
    """

    def __init__(self, *, filler_max_words: int = 2):
        super().__init__()
        self._was_interrupted = False
        self._filler_max_words = filler_max_words
        self._current_response = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Detect interruption BEFORE super() cancels the task queue
        if isinstance(frame, (InterruptionFrame, StartInterruptionFrame)):
            if self._current_response:
                self._was_interrupted = True
                logger.info(
                    f"[RepeatOnInterruption] Interruption detected. "
                    f"Text so far: '{self._current_response[:120]}'"
                )
            else:
                self._was_interrupted = True
                logger.info(
                    "[RepeatOnInterruption] Interruption detected "
                    "(no text accumulated — native audio mode)."
                )

        # Detect transcription BEFORE super() to ensure we process it
        if isinstance(frame, TranscriptionFrame) and self._was_interrupted:
            user_text = frame.text.strip()
            word_count = len(user_text.split())
            logger.info(
                f"[RepeatOnInterruption] Post-interruption transcription: "
                f"'{user_text}' ({word_count} words)"
            )

            if word_count <= self._filler_max_words:
                # Short filler — auto-repeat
                logger.info(
                    f"[RepeatOnInterruption] Filler detected ('{user_text}'). "
                    f"Telling LLM to resume."
                )
                resume_msg = {
                    "role": "system",
                    "content": (
                        f"The user just said '{user_text}' which is a "
                        f"short filler/acknowledgment. They did NOT ask "
                        f"a new question. Please continue and resume exactly "
                        f"what you were saying before the interruption."
                    ),
                }
                await self.push_frame(
                    LLMMessagesAppendFrame([resume_msg], run_llm=True),
                    FrameDirection.UPSTREAM,
                )
            else:
                # Genuine interruption — save context note
                logger.info(
                    f"[RepeatOnInterruption] Genuine interruption "
                    f"('{user_text}'). Adding context note."
                )
                context_msg = {
                    "role": "system",
                    "content": (
                        f"The user interrupted you. If they ask you "
                        f"to repeat or continue what you were saying, "
                        f"please do so."
                    ),
                }
                await self.push_frame(
                    LLMMessagesAppendFrame([context_msg]),
                    FrameDirection.UPSTREAM,
                )

            # Reset state
            self._was_interrupted = False
            self._current_response = ""

        # Accumulate text when available (works in text/TTS mode)
        if isinstance(frame, TextFrame) and direction == FrameDirection.DOWNSTREAM:
            self._current_response += frame.text

        if isinstance(frame, LLMFullResponseEndFrame) and not self._was_interrupted:
            self._current_response = ""

        # Now let the base class handle lifecycle (StartFrame, InterruptionFrame, etc.)
        await super().process_frame(frame, direction)

        # Always pass the frame through
        await self.push_frame(frame, direction)
