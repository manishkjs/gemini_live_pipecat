#!/usr/bin/env python3
import os
import sys
import xml.etree.ElementTree as ET

ASSETS_DIR = "/usr/local/google/home/manishkjs/Downloads/Code/gemini_live_pipecat/presentation/assets"

REQUIRED_ASSETS = [
    "latency_waterfall.svg",
    "decision_tree.svg",
    "enterprise_logos_4quadrant.svg",
    "battlecard_matrix.svg",
    "cascade_vs_duplex.svg",
    "cost_advantage_10x.svg",
    "sub_500ms_delight.svg",
    "india_market_inflection.svg",
]

def verify_all():
    print("=" * 80)
    print("VALIDATING PRESENTATION SVG ASSETS SUITE")
    print("=" * 80)
    
    all_ok = True
    for asset_name in REQUIRED_ASSETS:
        path = os.path.join(ASSETS_DIR, asset_name)
        if not os.path.exists(path):
            print(f"❌ [MISSING] {asset_name} not found in {ASSETS_DIR}")
            all_ok = False
            continue
        
        file_size = os.path.getsize(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # 1. XML parse test
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            print(f"❌ [XML PARSE ERROR] {asset_name}: {e}")
            all_ok = False
            continue
            
        # 2. Attribute checks
        viewbox = root.attrib.get("viewBox")
        width = root.attrib.get("width")
        height = root.attrib.get("height")
        
        if not viewbox or not width or not height:
            print(f"❌ [ATTR ERROR] {asset_name} missing viewBox/width/height: {root.attrib}")
            all_ok = False
            continue
            
        # 3. Check Google AI Dark Theme Tokens
        has_dark_bg = "#0B0F19" in content or "#0b0f19" in content or "bgGrad" in content
        has_accent = any(color in content for color in ["#00E5FF", "#4285F4", "#34A853", "#10B981", "#A855F7"])
        
        if not has_dark_bg or not has_accent:
            print(f"❌ [THEME WARNING] {asset_name} missing expected dark theme or accent tokens")
            all_ok = False
            continue
            
        print(f"✅ [PASSED] {asset_name:<32} | {file_size/1024:5.1f} KB | {width}x{height} | viewBox='{viewbox}'")

    print("=" * 80)
    if all_ok:
        print(f"🎉 ALL {len(REQUIRED_ASSETS)} SVG ASSETS VERIFIED PERFECTLY!")
        return 0
    else:
        print("❌ SOME SVG ASSETS FAILED VERIFICATION.")
        return 1

if __name__ == "__main__":
    sys.exit(verify_all())
