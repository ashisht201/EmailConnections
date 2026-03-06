#!/usr/bin/env python3
"""
email_parser.py  —  Offline Email Communication Analyzer (monthly buckets)
===========================================================================
Reads a local email dump (mbox or folder of .eml files) and outputs
email_data.json for the starburst visualization.

The JSON now stores per-month counts for every contact, so the
visualization can filter to any date range without re-running this script.

Run this ONCE against your full dump. The viz handles all time filtering.

No credentials. No network connection. Runs entirely offline.

──────────────────────────────────────────────────────────────────────
HOW TO GET YOUR EMAIL DUMP
──────────────────────────────────────────────────────────────────────

GMAIL  (produces .mbox files)
  1. Go to https://takeout.google.com
  2. Deselect all → select only "Mail"
  3. Choose "All Mail" or specific labels (e.g. INBOX, Sent)
  4. Export → download the .zip → extract
  5. You'll find:  All mail Including Spam and Trash.mbox
                   Sent.mbox
  Run:
    python email_parser.py \\
      --me    you@gmail.com \\
      --inbox "Takeout/Mail/All mail Including Spam and Trash.mbox" \\
      --sent  "Takeout/Mail/Sent.mbox"

OUTLOOK / OFFICE 365
  Option A — export via Thunderbird + ImportExportTools NG add-on:
    Tools → ImportExportTools NG → Export folder → mbox
  Option B — Outlook.com web: Settings → General → Privacy → Export mailbox

APPLE MAIL
  Mailbox menu → Export Mailbox… → saves as a folder of .eml files
  Run:
    python email_parser.py \\
      --me    you@icloud.com \\
      --inbox ~/Desktop/Inbox.mbox \\
      --sent  ~/Desktop/Sent.mbox

THUNDERBIRD
  Inbox/Sent folders are plain mbox files — no export step needed.
  Linux:   ~/.thunderbird/<profile>/Mail/Local Folders/
  macOS:   ~/Library/Thunderbird/Profiles/<profile>/Mail/
  Windows: %APPDATA%\\Thunderbird\\Profiles\\<profile>\\Mail\\

──────────────────────────────────────────────────────────────────────
USAGE
──────────────────────────────────────────────────────────────────────
  # Scan everything (recommended — run once, filter in the viz)
  python email_parser.py \\
    --me    you@example.com \\
    --inbox path/to/inbox.mbox \\
    --sent  path/to/sent.mbox  \\
    --out   email_data.json

  # Optionally narrow the scan window to save time on huge mailboxes
  python email_parser.py \\
    --me    you@example.com \\
    --inbox path/to/inbox.mbox \\
    --sent  path/to/sent.mbox  \\
    --from  2023-01-01 --to 2025-12-31

  # EML folder instead of mbox:
  python email_parser.py \\
    --me    you@example.com \\
    --inbox path/to/inbox_eml_folder/ \\
    --sent  path/to/sent_eml_folder/

FLAGS
  --me          Your email address (required)
  --inbox       Inbox mbox file or .eml folder
  --sent        Sent  mbox file or .eml folder (optional)
  --from        Optional earliest date to scan, YYYY-MM-DD
  --to          Optional latest   date to scan, YYYY-MM-DD
  --out         Output JSON path (default: email_data.json)
  --min-count   Min total interactions across ALL time to include a
                contact at all (default: 3 — the viz applies its own
                per-window threshold of 5)
  --verbose     Print per-message debug info

OUTPUT FORMAT (email_data.json)
──────────────────────────────────────────────────────────────────────
{
  "me": "you@example.com",
  "data_from": "2024-01",          ← earliest month present
  "data_to":   "2025-03",          ← latest  month present
  "contacts": [
    {
      "email": "alice@example.com",
      "name":  "Alice Example",
      "months": {
        "2024-01": { "sent": 2, "received": 3, "responded": 1 },
        "2024-02": { "sent": 0, "received": 1, "responded": 0 },
        ...
      }
    },
    ...
  ]
}

The viz sums whichever months fall inside the chosen date range,
then applies the top-5 / min-5 rules on the resulting totals.
"""

import mailbox
import email
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
import json
import argparse
import sys
import re
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Parse local email dump → email_data.json (monthly buckets)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--me",        required=True,  help="Your email address")
    p.add_argument("--inbox",     default=None,   help="Inbox mbox file or .eml folder")
    p.add_argument("--sent",      default=None,   help="Sent  mbox file or .eml folder (optional)")
    p.add_argument("--from",      dest="date_from", default=None, help="Scan start date YYYY-MM-DD (optional)")
    p.add_argument("--to",        dest="date_to",   default=None, help="Scan end   date YYYY-MM-DD (optional)")
    p.add_argument("--out",       default="email_data.json")
    p.add_argument("--min-count", type=int, default=3,
                   help="Min lifetime interactions to include a contact (default: 3)")
    p.add_argument("--verbose",   action="store_true")
    return p.parse_args()


# ── Header helpers ────────────────────────────────────────────────────────────

def decode_str(raw):
    if raw is None:
        return ""
    parts = decode_header(raw)
    out = []
    for part, enc in parts:
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(part))
    return " ".join(out).strip()


def extract_address(raw_header):
    name, addr = parseaddr(decode_str(raw_header))
    return name.strip(), addr.strip().lower()


def parse_date(msg):
    raw = msg.get("Date", "")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def normalize_subject(subj: str) -> str:
    subj = decode_str(subj)
    subj = re.sub(r"(?i)^(re|fwd?|fw|aw|sv|vs|tr)[\[\d\]]*\s*:\s*", "", subj).strip()
    return subj.lower()


def derive_name(addr: str) -> str:
    local = addr.split("@")[0]
    return " ".join(w.capitalize() for w in re.split(r"[._\-+]", local))


def ym(dt: datetime) -> str:
    """Return 'YYYY-MM' string for a datetime."""
    return dt.strftime("%Y-%m")


# ── Message loaders ───────────────────────────────────────────────────────────

def load_mbox(path: str):
    mb = mailbox.mbox(path, factory=None, create=False)
    for msg in mb:
        yield msg


def load_eml_folder(path: str):
    folder = Path(path)
    files = list(folder.rglob("*.eml"))
    if not files:
        files = [f for f in folder.rglob("*") if f.is_file()]
    for fpath in files:
        try:
            with open(fpath, "rb") as f:
                yield email.message_from_bytes(f.read())
        except Exception:
            pass


def load_source(path: str):
    if path is None:
        return
    p = Path(path)
    if not p.exists():
        print(f"  ⚠  Path not found: {path}", file=sys.stderr)
        return
    if p.is_dir():
        yield from load_eml_folder(path)
    else:
        yield from load_mbox(path)


# ── Core analysis ─────────────────────────────────────────────────────────────

def analyze(args):
    since  = datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.date_from else None
    before = datetime.strptime(args.date_to,   "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.date_to   else None
    my_email = args.me.lower()

    # contact → month → { sent_threads, received_threads }
    # We track sets of thread_keys per month so we can compute responded
    # (intersection of sent & received) correctly within each month.
    sent_by_month     = defaultdict(lambda: defaultdict(set))  # [contact][month] = set of thread_keys
    received_by_month = defaultdict(lambda: defaultdict(set))
    names             = {}
    all_months        = set()

    def process(msg, label):
        dt = parse_date(msg)
        if dt is None:
            return
        if since  and dt < since:
            return
        if before and dt > before:
            return

        month = ym(dt)
        all_months.add(month)

        from_name, from_addr = extract_address(msg.get("From", ""))
        to_header = msg.get("To", "")
        subject   = normalize_subject(msg.get("Subject", ""))

        to_pairs = [parseaddr(a.strip()) for a in to_header.split(",") if a.strip()]
        to_addrs = [(n.strip(), a.strip().lower()) for n, a in to_pairs]

        i_am_sender    = (from_addr == my_email)
        i_am_direct_to = any(a == my_email for _, a in to_addrs)

        if args.verbose:
            print(f"  [{label}] {dt.date()} from={from_addr} subj={subject[:50]}")

        if i_am_sender:
            for rec_name, rec_addr in to_addrs:
                if not rec_addr or rec_addr == my_email:
                    continue
                sent_by_month[rec_addr][month].add(f"{rec_addr}::{subject}")
                if rec_name and rec_addr not in names:
                    names[rec_addr] = rec_name

        elif i_am_direct_to and from_addr and from_addr != my_email:
            received_by_month[from_addr][month].add(f"{from_addr}::{subject}")
            if from_name:
                names[from_addr] = from_name

    # ── Scan ──────────────────────────────────────────────────────────────
    if args.inbox:
        print(f"📥 Inbox:  {args.inbox}")
        n = 0
        for msg in load_source(args.inbox):
            process(msg, "inbox")
            n += 1
            if n % 1000 == 0:
                print(f"   … {n} scanned")
        print(f"   {n} messages read")
    else:
        print("ℹ  No --inbox given; only sent mail analysed.")

    if args.sent:
        print(f"📤 Sent:   {args.sent}")
        n = 0
        for msg in load_source(args.sent):
            process(msg, "sent")
            n += 1
            if n % 1000 == 0:
                print(f"   … {n} scanned")
        print(f"   {n} messages read")
    else:
        print("ℹ  No --sent given; 'responded' counts will be 0.")

    if not all_months:
        print("⚠  No messages found in the specified range.", file=sys.stderr)
        sys.exit(1)

    # ── Build per-contact monthly records ─────────────────────────────────
    all_contacts = set(sent_by_month) | set(received_by_month)
    results = []

    for contact in all_contacts:
        s_months = sent_by_month.get(contact, {})
        r_months = received_by_month.get(contact, {})
        all_c_months = set(s_months) | set(r_months)

        months_data = {}
        lifetime_total = 0

        for m in sorted(all_c_months):
            s_set = s_months.get(m, set())
            r_set = r_months.get(m, set())
            d_set = s_set & r_set
            s, r, d = len(s_set), len(r_set), len(d_set)
            if s or r or d:
                months_data[m] = {"sent": s, "received": r, "responded": d}
                lifetime_total += s + r + d

        if lifetime_total < args.min_count:
            continue

        results.append({
            "email":  contact,
            "name":   names.get(contact) or derive_name(contact),
            "months": months_data,
        })

    # Sort by lifetime score descending
    def lifetime(c):
        return sum(v["sent"] + v["received"] + v["responded"] for v in c["months"].values())

    results.sort(key=lifetime, reverse=True)

    # ── Write output ───────────────────────────────────────────────────────
    sorted_months = sorted(all_months)
    output = {
        "me":        my_email,
        "data_from": sorted_months[0],
        "data_to":   sorted_months[-1],
        "contacts":  results,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✅  Wrote {len(results)} contacts → {args.out}")
    print(f"    Data spans {sorted_months[0]} → {sorted_months[-1]}\n")
    print(f"   {'#':>3}  {'Lifetime':>8}  Name")
    print("   " + "─" * 50)
    for i, c in enumerate(results[:20], 1):
        lt = lifetime(c)
        print(f"   {i:>3}.  {lt:>8}  {c['name'] or c['email']}")

    return output


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = parse_args()
    if not args.inbox and not args.sent:
        print("❌  Provide at least --inbox or --sent.", file=sys.stderr)
        sys.exit(1)
    try:
        analyze(args)
    except KeyboardInterrupt:
        print("\n⚡ Interrupted.")
        sys.exit(0)
