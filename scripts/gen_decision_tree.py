import os
import xml.etree.ElementTree as ET
from build_assets import SHARED_DEFS, FONT_STACK, MONO_FONT, ASSETS_DIR

def build_decision_tree():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 840" width="1400" height="840" style="background-color: #0B0F19; font-family: {FONT_STACK};">
  {SHARED_DEFS}

  <!-- Canvas Background -->
  <rect width="1400" height="840" fill="url(#bgGrad)"/>
  <rect width="1400" height="840" fill="url(#gridPattern)"/>

  <!-- Header Block -->
  <g transform="translate(60, 45)">
    <rect x="0" y="0" width="260" height="28" rx="14" fill="#4285F4" fill-opacity="0.12" stroke="#4285F4" stroke-width="1.2"/>
    <circle cx="14" cy="14" r="5" fill="#4285F4"/>
    <text x="28" y="18" fill="#4285F4" font-size="12" font-weight="700" letter-spacing="1.2">WORKLOAD ARCHITECTURE MATRIX</text>
    
    <text x="0" y="62" fill="#FFFFFF" font-size="28" font-weight="800" letter-spacing="-0.5">Enterprise Voice AI 3-Way Workload Decision Tree</text>
    <text x="0" y="90" fill="#94A3B8" font-size="15" font-weight="400">Guiding CEs and FSRs to the optimal conversational architecture based on compliance, latency, and prosody requirements</text>
  </g>

  <!-- Root Intake Node -->
  <g transform="translate(480, 150)">
    <rect width="440" height="74" rx="12" fill="url(#cardGradHighlight)" stroke="#4285F4" stroke-width="2" filter="url(#dropShadow)"/>
    <circle cx="24" cy="37" r="10" fill="#4285F4" fill-opacity="0.2"/>
    <circle cx="24" cy="37" r="5" fill="#4285F4"/>
    <text x="48" y="32" fill="#FFFFFF" font-size="16" font-weight="800" letter-spacing="0.5">ENTERPRISE VOICE WORKLOAD INTAKE</text>
    <text x="48" y="54" fill="#94A3B8" font-size="13">Evaluate: Latency SLA • Regulatory DLP • Turn-Taking • Custom Dicts</text>
  </g>

  <!-- Connector Paths from Root to 3 Branches -->
  <!-- Left Path to Dialogflow CX -->
  <path d="M 520 224 L 520 270 Q 520 290 490 290 L 260 290 Q 230 290 230 310 L 230 340" fill="none" stroke="#FBBC04" stroke-width="2.5" marker-end="url(#arrowAmber)"/>

  <!-- Center Path to Modular Cascade -->
  <path d="M 700 224 L 700 340" fill="none" stroke="#A855F7" stroke-width="2.5" marker-end="url(#arrowPurple)"/>

  <!-- Right Path to Gemini Live -->
  <path d="M 880 224 L 880 270 Q 880 290 910 290 L 1140 290 Q 1170 290 1170 310 L 1170 340" fill="none" stroke="#00E5FF" stroke-width="2.5" marker-end="url(#arrowCyan)"/>

  <!-- Decision Node 1 (Left - Amber) -->
  <g transform="translate(60, 350)">
    <!-- Card Container -->
    <rect width="380" height="430" rx="14" fill="url(#cardGrad)" stroke="#FBBC04" stroke-width="1.5" filter="url(#dropShadow)"/>
    
    <!-- Top Pill -->
    <rect x="24" y="20" width="160" height="24" rx="12" fill="#FBBC04" fill-opacity="0.15" stroke="#FBBC04" stroke-width="1"/>
    <text x="104" y="36" fill="#FDE68A" font-size="11" font-weight="700" text-anchor="middle">FIXED DETERMINISTIC IVR</text>

    <text x="24" y="72" fill="#FFFFFF" font-size="20" font-weight="800">Dialogflow CX</text>
    <text x="24" y="94" fill="#94A3B8" font-size="13">Visual State Machines &amp; Fixed Intents</text>

    <line x1="24" y1="110" x2="356" y2="110" stroke="#1E293B" stroke-width="1"/>

    <!-- Key Workload Criteria -->
    <text x="24" y="134" fill="#FBBC04" font-size="12" font-weight="700">WHEN TO PITCH THIS ARCHITECTURE:</text>
    <text x="24" y="158" fill="#E2E8F0" font-size="13">• Zero LLM drift or hallucination tolerated</text>
    <text x="24" y="180" fill="#E2E8F0" font-size="13">• Legacy DTMF keypress + simple speech</text>
    <text x="24" y="202" fill="#E2E8F0" font-size="13">• Fixed visual tree compliance flows</text>
    <text x="24" y="224" fill="#E2E8F0" font-size="13">• Deterministic CRM webhook routing</text>

    <!-- Specs Box -->
    <rect x="24" y="246" width="332" height="150" rx="10" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
    <g transform="translate(40, 268)">
      <text x="0" y="0" fill="#94A3B8" font-size="11">TURNAROUND LATENCY</text>
      <text x="0" y="18" fill="#FDE68A" font-size="14" font-weight="700" font-family="{MONO_FONT}">800ms – 1,500ms</text>

      <text x="0" y="44" fill="#94A3B8" font-size="11">COMMERCIAL UNIT COST</text>
      <text x="0" y="62" fill="#FDE68A" font-size="14" font-weight="700" font-family="{MONO_FONT}">$0.007 / Turn</text>

      <text x="0" y="88" fill="#94A3B8" font-size="11">TARGET WORKLOADS</text>
      <text x="0" y="106" fill="#E2E8F0" font-size="12">Banking OTPs • Order Status • Basic FAQ</text>
    </g>
  </g>

  <!-- Decision Node 2 (Middle - Purple) -->
  <g transform="translate(510, 350)">
    <!-- Card Container -->
    <rect width="380" height="430" rx="14" fill="url(#cardGrad)" stroke="#A855F7" stroke-width="1.5" filter="url(#dropShadow)"/>
    
    <!-- Top Pill -->
    <rect x="24" y="20" width="190" height="24" rx="12" fill="#A855F7" fill-opacity="0.15" stroke="#A855F7" stroke-width="1"/>
    <text x="119" y="36" fill="#E9D5FF" font-size="11" font-weight="700" text-anchor="middle">STRICT PII &amp; DICTIONARIES</text>

    <text x="24" y="72" fill="#FFFFFF" font-size="20" font-weight="800">Modular Cascade</text>
    <text x="24" y="94" fill="#94A3B8" font-size="13">Chirp 2 USM → Gemini Flash → Chirp 3 HD</text>

    <line x1="24" y1="110" x2="356" y2="110" stroke="#1E293B" stroke-width="1"/>

    <!-- Key Workload Criteria -->
    <text x="24" y="134" fill="#C084FC" font-size="12" font-weight="700">WHEN TO PITCH THIS ARCHITECTURE:</text>
    <text x="24" y="158" fill="#E2E8F0" font-size="13">• Hard PII text redaction before LLM (DLP)</text>
    <text x="24" y="180" fill="#E2E8F0" font-size="13">• Rare pharma / SKU class phrase biasing</text>
    <text x="24" y="202" fill="#E2E8F0" font-size="13">• Noisy 8kHz PSTN narrowband telephony</text>
    <text x="24" y="224" fill="#E2E8F0" font-size="13">• Exact statutory legal audio disclaimers</text>

    <!-- Specs Box -->
    <rect x="24" y="246" width="332" height="150" rx="10" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
    <g transform="translate(40, 268)">
      <text x="0" y="0" fill="#94A3B8" font-size="11">TURNAROUND LATENCY</text>
      <text x="0" y="18" fill="#E9D5FF" font-size="14" font-weight="700" font-family="{MONO_FONT}">2.5s – 2.85s (Cumulative)</text>

      <text x="0" y="44" fill="#94A3B8" font-size="11">COMMERCIAL UNIT COST</text>
      <text x="0" y="62" fill="#E9D5FF" font-size="14" font-weight="700" font-family="{MONO_FONT}">$1.12 – $2.50+ / Hour</text>

      <text x="0" y="88" fill="#94A3B8" font-size="11">TARGET WORKLOADS</text>
      <text x="0" y="106" fill="#E2E8F0" font-size="12">Healthcare Rx • FinTech KYC • Audited IVR</text>
    </g>
  </g>

  <!-- Decision Node 3 (Right - Google Cyan/Blue Highlight) -->
  <g transform="translate(960, 350)">
    <!-- Card Container Highlighted -->
    <rect width="380" height="430" rx="14" fill="url(#cardGradHighlight)" stroke="#00E5FF" stroke-width="2" filter="url(#dropShadow)"/>
    
    <!-- Top Pill Highlight -->
    <rect x="24" y="20" width="200" height="24" rx="12" fill="#00E5FF" fill-opacity="0.2" stroke="#00E5FF" stroke-width="1.2"/>
    <text x="124" y="36" fill="#00E5FF" font-size="11" font-weight="800" text-anchor="middle">DELIGHT &amp; CONVERSATIONAL S2S</text>

    <text x="24" y="72" fill="#FFFFFF" font-size="20" font-weight="800">Gemini Live (S2S)</text>
    <text x="24" y="94" fill="#00E5FF" font-size="13">Native Bidirectional Thinker-Talker Engine</text>

    <line x1="24" y1="110" x2="356" y2="110" stroke="#1E293B" stroke-width="1"/>

    <!-- Key Workload Criteria -->
    <text x="24" y="134" fill="#00E5FF" font-size="12" font-weight="700">WHEN TO PITCH THIS ARCHITECTURE:</text>
    <text x="24" y="158" fill="#E2E8F0" font-size="13">• Conversational intimacy &amp; acoustic prosody</text>
    <text x="24" y="180" fill="#E2E8F0" font-size="13">• Sub-500ms speed with natural barge-in</text>
    <text x="24" y="202" fill="#E2E8F0" font-size="13">• Fluent Indic code-switching (10+ langs)</text>
    <text x="24" y="224" fill="#E2E8F0" font-size="13">• Continuous narration during async tools</text>

    <!-- Specs Box -->
    <rect x="24" y="246" width="332" height="150" rx="10" fill="#0B0F19" stroke="#00E5FF" stroke-width="1" stroke-opacity="0.4"/>
    <g transform="translate(40, 268)">
      <text x="0" y="0" fill="#94A3B8" font-size="11">TURNAROUND LATENCY</text>
      <text x="0" y="18" fill="#34D399" font-size="14" font-weight="800" font-family="{MONO_FONT}">&lt; 500ms TTFT (Sub-Second)</text>

      <text x="0" y="44" fill="#94A3B8" font-size="11">COMMERCIAL UNIT COST</text>
      <text x="0" y="62" fill="#34D399" font-size="14" font-weight="800" font-family="{MONO_FONT}">$0.30 – $0.90 / Hour (10.6x Lead)</text>

      <text x="0" y="88" fill="#94A3B8" font-size="11">TARGET WORKLOADS</text>
      <text x="0" y="106" fill="#E2E8F0" font-size="12">VIP Concierge • EdTech Coach • Hearables</text>
    </g>
  </g>
</svg>"""
    out_file = os.path.join(ASSETS_DIR, "decision_tree.svg")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(svg)
    ET.fromstring(svg)
    print(f"Generated and validated {out_file}")

if __name__ == "__main__":
    build_decision_tree()
