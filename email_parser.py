#!/usr/bin/env python3
"""
email_parser.py  —  Offline Email Communication Analyzer
=========================================================
Reads a local email dump (mbox or folder of .eml files) and outputs
email_data.json for the starburst visualization.

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
      --sent  "Takeout/Mail/Sent.mbox" \\
      --from  2024-03-01 --to 2025-03-01

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
      --sent  ~/Desktop/Sent.mbox \\
      --from  2024-03-01 --to 2025-03-01

THUNDERBIRD
  Inbox/Sent are plain mbox files already — no export step needed.
  Linux:   ~/.thunderbird/<profile>/Mail/Local Folders/
  macOS:   ~/Library/Thunderbird/Profiles/<profile>/Mail/
  Windows: %APPDATA%\\Thunderbird\\Profiles\\<profile>\\Mail\\

──────────────────────────────────────────────────────────────────────
USAGE
──────────────────────────────────────────────────────────────────────
  python email_parser.py \\
    --me    you@example.com \\
    --inbox path/to/inbox.mbox \\
    --sent  path/to/sent.mbox \\
    --from  2024-03-01 \\
    --to    2025-03-01 \\
    --out   email_data.json

  # EML folder instead of mbox:
  python email_parser.py \\
    --me    you@example.com \\
    --inbox path/to/inbox_eml_folder/ \\
    --sent  path/to/sent_eml_folder/ \\
    --from  2024-03-01 --to 2025-03-01

  # Inbox only (no separate sent folder):
  python email_parser.py \\
    --me    you@example.com \\
    --inbox path/to/all_mail.mbox \\
    --from  2024-03-01 --to 2025-03-01

FLAGS
  --me          Your email address (required)
  --inbox       Inbox mbox file or folder of .eml files
  --sent        Sent  mbox file or folder of .eml files (optional)
  --from        Start date inclusive, YYYY-MM-DD
  --to          End date   inclusive, YYYY-MM-DD
  --out         Output JSON path (default: email_data.json)
  --min-count   Min total interactions to include a contact (default: 5)
  --top-n       Max contacts in output (default: 5)
  --verbose     Print per-message debug info
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
        description="Parse local email dump → email_data.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--me",        required=True,  help="Your email address")
    p.add_argument("--inbox",     default=None,   help="Inbox mbox file or .eml folder")
    p.add_argument("--sent",      default=None,   help="Sent  mbox file or .eml folder (optional)")
    p.add_argument("--from",      dest="date_from", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--to",        dest="date_to",   required=True, help="End date   YYYY-MM-DD")
    p.add_argument("--out",       default="email_data.json")
    p.add_argument("--min-count", type=int, default=5)
    p.add_argument("--top-n",     type=int, default=5)
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
    since    = datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    before   = datetime.strptime(args.date_to,   "%Y-%m-%d").replace(tzinfo=timezone.utc)
    my_email = args.me.lower()

    threads_received = defaultdict(set)   # contact → set of thread_keys
    threads_sent     = defaultdict(set)
    names            = {}                 # email → display name

    def process(msg, label):
        dt = parse_date(msg)
        if dt is None or not (since <= dt <= before):
            return

        from_name, from_addr = extract_address(msg.get("From", ""))
        to_header = msg.get("To", "")
        subject   = normalize_subject(msg.get("Subject", ""))

        # Direct To only — split on comma, skip CC/BCC entirely
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
                threads_sent[rec_addr].add(f"{rec_addr}::{subject}")
                if rec_name and rec_addr not in names:
                    names[rec_addr] = rec_name

        elif i_am_direct_to and from_addr and from_addr != my_email:
            threads_received[from_addr].add(f"{from_addr}::{subject}")
            if from_name:
                names[from_addr] = from_name

    # ── Scan inbox ─────────────────────────────────────────────────────────
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

    # ── Scan sent ──────────────────────────────────────────────────────────
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

    # ── Score & filter ─────────────────────────────────────────────────────
    all_contacts = set(threads_received) | set(threads_sent)
    results = []

    for contact in all_contacts:
        s_set = threads_sent.get(contact, set())
        r_set = threads_received.get(contact, set())
        d_set = s_set & r_set          # threads with traffic in both directions

        s, r, d = len(s_set), len(r_set), len(d_set)
        total = s + r + d

        if total < args.min_count:
            continue

        results.append({
            "email":     contact,
            "name":      names.get(contact) or derive_name(contact),
            "sent":      s,
            "received":  r,
            "responded": d,
        })

    results.sort(key=lambda x: x["sent"] + x["received"] + x["responded"], reverse=True)
    results = results[:args.top_n]

    # ── Write JSON ─────────────────────────────────────────────────────────
    output = {
        "me":      my_email,
        "period":  {"from": args.date_from, "to": args.date_to},
        "contacts": results,
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n✅  Wrote {len(results)} contacts → {args.out}\n")
    print(f"   {'#':>3}  {'Score':>5}  {'Name':<30}  Breakdown (sent / received / responded)")
    print("   " + "─" * 72)
    for i, c in enumerate(results, 1):
        total = c["sent"] + c["received"] + c["responded"]
        bar = "▪" * min(24, total // 2)
        print(f"   {i:>3}.  {total:>5}  {(c['name'] or c['email']):<30}  "
              f"s={c['sent']} r={c['received']} d={c['responded']}  {bar}")

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
