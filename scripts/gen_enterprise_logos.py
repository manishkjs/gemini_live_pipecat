import os
import xml.etree.ElementTree as ET
from build_assets import SHARED_DEFS, FONT_STACK, MONO_FONT, ASSETS_DIR

def build_enterprise_logos():
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 840" width="1400" height="840" style="background-color: #0B0F19; font-family: {FONT_STACK};">
  {SHARED_DEFS}

  <!-- Canvas Background -->
  <rect width="1400" height="840" fill="url(#bgGrad)"/>
  <rect width="1400" height="840" fill="url(#gridPattern)"/>

  <!-- Header Block -->
  <g transform="translate(60, 45)">
    <rect x="0" y="0" width="260" height="28" rx="14" fill="#34A853" fill-opacity="0.12" stroke="#34A853" stroke-width="1.2"/>
    <circle cx="14" cy="14" r="5" fill="#34A853"/>
    <text x="28" y="18" fill="#34A853" font-size="12" font-weight="700" letter-spacing="1.2">ENTERPRISE PROVEN DEPLOYMENTS</text>
    
    <text x="0" y="62" fill="#FFFFFF" font-size="28" font-weight="800" letter-spacing="-0.5">4-Quadrant Enterprise Logo &amp; Architectural Showcase</text>
    <text x="0" y="90" fill="#94A3B8" font-size="15" font-weight="400">Proven production voice AI architectures powering India's leading enterprises, consumer electronics, and global tech platforms</text>
  </g>

  <!-- 4-Quadrant Container Cards -->
  
  <!-- Quadrant 1: BFSI & Debt Collections (Top-Left) -->
  <g transform="translate(60, 160)">
    <rect width="620" height="300" rx="14" fill="url(#cardGrad)" stroke="#F59E0B" stroke-width="1.5" filter="url(#dropShadow)"/>
    
    <!-- Quadrant Header -->
    <rect x="24" y="20" width="220" height="24" rx="12" fill="#F59E0B" fill-opacity="0.15" stroke="#F59E0B" stroke-width="1"/>
    <text x="134" y="36" fill="#FDE68A" font-size="11" font-weight="700" text-anchor="middle">QUADRANT 1: BFSI &amp; DEBT</text>
    <text x="24" y="70" fill="#FFFFFF" font-size="19" font-weight="800">Financial Services &amp; Collections</text>

    <!-- Verified Logos Row -->
    <g transform="translate(24, 88)">
      <!-- Logo 1: Groww -->
      <rect x="0" y="0" width="130" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <circle cx="22" cy="21" r="10" fill="#00D09C"/>
      <text x="42" y="26" fill="#FFFFFF" font-size="14" font-weight="800">Groww</text>

      <!-- Logo 2: LendenClub -->
      <rect x="145" y="0" width="145" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <rect x="157" y="12" width="18" height="18" rx="4" fill="#3B82F6"/>
      <text x="183" y="26" fill="#FFFFFF" font-size="13" font-weight="800">LendenClub</text>

      <!-- Logo 3: Cymbal Lending -->
      <rect x="305" y="0" width="155" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <circle cx="323" cy="21" r="9" fill="#F59E0B"/>
      <text x="340" y="26" fill="#FFFFFF" font-size="13" font-weight="800">Cymbal Lending</text>
    </g>

    <!-- Use Cases & Tech Invariant -->
    <g transform="translate(24, 150)">
      <text x="0" y="16" fill="#FDE68A" font-size="12" font-weight="700">CORE WORKFLOWS:</text>
      <text x="0" y="36" fill="#E2E8F0" font-size="13">• Automated debt restructuring &amp; Hinglish EMI negotiation</text>
      <text x="0" y="56" fill="#E2E8F0" font-size="13">• Dynamic loan pre-qualification &amp; secure KYC OTP validation</text>

      <line x1="0" y1="74" x2="572" y2="74" stroke="#1E293B" stroke-width="1"/>

      <text x="0" y="98" fill="#94A3B8" font-size="11" font-weight="700">TECHNICAL INVARIANT:</text>
      <text x="0" y="118" fill="#CBD5E1" font-size="12">Deterministic numeric ledger preventing conflicting quotes • RBI compliance audit trail</text>
      <text x="0" y="136" fill="#10B981" font-size="12" font-weight="700">✓ 94.4% Cost Reduction (₹180 → ₹10 per call) • +22% Recovery Rate</text>
    </g>
  </g>

  <!-- Quadrant 2: Consumer Hardware & IoT (Top-Right) -->
  <g transform="translate(720, 160)">
    <rect width="620" height="300" rx="14" fill="url(#cardGrad)" stroke="#00E5FF" stroke-width="1.5" filter="url(#dropShadow)"/>
    
    <!-- Quadrant Header -->
    <rect x="24" y="20" width="220" height="24" rx="12" fill="#00E5FF" fill-opacity="0.15" stroke="#00E5FF" stroke-width="1"/>
    <text x="134" y="36" fill="#00E5FF" font-size="11" font-weight="700" text-anchor="middle">QUADRANT 2: HARDWARE &amp; IOT</text>
    <text x="24" y="70" fill="#FFFFFF" font-size="19" font-weight="800">Consumer Hearables &amp; Smart Devices</text>

    <!-- Verified Logos Row -->
    <g transform="translate(24, 88)">
      <!-- Logo 1: boAt -->
      <rect x="0" y="0" width="120" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <path d="M 22 26 L 32 14 L 38 26 z" fill="#EF4444"/>
      <text x="45" y="27" fill="#FFFFFF" font-size="16" font-weight="900" letter-spacing="1">boAt</text>

      <!-- Logo 2: MIVI -->
      <rect x="135" y="0" width="120" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <text x="195" y="27" fill="#FFFFFF" font-size="15" font-weight="900" text-anchor="middle" letter-spacing="2">MIVI</text>

      <!-- Logo 3: Noise -->
      <rect x="270" y="0" width="120" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <circle cx="288" cy="21" r="8" fill="#00E5FF"/>
      <text x="306" y="26" fill="#FFFFFF" font-size="14" font-weight="800">Noise</text>
    </g>

    <!-- Use Cases & Tech Invariant -->
    <g transform="translate(24, 150)">
      <text x="0" y="16" fill="#00E5FF" font-size="12" font-weight="700">CORE WORKFLOWS:</text>
      <text x="0" y="36" fill="#E2E8F0" font-size="13">• Hands-free ANC controls &amp; contextual smart hearable assistant</text>
      <text x="0" y="56" fill="#E2E8F0" font-size="13">• Ultra-low power voice triggers for smart home &amp; connected TV</text>

      <line x1="0" y1="74" x2="572" y2="74" stroke="#1E293B" stroke-width="1"/>

      <text x="0" y="98" fill="#94A3B8" font-size="11" font-weight="700">TECHNICAL INVARIANT:</text>
      <text x="0" y="118" fill="#CBD5E1" font-size="12">Sub-400ms TTFT • Robust Edge DSP noise suppression in loud Indian traffic</text>
      <text x="0" y="136" fill="#10B981" font-size="12" font-weight="700">✓ 10M+ Monthly Voice Interventions • Flawless AEC Acoustic Performance</text>
    </g>
  </g>

  <!-- Quadrant 3: Education & Communication Coaching (Bottom-Left) -->
  <g transform="translate(60, 480)">
    <rect width="620" height="300" rx="14" fill="url(#cardGrad)" stroke="#A855F7" stroke-width="1.5" filter="url(#dropShadow)"/>
    
    <!-- Quadrant Header -->
    <rect x="24" y="20" width="220" height="24" rx="12" fill="#A855F7" fill-opacity="0.15" stroke="#A855F7" stroke-width="1"/>
    <text x="134" y="36" fill="#E9D5FF" font-size="11" font-weight="700" text-anchor="middle">QUADRANT 3: EDTECH &amp; COACHING</text>
    <text x="24" y="70" fill="#FFFFFF" font-size="19" font-weight="800">Communication &amp; Fluency Coaching</text>

    <!-- Verified Logos Row -->
    <g transform="translate(24, 88)">
      <!-- Logo 1: Yoodli -->
      <rect x="0" y="0" width="130" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <circle cx="20" cy="21" r="9" fill="#A855F7"/>
      <text x="38" y="26" fill="#FFFFFF" font-size="14" font-weight="800">Yoodli</text>

      <!-- Logo 2: HeyAto -->
      <rect x="145" y="0" width="130" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <circle cx="165" cy="21" r="9" fill="#EC4899"/>
      <text x="183" y="26" fill="#FFFFFF" font-size="14" font-weight="800">HeyAto</text>

      <!-- Logo 3: Vernacular EdTech -->
      <rect x="290" y="0" width="170" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <rect x="302" y="13" width="16" height="16" rx="3" fill="#8B5CF6"/>
      <text x="326" y="26" fill="#FFFFFF" font-size="12" font-weight="800">Vernacular EdTech</text>
    </g>

    <!-- Use Cases & Tech Invariant -->
    <g transform="translate(24, 150)">
      <text x="0" y="16" fill="#E9D5FF" font-size="12" font-weight="700">CORE WORKFLOWS:</text>
      <text x="0" y="36" fill="#E2E8F0" font-size="13">• Real-time spoken English fluency coaching &amp; mock interview prep</text>
      <text x="0" y="56" fill="#E2E8F0" font-size="13">• Multi-dialect pronunciation guidance with instant emotional feedback</text>

      <line x1="0" y1="74" x2="572" y2="74" stroke="#1E293B" stroke-width="1"/>

      <text x="0" y="98" fill="#94A3B8" font-size="11" font-weight="700">TECHNICAL INVARIANT:</text>
      <text x="0" y="118" fill="#CBD5E1" font-size="12">Acoustic prosody analysis • Natural barge-in and cadence correction</text>
      <text x="0" y="136" fill="#10B981" font-size="12" font-weight="700">✓ 98% Pronunciation Accuracy • Warm Human Persona with Zero Robot Tone</text>
    </g>
  </g>

  <!-- Quadrant 4: E-Commerce & Enterprise Support (Bottom-Right) -->
  <g transform="translate(720, 480)">
    <rect width="620" height="300" rx="14" fill="url(#cardGrad)" stroke="#34A853" stroke-width="1.5" filter="url(#dropShadow)"/>
    
    <!-- Quadrant Header -->
    <rect x="24" y="20" width="220" height="24" rx="12" fill="#34A853" fill-opacity="0.15" stroke="#34A853" stroke-width="1"/>
    <text x="134" y="36" fill="#86EFAC" font-size="11" font-weight="700" text-anchor="middle">QUADRANT 4: E-COMMERCE &amp; CRM</text>
    <text x="24" y="70" fill="#FFFFFF" font-size="19" font-weight="800">VIP Concierge &amp; Enterprise Support</text>

    <!-- Verified Logos Row -->
    <g transform="translate(24, 88)">
      <!-- Logo 1: Lenskart 'B' -->
      <rect x="0" y="0" width="150" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <circle cx="20" cy="21" r="10" fill="#34A853"/>
      <text x="38" y="26" fill="#FFFFFF" font-size="14" font-weight="800">Lenskart 'B'</text>

      <!-- Logo 2: KaptureCX -->
      <rect x="165" y="0" width="135" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <rect x="177" y="12" width="18" height="18" rx="4" fill="#06B6D4"/>
      <text x="203" y="26" fill="#FFFFFF" font-size="13" font-weight="800">KaptureCX</text>

      <!-- Logo 3: Nurix AI -->
      <rect x="315" y="0" width="135" height="42" rx="8" fill="#0B0F19" stroke="#334155" stroke-width="1"/>
      <circle cx="333" cy="21" r="9" fill="#10B981"/>
      <text x="350" y="26" fill="#FFFFFF" font-size="13" font-weight="800">Nurix AI</text>
    </g>

    <!-- Use Cases & Tech Invariant -->
    <g transform="translate(24, 150)">
      <text x="0" y="16" fill="#86EFAC" font-size="12" font-weight="700">CORE WORKFLOWS:</text>
      <text x="0" y="36" fill="#E2E8F0" font-size="13">• Long-term contextual memory shopping concierge &amp; frame stylist</text>
      <text x="0" y="56" fill="#E2E8F0" font-size="13">• Omnichannel customer support, delivery tracking &amp; eye test booking</text>

      <line x1="0" y1="74" x2="572" y2="74" stroke="#1E293B" stroke-width="1"/>

      <text x="0" y="98" fill="#94A3B8" font-size="11" font-weight="700">TECHNICAL INVARIANT:</text>
      <text x="0" y="118" fill="#CBD5E1" font-size="12">Dual-threshold pgvector (0.83 dedup / 0.40 recall) • AntiCancel tool shields</text>
      <text x="0" y="136" fill="#10B981" font-size="12" font-weight="700">✓ Zero Dead Air During CRM Lookups • Continuous Fluent Narration</text>
    </g>
  </g>
</svg>"""
    out_file = os.path.join(ASSETS_DIR, "enterprise_logos_4quadrant.svg")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(svg)
    ET.fromstring(svg)
    print(f"Generated and validated {out_file}")

if __name__ == "__main__":
    build_enterprise_logos()
