import os
import xml.etree.ElementTree as ET
from build_assets import SHARED_DEFS, FONT_STACK, MONO_FONT, ASSETS_DIR

def build_cascade_vs_duplex():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 820" width="1400" height="820" style="background-color: #0B0F19; font-family: {FONT_STACK};">
  {SHARED_DEFS}

  <!-- Canvas Background -->
  <rect width="1400" height="820" fill="url(#bgGrad)"/>
  <rect width="1400" height="820" fill="url(#gridPattern)"/>

  <!-- Header Block -->
  <g transform="translate(60, 45)">
    <rect x="0" y="0" width="270" height="28" rx="14" fill="#EF4444" fill-opacity="0.12" stroke="#EF4444" stroke-width="1.2"/>
    <circle cx="14" cy="14" r="5" fill="#EF4444"/>
    <text x="28" y="18" fill="#EF4444" font-size="12" font-weight="700" letter-spacing="1.2">ARCHITECTURAL CONTRAST</text>
    
    <text x="0" y="62" fill="#FFFFFF" font-size="28" font-weight="800" letter-spacing="-0.5">Cascade Plumbing Disaster vs Duplex Gemini Live</text>
    <text x="0" y="90" fill="#94A3B8" font-size="15" font-weight="400">Why multi-hop plumbing creates fragile conversational failure modes while unified S2S delivers effortless intimacy</text>
  </g>

  <!-- Left Side: The Fragile Cascaded Plumbing Loop -->
  <g transform="translate(60, 160)">
    <rect width="615" height="610" rx="16" fill="url(#cardGrad)" stroke="#EF4444" stroke-width="1.5" filter="url(#dropShadow)"/>
    
    <!-- Header -->
    <rect x="24" y="24" width="260" height="28" rx="14" fill="#EF4444" fill-opacity="0.15" stroke="#EF4444" stroke-width="1"/>
    <text x="154" y="42" fill="#FCA5A5" font-size="12" font-weight="800" text-anchor="middle">❌ THE FRAGILE PLUMBING LOOP</text>
    <text x="24" y="82" fill="#FFFFFF" font-size="20" font-weight="800">Cascaded Multi-Hop Architecture</text>
    <text x="24" y="104" fill="#94A3B8" font-size="13">3 Disjoint APIs • 3 Serialization Hops • 2.85s Dead Air</text>

    <!-- Leaky Pipeline Diagram -->
    <g transform="translate(24, 125)">
      <!-- Stage 1: VAD -->
      <rect x="0" y="0" width="567" height="64" rx="8" fill="#131B2E" stroke="#F59E0B" stroke-width="1.2"/>
      <text x="18" y="26" fill="#F59E0B" font-size="13" font-weight="700">1. Client / Server VAD (Silero)</text>
      <text x="18" y="46" fill="#94A3B8" font-size="12">600ms silence waiting window • False turn cutting on room noise</text>
      <rect x="445" y="16" width="105" height="30" rx="6" fill="#F59E0B" fill-opacity="0.2"/>
      <text x="497" y="35" fill="#FDE68A" font-size="11" font-weight="700" text-anchor="middle">+600ms</text>

      <!-- Leak Arrow 1 -->
      <path d="M 283 64 L 283 80" stroke="#EF4444" stroke-width="2" stroke-dasharray="3,3"/>
      <text x="300" y="76" fill="#EF4444" font-size="10" font-weight="700">⚠️ Leak: Prosody Stripped</text>

      <!-- Stage 2: STT -->
      <rect x="0" y="80" width="567" height="64" rx="8" fill="#131B2E" stroke="#EF4444" stroke-width="1.2"/>
      <text x="18" y="106" fill="#EF4444" font-size="13" font-weight="700">2. Speech-to-Text (Chirp 2 / Whisper)</text>
      <text x="18" y="126" fill="#94A3B8" font-size="12">Acoustic waveform converted to plain text • Error propagation risk</text>
      <rect x="445" y="96" width="105" height="30" rx="6" fill="#EF4444" fill-opacity="0.2"/>
      <text x="497" y="115" fill="#FCA5A5" font-size="11" font-weight="700" text-anchor="middle">+350ms</text>

      <!-- Leak Arrow 2 -->
      <path d="M 283 144 L 283 160" stroke="#EF4444" stroke-width="2" stroke-dasharray="3,3"/>
      <text x="300" y="156" fill="#EF4444" font-size="10" font-weight="700">⚠️ Leak: Net Serialization Hop</text>

      <!-- Stage 3: LLM -->
      <rect x="0" y="160" width="567" height="64" rx="8" fill="#131B2E" stroke="#DC2626" stroke-width="1.2"/>
      <text x="18" y="186" fill="#DC2626" font-size="13" font-weight="700">3. Language Model (Gemini Flash / GPT-4o)</text>
      <text x="18" y="206" fill="#94A3B8" font-size="12">Text reasoning &amp; token streaming • Monolithic pause on tool calls</text>
      <rect x="445" y="176" width="105" height="30" rx="6" fill="#DC2626" fill-opacity="0.2"/>
      <text x="497" y="195" fill="#FCA5A5" font-size="11" font-weight="700" text-anchor="middle">+700ms</text>

      <!-- Leak Arrow 3 -->
      <path d="M 283 224 L 283 240" stroke="#EF4444" stroke-width="2" stroke-dasharray="3,3"/>
      <text x="300" y="236" fill="#EF4444" font-size="10" font-weight="700">⚠️ Leak: Jitter Buffer Delay</text>

      <!-- Stage 4: TTS -->
      <rect x="0" y="240" width="567" height="64" rx="8" fill="#131B2E" stroke="#EA580C" stroke-width="1.2"/>
      <text x="18" y="266" fill="#EA580C" font-size="13" font-weight="700">4. Text-to-Speech (Chirp 3 HD / ElevenLabs)</text>
      <text x="18" y="286" fill="#94A3B8" font-size="12">Blind neural audio reconstruction • Flat emotionless voice tone</text>
      <rect x="445" y="256" width="105" height="30" rx="6" fill="#EA580C" fill-opacity="0.2"/>
      <text x="497" y="275" fill="#FED7AA" font-size="11" font-weight="700" text-anchor="middle">+1,200ms</text>
    </g>

    <!-- Failures List Card -->
    <g transform="translate(24, 450)">
      <rect width="567" height="135" rx="10" fill="#0B0F19" stroke="#EF4444" stroke-width="1" stroke-opacity="0.4"/>
      <text x="16" y="24" fill="#FCA5A5" font-size="12" font-weight="800">FATAL CASCADE CONSEQUENCES:</text>
      <text x="16" y="48" fill="#E2E8F0" font-size="12">• <tspan fill="#EF4444" font-weight="700">2.85s Cumulative Delay</tspan>: Destroys natural human conversational flow.</text>
      <text x="16" y="70" fill="#E2E8F0" font-size="12">• <tspan fill="#EF4444" font-weight="700">Error Snowballing</tspan>: 1 mistranscribed word cascades into false advice.</text>
      <text x="16" y="92" fill="#E2E8F0" font-size="12">• <tspan fill="#EF4444" font-weight="700">Choppy Barge-in</tspan>: Client must manually kill active audio queues.</text>
      <text x="16" y="114" fill="#EF4444" font-size="12" font-weight="700">3 Separate Vendor Contracts • 3 Failure SLAs • High TCO</text>
    </g>
  </g>

  <!-- Right Side: The Duplex Gemini Live Elegance -->
  <g transform="translate(725, 160)">
    <rect width="615" height="610" rx="16" fill="url(#cardGradHighlight)" stroke="#00E5FF" stroke-width="2" filter="url(#dropShadow)"/>
    
    <!-- Header -->
    <rect x="24" y="24" width="280" height="28" rx="14" fill="#00E5FF" fill-opacity="0.2" stroke="#00E5FF" stroke-width="1.2"/>
    <text x="164" y="42" fill="#00E5FF" font-size="12" font-weight="800" text-anchor="middle">✓ THE DUPLEX GEMINI LIVE ELEGANCE</text>
    <text x="24" y="82" fill="#FFFFFF" font-size="20" font-weight="800">Native Speech-to-Speech (S2S)</text>
    <text x="24" y="104" fill="#00E5FF" font-size="13">1 WebSocket • Direct Acoustic Modeling • Sub-500ms Speed</text>

    <!-- Unified S2S Stream Diagram -->
    <g transform="translate(24, 125)">
      <!-- Audio In Stream Box -->
      <rect x="0" y="0" width="567" height="60" rx="8" fill="#131B2E" stroke="#00E5FF" stroke-width="1.2"/>
      <circle cx="24" cy="30" r="10" fill="#00E5FF" fill-opacity="0.2"/>
      <text x="44" y="26" fill="#00E5FF" font-size="13" font-weight="700">Streaming Audio In (PCM 16kHz Mono)</text>
      <text x="44" y="44" fill="#94A3B8" font-size="12">Direct acoustic tokenization preserving emotion &amp; inflection</text>

      <!-- Center Foundation Model Engine -->
      <rect x="0" y="80" width="567" height="145" rx="12" fill="url(#cardGradHighlight)" stroke="#4285F4" stroke-width="2" filter="url(#glowBlue)"/>
      <text x="24" y="110" fill="#FFFFFF" font-size="16" font-weight="800">VERTEX AI GEMINI LIVE FOUNDATION ENGINE</text>
      
      <!-- Thinker-Talker Dual Block -->
      <g transform="translate(20, 125)">
        <!-- Talker -->
        <rect x="0" y="0" width="250" height="75" rx="8" fill="#0B0F19" stroke="#00E5FF" stroke-width="1"/>
        <text x="14" y="24" fill="#00E5FF" font-size="12" font-weight="800">TALKER CORE (&lt; 450ms TTFT)</text>
        <text x="14" y="44" fill="#E2E8F0" font-size="11">• Instant conversational response</text>
        <text x="14" y="60" fill="#E2E8F0" font-size="11">• Emits verbal filler during DB queries</text>

        <!-- Thinker -->
        <rect x="275" y="0" width="250" height="75" rx="8" fill="#0B0F19" stroke="#A855F7" stroke-width="1"/>
        <text x="289" y="24" fill="#C084FC" font-size="12" font-weight="800">THINKER CORE (Deep Async)</text>
        <text x="289" y="44" fill="#E2E8F0" font-size="11">• Non-blocking CRM &amp; tool execution</text>
        <text x="289" y="60" fill="#E2E8F0" font-size="11">• Zero dead air on user stream</text>
      </g>

      <!-- Audio Out Stream Box -->
      <rect x="0" y="245" width="567" height="60" rx="8" fill="#131B2E" stroke="#10B981" stroke-width="1.2"/>
      <circle cx="24" cy="275" r="10" fill="#10B981" fill-opacity="0.2"/>
      <text x="44" y="271" fill="#34D399" font-size="13" font-weight="700">Streaming Audio Out (PCM 24kHz Studio Audio)</text>
      <text x="44" y="289" fill="#94A3B8" font-size="12">Natural cadence, expressive laughter &amp; instant acoustic barge-in</text>
    </g>

    <!-- Success Proof Cards -->
    <g transform="translate(24, 450)">
      <rect width="567" height="135" rx="10" fill="#0B0F19" stroke="#00E5FF" stroke-width="1" stroke-opacity="0.4"/>
      <text x="16" y="24" fill="#00E5FF" font-size="12" font-weight="800">UNMATCHED GEMINI LIVE ADVANTAGES:</text>
      <text x="16" y="48" fill="#E2E8F0" font-size="12">• <tspan fill="#34D399" font-weight="700">Sub-500ms Latency</tspan>: True human conversational rhythm and intimacy.</text>
      <text x="16" y="70" fill="#E2E8F0" font-size="12">• <tspan fill="#34D399" font-weight="700">10.6x Cost Advantage</tspan>: $2.00 vs $20.00 / 1M audio output tokens.</text>
      <text x="16" y="92" fill="#E2E8F0" font-size="12">• <tspan fill="#34D399" font-weight="700">10+ Indic Languages</tspan>: SOTA code-switching in Hinglish, Tanglish, etc.</text>
      <text x="16" y="114" fill="#34D399" font-size="12" font-weight="700">1 Managed Enterprise Endpoint • Vertex AI PT Quotas • Single SLA</text>
    </g>
  </g>
</svg>"""
    out_file = os.path.join(ASSETS_DIR, "cascade_vs_duplex.svg")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(svg)
    ET.fromstring(svg)
    print(f"Generated and validated {out_file}")

def build_cost_advantage_10x():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 820" width="1400" height="820" style="background-color: #0B0F19; font-family: {FONT_STACK};">
  {SHARED_DEFS}

  <!-- Canvas Background -->
  <rect width="1400" height="820" fill="url(#bgGrad)"/>
  <rect width="1400" height="820" fill="url(#gridPattern)"/>

  <!-- Header Block -->
  <g transform="translate(60, 45)">
    <rect x="0" y="0" width="270" height="28" rx="14" fill="#34A853" fill-opacity="0.12" stroke="#34A853" stroke-width="1.2"/>
    <circle cx="14" cy="14" r="5" fill="#34A853"/>
    <text x="28" y="18" fill="#34A853" font-size="12" font-weight="700" letter-spacing="1.2">COMMERCIAL TCO &amp; UNIT ECONOMICS</text>
    
    <text x="0" y="62" fill="#FFFFFF" font-size="28" font-weight="800" letter-spacing="-0.5">The 10.6x Cost Advantage &amp; Hourly Unit Economics</text>
    <text x="0" y="90" fill="#94A3B8" font-size="15" font-weight="400">Comparing effective hourly voice operational cost across Google Gemini Live, Competitors, and Human Contact Centers</text>
  </g>

  <!-- Left: Big Bar Chart of Hourly Cost -->
  <g transform="translate(60, 160)">
    <rect width="780" height="610" rx="16" fill="url(#cardGrad)" stroke="#1E293B" stroke-width="1.5" filter="url(#dropShadow)"/>

    <text x="30" y="38" fill="#FFFFFF" font-size="18" font-weight="800">Effective Fully Loaded Cost per Active Audio Hour</text>
    <text x="30" y="58" fill="#94A3B8" font-size="13">Based on standard 28.5 audio tokens/s in + 140 words/min out</text>

    <!-- Chart Coordinate Area -->
    <g transform="translate(30, 85)">
      <!-- Bar 1: Human Agent (India Contact Center) -->
      <text x="0" y="32" fill="#E2E8F0" font-size="13" font-weight="700">Human Agent (₹180/call)</text>
      <rect x="220" y="12" width="480" height="34" rx="6" fill="#EF4444" fill-opacity="0.4" stroke="#EF4444" stroke-width="1.5"/>
      <text x="710" y="34" fill="#FCA5A5" font-size="14" font-weight="800" font-family="{MONO_FONT}">$25.80 / hr</text>
      <text x="235" y="34" fill="#FFFFFF" font-size="11" font-weight="700">Traditional BPO Baseline (100%)</text>

      <!-- Bar 2: ElevenLabs Agents -->
      <text x="0" y="92" fill="#E2E8F0" font-size="13" font-weight="700">ElevenLabs Agents</text>
      <rect x="220" y="72" width="180" height="34" rx="6" fill="#F59E0B" fill-opacity="0.3" stroke="#F59E0B" stroke-width="1.5"/>
      <text x="410" y="94" fill="#FDE68A" font-size="14" font-weight="800" font-family="{MONO_FONT}">$6.00 / hr</text>
      <text x="235" y="94" fill="#FDE68A" font-size="11" font-weight="700">Minute-based ($0.10/min)</text>

      <!-- Bar 3: OpenAI Realtime (2.1) -->
      <text x="0" y="152" fill="#E2E8F0" font-size="13" font-weight="700">OpenAI Realtime 2.1</text>
      <rect x="220" y="132" width="120" height="34" rx="6" fill="#DC2626" fill-opacity="0.3" stroke="#DC2626" stroke-width="1.5"/>
      <text x="350" y="154" fill="#FCA5A5" font-size="14" font-weight="800" font-family="{MONO_FONT}">$3.05 / hr</text>
      <text x="230" y="154" fill="#FCA5A5" font-size="10" font-weight="700">$20/1M audio out</text>

      <!-- Bar 4: Deepgram + Groq DIY -->
      <text x="0" y="212" fill="#E2E8F0" font-size="13" font-weight="700">Deepgram + Groq DIY</text>
      <rect x="220" y="192" width="65" height="34" rx="6" fill="#64748B" fill-opacity="0.4" stroke="#94A3B8" stroke-width="1.5"/>
      <text x="295" y="214" fill="#CBD5E1" font-size="14" font-weight="800" font-family="{MONO_FONT}">$1.10 / hr</text>

      <!-- Bar 5: Google Gemini 3.5 Flash Live -->
      <text x="0" y="272" fill="#E2E8F0" font-size="13" font-weight="700">Gemini 3.5 Flash Live</text>
      <rect x="220" y="252" width="45" height="34" rx="6" fill="url(#cyanGrad)" filter="url(#glowCyan)"/>
      <text x="275" y="274" fill="#00E5FF" font-size="14" font-weight="900" font-family="{MONO_FONT}">$0.90 / hr</text>

      <!-- Bar 6: Google Gemini 3.5 Flash-Lite Live -->
      <text x="0" y="332" fill="#E2E8F0" font-size="13" font-weight="700">Gemini 3.5 Flash-Lite</text>
      <rect x="220" y="312" width="25" height="34" rx="6" fill="url(#greenGrad)" filter="url(#glowCyan)"/>
      <text x="255" y="334" fill="#34D399" font-size="14" font-weight="900" font-family="{MONO_FONT}">$0.35 / hr</text>
    </g>

    <!-- Bottom Highlights inside chart card -->
    <g transform="translate(30, 475)">
      <rect width="720" height="100" rx="10" fill="#0B0F19" stroke="#34A853" stroke-width="1.2"/>
      <text x="20" y="28" fill="#34D399" font-size="13" font-weight="800">EXECUTIVE ROI SUMMARY:</text>
      <text x="20" y="52" fill="#E2E8F0" font-size="13">• Replacing human Tier-1 calls (₹180) with Gemini Live (₹10) yields <tspan fill="#34D399" font-weight="800">94.4% net savings</tspan>.</text>
      <text x="20" y="74" fill="#E2E8F0" font-size="13">• For 100,000 calls/month, annual operating savings exceed <tspan fill="#00E5FF" font-weight="800">₹2.04 Crore ($245,000 USD)</tspan>.</text>
    </g>
  </g>

  <!-- Right: Token Rate Card Comparison Cards -->
  <g transform="translate(865, 160)">
    <rect width="475" height="610" rx="16" fill="url(#cardGradHighlight)" stroke="#00E5FF" stroke-width="2" filter="url(#dropShadow)"/>

    <text x="28" y="38" fill="#00E5FF" font-size="18" font-weight="800">Token Rate Card Invariants</text>
    <text x="28" y="58" fill="#94A3B8" font-size="13">Audio Token Pricing (/1M Tokens)</text>

    <!-- Card A: Audio Output Tokens (The 10.6x Metric) -->
    <g transform="translate(24, 85)">
      <rect width="425" height="145" rx="12" fill="#0B0F19" stroke="#00E5FF" stroke-width="1.5"/>
      <rect x="18" y="16" width="170" height="24" rx="6" fill="#00E5FF" fill-opacity="0.15"/>
      <text x="103" y="32" fill="#00E5FF" font-size="11" font-weight="800" text-anchor="middle">AUDIO OUTPUT TOKENS</text>

      <text x="18" y="70" fill="#94A3B8" font-size="12">Google Gemini 3.5 Flash-Lite:</text>
      <text x="320" y="70" fill="#34D399" font-size="16" font-weight="900" font-family="{MONO_FONT}">$2.00 / 1M</text>

      <text x="18" y="98" fill="#94A3B8" font-size="12">OpenAI Realtime 2.1:</text>
      <text x="320" y="98" fill="#EF4444" font-size="16" font-weight="900" font-family="{MONO_FONT}">$20.00 / 1M</text>

      <line x1="18" y1="112" x2="407" y2="112" stroke="#1E293B" stroke-width="1"/>
      <text x="18" y="132" fill="#00E5FF" font-size="13" font-weight="800">★ EXACT 10.0x TO 10.6x GOOGLE COST LEAD</text>
    </g>

    <!-- Card B: Audio Input Tokens -->
    <g transform="translate(24, 245)">
      <rect width="425" height="145" rx="12" fill="#0B0F19" stroke="#4285F4" stroke-width="1"/>
      <rect x="18" y="16" width="160" height="24" rx="6" fill="#4285F4" fill-opacity="0.15"/>
      <text x="98" y="32" fill="#4285F4" font-size="11" font-weight="800" text-anchor="middle">AUDIO INPUT TOKENS</text>

      <text x="18" y="70" fill="#94A3B8" font-size="12">Google Gemini 3.5 Flash-Lite:</text>
      <text x="320" y="70" fill="#34D399" font-size="16" font-weight="900" font-family="{MONO_FONT}">$0.50 / 1M</text>

      <text x="18" y="98" fill="#94A3B8" font-size="12">OpenAI Realtime 2.1:</text>
      <text x="320" y="98" fill="#EF4444" font-size="16" font-weight="900" font-family="{MONO_FONT}">$10.00 / 1M</text>

      <line x1="18" y1="112" x2="407" y2="112" stroke="#1E293B" stroke-width="1"/>
      <text x="18" y="132" fill="#4285F4" font-size="13" font-weight="800">★ 20x LOWER AUDIO INGESTION COST</text>
    </g>

    <!-- Card C: Batch Pricing Promo -->
    <g transform="translate(24, 405)">
      <rect width="425" height="175" rx="12" fill="#0B0F19" stroke="#A855F7" stroke-width="1"/>
      <text x="18" y="28" fill="#C084FC" font-size="13" font-weight="800">POST-CALL BATCH TRANSCRIPTION</text>
      <text x="18" y="52" fill="#E2E8F0" font-size="12">Gemini 3.5 Transcribe Batch: <tspan fill="#34D399" font-weight="800">$0.13 – $0.16 / hr</tspan></text>
      <text x="18" y="72" fill="#94A3B8" font-size="11">50% discount vs sync streaming for analytics &amp; QA</text>
      
      <line x1="18" y1="88" x2="407" y2="88" stroke="#1E293B" stroke-width="1"/>
      <text x="18" y="112" fill="#E2E8F0" font-size="12">• Outperforms Whisper on Hinglish / Tanglish</text>
      <text x="18" y="134" fill="#E2E8F0" font-size="12">• Multi-speaker diarization &amp; word timestamps</text>
      <text x="18" y="156" fill="#C084FC" font-size="12" font-weight="700">Instant Custom Voice 10s Clone + SynthID</text>
    </g>
  </g>
</svg>"""
    out_file = os.path.join(ASSETS_DIR, "cost_advantage_10x.svg")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(svg)
    ET.fromstring(svg)
    print(f"Generated and validated {out_file}")

def build_sub_500ms_delight():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 820" width="1400" height="820" style="background-color: #0B0F19; font-family: {FONT_STACK};">
  {SHARED_DEFS}

  <!-- Canvas Background -->
  <rect width="1400" height="820" fill="url(#bgGrad)"/>
  <rect width="1400" height="820" fill="url(#gridPattern)"/>

  <!-- Header Block -->
  <g transform="translate(60, 45)">
    <rect x="0" y="0" width="270" height="28" rx="14" fill="#00E5FF" fill-opacity="0.12" stroke="#00E5FF" stroke-width="1.2"/>
    <circle cx="14" cy="14" r="5" fill="#00E5FF"/>
    <text x="28" y="18" fill="#00E5FF" font-size="12" font-weight="700" letter-spacing="1.2">PSYCHOLOGY OF VOICE AI</text>
    
    <text x="0" y="62" fill="#FFFFFF" font-size="28" font-weight="800" letter-spacing="-0.5">Sub-500ms Delight: The Conversational Intimacy Curve</text>
    <text x="0" y="90" fill="#94A3B8" font-size="15" font-weight="400">Why human conversational satisfaction drops off precipitously beyond 500ms and collapses in cascaded stacks</text>
  </g>

  <!-- Main Curve Visualization Card -->
  <g transform="translate(60, 160)">
    <rect width="1280" height="610" rx="16" fill="url(#cardGrad)" stroke="#1E293B" stroke-width="1.5" filter="url(#dropShadow)"/>

    <!-- Left Axis Labels & Gradient Zone Areas -->
    <!-- X-axis: 0ms to 3000ms across 1100px (x=100 to x=1200) -->
    <!-- Zone 1: Green Zone (0 - 500ms) width=183px -->
    <rect x="100" y="60" width="183" height="380" fill="#10B981" fill-opacity="0.1" stroke="#10B981" stroke-width="1" stroke-dasharray="4,4"/>
    <text x="191" y="90" fill="#34D399" font-size="13" font-weight="800" text-anchor="middle">NATURAL HUMAN FLOW</text>
    <text x="191" y="110" fill="#6EE7B7" font-size="11" text-anchor="middle">0 – 500ms (High Intimacy)</text>

    <!-- Zone 2: Amber Zone (500ms - 1200ms) width=256px -->
    <rect x="283" y="60" width="256" height="380" fill="#F59E0B" fill-opacity="0.08" stroke="#F59E0B" stroke-width="1" stroke-dasharray="4,4"/>
    <text x="411" y="90" fill="#FDE68A" font-size="13" font-weight="700" text-anchor="middle">MILD AI DELAY</text>
    <text x="411" y="110" fill="#FDE68A" font-size="11" text-anchor="middle">500ms – 1,200ms (Tolerable)</text>

    <!-- Zone 3: Orange Zone (1200ms - 2000ms) width=293px -->
    <rect x="539" y="60" width="293" height="380" fill="#EA580C" fill-opacity="0.08" stroke="#EA580C" stroke-width="1" stroke-dasharray="4,4"/>
    <text x="685" y="90" fill="#FED7AA" font-size="13" font-weight="700" text-anchor="middle">UNCANNY VALLEY PAUSE</text>
    <text x="685" y="110" fill="#FED7AA" font-size="11" text-anchor="middle">1.2s – 2.0s (User Over-Talk)</text>

    <!-- Zone 4: Red Zone (2000ms - 3000ms) width=368px -->
    <rect x="832" y="60" width="368" height="380" fill="#EF4444" fill-opacity="0.1" stroke="#EF4444" stroke-width="1" stroke-dasharray="4,4"/>
    <text x="1016" y="90" fill="#FCA5A5" font-size="13" font-weight="800" text-anchor="middle">CASCADE DISASTER ZONE</text>
    <text x="1016" y="110" fill="#FCA5A5" font-size="11" text-anchor="middle">2.0s – 3.0s (40%+ Drop-Off)</text>

    <!-- Satisfaction Curve Path (Decreasing Sigmoid Curve) -->
    <!-- Start (100, 140) -> (283, 160) -> (539, 280) -> (832, 380) -> (1200, 410) -->
    <path d="M 100 140 Q 220 140 283 170 T 539 300 T 832 390 T 1200 415" fill="none" stroke="url(#geminiGrad)" stroke-width="5" filter="url(#glowCyan)"/>

    <!-- Gemini Live Marker Pill -->
    <g transform="translate(180, 160)">
      <circle cx="0" cy="0" r="8" fill="#00E5FF" filter="url(#glowCyan)"/>
      <rect x="-80" y="-70" width="160" height="54" rx="8" fill="#131B2E" stroke="#00E5FF" stroke-width="1.5"/>
      <text x="0" y="-48" fill="#00E5FF" font-size="12" font-weight="800" text-anchor="middle">GEMINI LIVE (&lt;450ms)</text>
      <text x="0" y="-30" fill="#FFFFFF" font-size="11" text-anchor="middle">98% Human Cadence NPS</text>
    </g>

    <!-- OpenAI Realtime Marker Pill -->
    <g transform="translate(420, 240)">
      <circle cx="0" cy="0" r="7" fill="#F59E0B"/>
      <rect x="-70" y="-55" width="140" height="44" rx="6" fill="#131B2E" stroke="#F59E0B" stroke-width="1"/>
      <text x="0" y="-35" fill="#FDE68A" font-size="11" font-weight="700" text-anchor="middle">OpenAI Realtime (~750ms)</text>
      <text x="0" y="-20" fill="#94A3B8" font-size="10" text-anchor="middle">Noticeable brief pause</text>
    </g>

    <!-- Modular Cascade Marker Pill -->
    <g transform="translate(1040, 400)">
      <circle cx="0" cy="0" r="8" fill="#EF4444"/>
      <rect x="-95" y="-60" width="190" height="50" rx="8" fill="#131B2E" stroke="#EF4444" stroke-width="1.5"/>
      <text x="0" y="-40" fill="#FCA5A5" font-size="11" font-weight="800" text-anchor="middle">MODULAR CASCADE (2.85s)</text>
      <text x="0" y="-24" fill="#EF4444" font-size="10" font-weight="700" text-anchor="middle">High Drop-Off &amp; Over-Talk</text>
    </g>

    <!-- Bottom 3 Takeaway Cards -->
    <g transform="translate(40, 470)">
      <rect x="0" y="0" width="370" height="110" rx="10" fill="#131B2E" stroke="#10B981" stroke-width="1"/>
      <text x="18" y="28" fill="#34D399" font-size="13" font-weight="800">HUMAN CONVERSATION SLA</text>
      <text x="18" y="52" fill="#E2E8F0" font-size="12">Natural human pause between dialogue turns is <tspan fill="#34D399" font-weight="700">200–400ms</tspan>. Sub-500ms feels indistinguishable from human fluency.</text>

      <rect x="415" y="0" width="370" height="110" rx="10" fill="#131B2E" stroke="#F59E0B" stroke-width="1"/>
      <text x="433" y="28" fill="#FDE68A" font-size="13" font-weight="800">THE 1.0-SECOND CLIFF</text>
      <text x="433" y="52" fill="#E2E8F0" font-size="12">Beyond 1,000ms, users assume the system disconnected and begin speaking again, causing cross-talk and state collision.</text>

      <rect x="830" y="0" width="370" height="110" rx="10" fill="#131B2E" stroke="#00E5FF" stroke-width="1.5"/>
      <text x="848" y="28" fill="#00E5FF" font-size="13" font-weight="800">EMOTIONAL PROSODY PRESERVATION</text>
      <text x="848" y="52" fill="#E2E8F0" font-size="12">Gemini Live hears sighs, sarcasm, and urgency directly in audio waveforms, enabling warm empathy impossible in text cascades.</text>
    </g>
  </g>
</svg>"""
    out_file = os.path.join(ASSETS_DIR, "sub_500ms_delight.svg")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(svg)
    ET.fromstring(svg)
    print(f"Generated and validated {out_file}")

def build_india_market_inflection():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 820" width="1400" height="820" style="background-color: #0B0F19; font-family: {FONT_STACK};">
  {SHARED_DEFS}

  <!-- Canvas Background -->
  <rect width="1400" height="820" fill="url(#bgGrad)"/>
  <rect width="1400" height="820" fill="url(#gridPattern)"/>

  <!-- Header Block -->
  <g transform="translate(60, 45)">
    <rect x="0" y="0" width="240" height="28" rx="14" fill="#4285F4" fill-opacity="0.12" stroke="#4285F4" stroke-width="1.2"/>
    <circle cx="14" cy="14" r="5" fill="#4285F4"/>
    <text x="28" y="18" fill="#4285F4" font-size="12" font-weight="700" letter-spacing="1.2">MACRO MARKET EXPANSION</text>
    
    <text x="0" y="62" fill="#FFFFFF" font-size="28" font-weight="800" letter-spacing="-0.5">India Voice AI Market: $565M (2025) → $5.90B (2034)</text>
    <text x="0" y="90" fill="#94A3B8" font-size="15" font-weight="400">Compounding at 26.6% CAGR across 1.1 Billion mobile subscribers, 1,700+ GCCs, and high-growth vernacular commerce</text>
  </g>

  <!-- Left: Area Chart & Growth Curve -->
  <g transform="translate(60, 160)">
    <rect width="780" height="610" rx="16" fill="url(#cardGrad)" stroke="#1E293B" stroke-width="1.5" filter="url(#dropShadow)"/>

    <text x="30" y="38" fill="#FFFFFF" font-size="18" font-weight="800">India Conversational Voice AI Market Size Projection</text>
    <text x="30" y="58" fill="#94A3B8" font-size="13">Sources: NASSCOM • IMARC Group • MarketsandMarkets Research</text>

    <!-- Area Chart Coordinate System -->
    <g transform="translate(40, 80)">
      <!-- Background grid lines -->
      <line x1="40" y1="300" x2="680" y2="300" stroke="#334155" stroke-width="1"/>
      <line x1="40" y1="225" x2="680" y2="225" stroke="#1E293B" stroke-width="1" stroke-dasharray="4,4"/>
      <line x1="40" y1="150" x2="680" y2="150" stroke="#1E293B" stroke-width="1" stroke-dasharray="4,4"/>
      <line x1="40" y1="75" x2="680" y2="75" stroke="#1E293B" stroke-width="1" stroke-dasharray="4,4"/>
      <line x1="40" y1="0" x2="680" y2="0" stroke="#1E293B" stroke-width="1" stroke-dasharray="4,4"/>

      <!-- Y-Axis Labels -->
      <text x="30" y="304" fill="#64748B" font-size="11" font-family="{MONO_FONT}" text-anchor="end">$0B</text>
      <text x="30" y="229" fill="#64748B" font-size="11" font-family="{MONO_FONT}" text-anchor="end">$1.5B</text>
      <text x="30" y="154" fill="#64748B" font-size="11" font-family="{MONO_FONT}" text-anchor="end">$3.0B</text>
      <text x="30" y="79" fill="#64748B" font-size="11" font-family="{MONO_FONT}" text-anchor="end">$4.5B</text>
      <text x="30" y="4" fill="#00E5FF" font-size="11" font-family="{MONO_FONT}" text-anchor="end">$6.0B</text>

      <!-- Shaded Area Chart Polygon -->
      <polygon points="50,272 120,260 190,240 260,215 330,185 400,150 470,110 540,70 610,30 670,5 670,300 50,300" fill="#00E5FF" fill-opacity="0.12"/>

      <!-- Curve Line -->
      <path d="M 50 272 Q 260 220 400 150 T 670 5" fill="none" stroke="url(#geminiGrad)" stroke-width="4" filter="url(#glowCyan)"/>

      <!-- 2025 Point Marker -->
      <circle cx="50" cy="272" r="6" fill="#4285F4"/>
      <rect x="25" y="225" width="80" height="34" rx="6" fill="#131B2E" stroke="#4285F4" stroke-width="1"/>
      <text x="65" y="240" fill="#94A3B8" font-size="10" text-anchor="middle">2025</text>
      <text x="65" y="254" fill="#FFFFFF" font-size="12" font-weight="800" text-anchor="middle">$565M</text>

      <!-- 2030 Midpoint Marker -->
      <circle cx="400" cy="150" r="6" fill="#A855F7"/>
      <rect x="365" y="100" width="85" height="34" rx="6" fill="#131B2E" stroke="#A855F7" stroke-width="1"/>
      <text x="407" y="115" fill="#94A3B8" font-size="10" text-anchor="middle">2030</text>
      <text x="407" y="129" fill="#E9D5FF" font-size="12" font-weight="800" text-anchor="middle">$2.80B</text>

      <!-- 2034 Target Marker -->
      <circle cx="670" cy="5" r="8" fill="#00E5FF" filter="url(#glowCyan)"/>
      <rect x="595" y="-45" width="105" height="42" rx="8" fill="#131B2E" stroke="#00E5FF" stroke-width="1.5"/>
      <text x="647" y="-28" fill="#00E5FF" font-size="11" font-weight="700" text-anchor="middle">2034 INFLECTION</text>
      <text x="647" y="-10" fill="#34D399" font-size="15" font-weight="900" font-family="{MONO_FONT}" text-anchor="middle">$5.90 BILLION</text>

      <!-- X-Axis Labels -->
      <text x="50" y="324" fill="#94A3B8" font-size="12" font-weight="700" text-anchor="middle">2025</text>
      <text x="190" y="324" fill="#94A3B8" font-size="12" font-weight="700" text-anchor="middle">2027</text>
      <text x="330" y="324" fill="#94A3B8" font-size="12" font-weight="700" text-anchor="middle">2029</text>
      <text x="470" y="324" fill="#94A3B8" font-size="12" font-weight="700" text-anchor="middle">2031</text>
      <text x="610" y="324" fill="#94A3B8" font-size="12" font-weight="700" text-anchor="middle">2033</text>
      <text x="670" y="324" fill="#00E5FF" font-size="12" font-weight="800" text-anchor="middle">2034</text>
    </g>

    <!-- CAGR Callout Badge -->
    <g transform="translate(30, 490)">
      <rect width="720" height="85" rx="10" fill="#0B0F19" stroke="#4285F4" stroke-width="1.2"/>
      <text x="20" y="28" fill="#00E5FF" font-size="14" font-weight="800">26.6% COMPOUND ANNUAL GROWTH RATE (CAGR):</text>
      <text x="20" y="52" fill="#E2E8F0" font-size="13">India represents the fastest-growing enterprise voice AI market globally, outperforming global average CAGR (23.4%) driven by mobile vernacular adoption.</text>
    </g>
  </g>

  <!-- Right: 3 Macro Driver Cards -->
  <g transform="translate(865, 160)">
    <rect width="475" height="610" rx="16" fill="url(#cardGradHighlight)" stroke="#4285F4" stroke-width="1.5" filter="url(#dropShadow)"/>

    <text x="28" y="38" fill="#FFFFFF" font-size="18" font-weight="800">India Macro Growth Engines</text>
    <text x="28" y="58" fill="#94A3B8" font-size="13">Key tailwinds propelling voice adoption</text>

    <!-- Card 1: 1.1B Mobile Users -->
    <g transform="translate(24, 85)">
      <rect width="425" height="145" rx="12" fill="#0B0F19" stroke="#00E5FF" stroke-width="1"/>
      <circle cx="36" cy="36" r="16" fill="#00E5FF" fill-opacity="0.15"/>
      <text x="36" y="42" fill="#00E5FF" font-size="18" font-weight="800" text-anchor="middle">1.1B</text>

      <text x="68" y="30" fill="#FFFFFF" font-size="15" font-weight="800">Mobile-First Population</text>
      <text x="68" y="48" fill="#94A3B8" font-size="12">850M+ Smartphones • Voice-First Interfaces</text>

      <text x="18" y="86" fill="#CBD5E1" font-size="12">Over 70% of next-generation Indian internet users interact primarily via voice rather than typing keyboards.</text>
      <text x="18" y="112" fill="#00E5FF" font-size="12" font-weight="700">✓ Overcomes English literacy barriers in Tier 2/3/4</text>
    </g>

    <!-- Card 2: 1,700+ GCCs -->
    <g transform="translate(24, 250)">
      <rect width="425" height="145" rx="12" fill="#0B0F19" stroke="#A855F7" stroke-width="1"/>
      <circle cx="36" cy="36" r="16" fill="#A855F7" fill-opacity="0.15"/>
      <text x="36" y="42" fill="#C084FC" font-size="16" font-weight="800" text-anchor="middle">1,700</text>

      <text x="68" y="30" fill="#FFFFFF" font-size="15" font-weight="800">Global Capability Centers (GCCs)</text>
      <text x="68" y="48" fill="#94A3B8" font-size="12">Managing 45%+ of Global Contact Centers</text>

      <text x="18" y="86" fill="#CBD5E1" font-size="12">India hosts the epicenter of enterprise voice operations across global banking, technology support, and healthcare.</text>
      <text x="18" y="112" fill="#C084FC" font-size="12" font-weight="700">✓ High-volume enterprise deflection opportunity</text>
    </g>

    <!-- Card 3: ₹180 -> ₹10 Unit Economics -->
    <g transform="translate(24, 415)">
      <rect width="425" height="165" rx="12" fill="#0B0F19" stroke="#34A853" stroke-width="1.5"/>
      <circle cx="36" cy="36" r="16" fill="#34A853" fill-opacity="0.15"/>
      <text x="36" y="42" fill="#34D399" font-size="15" font-weight="800" text-anchor="middle">94%</text>

      <text x="68" y="30" fill="#FFFFFF" font-size="15" font-weight="800">Economic Unit Transformation</text>
      <text x="68" y="48" fill="#94A3B8" font-size="12">₹180 Human Call → ₹10 Google Voice AI</text>

      <text x="18" y="86" fill="#CBD5E1" font-size="12">Unlocking massive EBITDA margin expansion for FinTechs, NBFCs, and E-Commerce while scaling 24/7 capacity.</text>
      <text x="18" y="112" fill="#34D399" font-size="12" font-weight="800">✓ Gartner: $80B Global Labor Reduction</text>
    </g>
  </g>
</svg>"""
    out_file = os.path.join(ASSETS_DIR, "india_market_inflection.svg")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(svg)
    ET.fromstring(svg)
    print(f"Generated and validated {out_file}")

if __name__ == "__main__":
    build_cascade_vs_duplex()
    build_cost_advantage_10x()
    build_sub_500ms_delight()
    build_india_market_inflection()
