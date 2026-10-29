"""The bot's transcript streams raw LLM tokens, and Gemini 3.8 TTS markup is cut across them.

The studio appends every `transcription` message it gets, so the broadcaster must
send only settled, markup-free text, and never an empty one (that clears a partial).
The raw tokens still go to the TTS untouched: it performs the markup.
"""
import unittest
from unittest.mock import AsyncMock

from pipecat.frames.frames import (InterruptionFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame,
                                   LLMTextFrame, TranscriptionFrame)
from pipecat.processors.frame_processor import FrameDirection

DOWN = FrameDirection.DOWNSTREAM


def _broadcaster(participant="Bot"):
    from agent import TranscriptionBroadcaster

    b = TranscriptionBroadcaster(participant=participant)
    b.forwarded, b.sent = [], []

    async def push(frame, direction=DOWN):
        data = getattr(frame, "message", {}).get("data", {}) if isinstance(getattr(frame, "message", None), dict) else {}
        (b.sent if data.get("type") == "transcription" else b.forwarded).append(data or frame)

    b.push_frame = push
    # Outside a running pipeline, Pipecat's interruption handler spawns a task nobody awaits.
    b._start_interruption = AsyncMock()
    return b


def _token(text, response_id="r1"):
    frame = LLMTextFrame(text)
    frame.response_id = response_id
    return frame


class TestBotTranscript(unittest.IsolatedAsyncioTestCase):
    async def test_markup_split_across_tokens_never_reaches_the_studio(self):
        b = _broadcaster()
        tokens = ["[[amused disbelief, hi", "gh pitch, fast]] Arre bhai! <la", "ugh> Kya haal hai?"]
        await b.process_frame(LLMFullResponseStartFrame(), DOWN)
        for text in tokens:
            await b.process_frame(_token(text), DOWN)
        await b.process_frame(LLMFullResponseEndFrame(), DOWN)

        self.assertEqual("".join(m["text"] for m in b.sent), "Arre bhai! Kya haal hai?")
        self.assertTrue(all(m["text"] for m in b.sent), "an empty transcription clears the studio's partial")
        self.assertEqual({(m["participant"], m["response_id"]) for m in b.sent}, {("Bot", "r1")})
        self.assertEqual([f.text for f in b.forwarded if isinstance(f, LLMTextFrame)], tokens,
                         "the TTS still gets the raw script")

    async def test_the_last_word_is_sent_when_the_reply_ends(self):
        b = _broadcaster()
        await b.process_frame(LLMFullResponseStartFrame(), DOWN)
        await b.process_frame(_token("Theek hai"), DOWN)
        self.assertEqual([m["text"] for m in b.sent], ["Theek"])
        await b.process_frame(LLMFullResponseEndFrame(), DOWN)
        self.assertEqual([m["text"] for m in b.sent], ["Theek", " hai"])

    async def test_an_interruption_drops_what_was_not_sent(self):
        b = _broadcaster()
        await b.process_frame(LLMFullResponseStartFrame(), DOWN)
        await b.process_frame(_token("Kya haal hai"), DOWN)
        await b.process_frame(InterruptionFrame(), DOWN)
        await b.process_frame(LLMFullResponseEndFrame(), DOWN)
        self.assertEqual("".join(m["text"] for m in b.sent), "Kya haal")

    async def test_a_new_response_settles_the_previous_one_first(self):
        b = _broadcaster()
        await b.process_frame(_token("Pehla jawab", "r1"), DOWN)
        await b.process_frame(_token("Doosra jawab", "r2"), DOWN)
        self.assertEqual([(m["text"], m["response_id"]) for m in b.sent],
                         [("Pehla", "r1"), (" jawab", "r1"), ("Doosra", "r2")])

    async def test_user_transcripts_are_unchanged(self):
        b = _broadcaster("User")
        await b.process_frame(TranscriptionFrame("namaste [noise]", "user", "t"), DOWN)
        self.assertEqual([(m["participant"], m["text"]) for m in b.sent], [("User", "namaste")])


if __name__ == "__main__":
    unittest.main()
