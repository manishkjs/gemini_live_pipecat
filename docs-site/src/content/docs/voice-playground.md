---
title: Interactive Voice Studio
description: Audition Gemini Live HD voices, test VAD sensitivity, and inspect real-time token telemetry in the browser.
---

<aside class="one-minute" aria-label="In one minute">
  <div class="one-minute-head">
    <span class="badge badge-blue">In one minute</span>
    <span class="one-minute-audience">For product managers and solution architects</span>
  </div>
  <dl class="one-minute-grid">
    <div class="one-minute-cell"><dt>What this page covers</dt><dd>A browser sandbox where you talk to a live agent, try the prebuilt voices, change the instructions, and watch latency and token counts per turn.</dd></div>
    <div class="one-minute-cell"><dt>Why it matters</dt><dd>Voice choice and turn-taking settings are product decisions. Hearing them is faster than reading about them.</dd></div>
    <div class="one-minute-cell one-minute-number"><dt>The number to remember</dt><dd>Five flagship HD voices (Puck, Charon, Kore, Fenrir, Aoede) plus 25 or more regional ones. Playback should stop within 100 ms when you interrupt.</dd></div>
    <div class="one-minute-cell"><dt>The decision you own</dt><dd>Which voice and which end-of-speech sensitivity your product ships with.</dd></div>
  </dl>
</aside>

The **Gemini Voice Studio** lets you audition prebuilt HD voices (`Puck`, `Charon`, `Kore`, `Fenrir`, `Aoede`, and 25+ regional voices), experiment with system instructions, and watch per-turn latency and token telemetry in real time.

<div class="hero-card" style="display: flex; flex-direction: column; gap: 1rem; margin: 1.5rem 0;">
  <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 1rem;">
    <div>
      <span class="badge badge-blue">Interactive Sandbox</span>
      <h3 style="margin: 0.5rem 0 0.25rem 0;">Launch Gemini Voice Studio</h3>
      <p style="margin: 0; font-size: 0.95rem; opacity: 0.85;">
        Test live microphone streaming, barge-in interruption, custom system prompts, and voice selection.
      </p>
    </div>
    <a href="https://aistudio.google.com/live" target="_blank" rel="noopener noreferrer" style="display: inline-flex; align-items: center; gap: 0.5rem; background: var(--sl-color-accent); color: #ffffff; font-weight: 600; padding: 0.65rem 1.25rem; border-radius: 8px; text-decoration: none;">
      Open in Google AI Studio ↗
    </a>
  </div>
</div>

---

## 1. Choosing the right prebuilt HD voice

Configure the model's voice in `speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName`:

| Voice Name | Vocal Profile & Cadence | Recommended Use Cases |
| :--- | :--- | :--- |
| **`Aoede`** | Warm, composed, articulate mid-register | Enterprise concierge, healthcare intake, wealth management, executive assistants. |
| **`Kore`** | Crisp, upbeat, clear diction | Retail customer support, order tracking, onboarding walkthroughs, travel booking. |
| **`Puck`** | Energetic, conversational, fast-paced | Consumer companions, interactive gaming, brainstorming, casual tutoring. |
| **`Charon`** | Calm, measured, authoritative low-register | Technical troubleshooting, IT helpdesk, financial disclosures, step-by-step guidance. |
| **`Fenrir`** | Deep, resonant, steady | Storytelling, coaching, hardware/automotive voice interfaces. |

```python
from google.genai import types

config = types.LiveConnectConfig(
    response_modalities=[types.Modality.AUDIO],
    speech_config=types.SpeechConfig(
        voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                voice_name="Aoede"
            )
        )
    ),
)
```

---

## 2. Running a local reference Voice Studio

To run the reference Gemini Live Voice Studio locally with live token accounting and tool-call inspection:

```bash
git clone https://github.com/manishkjs/gemini-live.git
cd gemini-live

# Configure your project or API key
export GOOGLE_CLOUD_PROJECT="your-project-id"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GOOGLE_GENAI_USE_VERTEXAI="TRUE"

# Start the backend and web UI
uv run python server.py
```

### What to test in your first 2 minutes
1. **Barge-in latency**: Interrupt the model mid-sentence with *"Hold on, change the date to Friday"* and verify that playback stops within `<100ms`.
2. **VAD sensitivity**: Pause for half a second mid-thought (for example, reciting a 10-digit phone number in groups of three) and tune `silenceDurationMs` until the model waits naturally for the full number.
3. **Per-turn `usageMetadata` inspector**: Watch the `Input AUDIO` token counter across Turns 1 to 10 with `contextWindowCompression` toggled on vs. off.
