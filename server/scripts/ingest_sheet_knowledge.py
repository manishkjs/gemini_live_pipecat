#!/usr/bin/env python3
"""
Standalone Google Sheet Q&A Dataset Ingestion & Memorystore/Redis Syncer.

Extracts all Q&A records from Google Sheet '1JI9MOdsqIZAPedATGdODWCDJ-nm9R-ZJ57taZtNrsiM'
using the gsheets CLI, sanitizes multiline answers and special characters, saves the structured
records to server/data/sheet_knowledge.json, and synchronizes inverted index tokens and documents
to Google Cloud Memorystore / Redis under key schema cymbal:sheet_rag:*.
"""

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from loguru import logger

DEFAULT_SHEET_ID = "1JI9MOdsqIZAPedATGdODWCDJ-nm9R-ZJ57taZtNrsiM"
DEFAULT_RANGE = "Sheet1!A1:Z"
DEFAULT_OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "sheet_knowledge.json")
GSHEETS_CLI = "/google/bin/releases/gemini-agents-gsheets/gsheets"


def extract_sheet_data(
    sheet_id: str = DEFAULT_SHEET_ID,
    range_name: str = DEFAULT_RANGE,
    raw_json_input: Optional[str] = None
) -> List[List[str]]:
    """Extract raw row data from Google Sheet via gsheets CLI or raw input file."""
    if raw_json_input and os.path.exists(raw_json_input):
        logger.info(f"Loading raw sheet data from input file: {raw_json_input}")
        with open(raw_json_input, "r", encoding="utf-8") as f:
            return json.load(f)

    if not os.path.exists(GSHEETS_CLI):
        raise FileNotFoundError(f"gsheets CLI tool not found at {GSHEETS_CLI}")

    cmd = [GSHEETS_CLI, "readonly", "read", sheet_id, range_name, "--json"]
    logger.info(f"Executing gsheets extraction: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    raw_data = json.loads(result.stdout)
    logger.info(f"Successfully fetched {len(raw_data)} raw rows from Google Sheet.")
    return raw_data


def sanitize_and_save(raw_data: List[List[str]], output_path: str = DEFAULT_OUTPUT_PATH) -> List[Dict[str, Any]]:
    """Sanitize raw sheet rows, strip header, clean whitespace, and write structured JSON."""
    if not raw_data:
        raise ValueError("Raw data is empty.")

    header = raw_data[0]
    logger.info(f"Header row detected and filtered: {header}")
    data_rows = raw_data[1:]

    records: List[Dict[str, Any]] = []
    for idx, row in enumerate(data_rows):
        question = row[0].strip() if len(row) > 0 and row[0] else ""
        answer = row[1].strip() if len(row) > 1 and row[1] else ""
        category = row[2].strip() if len(row) > 2 and row[2] else "General"
        subcategory = row[3].strip() if len(row) > 3 and row[3] else ""

        # Preserve multiline paragraphs while trimming whitespace on individual lines
        answer_lines = [line.strip() for line in answer.splitlines() if line.strip()]
        cleaned_answer = "\n".join(answer_lines) if answer_lines else answer

        record = {
            "id": idx,
            "question": question,
            "answer": cleaned_answer,
            "category": category if category else "General",
            "subcategory": subcategory,
        }
        records.append(record)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    logger.info(f"✅ Successfully sanitized and wrote {len(records)} structured records to {output_path}")
    return records


async def sync_to_redis(
    records: List[Dict[str, Any]],
    redis_url: Optional[str] = None
) -> bool:
    """Ingest documents, inverted index tokens, and metadata into Memorystore / Redis."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("[RedisSync] redis-py not installed; skipping live Redis push.")
        return False

    host = os.getenv("MEMORYSTORE_HOST") or os.getenv("REDIS_HOST") or "10.198.162.203"
    port = os.getenv("MEMORYSTORE_PORT") or os.getenv("REDIS_PORT") or "6379"
    url = redis_url or os.getenv("REDIS_URL") or f"redis://{host}:{port}/0"

    logger.info(f"Connecting to Redis at {url} for ingestion...")
    try:
        client = aioredis.from_url(url, decode_responses=True, socket_timeout=2.0, socket_connect_timeout=2.0)
        await asyncio.wait_for(client.ping(), timeout=2.5)
    except Exception as e:
        logger.warning(f"☁️🔴 Redis instance not reachable at {url} ({e}). Sync to remote Redis skipped.")
        return False

    logger.info("Syncing metadata, documents, and token postings to Redis...")
    pipe = client.pipeline()

    # 1. Dataset metadata
    meta_key = "cymbal:sheet_rag:meta"
    pipe.hset(
        meta_key,
        mapping={
            "total_docs": str(len(records)),
            "version": "1.0",
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    # 2. Documents and Inverted Index Tokens
    token_postings: Dict[str, List[int]] = {}
    for r in records:
        doc_id = r["id"]
        doc_key = f"cymbal:sheet_rag:doc:{doc_id}"
        pipe.set(doc_key, json.dumps(r, ensure_ascii=False))

        # Build tokens
        text = f"{r['question']} {r['category']} {r.get('subcategory', '')} {r['answer']}".lower()
        # Normalization
        text = text.replace("₹", " rs rupees inr ")
        tokens = set(re.findall(r"\w+", text))
        for t in tokens:
            if len(t) > 2:
                if t not in token_postings:
                    token_postings[t] = []
                token_postings[t].append(doc_id)

    # Push token postings
    for token, doc_ids in token_postings.items():
        token_key = f"cymbal:sheet_rag:token:{token}"
        pipe.sadd(token_key, *doc_ids)

    await pipe.execute()
    logger.info(f"✅ Ingested {len(records)} docs and {len(token_postings)} token posting keys into Redis.")
    await client.aclose()
    return True


def verify_dataset(records_or_path: Any) -> bool:
    """Verify dataset integrity, record count, and benchmark search retrieval."""
    if isinstance(records_or_path, str):
        with open(records_or_path, "r", encoding="utf-8") as f:
            records = json.load(f)
    else:
        records = records_or_path

    total_records = len(records)
    logger.info(f"Auditing {total_records} records...")
    assert total_records == 896, f"Expected exactly 896 records, found {total_records}"
    assert records[0]["id"] == 0, f"Expected first record ID to be 0, got {records[0]['id']}"
    assert records[-1]["id"] == 895, f"Expected last record ID to be 895, got {records[-1]['id']}"

    # Verify no header row pollution
    assert records[0]["question"] != "Questions", "Header row leaked into records!"
    assert records[0]["answer"] != "Final Response", "Header row leaked into records!"

    # Verify benchmark queries
    benchmark_checks = [
        ("minimum amount to lend", ["250", "rupees 250", "₹250"]),
        ("maximum amount per PAN ₹50 Lakh", ["50 lakh", "₹50 lakh", "chartered accountant"]),
        ("14 month EMI option", ["18% per annum", "medium risk", "14 month"]),
        ("CTO February 2025 update", ["dipesh karki", "stl", "february 2025"]),
    ]

    all_passed = True
    for query, expected_terms in benchmark_checks:
        matched = False
        for r in records:
            combined = f"{r['question']} {r['answer']}".lower()
            if any(term.lower() in combined for term in expected_terms):
                matched = True
                break
        if matched:
            logger.info(f"  ✓ Verified query presence in dataset: '{query}'")
        else:
            logger.error(f"  ✗ Failed query presence check: '{query}'")
            all_passed = False

    return all_passed


def main():
    parser = argparse.ArgumentParser(description="Ingest Google Sheet Q&A Dataset to JSON and Redis.")
    parser.add_argument("--sheet-id", default=DEFAULT_SHEET_ID, help="Google Sheet ID")
    parser.add_argument("--range", default=DEFAULT_RANGE, help="Sheet range (e.g. Sheet1!A1:Z)")
    parser.add_argument("--output", "--json-path", default=DEFAULT_OUTPUT_PATH, help="Output JSON path")
    parser.add_argument("--raw-json", default=None, help="Path to raw JSON if bypassing gsheets CLI")
    parser.add_argument("--extract", action="store_true", help="Extract and sanitize from Google Sheet")
    parser.add_argument("--sync-redis", action="store_true", help="Sync structured JSON to Redis")
    parser.add_argument("--verify", action="store_true", help="Verify dataset integrity")
    parser.add_argument("--all", action="store_true", help="Run extract, save, sync, and verify")

    args = parser.parse_args()

    # Default to all if no specific action specified
    run_all = args.all or (not args.extract and not args.sync_redis and not args.verify)

    records = None
    if run_all or args.extract:
        raw_data = extract_sheet_data(args.sheet_id, args.range, args.raw_json)
        records = sanitize_and_save(raw_data, args.output)

    if run_all or args.verify:
        target_path = args.output
        if records is None:
            with open(target_path, "r", encoding="utf-8") as f:
                records = json.load(f)
        verify_dataset(records)

    if run_all or args.sync_redis:
        if records is None:
            with open(args.output, "r", encoding="utf-8") as f:
                records = json.load(f)
        asyncio.run(sync_to_redis(records))


if __name__ == "__main__":
    main()
