#!/usr/bin/env python3
"""Email a daily digest of which Googlers used the IAP-protected studio demo.

Reads the `studio_daily_users` collection written by `server/demo_users.py`
(Firestore database `v2v-demo-visits`), merges the last 24 hours per email,
and sends the digest with the Gmail CLI. Run by a systemd user timer; use
`--dry-run` to print the HTML instead of sending.

    python3 scripts/daily_demo_users_report.py --project deep-clock-339817 --to manishkjs@google.com
"""
import argparse
import html
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

COLLECTION = "studio_daily_users"
DEFAULT_DB = "v2v-demo-visits"
GMAIL = os.environ.get("GMAIL_CLI", "/google/bin/releases/gemini-agents-gmail/gmail")
IST = ZoneInfo("Asia/Kolkata")


def _token() -> str:
    import google.auth
    from google.auth.transport.requests import Request

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/datastore"])
    if not creds.valid:
        creds.refresh(Request())
    return creds.token


def _unwrap(value):
    if "stringValue" in value:
        return value["stringValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "arrayValue" in value:
        return [_unwrap(v) for v in value["arrayValue"].get("values", [])]
    return next(iter(value.values()), None)


def fetch_rows(project: str, database: str, since_epoch: int):
    parent = f"projects/{project}/databases/{database}/documents"
    query = {
        "structuredQuery": {
            "from": [{"collectionId": COLLECTION}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": "last_seen_epoch"},
                    "op": "GREATER_THAN_OR_EQUAL",
                    "value": {"integerValue": str(since_epoch)},
                }
            },
        }
    }
    req = urllib.request.Request(
        f"https://firestore.googleapis.com/v1/{parent}:runQuery",
        data=json.dumps(query).encode("utf-8"),
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        results = json.loads(resp.read().decode("utf-8"))
    rows = []
    for item in results:
        doc = item.get("document")
        if doc:
            rows.append({k: _unwrap(v) for k, v in doc.get("fields", {}).items()})
    return rows


def merge_by_email(rows):
    merged = {}
    for row in rows:
        email = row.get("email") or "unknown"
        entry = merged.setdefault(
            email,
            {"email": email, "page_visits": 0, "sessions_started": 0, "first": None, "last": None,
             "personas": set(), "engines": set(), "models": set()},
        )
        entry["page_visits"] += int(row.get("page_visits") or 0)
        entry["sessions_started"] += int(row.get("sessions_started") or 0)
        for key in ("personas", "engines", "models"):
            entry[key].update(x for x in (row.get(key) or []) if x)
        first, last = row.get("first_seen_epoch"), row.get("last_seen_epoch")
        if first is not None:
            entry["first"] = first if entry["first"] is None else min(entry["first"], first)
        if last is not None:
            entry["last"] = last if entry["last"] is None else max(entry["last"], last)
    return sorted(merged.values(), key=lambda e: (-e["sessions_started"], -e["page_visits"], e["email"]))


def _ist(epoch):
    if epoch is None:
        return ""
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).astimezone(IST).strftime("%H:%M IST")


def render(entries, window_start: datetime, window_end: datetime, demo_url: str) -> tuple[str, str]:
    total_sessions = sum(e["sessions_started"] for e in entries)
    total_visits = sum(e["page_visits"] for e in entries)
    heading = (
        f"{len(entries)} Googler{'s' if len(entries) != 1 else ''}, "
        f"{total_sessions} voice session{'s' if total_sessions != 1 else ''}, {total_visits} page loads"
    )
    window = f"{window_start.astimezone(IST):%d %b %H:%M} to {window_end.astimezone(IST):%d %b %H:%M} IST"
    cell = "padding:6px 10px;border-bottom:1px solid #e0e0e0;font-size:13px;vertical-align:top"
    head = "padding:6px 10px;background:#e8f0fe;font-size:12px;text-align:left"
    body_rows = []
    for e in entries:
        body_rows.append(
            "<tr>"
            f"<td style='{cell}'>{html.escape(e['email'])}</td>"
            f"<td style='{cell};text-align:center'><b>{e['sessions_started']}</b></td>"
            f"<td style='{cell};text-align:center'>{e['page_visits']}</td>"
            f"<td style='{cell}'>{_ist(e['first'])} to {_ist(e['last'])}</td>"
            f"<td style='{cell}'>{html.escape(', '.join(sorted(e['personas'])) or '-')}</td>"
            f"<td style='{cell}'>{html.escape(', '.join(sorted(e['engines'])) or '-')}</td>"
            f"<td style='{cell}'>{html.escape(', '.join(sorted(e['models'])) or '-')}</td>"
            "</tr>"
        )
    if not body_rows:
        body_rows.append(f"<tr><td colspan='7' style='{cell}'>No signed-in Google users in this window.</td></tr>")
    page = f"""<div style="font-family:Google Sans,Roboto,Arial,sans-serif;color:#202124">
<h2 style="margin:0 0 4px">Voice Studio demo: who used it</h2>
<div style="color:#5f6368;font-size:13px;margin-bottom:12px">{html.escape(window)} &middot; <a href="{html.escape(demo_url)}">{html.escape(demo_url)}</a></div>
<p style="font-size:15px;margin:0 0 12px"><b>{html.escape(heading)}</b></p>
<table style="border-collapse:collapse;min-width:720px">
<tr><th style="{head}">Googler</th><th style="{head}">Sessions</th><th style="{head}">Page loads</th><th style="{head}">Active (IST)</th><th style="{head}">Personas</th><th style="{head}">Engine</th><th style="{head}">Models</th></tr>
{''.join(body_rows)}
</table>
<p style="color:#5f6368;font-size:12px;margin-top:14px">Source: Cloud IAP header on each request, stored per day in Firestore <code>{COLLECTION}</code>. Anonymous or non-IAP traffic is not counted.</p>
</div>"""
    return heading, page


def send(to: str, subject: str, body_html: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(body_html)
        path = f.name
    try:
        subprocess.run(
            [GMAIL, "mutate", "send", "--to", to, "--subject", subject, "--body-file", path, "--html"],
            check=True,
        )
    finally:
        os.unlink(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.environ.get("GCP_PROJECT_ID", "deep-clock-339817"))
    ap.add_argument("--database", default=DEFAULT_DB)
    ap.add_argument("--to", default="manishkjs@google.com")
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--demo-url", default="https://demo-1525.1987984870407.demo.altostrat.com")
    ap.add_argument("--dry-run", action="store_true", help="print the HTML instead of sending it")
    args = ap.parse_args()

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=args.hours)
    entries = merge_by_email(fetch_rows(args.project, args.database, int(start.timestamp())))
    heading, body = render(entries, start, end, args.demo_url)
    subject = f"Voice Studio demo users, {end.astimezone(IST):%d %b %Y}: {heading}"
    if args.dry_run:
        print(subject)
        print(body)
        return 0
    send(args.to, subject, body)
    print(f"sent to {args.to}: {subject}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
