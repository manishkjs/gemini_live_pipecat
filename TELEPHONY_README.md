# Telephony Integration Guide

This guide explains how to integrate your Gemini Live bot with telephony providers like Twilio or Telnyx.

## Overview

The telephony integration allows you to receive phone calls and have users interact with your Gemini-powered AI bot over the phone. This uses a separate endpoint optimized for telephony (8kHz audio) rather than the browser-based endpoint (24kHz audio).

## Architecture

```
Phone Call → Twilio/Telnyx → WebSocket → Your Server (/ws/phone) → Gemini Live API
```

**Key Differences from Browser Integration:**
- **Audio Sample Rate**: 8kHz (telephony standard) vs 24kHz (browser)
- **Transport**: TwilioFrameSerializer vs ProtobufFrameSerializer
- **Endpoint**: `/ws/phone` vs `/ws`
- **No WAV headers**: Telephony uses raw PCM audio

## Prerequisites

1. **Twilio Account** (or Telnyx)
   - Sign up at [twilio.com](https://www.twilio.com)
   - Get a phone number with voice capabilities
   - Note your Account SID and Auth Token

2. **ngrok** (for local development)
   - Install ngrok: `brew install ngrok` (macOS) or download from [ngrok.com](https://ngrok.com)
   - Sign up for free account to get auth token
   - Configure: `ngrok config add-authtoken YOUR_TOKEN`

3. **Google/Gemini API Key**
   - Already configured for your existing setup

## Setup Instructions

### 1. Configure Environment Variables

Add to your `server/.env` file:

```bash
# Twilio Configuration
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
```

### 2. Start Your Server

```bash
cd server
python server.py
```

The server will start on `http://localhost:7860` with:
- `/ws` - Browser clients (existing)
- `/ws/phone` - Telephony clients (new)

### 3. Expose Your Server with ngrok

In a new terminal:

```bash
ngrok http 7860
```

You'll see output like:
```
Forwarding  https://abc123.ngrok.io -> http://localhost:7860
```

Copy the `https://abc123.ngrok.io` URL.

### 4. Configure Twilio Webhook

1. Go to [Twilio Console](https://console.twilio.com)
2. Navigate to **Phone Numbers** → **Manage** → **Active numbers**
3. Click on your phone number
4. Scroll to **Voice Configuration**
5. Set **A CALL COMES IN** to:
   - **Webhook**: `https://YOUR_NGROK_URL/twiml?api_key=YOUR_GEMINI_KEY&bot_type=gemini-live`
   - **HTTP**: `GET`
6. Click **Save**

### Full Webhook URL Examples

**Basic (Gemini Live):**
```
https://abc123.ngrok.io/twiml?api_key=YOUR_KEY&bot_type=gemini-live
```

**With Custom Parameters:**
```
https://abc123.ngrok.io/twiml?api_key=YOUR_KEY&bot_type=gemini-live&model=gemini-2.5-flash-native-audio-preview-09-2025&language=en-US&voice=Puck
```

**Note:** The `/twiml` endpoint returns TwiML XML that tells Twilio to stream audio to the `/ws/phone` WebSocket endpoint.

## Testing

1. **Call your Twilio number** from your phone
2. **Check server logs** for connection status:
   ```
   Phone WebSocket connection accepted
   Telephony provider detected: twilio
   Phone call connected
   ```
3. **Start talking** - Gemini should respond with voice

## Supported Parameters

Query parameters for `/ws/phone`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `api_key` | *required* | Your Gemini API key |
| `bot_type` | `gemini-live` | Bot type: `gemini-live` or `tts-llm-stt` |
| `model` | `gemini-2.5-flash-native-audio-preview-09-2025` | Gemini model |
| `voice` | `Puck` | Gemini voice ID |
| `language` | `en-US` | Language code |
| `system_instruction` | (from SYSTEM_PROMPT) | Custom prompt |

## Troubleshooting

### Call connects but no audio

**Problem**: Gemini outputs 24kHz audio but telephony needs 8kHz.

**Solution**: The current implementation may need audio resampling. If you experience this:

1. Check if `pipecat-ai` handles resampling automatically
2. If not, you may need to add a resampler processor in the pipeline:

```python
from pipecat.processors.audio.resampler import ResampleProcessor

# In agent_phone.py, add to pipeline:
pipeline = Pipeline([
    transport.input(),
    context_aggregator.user(),
    llm,
    ResampleProcessor(input_rate=24000, output_rate=8000),  # Add this
    transport.output(),
    context_aggregator.assistant(),
])
```

### Connection fails immediately

1. **Check ngrok is running**: Visit `http://localhost:4040` to see ngrok dashboard
2. **Verify webhook URL**: Make sure it includes `/ws/phone` (not `/ws`)
3. **Check logs**: Look for error messages in your server logs
4. **Test locally**: Use a WebSocket client to test `/ws/phone` endpoint

### Bot doesn't respond

1. **Check API key**: Verify `GEMINI_API_KEY` is set correctly
2. **Check Twilio credentials**: Verify `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`
3. **Enable debug logging**: Add `logger.setLevel("DEBUG")` in `agent_phone.py`

### Audio quality issues

- Telephony uses 8kHz µ-law encoding (lower quality than browser)
- This is normal for phone calls
- Use clear speech and avoid background noise

## Production Deployment

### Cloud Run / Similar Platforms

1. **Set environment variables** in your cloud platform:
   ```bash
   TWILIO_ACCOUNT_SID=ACxxx...
   TWILIO_AUTH_TOKEN=xxx...
   ```

2. **Update Twilio webhook** to your production URL:
   ```
   https://your-app.run.app/ws/phone?api_key=YOUR_KEY&bot_type=gemini-live
   ```

3. **No ngrok needed** - use your actual domain

### Security Considerations

1. **Don't expose API key in URL** - Consider using a server-side configuration instead
2. **Enable Twilio signature validation** - Verify requests are from Twilio
3. **Use environment variables** for all secrets
4. **Rate limiting** - Implement to prevent abuse

## Alternative: Telnyx

The code auto-detects the telephony provider. To use Telnyx:

1. Set up Telnyx account and phone number
2. Configure webhook to point to `/ws/phone`
3. Add Telnyx credentials if needed (similar to Twilio)

The `parse_telephony_websocket()` function will auto-detect Telnyx.

## Code Architecture

### Files Modified/Created

1. **`server/agent_phone.py`** - New telephony handlers
   - `run_phone_bot()` - Gemini Live for telephony
   - `run_phone_bot_with_tts()` - Traditional pipeline (placeholder)

2. **`server/server.py`** - Added `/ws/phone` endpoint

3. **`server/.env.example`** - Added Twilio credentials

### Key Components

- **TwilioFrameSerializer**: Handles Twilio-specific metadata
- **8kHz audio**: Telephony standard sample rate
- **parse_telephony_websocket()**: Auto-detects provider
- **No WAV headers**: Raw PCM audio for telephony

## Next Steps

1. **Test thoroughly** with different scenarios
2. **Add error handling** for production
3. **Implement audio resampling** if needed
4. **Add call analytics** and logging
5. **Consider adding**:
   - Call recording
   - DTMF (keypad) support
   - Transfer to human agent
   - Multi-language support

## Support

- **Pipecat Docs**: https://docs.pipecat.ai
- **Twilio Docs**: https://www.twilio.com/docs/voice
- **Gemini API**: https://ai.google.dev/gemini-api/docs

## License

Same as main project.
