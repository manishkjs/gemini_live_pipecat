# Project: Google Voice Models Sales Enablement Deck & Field Playbook

## Architecture & Executive Vision
A high-impact, 14-slide internal enablement presentation deck and field playbook on Google Voice Models in **both Google Slides and Open Design (interactive HTML)**, tailored specifically for Google's internal sales audience (Customer Engineers, Field Sales Representatives, and AI Specialists).

### Deliverables
1. **Interactive Open Design Presentation Deck (`presentation/google_voice_models_sales_deck.html`)**:
   - Standalone, zero-dependency executive HTML5/CSS3/JS presentation.
   - Executive Google AI Dark Palette (`#0B0F19` slate, `#00E5FF` cyan, `#4285F4` blue, `#34A853` green, `#FBBC04` amber, `#EA4335` red, glassmorphism cards).
   - Navigation: Keyboard (`←`, `→`, `Space`, `P`, `F`, `G`), swipe gestures, top progress bar, and 14-tile thumbnail grid.
   - CE/FSR Live Teleprompter Drawer (`[P]` hotkey) with 4 structured tabs per slide (Pitch Script, Technical Proof, Objections, Discovery).
   - Interactive Visuals: Chart.js / SVG charts for Market Growth ($5.9B India), ROI Calculator (₹180 → ₹10), Latency Waterfall (2.85s breakdown), and TCO Battlecards (10.6x cost advantage).
   - Interactive 3-way Decision Tree, 4-Quadrant Logo Showcase, and filterable Battlecard Matrix.
   - Canvas-based neural particle background.

2. **Native Google Slides Presentation (`scripts/build_google_slides.py` & Live Slides URL)**:
   - Programmatically built via Google Slides CLI `/google/bin/releases/gemini-agents-gslides/gslides` and batch JSON schemas.
   - Live URL: `https://docs.google.com/presentation/d/1NK-GaneNoQF2mKQCFjy7OVbJkG_oP7tkmY_7YnyXvJw/edit`
   - Presentation ID: `1NK-GaneNoQF2mKQCFjy7OVbJkG_oP7tkmY_7YnyXvJw`
   - 16:9 widescreen layout (720pt x 405pt) with dark theme canvas, container cards, metric callouts, and structured tables.
   - Complete speaker notes populated on all 14 slides with verbatim pitch guidance and technical proof points.

3. **Standalone Visual Assets & Diagram Library (`presentation/assets/`)**:
   - 8 High-resolution SVG diagrams: Latency Waterfall, 3-Way Workload Decision Tree, 4-Quadrant Customer Matrix, Battlecard Matrix, Cascade vs Duplex, 10x Cost Advantage, Sub-500ms Delight, India Market Inflection.

---

## Feature Inventory

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Executive Title & Strategic Scope (Slide 1) | Framing the $5.9B voice inflection point, agenda across 7 pillars, session goals | M1, M2 | Survey / ORIGINAL_REQUEST |
| 2 | India & Global Market Surge (Slide 2) | India market expansion ($565M 2025 → $5.9B 2034 @ 26.6% CAGR, 1.1B mobile users, 1,700+ GCCs) with growth area chart | M1, M2 | Survey / ORIGINAL_REQUEST |
| 3 | Gartner & McKinsey Economic Value (Slide 3) | $80B contact center labor reduction, 30–50% deflection, ₹180 → ₹10 call cost reduction (94.4% savings) with ROI calculator | M1, M2 | Survey / ORIGINAL_REQUEST |
| 4 | Enterprise 4-Quadrant Logos (Slide 4) | Unified 4-quadrant showcase: BFSI/Debt, Hardware (boAt, MIVI), Education (Yoodli, HeyAto), E-Commerce (Lenskart 'B', KaptureCX, Nurix) | M1, M2 | Survey / ORIGINAL_REQUEST |
| 5 | Workload Decision Matrix (Slide 5) | Visual 3-way decision tree (Gemini Live S2S vs Modular Cascade vs Dialogflow CX) with interactive branching | M1, M2 | Survey / ORIGINAL_REQUEST |
| 6 | Difficult Inbound vs Delight Experience (Slide 6) | Deep-dive contrast: Regulated/narrowband/PII inbound (Cascade) vs Prosody/sub-500ms S2S (Gemini Live) | M1, M2 | Survey / ORIGINAL_REQUEST |
| 7 | Current Stack Part 1: Modular Cascade (Slide 7) | Chirp 2 USM 100+ langs + Gemini 2.5 Flash + Chirp 3 HD 48kHz Studio Diffusion & Journey Voices | M1, M2 | Survey / ORIGINAL_REQUEST |
| 8 | Current Stack Part 2: Realtime Duplex (Slide 8) | Gemini 2.5 & 3.1 Flash Live BidiGenerateContent streaming WebSocket + Thinker-Talker dual-engine | M1, M2 | Survey / ORIGINAL_REQUEST |
| 9 | Gotchas & Field Challenges: Cascaded (Slide 9) | 2.85s latency waterfall (600ms VAD + 350ms STT + 650ms LLM + 250ms TTS + 1000ms buffers), error cascades, prosody loss | M1, M2 | Survey / ORIGINAL_REQUEST |
| 10 | Gotchas & Field Fixes: Gemini Live (Slide 10) | Silero/Krisp VAD, 30s sliding window at 20k tokens, GKE session affinity, DSP 8kHz↔24kHz resampling | M1, M2 | Survey / ORIGINAL_REQUEST |
| 11 | Roadmap Part 1: Next-Gen Cascaded (Slide 11) | Gemini 3.5 Transcribe Live (word biasing), Transcribe Batch ($0.13-$0.16/hr), Instant Custom Voice 10s + SynthID | M1, M2 | Survey / ORIGINAL_REQUEST |
| 12 | Roadmap Part 2: Gemini Live & Avatars (Slide 12) | Gemini 3.5 Live API / Phonos GA / Rev25 (92% numeric acc), Omni Live & Live Avatar v2, PT pricing | M1, M2 | Survey / ORIGINAL_REQUEST |
| 13 | Competitive Battlecards (Slide 13) | Feature & architectural matrix vs OpenAI Realtime 2.1 (10.6x cost advantage), ElevenLabs, Deepgram+Groq DIY, Tavus/HeyGen | M1, M2 | Survey / ORIGINAL_REQUEST |
| 14 | Positioning, TCO & FSR Discovery (Slide 14) | Commercial TCO ($3 vs $32 audio in), 5 India discovery questions, 2-Week Funded POC closing framework | M1, M2 | Survey / ORIGINAL_REQUEST |
| 15 | Live Teleprompter Speaker Notes Drawer | 'P' key hotkey drawer with pitch scripts, technical proof points, objections, and discovery cues for all 14 slides | M1, M2 | Survey / ORIGINAL_REQUEST |
| 16 | Interactive Keyboard & Navigation Dock | Full presentation keyboard controls (`←`, `→`, `Space`, `F`, `G`), progress bar, thumbnail overview grid | M1 | Survey / ORIGINAL_REQUEST |
| 17 | High-Res Diagrams & Visual Graphics | SVG diagrams (Latency Waterfall, Decision Tree, 4-Quadrant Grid, Battlecard Matrix) and sales visuals | M1, M3 | Survey / ORIGINAL_REQUEST |
| 18 | Automated Google Slides Generator Script | Python script using `/google/bin/releases/gemini-agents-gslides/gslides` batch JSON to build and update the 14-slide deck | M2 | Survey / ORIGINAL_REQUEST |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M0 | Survey & Spec Synthesis | Comprehensive domain extraction, Open Design architecture, Google Slides tooling survey | none | **DONE** |
| M1 | Open Design Interactive Deck | Build `presentation/google_voice_models_sales_deck.html` with all 14 slides, teleprompter drawer, interactive charts, widgets, and particles | M0 | **DONE** (Worker M1: dbaa46d1) |
| M2 | Google Slides Generation & Deck Build | Build `scripts/build_google_slides.py`, execute gslides batch updates, format dark theme slides with speaker notes | M0 | **DONE** (Live URL: https://docs.google.com/presentation/d/1NK-GaneNoQF2mKQCFjy7OVbJkG_oP7tkmY_7YnyXvJw/edit) |
| M3 | Standalone Visual Assets & Diagram Library | Generate high-res SVGs and diagram components for presentation embedding and export | M0 | **DONE** (8 SVGs in `presentation/assets/`) |
| M4 | Dual-Track Verification, Testing & Audit | 2 Reviewers + 2 Challengers + 1 Forensic Auditor validating all 14 slides, speaker notes, interactive controls, and API correctness | M1, M2, M3 | **DONE** (Unanimous APPROVE + CLEAN audit) |

---

## Code Layout

```
gemini_live_pipecat/
├── presentation/
│   ├── google_voice_models_sales_deck.html   # Standalone interactive 14-slide Open Design deck
│   └── assets/
│       ├── latency_waterfall.svg            # 2.85s cascaded latency waterfall
│       ├── decision_tree.svg                # 3-way workload decision tree
│       ├── enterprise_logos_4quadrant.svg   # 4-quadrant enterprise customer grid
│       ├── battlecard_matrix.svg            # Competitive comparison matrix
│       ├── cascade_vs_duplex.svg            # Leaky multi-hop plumbing vs unified S2S
│       ├── cost_advantage_10x.svg           # 10.6x cost advantage diagram
│       ├── sub_500ms_delight.svg            # Sub-500ms conversational delight curve
│       └── india_market_inflection.svg      # India $5.9B market expansion chart
├── scripts/
│   └── build_google_slides.py               # Google Slides automated generator & batch JSON builder
└── .agents/
    ├── orchestrator_1/                      # Project Orchestrator state & logs
    ├── teamwork_preview_spec_miner_survey_1/
    ├── teamwork_preview_explorer_survey_2/
    ├── teamwork_preview_explorer_survey_3/
    ├── teamwork_preview_worker_m1/
    ├── teamwork_preview_worker_m2/
    └── teamwork_preview_worker_m3/
```
