# Jarvis

A floating voice agent for the Mac. You talk, it looks at your screen and
works your apps: Chrome, Google Meet, `draw.io`, Terminal, or mobile apps
(Android emulator/device via `adb` or iPhone Mirroring). A glass pill at the
top of the screen shows what it hears, says and does. Risky actions (deleting
things, force pushes, "Deploy to production", "Pay" / "Place order") stop
and wait for you to approve them.

Built on Pipecat 1.16+ and the Gemini Live API (AI Studio key only, no
Vertex). If you installed an older venv, run `pip install -U -r requirements.txt`.

## How it works

```
Mac mic / BlackHole ──▶ Pipecat LocalAudioTransport ──▶ Gemini Live ──▶ Speakers / BlackHole
                                                          │   ▲
                              click, type, meet_join,     │   │ screenshots pushed
                              open_drawio, mobile_*       ▼   │ as video frames
                                                     mac_actions.py
                                       (screencapture, Quartz CGEvent, System Events, adb)
                                                          │
                                          risky? ──▶ Approve / Deny in the Jarvis pill
```

| File | What it does |
|---|---|
| `jarvis_app.py` | Starts the floating window (`pywebview`), first-run setup flow, and voice pipeline thread |
| `jarvis_config.py` | API key lookup (`env` → `.env` → `~/.jarvis/config.json`), `0600` storage, and key validation |
| `mac_permissions.py` | Non-prompting macOS permission checks and System Settings Privacy pane links |
| `build_app.py` | Builds a native macOS `Jarvis.app` bundle in `/Applications` (with icon & permissions metadata) |
| `bot.py` | Pipecat pipeline, Gemini Live setup, desktop/Meet/draw.io/mobile tools, approval gate |
| `mac_actions.py` | Screenshots, clicks, typing, isolated Chrome profile, ADB mobile helpers, safety rules |
| `ui/index.html` | The Dynamic-Island style pill and first-run setup UI |

## Run it on your Mac

```bash
brew install portaudio            # needed by PyAudio
cd demos/jarvis
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python jarvis_app.py
```

### First run

When Jarvis starts without an API key configured, it opens a setup card in the
same floating window instead of the collapsed pill:

1. **Gemini API Key** — Click **Get a key ↗** to open Google AI Studio in your
   default browser, paste your key into the masked field (with **Show / Hide**),
   and click **Verify & Save**. Jarvis checks the key against the Gemini API
   before saving it to `~/.jarvis/config.json` (mode `0600`). Lookup order is
   environment variable (`GEMINI_API_KEY` / `GOOGLE_API_KEY`) → `demos/jarvis/.env`
   → `~/.jarvis/config.json`, so existing `.env` setups keep working unchanged.
2. **macOS Permissions** — Shows the status of **Microphone**, **Screen Recording**,
   **Accessibility**, and **Automation** (plainly noting when macOS cannot report
   status beforehand), with **Open Settings** shortcuts to each Privacy pane and
   a **Re-check** button.
3. **Start Jarvis** — Shrinks the window into the floating pill and starts the
   voice pipeline in the same process with no relaunch. Click the gear (**⚙**)
   button on the pill anytime to replace your key, and if Gemini rejects a saved
   key while connecting, Jarvis reopens setup with the reason.

### Install as a macOS Desktop App (`Jarvis.app`)

```bash
python build_app.py               # installs /Applications/Jarvis.app
open /Applications/Jarvis.app     # or launch "Jarvis" from Spotlight / Dock
```

Logs for the desktop app are written to `~/Library/Logs/Jarvis/jarvis.log`.

Permissions: the app that launches Jarvis (Terminal, iTerm, or your IDE)
needs **Microphone**, **Screen Recording** and **Accessibility** in
System Settings → Privacy & Security. Restart the terminal after granting.

Use headphones. Without them Jarvis hears itself and interrupts itself.

Optional `.env` settings:

| Variable | Default | Meaning |
|---|---|---|
| `JARVIS_MODEL` | `gemini-3.8-live` | Any Gemini Live model your key can use |
| `JARVIS_VOICE` | `Charon` | Gemini voice name |
| `JARVIS_INPUT_DEVICE` | System default | Audio input index or name substring (e.g. `BlackHole 2ch`) |
| `JARVIS_OUTPUT_DEVICE` | System default | Audio output index or name substring (e.g. `BlackHole 16ch`) |
| `JARVIS_ECHO_GUARD` | `auto` | Mutes mic during speech on open speakers (`auto`, `on`, `off`) |
| `JARVIS_CHROME_PROFILE` | `~/.jarvis-chrome-profile` | Isolated Chrome profile for Jarvis as a separate Meet user |

List audio device indexes on your Mac:

```bash
python jarvis_app.py --list-audio
```

## Demo Workflows

### 1. Join Google Meet as a separate "Jarvis" user
1. To route audio cleanly into a separate Chrome Meet window without echoing,
   install two virtual audio buses (e.g., `brew install blackhole-2ch blackhole-16ch`)
   and set `JARVIS_INPUT_DEVICE` / `JARVIS_OUTPUT_DEVICE` in `.env` (or use
   room audio for a quick local test).
2. Say: *"Jarvis, join Meet `abc-defg-hij` in your own Chrome profile."*
3. Jarvis launches an isolated Chrome profile (`~/.jarvis-chrome-profile`), where
   it can join as a guest (`"Jarvis"`) or a dedicated demo Google account.

### 2. Build an architecture diagram in `draw.io`
Say: *"Jarvis, open draw.io and draw a Cloud Run + Spanner + Gemini Live architecture."*
Jarvis opens `https://app.diagrams.net/?splash=0` with Mermaid syntax on your
clipboard and inserts it via **Arrange → Insert → Advanced → Mermaid**.

### 3. Drive Swiggy mobile app
- **Android Emulator / Phone (`adb`)**: Connect your emulator/phone (`adb devices`)
  and say *"Jarvis, open Swiggy and search for biryani."* Tapping **Pay** or
  **Place order** triggers the red Approval Pill.
- **iPhone Mirroring / Mobile Web**: Open iPhone Mirroring (or `swiggy.com` in
  Chrome) and Jarvis drives it with desktop `click`, `type_text`, and `scroll`.

## Tests

```bash
python -m unittest discover -s demos/jarvis/tests
```

The tests cover the safety rules, key handling, Meet/draw.io/audio/ADB helpers
and run on any OS.

## Known limits

- Clicks use screenshot coordinates, so small targets can be missed. Prefer
  `open_app`, `open_url`, `meet_join`, `meet_action`, `open_drawio` and shortcuts.
- Context window compression is on, and Pipecat reconnects with session
  resumption handles, so long screen-sharing sessions keep going.
- Multiple displays work: `look_at_screen(display=2)` first, then click or
  scroll with `display=2`. Clicks always use that display's own screenshot.
