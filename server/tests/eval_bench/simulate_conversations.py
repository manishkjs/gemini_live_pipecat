import os
import sys
import time
from datetime import datetime

# Set DSN if not already loaded
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from memory_function import (
    get_mem0_instance,
    process_extracted_fact,
    pre_load_user_profile,
    recall_user_memories,
)

def run_simulation():
    print("==========================================================================")
    print("🤖 LENSKART 'B' — MULTI-TURN & MULTI-HOP CONVERSATION SIMULATION BENCHMARK")
    print("==========================================================================")
    
    mem0 = get_mem0_instance()
    if not mem0:
        print("❌ ERROR: Could not connect to Mem0 engine.")
        return False

    test_user = "user:simulation_test_rohan"
    
    print(f"\nPhase 1: Simulating Turn 1 — Identity & Son Introduction ({test_user})")
    print("User says: 'Hi! My name is Rohan Sharma, and my son's name is Kabir.'")
    
    # Simulate post-session or mid-session extraction of these facts
    process_extracted_fact("User name is Rohan Sharma", "M1_Identity", test_user, is_explicit_remember=True)
    process_extracted_fact("User Rohan Sharma's son's name is Kabir", "M2_Relation", test_user, is_explicit_remember=True)
    process_extracted_fact("Kabir likes swimming and playing chess", "M3_Preference", test_user, is_explicit_remember=True)
    
    print("\nPhase 2: Verifying Path 1 Connection Pre-Load on next session connect...")
    preloaded = pre_load_user_profile(test_user)
    print(f"Path 1 Pre-loaded facts ({len(preloaded)} retrieved):")
    for f in preloaded:
        print(" ->", f)
    
    assert any("Kabir" in f for f in preloaded), "Assertion Failed: Son's name Kabir not in Path 1 pre-load!"
    print("✅ Path 1 Pre-Load exact match verified!\n")

    print("Phase 3: Simulating Turn 2 — Mentioning Upcoming Exam (Multi-turn Context)")
    print("User says: 'Kabir has his final Math exam scheduled for tomorrow morning.'")
    process_extracted_fact("User Rohan's son Kabir has his final Math exam scheduled for tomorrow morning", "M6_Recent", test_user, is_explicit_remember=True)
    
    print("\nPhase 4: Simulating Turn 3 — Multi-Hop Relational Recall ('uska exam kab hai?')")
    print("User asks: 'Can you tell me which exam my son has tomorrow and what does he like?'")
    
    recalled = recall_user_memories("son exam schedule and hobby", test_user)
    print(f"Path 2 Deep Recall facts ({len(recalled)} retrieved):")
    for r in recalled:
        print(" ->", r)
        
    assert any("Math exam" in r for r in recalled), "Assertion Failed: Math exam not retrieved in multi-hop recall!"
    assert any("swimming" in r or "chess" in r for r in recalled), "Assertion Failed: Hobby not retrieved in multi-hop recall!"
    print("✅ Path 2 Multi-Hop exact match verified!\n")
    
    print("Phase 5: Simulating Alias / Script Mismatch ('user:रोहन' -> Hindi Script)")
    hindi_user = "user:रोहन"
    print(f"Querying recall_user_memories('son exam', user_id='{hindi_user}')...")
    hindi_recall = recall_user_memories("son exam", hindi_user)
    print(f"Fallback retrieved ({len(hindi_recall)} facts):")
    for hr in hindi_recall:
        print(" ->", hr)
        
    assert any("Kabir" in hr for hr in hindi_recall), "Assertion Failed: Fallback did not resolve son Kabir for Hindi identity!"
    print("✅ Multi-tenant Script Fallback verified!\n")
    
    print("==========================================================================")
    print("🏁 ALL CONVERSATION SIMULATIONS PASSED 100% EXACT ACCURACY")
    print("==========================================================================")
    return True

if __name__ == "__main__":
    success = run_simulation()
    sys.exit(0 if success else 1)
