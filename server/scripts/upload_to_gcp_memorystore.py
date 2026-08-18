#!/usr/bin/env python3
"""
Uploads all Google Sheet Q&A records, BM25 index, canonical domain rules,
and user memories directly to Google Cloud Memorystore (us-central1).
"""

import json
import os
import re
import socket
import sys

MEMORYSTORE_HOST = os.environ.get("MEMORYSTORE_HOST", "10.198.162.203")
MEMORYSTORE_PORT = int(os.environ.get("MEMORYSTORE_PORT", "6379"))

def redis_cmd(s: socket.socket, cmd_parts):
    buf = f"*{len(cmd_parts)}\r\n".encode("utf-8")
    for p in cmd_parts:
        if isinstance(p, str):
            pb = p.encode("utf-8")
        elif isinstance(p, bytes):
            pb = p
        else:
            pb = str(p).encode("utf-8")
        buf += f"${len(pb)}\r\n".encode("utf-8") + pb + b"\r\n"
    s.sendall(buf)
    
    # Read response
    resp = s.recv(65536)
    return resp

def main():
    json_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/sheet_knowledge.json"
    if not os.path.exists(json_path):
        json_path = os.path.join(os.path.dirname(__file__), "..", "data", "sheet_knowledge.json")
    
    if not os.path.exists(json_path):
        print(f"Error: {json_path} not found.")
        sys.exit(1)

    print(f"Loading data from {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    print(f"Connecting to Google Cloud Memorystore at {MEMORYSTORE_HOST}:{MEMORYSTORE_PORT}...")
    try:
        s = socket.create_connection((MEMORYSTORE_HOST, MEMORYSTORE_PORT), timeout=10)
    except Exception as e:
        print(f"Failed to connect to Memorystore at {MEMORYSTORE_HOST}:{MEMORYSTORE_PORT}: {e}")
        sys.exit(1)

    ping_res = redis_cmd(s, ["PING"])
    print(f"PING response: {ping_res.decode('utf-8', errors='ignore').strip()}")

    print(f"Ingesting {len(records)} Q&A records into Google Cloud Memorystore...")

    # Store full JSON array in Memorystore
    all_json_bytes = json.dumps(records, ensure_ascii=False)
    redis_cmd(s, ["SET", "cymbal:sheet_qa:all", all_json_bytes])

    # Store individual records and build token index
    token_index = {}
    doc_lengths = {}
    doc_tokens_q = {}
    doc_tokens_c = {}
    doc_tokens_a = {}

    for idx, r in enumerate(records):
        doc_key = f"cymbal:sheet_qa:{idx}"
        rec_json = json.dumps(r, ensure_ascii=False)
        redis_cmd(s, ["SET", doc_key, rec_json])

        # Direct question -> answer lookup
        q_raw = r.get("question", "")
        a_raw = r.get("answer", "")
        cat_raw = r.get("category", "")

        q_norm = " ".join(sorted([w for w in re.findall(r"\w+", q_raw.lower()) if len(w) > 1]))
        if q_norm:
            redis_cmd(s, ["SET", f"cymbal:qa:q:{q_norm}", a_raw])

        # Token stats
        q_toks = re.findall(r"\w+", q_raw.lower())
        c_toks = re.findall(r"\w+", cat_raw.lower())
        a_toks = re.findall(r"\w+", a_raw.lower())
        all_toks = q_toks + c_toks + a_toks

        doc_lengths[str(idx)] = len(all_toks)
        doc_tokens_q[str(idx)] = {t: q_toks.count(t) for t in set(q_toks)}
        doc_tokens_c[str(idx)] = {t: c_toks.count(t) for t in set(c_toks)}
        doc_tokens_a[str(idx)] = {t: a_toks.count(t) for t in set(a_toks)}

        for t in set(all_toks):
            if len(t) > 1:
                if t not in token_index:
                    token_index[t] = []
                token_index[t].append(idx)

    # Store BM25 Index Metadata in Memorystore
    print(f"Uploading BM25 index ({len(token_index)} unique tokens) to Memorystore...")
    redis_cmd(s, ["SET", "cymbal:bm25:token_index", json.dumps(token_index)])
    redis_cmd(s, ["SET", "cymbal:bm25:doc_lengths", json.dumps(doc_lengths)])
    redis_cmd(s, ["SET", "cymbal:bm25:doc_tokens_q", json.dumps(doc_tokens_q)])
    redis_cmd(s, ["SET", "cymbal:bm25:doc_tokens_c", json.dumps(doc_tokens_c)])
    redis_cmd(s, ["SET", "cymbal:bm25:doc_tokens_a", json.dumps(doc_tokens_a)])

    # Store Canonical Domain Knowledge in Memorystore
    canonical_rules = {
        "cymbal:canonical:fd_returns": "LenDenClub P2P delivers 12% to 15% indicative XIRR under STL schemes, compared to traditional Bank FDs at 6.5% to 7.2%. Non-market linked P2P loans.",
        "cymbal:canonical:rbi_limits": "Reserve Bank of India (RBI) mandates maximum ₹50 Lakh exposure across all P2P platforms per lender. Minimum investment is ₹250 per loan.",
        "cymbal:canonical:tenure_options": "LenDenClub offers short-term tenures (5-month and 7-month STL) and mid-term options (14-month monthly EMI / Daily Return).",
        "cymbal:canonical:risk_mitigation": "Diversification across hundreds of vetted borrowers (₹250-₹4000 per borrower) reduces default risk. Secondary debt recovery partner network active across 29 states.",
        "cymbal:canonical:tds_taxation": "LenDenClub P2P platform does NOT deduct TDS on interest earnings for Indian residents. Gross interest is credited directly to your bank account. Report under Income from Other Sources.",
        "cymbal:canonical:kyc": "Mandatory 100% digital KYC: PAN verification, Aadhaar OTP authentication, and Penny Drop bank account verification. Zero manual paperwork.",
        "cymbal:canonical:nri_investing": "NRIs are eligible to invest via NRO (Non-Resident Ordinary) bank accounts with Indian PAN. Repatriation subject to FEMA guidelines.",
    }

    for ckey, cval in canonical_rules.items():
        redis_cmd(s, ["SET", ckey, cval])

    # Check dbsize
    dbsize_res = redis_cmd(s, ["DBSIZE"])
    print(f"✅ Memorystore Ingestion Complete! DBSIZE: {dbsize_res.decode('utf-8', errors='ignore').strip()}")

    s.close()

if __name__ == "__main__":
    main()
