# Jarvis

A floating voice agent for the Mac. You talk, it looks at your screen and
works your apps: opens them, clicks, types, runs terminal commands. A glass
pill at the top of the screen shows what it hears, says and does. Risky
actions (deleting things, force pushes, "Deploy to production") stop and wait
for you to approve them.

Built on Pipecat 1.2.1 and the Gemini Live API (AI Studio key only, no
Vertex).

## How it works

```
Mac mic ──▶ Pipecat LocalAudioTransport ──▶ Gemini Live ──▶ Mac speakers
                                              │   ▲
                         tool calls (click,   │   │ screenshots pushed
                         type, open_app...)   ▼   │ as video frames
                                         mac_actions.py
                                  (screencapture, CoreGraphics clicks,
                                   System Events keystrokes)
                                              │
                               risky? ──▶ Approve / Deny in the Jarvis pill
```

| File | What it does |
|---|---|
| `jarvis_app.py` | Starts the floating window (pywebview) and the voice pipeline thread |
| `bot.py` | Pipecat pipeline, Gemini Live setup, tools, approval gate |
| `mac_actions.py` | Screenshots, clicks, typing, plus the safety rules |
| `ui/index.html` | The Dynamic-Island style UI |

## Run it on your Mac

```bash
brew install portaudio            # needed by PyAudio
cd demos/jarvis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "GEMINI_API_KEY=<your AI Studio key>" > .env
python jarvis_app.py
```

Permissions: the app that launches Jarvis (Terminal, iTerm, or your IDE)
needs **Microphone**, **Screen Recording** and **Accessibility** in
System Settings → Privacy & Security. Restart the terminal after granting.

Use headphones. Without them Jarvis hears itself and interrupts itself.

Optional `.env` settings:

| Variable | Default | Meaning |
|---|---|---|
| `JARVIS_MODEL` | `gemini-3.8-live` | Any Gemini Live model your key can use |
| `JARVIS_VOICE` | `Charon` | Gemini voice name |

## Try it

- "Open Terminal and show me what's running on port 3000."
- "Look at my screen. What's this error?"
- "Open the Cloud Run console for checkout." (then interrupt: "No wait, the payments service.")
- "Clean up disk space by deleting the database volume." → the pill turns red and asks you.

Press ⏎ in the pill to approve, Esc to deny.

## Tests

```bash
python -m unittest discover -s demos/jarvis/tests
```

The tests cover the safety rules and key handling and run on any OS.

## Known limits

- Clicks use screenshot coordinates, so small targets can be missed. Prefer
  `open_app`, `open_url` and shortcuts.
- Gemini Live caps audio+video sessions (about 2 minutes without context
  compression, about 10 minutes per connection). Long sessions need
  compression and session resumption, which are not wired in yet.
- Only the main display is supported.
