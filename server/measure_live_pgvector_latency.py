import os
import time
import json
import statistics
from datetime import datetime

import sys
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

if not os.getenv("CLOUDSQL_PG_DSN"):
    print("❌ ERROR: CLOUDSQL_PG_DSN not set in .env or environment!")
    sys.exit(1)

from memory_function import (
    get_mem0_instance,
    pre_load_user_profile,
    recall_user_memories,
    process_extracted_fact,
)

def run_latency_benchmark():
    print("==========================================================================")
    print("🚀 LENSKART 'B' MEMORY ENGINE — EXACT LATENCY BENCHMARK (CLOUD SQL PGVECTOR)")
    print("==========================================================================")
    print(f"Target Database: Cloud SQL PostgreSQL (instance: vertex-router-db @ 136.114.180.75)")
    print(f"Connection DSN : {os.environ['CLOUDSQL_PG_DSN'].split('@')[1]}")
    print("--------------------------------------------------------------------------\n")

    mem0 = get_mem0_instance()
    if not mem0:
        print("❌ ERROR: Could not initialize Mem0 engine against Cloud SQL!")
        return

    test_user = "user:latency_bench_rohan"
    
    # 1. Seeding / Warmup
    print("1️⃣ Seeding baseline memories into Cloud SQL pgvector table...")
    seed_facts = [
        ("User name is Rohan Sharma, works at Lenskart HQ in Gurgaon", "M1_Identity"),
        ("Spouse name is Priya, she prefers titanium frames and vegetarian food", "M2_Relation"),
        ("Always orders black coffee without sugar when at Connaught Place cafe", "M3_Preference"),
        ("Wants a 12-month tenure for any frame replacement EMI plan", "M3_Preference"),
        ("Prefers rimless glasses for daily office wear, blue light filter mandatory", "M3_Preference"),
        ("Severe peanut allergy — never recommend snacks with nuts", "M7_Safety"),
        ("Meeting with supplier scheduled at CP office tomorrow 3 PM", "M6_Recent"),
        ("Bought Lenskart Air glasses in March 2025, prescription is -2.25 both eyes", "M4_Behavioral"),
    ]
    
    start_seed = time.time()
    for text, cat in seed_facts:
        process_extracted_fact(text, cat, test_user, is_explicit_remember=True)
    seed_dur = time.time() - start_seed
    print(f"✅ Seeding complete: {len(seed_facts)} facts seeded in {seed_dur:.2f}s total.\n")

    # 2. Measure Path 1: Connection Pre-Load (`pre_load_user_profile`)
    print("2️⃣ Measuring Path 1: Connection Pre-Load Latency (Target Budget: ~35–40ms)")
    path1_times = []
    for i in range(10):
        t0 = time.perf_counter()
        facts = pre_load_user_profile(test_user)
        t1 = time.perf_counter()
        path1_times.append((t1 - t0) * 1000.0) # ms
    
    p50_p1 = statistics.median(path1_times)
    p95_p1 = sorted(path1_times)[int(len(path1_times) * 0.95)]
    p99_p1 = max(path1_times)
    print(f"   ► Path 1 Pre-Load Latency over 10 runs (Retrieved {len(facts)} active facts):")
    print(f"     • p50 (Median) : {p50_p1:.2f} ms")
    print(f"     • p95          : {p95_p1:.2f} ms")
    print(f"     • p99 (Peak)   : {p99_p1:.2f} ms\n")

    # 3. Measure Path 2: On-Demand Deep Recall (`recall_user_memories`)
    print("3️⃣ Measuring Path 2: On-Demand Deep Recall Latency (Target: ~80ms DB / Masked via Speech Bridge)")
    queries = ["What frames does my wife Priya like?", "What is my coffee preference?", "Tell me my eye prescription"]
    path2_times = []
    for q in queries:
        for _ in range(5):
            t0 = time.perf_counter()
            recalled = recall_user_memories(q, test_user)
            t1 = time.perf_counter()
            path2_times.append((t1 - t0) * 1000.0)
    
    p50_p2 = statistics.median(path2_times)
    p95_p2 = sorted(path2_times)[int(len(path2_times) * 0.95)]
    p99_p2 = max(path2_times)
    print(f"   ► Path 2 Deep Recall Latency over 15 runs (HNSW Cosine Similarity Query):")
    print(f"     • p50 (Median) : {p50_p2:.2f} ms")
    print(f"     • p95          : {p95_p2:.2f} ms")
    print(f"     • p99 (Peak)   : {p99_p2:.2f} ms\n")

    # 4. Measure Post-Session Async Ingestion (`process_extracted_fact`)
    print("4️⃣ Measuring Post-Session Async Ingestion (`process_extracted_fact`) off Critical Path")
    new_facts = [
        ("User visited Saket store and tried Aviator frames", "M4_Behavioral"),
        ("User mentioned looking for computer glasses next month", "M5_Commitment"),
        ("Always orders black coffee without sugar when at Connaught Place cafe", "M3_Preference") # Deduplication test
    ]
    async_times = []
    for text, cat in new_facts:
        t0 = time.perf_counter()
        process_extracted_fact(text, cat, test_user, is_explicit_remember=False)
        t1 = time.perf_counter()
        async_times.append((t1 - t0) * 1000.0)
        
    p50_async = statistics.median(async_times)
    print(f"   ► Post-Session Async Worker Latency (Insert + Deduplication checks):")
    print(f"     • p50 (Median) : {p50_async:.2f} ms (Runs in background after session end — 0ms impact on user!)\n")

    print("==========================================================================")
    print("🏁 BENCHMARK SUMMARY FOR LENSKART STAKEHOLDERS")
    print("==========================================================================")
    print(f"• Path 1 Connection Pre-Load (p50): {p50_p1:.2f} ms (vs ~40ms budget)")
    print(f"• Path 2 Deep Vector Recall  (p50): {p50_p2:.2f} ms (Masked to 0s by 'Let me check your notes...')")
    print(f"• Post-Session Async Worker  (p50): {p50_async:.2f} ms (Off critical path)")
    print("==========================================================================")

if __name__ == "__main__":
    run_latency_benchmark()
