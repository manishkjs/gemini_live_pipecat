# 🚀 Cymbal Enterprise Sales Studio v5.0 — Final Grill-Me Implementation Plan

**Target Repository:** `manishkjs/gemini_live_pipecat`  
**Location:** `/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat`  
**Purpose:** Precise, step-by-step instructions for an autonomous coding agent to implement the finalized UI revamp agreed upon via `/grill-me`.  
**Visual Target Reference:** Open [`docs/cymbal_live_studio_prototype.html`](file:///usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/docs/cymbal_live_studio_prototype.html) in any browser.

---

## 🎯 Finalized Architectural Decisions (from `/grill-me` Interview)

1. **Header Mode Switcher (`🚀 Sales Demo Mode` vs `⚙️ Engineer Studio Mode`)**:
   - Single integrated web app. The top header features a primary toggle button pair: `[🚀 Sales Demo Mode]` (opinionated persona hub & clean canvas visualizer) and `[⚙️ Engineer Studio Mode]` (full STT/LLM/TTS pipeline sliders, JSON tool textareas, Observability dashboard).

2. **Tucked Pipeline Switcher (Flow A vs Flow B)**:
   - Pipeline selection (`⚡ Flow B: Gemini Live Native Audio ~310ms` vs `⛓️ Flow A: Cascaded STT-LLM-TTS ~850ms`) is **tucked inside the Persona Config Drawer / Tweak Menu**, keeping the main stage clean during sales pitches.

3. **HTML5 Canvas 3D Liquid Orb Visualizer**:
   - The center stage features a dynamic 3D liquid crystal sphere drawn via HTML5 `<canvas id="audioCanvas">` with real-time waveform ripples and glowing theme rings (`#f59e0b` Amber for Vikram, `#ec4899` Pink for Saathi, `#06b6d4` Cyan for Rohan).

4. **Floating Toast Notifications for Tool Execution**:
   - Tool calls (e.g. `generate_payment_link`) execute as **bottom-right floating toast alerts** (`⚙️ Executed Tool: generate_payment_link(amount=18500)`), keeping transcript text bubbles 100% clean.

---

## 📁 File Modification Checklist

| File Path | Description of Changes |
| :--- | :--- |
| [`client/index.html`](file:///usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/client/index.html) | Add Header Mode Switcher (`#btnSalesMode` / `#btnEngineerMode`), inject 3 Cymbal persona cards into `#panelDemo`, replace `.dots-container` with `#audioCanvas`, add `#toast` notification container. |
| [`client/src/app.ts`](file:///usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/client/src/app.ts) | Add `switchAppMode('sales' | 'engineer')`, `CYMBAL_PRESETS` dictionary, `applyPersonaPreset()`, toast alert trigger, and HTML5 Canvas audio loop. |
| [`client/src/style.css`](file:///usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/client/src/style.css) | Add glassmorphic card styles (`.glass-card`), glowing orb animation CSS, and toast transitions. |
| [`docs/cymbal_live_studio_prototype.html`](file:///usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/docs/cymbal_live_studio_prototype.html) | Standalone interactive prototype reflecting all Grill-Me decisions. |

---

## 🛠️ Step 1: DOM Modifications in `client/index.html`

### 1.1 Insert Header Mode Switcher in `<header>`
Find line 30 in `client/index.html` and insert the Header Mode Switcher:

```html
<!-- HEADER MODE SWITCHER -->
<div class="header-mode-switcher" style="display:flex; background:rgba(0,0,0,0.6); padding:4px; border-radius:14px; border:1px solid rgba(255,255,255,0.15);">
  <button id="btnSalesMode" onclick="window.switchAppMode('sales')" class="mode-btn active" style="padding:6px 16px; border-radius:10px; font-size:12px; font-weight:600; background:linear-gradient(90deg, #f59e0b, #dc2626); color:#fff; border:none; cursor:pointer;">
    🚀 Sales Demo Mode
  </button>
  <button id="btnEngineerMode" onclick="window.switchAppMode('engineer')" class="mode-btn" style="padding:6px 16px; border-radius:10px; font-size:12px; font-weight:500; color:#94a3b8; background:transparent; border:none; cursor:pointer;">
    ⚙️ Engineer Studio Mode
  </button>
</div>
```

### 1.2 Inject `panelDemo` Container inside `.bot-configuration`
Add the `#panelDemo` container holding the 3 Cymbal persona cards:

```html
<div id="panelDemo" class="config-panel active">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
    <h4 style="margin:0; font-size:12px; text-transform:uppercase; color:#94a3b8;">Cymbal Indian Sales Presets</h4>
    <span style="font-size:10px; color:#34d399; background:rgba(52,211,153,0.1); padding:2px 8px; border-radius:12px;">3 Presets Active</span>
  </div>

  <div class="persona-cards" style="display:flex; flex-direction:column; gap:10px;">
    
    <!-- Vikram (Debt Collection en-IN) -->
    <div id="card-vikram" onclick="window.applyPersonaPreset('vikram')" style="padding:12px; border-radius:12px; border:1px solid rgba(245,158,11,0.4); background:rgba(245,158,11,0.1); cursor:pointer;">
      <div style="display:flex; justify-content:space-between;">
        <div style="display:flex; items-center:center; gap:10px;">
          <div style="width:36px; height:36px; border-radius:50%; background:linear-gradient(135deg, #d97706, #dc2626); display:flex; items-center:center; justify-content:center; color:#fff; font-weight:bold; font-size:12px;">VK</div>
          <div>
            <div style="font-weight:600; font-size:13px; color:#fff;">Vikram — Debt Officer</div>
            <div style="font-size:11px; color:#fcd34d;">Cymbal Finance EMI Recovery (en-IN Male)</div>
          </div>
        </div>
        <span style="width:8px; height:8px; border-radius:50%; background:#34d399;"></span>
      </div>
      <p style="font-size:11px; color:#94a3b8; margin:8px 0 0 0; line-height:1.4;">Firm, polite reminder for ₹18,500 overdue EMI. Offers instant UPI payment link generation.</p>
    </div>

    <!-- Saathi (Her Vibe Companion hi-IN) -->
    <div id="card-saathi" onclick="window.applyPersonaPreset('saathi')" style="padding:12px; border-radius:12px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.03); cursor:pointer;">
      <div style="display:flex; justify-content:space-between;">
        <div style="display:flex; items-center:center; gap:10px;">
          <div style="width:36px; height:36px; border-radius:50%; background:linear-gradient(135deg, #ec4899, #9333ea); display:flex; items-center:center; justify-content:center; color:#fff; font-weight:bold; font-size:12px;">ST</div>
          <div>
            <div style="font-weight:600; font-size:13px; color:#fff;">Saathi — AI Companion</div>
            <div style="font-size:11px; color:#f472b6;">'Her' Movie Vibe (hi-IN Female)</div>
          </div>
        </div>
      </div>
      <p style="font-size:11px; color:#94a3b8; margin:8px 0 0 0; line-height:1.4;">Charming, warm, poetic Hindi/Hinglish companion. Listens deeply and logs emotional mood.</p>
    </div>

    <!-- Rohan (Retail Support en-IN) -->
    <div id="card-rohan" onclick="window.applyPersonaPreset('rohan')" style="padding:12px; border-radius:12px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.03); cursor:pointer;">
      <div style="display:flex; justify-content:space-between;">
        <div style="display:flex; items-center:center; gap:10px;">
          <div style="width:36px; height:36px; border-radius:50%; background:linear-gradient(135deg, #06b6d4, #2563eb); display:flex; items-center:center; justify-content:center; color:#fff; font-weight:bold; font-size:12px;">RH</div>
          <div>
            <div style="font-weight:600; font-size:13px; color:#fff;">Rohan — Retail Support</div>
            <div style="font-size:11px; color:#38bdf8;">Cymbal Retail Concierge (en-IN Support)</div>
          </div>
        </div>
      </div>
      <p style="font-size:11px; color:#94a3b8; margin:8px 0 0 0; line-height:1.4;">Fast Indian English support. Checks order #CYM-8821 & initiates label-free doorstep returns.</p>
    </div>

  </div>
</div>
```

### 1.3 Add Bottom-Right Toast Notification Container
Before `</body>`, insert the `#toast` notification element:

```html
<!-- FLOATING TOAST NOTIFICATION FOR TOOL EXECUTION -->
<div id="toast" style="position:fixed; bottom:24px; right:24px; padding:12px 18px; border-radius:14px; background:#0891b2; color:#fff; font-size:12px; opacity:0; pointer-events:none; transition:all 0.3s ease; transform:translateY(10px); z-index:999; display:flex; align-items:center; gap:10px; border:1px solid rgba(255,255,255,0.2); box-shadow:0 10px 25px rgba(0,0,0,0.5);">
  <span style="font-size:16px;">⚙️</span>
  <div>
    <div style="font-weight:bold;" id="toastTitle">Tool Executed</div>
    <div style="font-family:monospace; font-size:11px;" id="toastMsg">generate_payment_link(amount=18500)</div>
  </div>
</div>
```

---

## 💻 Step 2: TypeScript Handlers in `client/src/app.ts`

Add `switchAppMode()` and `showToast()` to `client/src/app.ts`:

```typescript
export function switchAppMode(mode: 'sales' | 'engineer') {
  const btnSales = document.getElementById('btnSalesMode');
  const btnEng = document.getElementById('btnEngineerMode');
  const panelDemo = document.getElementById('panelDemo');
  const geminiLivePanel = document.getElementById('gemini-live-panel');

  if (mode === 'sales') {
    if (btnSales) {
      btnSales.style.background = 'linear-gradient(90deg, #f59e0b, #dc2626)';
      btnSales.style.color = '#ffffff';
    }
    if (btnEng) {
      btnEng.style.background = 'transparent';
      btnEng.style.color = '#94a3b8';
    }
    if (panelDemo) panelDemo.style.display = 'block';
    if (geminiLivePanel) geminiLivePanel.style.display = 'none';
    showToast('Activated 🚀 Sales Demo Mode', 'Full persona hub & clean voice orb loaded.');
  } else {
    if (btnEng) {
      btnEng.style.background = 'linear-gradient(90deg, #9333ea, #db2777)';
      btnEng.style.color = '#ffffff';
    }
    if (btnSales) {
      btnSales.style.background = 'transparent';
      btnSales.style.color = '#94a3b8';
    }
    if (panelDemo) panelDemo.style.display = 'none';
    if (geminiLivePanel) geminiLivePanel.style.display = 'block';
    showToast('Activated ⚙️ Engineer Studio Mode', 'Full pipeline sliders & JSON tool editors loaded.');
  }
}

export function showToast(title: string, msg: string) {
  const toast = document.getElementById('toast');
  const tTitle = document.getElementById('toastTitle');
  const tMsg = document.getElementById('toastMsg');

  if (toast && tTitle && tMsg) {
    tTitle.innerText = title;
    tMsg.innerText = msg;
    toast.style.opacity = '1';
    toast.style.transform = 'translateY(0px)';
    toast.style.pointerEvents = 'auto';

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      toast.style.pointerEvents = 'none';
    }, 3000);
  }
}

(window as any).switchAppMode = switchAppMode;
(window as any).showToast = showToast;
```

---

## 🧪 Verification & Final Target Reference

Open [`docs/cymbal_live_studio_prototype.html`](file:///usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/docs/cymbal_live_studio_prototype.html) in your web browser. Test toggling between `🚀 Sales Demo Mode` and `⚙️ Engineer Studio Mode` at the top header, select personas, and observe the bottom-right toast alerts when simulating conversation turns!
