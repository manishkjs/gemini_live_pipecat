import os
import xml.etree.ElementTree as ET
from build_assets import SHARED_DEFS, FONT_STACK, MONO_FONT, ASSETS_DIR

def build_battlecard_matrix():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 860" width="1400" height="860" style="background-color: #0B0F19; font-family: {FONT_STACK};">
  {SHARED_DEFS}

  <!-- Canvas Background -->
  <rect width="1400" height="860" fill="url(#bgGrad)"/>
  <rect width="1400" height="860" fill="url(#gridPattern)"/>

  <!-- Header Block -->
  <g transform="translate(60, 40)">
    <rect x="0" y="0" width="220" height="28" rx="14" fill="#EA4335" fill-opacity="0.12" stroke="#EA4335" stroke-width="1.2"/>
    <circle cx="14" cy="14" r="5" fill="#EA4335"/>
    <text x="28" y="18" fill="#EA4335" font-size="12" font-weight="700" letter-spacing="1.2">COMPETITIVE BATTLECARDS</text>
    
    <text x="0" y="60" fill="#FFFFFF" font-size="28" font-weight="800" letter-spacing="-0.5">Enterprise Voice AI Architectural &amp; Feature Matrix</text>
    <text x="0" y="86" fill="#94A3B8" font-size="14" font-weight="400">Head-to-head comparison: Google Gemini Live vs OpenAI Realtime 2.1 vs ElevenLabs vs Deepgram+Groq DIY</text>
  </g>

  <!-- Table Container Card -->
  <g transform="translate(60, 140)">
    <rect width="1280" height="610" rx="14" fill="url(#cardGrad)" stroke="#1E293B" stroke-width="1.5" filter="url(#dropShadow)"/>

    <!-- Highlight column background for Google Gemini Live (Column 2) -->
    <rect x="300" y="0" width="265" height="610" rx="0" fill="#4285F4" fill-opacity="0.08" stroke="#4285F4" stroke-width="1.5"/>

    <!-- Table Header Row -->
    <g transform="translate(0, 0)">
      <rect width="1280" height="56" rx="14" fill="#131B2E" stroke="#1E293B" stroke-width="1"/>
      
      <!-- Col 1: Dimension -->
      <text x="25" y="34" fill="#94A3B8" font-size="12" font-weight="700" letter-spacing="0.5">FEATURE / METRIC</text>

      <!-- Col 2: Google Gemini Live -->
      <rect x="310" y="8" width="245" height="40" rx="8" fill="url(#cyanGrad)" filter="url(#glowCyan)"/>
      <text x="432" y="32" fill="#0B0F19" font-size="13" font-weight="900" text-anchor="middle">GOOGLE GEMINI LIVE</text>

      <!-- Col 3: OpenAI Realtime -->
      <text x="690" y="34" fill="#FFFFFF" font-size="13" font-weight="700" text-anchor="middle">OpenAI Realtime 2.1</text>

      <!-- Col 4: ElevenLabs -->
      <text x="915" y="34" fill="#FFFFFF" font-size="13" font-weight="700" text-anchor="middle">ElevenLabs Agents</text>

      <!-- Col 5: Deepgram + Groq -->
      <text x="1150" y="34" fill="#FFFFFF" font-size="13" font-weight="700" text-anchor="middle">Deepgram + Groq DIY</text>
    </g>

    <!-- Row 1: Core Architecture -->
    <g transform="translate(0, 56)">
      <line x1="0" y1="0" x2="1280" y2="0" stroke="#1E293B" stroke-width="1"/>
      <text x="25" y="36" fill="#E2E8F0" font-size="13" font-weight="700">Core Architecture</text>
      
      <text x="432" y="36" fill="#00E5FF" font-size="12" font-weight="800" text-anchor="middle">Native Multimodal S2S</text>
      <text x="690" y="36" fill="#E2E8F0" font-size="12" text-anchor="middle">Native Multimodal S2S</text>
      <text x="915" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">Cascaded Stack (STT+LLM)</text>
      <text x="1150" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">Modular Pipeline (3 APIs)</text>
    </g>

    <!-- Row 2: Turnaround Latency (TTFT) with Visual Bars -->
    <g transform="translate(0, 114)">
      <line x1="0" y1="0" x2="1280" y2="0" stroke="#1E293B" stroke-width="1"/>
      <text x="25" y="30" fill="#E2E8F0" font-size="13" font-weight="700">End-to-End Latency</text>
      <text x="25" y="46" fill="#94A3B8" font-size="11">(Time to First Audio Byte)</text>
      
      <!-- Google Bar: <500ms (Green) -->
      <rect x="330" y="16" width="90" height="26" rx="5" fill="#10B981" fill-opacity="0.3" stroke="#10B981" stroke-width="1.2"/>
      <text x="375" y="34" fill="#34D399" font-size="12" font-weight="800" font-family="{MONO_FONT}" text-anchor="middle">&lt; 500ms</text>
      <text x="495" y="34" fill="#34D399" font-size="11" font-weight="700">(Fastest)</text>

      <!-- OpenAI Bar: 750-900ms (Amber) -->
      <rect x="620" y="16" width="140" height="26" rx="5" fill="#F59E0B" fill-opacity="0.2" stroke="#F59E0B" stroke-width="1"/>
      <text x="690" y="34" fill="#FDE68A" font-size="12" font-family="{MONO_FONT}" text-anchor="middle">600ms – 900ms</text>

      <!-- ElevenLabs Bar: 2.4s (Red) -->
      <rect x="830" y="16" width="170" height="26" rx="5" fill="#EF4444" fill-opacity="0.2" stroke="#EF4444" stroke-width="1"/>
      <text x="915" y="34" fill="#FCA5A5" font-size="12" font-family="{MONO_FONT}" text-anchor="middle">2,200ms – 3,000ms</text>

      <!-- Deepgram Bar: 1.4s (Orange) -->
      <rect x="1070" y="16" width="160" height="26" rx="5" fill="#EA580C" fill-opacity="0.2" stroke="#EA580C" stroke-width="1"/>
      <text x="1150" y="34" fill="#FED7AA" font-size="12" font-family="{MONO_FONT}" text-anchor="middle">1,200ms – 1,800ms</text>
    </g>

    <!-- Row 3: Effective Hourly Cost -->
    <g transform="translate(0, 175)">
      <line x1="0" y1="0" x2="1280" y2="0" stroke="#1E293B" stroke-width="1"/>
      <text x="25" y="36" fill="#E2E8F0" font-size="13" font-weight="700">Effective Hourly Cost</text>
      
      <text x="432" y="36" fill="#34D399" font-size="13" font-weight="900" font-family="{MONO_FONT}" text-anchor="middle">$0.30 – $0.90 / hr</text>
      
      <text x="690" y="28" fill="#F87171" font-size="13" font-weight="700" font-family="{MONO_FONT}" text-anchor="middle">$2.50 – $3.60 / hr</text>
      <text x="690" y="44" fill="#EF4444" font-size="10" font-weight="700" text-anchor="middle">(4x – 10.6x Higher)</text>

      <text x="915" y="36" fill="#F87171" font-size="13" font-weight="700" font-family="{MONO_FONT}" text-anchor="middle">$4.80 – $7.20 / hr</text>
      <text x="1150" y="36" fill="#CBD5E1" font-size="13" font-family="{MONO_FONT}" text-anchor="middle">$0.80 – $1.40 / hr</text>
    </g>

    <!-- Row 4: Audio Token Output Pricing -->
    <g transform="translate(0, 235)">
      <line x1="0" y1="0" x2="1280" y2="0" stroke="#1E293B" stroke-width="1"/>
      <text x="25" y="30" fill="#E2E8F0" font-size="13" font-weight="700">Audio Output Pricing</text>
      <text x="25" y="46" fill="#94A3B8" font-size="11">(Rate per 1 Million Tokens)</text>
      
      <text x="432" y="32" fill="#00E5FF" font-size="13" font-weight="800" font-family="{MONO_FONT}" text-anchor="middle">$2.00 (Lite) / $8.00</text>
      <text x="432" y="48" fill="#34D399" font-size="11" font-weight="700" text-anchor="middle">10.6x Cost Advantage</text>

      <text x="690" y="36" fill="#EF4444" font-size="13" font-weight="700" font-family="{MONO_FONT}" text-anchor="middle">$20.00 / 1M tokens</text>
      <text x="915" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">$0.08 – $0.12 / minute</text>
      <text x="1150" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">Disjoint ASR + TTS SKUs</text>
    </g>

    <!-- Row 5: Async Tool Calling (Dead Air) -->
    <g transform="translate(0, 295)">
      <line x1="0" y1="0" x2="1280" y2="0" stroke="#1E293B" stroke-width="1"/>
      <text x="25" y="30" fill="#E2E8F0" font-size="13" font-weight="700">Asynchronous Tool Calling</text>
      <text x="25" y="46" fill="#94A3B8" font-size="11">(Behavior during CRM lookup)</text>
      
      <text x="432" y="30" fill="#00E5FF" font-size="12" font-weight="800" text-anchor="middle">Thinker-Talker Engine</text>
      <text x="432" y="46" fill="#34D399" font-size="11" font-weight="700" text-anchor="middle">✓ ZERO Dead Air Filler</text>

      <text x="690" y="30" fill="#EF4444" font-size="12" font-weight="700" text-anchor="middle">Monolithic Freeze</text>
      <text x="690" y="46" fill="#F87171" font-size="11" text-anchor="middle">❌ 3-5s Awkward Silence</text>

      <text x="915" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">Cascaded Webhook Wait</text>
      <text x="1150" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">Custom Client Glue</text>
    </g>

    <!-- Row 6: Indic Reach & Code-Switching -->
    <g transform="translate(0, 355)">
      <line x1="0" y1="0" x2="1280" y2="0" stroke="#1E293B" stroke-width="1"/>
      <text x="25" y="36" fill="#E2E8F0" font-size="13" font-weight="700">Indic &amp; Code-Switching</text>
      
      <text x="432" y="30" fill="#00E5FF" font-size="12" font-weight="800" text-anchor="middle">10+ Indic Languages SOTA</text>
      <text x="432" y="46" fill="#34D399" font-size="11" font-weight="700" text-anchor="middle">✓ Hinglish, Tanglish, Bengali</text>

      <text x="690" y="30" fill="#F59E0B" font-size="12" text-anchor="middle">Basic Hindi Only</text>
      <text x="690" y="46" fill="#F87171" font-size="11" text-anchor="middle">High WER on South Indic</text>

      <text x="915" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">Limited Indic Voices</text>
      <text x="1150" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">English-Centric ASR</text>
    </g>

    <!-- Row 7: Native Acoustic Barge-In -->
    <g transform="translate(0, 415)">
      <line x1="0" y1="0" x2="1280" y2="0" stroke="#1E293B" stroke-width="1"/>
      <text x="25" y="36" fill="#E2E8F0" font-size="13" font-weight="700">Native Acoustic Barge-in</text>
      
      <text x="432" y="36" fill="#34D399" font-size="12" font-weight="800" text-anchor="middle">✓ YES (Built-in Server VAD)</text>
      <text x="690" y="36" fill="#34D399" font-size="12" font-weight="700" text-anchor="middle">✓ YES (Built-in Server VAD)</text>
      <text x="915" y="36" fill="#EF4444" font-size="12" text-anchor="middle">❌ NO (Client VAD Cut)</text>
      <text x="1150" y="36" fill="#EF4444" font-size="12" text-anchor="middle">❌ NO (Client VAD Cut)</text>
    </g>

    <!-- Row 8: Unified Video Avatar -->
    <g transform="translate(0, 475)">
      <line x1="0" y1="0" x2="1280" y2="0" stroke="#1E293B" stroke-width="1"/>
      <text x="25" y="36" fill="#E2E8F0" font-size="13" font-weight="700">Multimodal Video Avatar</text>
      
      <text x="432" y="30" fill="#00E5FF" font-size="12" font-weight="800" text-anchor="middle">Live Avatar v2 (Unified)</text>
      <text x="432" y="46" fill="#34D399" font-size="11" font-weight="700" text-anchor="middle">✓ Single Endpoint S2S + Video</text>

      <text x="690" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">None (Audio Only)</text>
      <text x="915" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">None (Audio Only)</text>
      <text x="1150" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">Requires Tavus / HeyGen</text>
    </g>

    <!-- Row 9: Enterprise SLA & PT -->
    <g transform="translate(0, 535)">
      <line x1="0" y1="0" x2="1280" y2="0" stroke="#1E293B" stroke-width="1"/>
      <text x="25" y="36" fill="#E2E8F0" font-size="13" font-weight="700">Enterprise SLA &amp; PT Quota</text>
      
      <text x="432" y="36" fill="#34D399" font-size="12" font-weight="800" text-anchor="middle">✓ Vertex AI PT + 99.9% SLA</text>
      <text x="690" y="36" fill="#F59E0B" font-size="12" text-anchor="middle">Limited Tier Reservations</text>
      <text x="915" y="36" fill="#94A3B8" font-size="12" text-anchor="middle">Enterprise Custom</text>
      <text x="1150" y="36" fill="#EF4444" font-size="12" text-anchor="middle">3 Disjoint Vendor SLAs</text>
    </g>
  </g>

  <!-- Bottom Hero Banner Callout -->
  <g transform="translate(60, 765)">
    <rect width="1280" height="60" rx="12" fill="url(#cardGradHighlight)" stroke="#00E5FF" stroke-width="1.5"/>
    <circle cx="30" cy="30" r="10" fill="#00E5FF" fill-opacity="0.2"/>
    <circle cx="30" cy="30" r="5" fill="#00E5FF"/>
    <text x="54" y="27" fill="#00E5FF" font-size="14" font-weight="800">GOOGLE ENTERPRISE ADVANTAGE SUMMARY:</text>
    <text x="54" y="47" fill="#E2E8F0" font-size="13">10.6x Cost Advantage on Audio Output Tokens • Sub-500ms Duplex Latency • Thinker-Talker Zero Dead Air • Unified Vertex AI Enterprise SLA</text>
  </g>
</svg>"""
    out_file = os.path.join(ASSETS_DIR, "battlecard_matrix.svg")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(svg)
    ET.fromstring(svg)
    print(f"Generated and validated {out_file}")

if __name__ == "__main__":
    build_battlecard_matrix()
