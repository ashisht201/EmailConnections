# Email Gravity Map

An interactive starburst visualization of your email communication patterns.
Contacts you interact with most appear **closer** and **larger**. Colors encode
the direction of communication — blue for sent, red for received, yellow for responded.

**[Live demo →](https://your-username.github.io/email-gravity-map/)**

---

## Repository layout

```
email-gravity-map/
├── index.html          ← the visualization (open this in a browser)
├── email_data.json     ← your data (replace with real output)
└── email_parser.py     ← offline script to generate email_data.json
```

---

## Quickstart

### 1 — Generate your data

You need a local email dump first. See the provider-specific steps below.

```bash
python email_parser.py \
  --me    you@gmail.com \
  --inbox "Takeout/Mail/All mail Including Spam and Trash.mbox" \
  --sent  "Takeout/Mail/Sent.mbox" \
  --from  2024-03-01 \
  --to    2025-03-01 \
  --out   email_data.json
```

This writes `email_data.json` in the same folder.

### 2 — View locally

```bash
# Any simple HTTP server works (needed so fetch() can read the JSON)
python -m http.server 8000
# then open http://localhost:8000
```

> **Why not just double-click index.html?**  
> Browsers block `fetch()` for local files due to CORS. A local server (one line above) solves this.

### 3 — Publish to GitHub Pages

```bash
# commit both files
git add index.html email_data.json
git commit -m "update email map"
git push
```

In your repo → **Settings → Pages → Source: main / root** → Save.  
Your map will be live at `https://<you>.github.io/<repo>/`.

> **Privacy note:** `email_data.json` contains only names, email addresses, and
> interaction counts — no message content or subjects. Review it before pushing
> to a public repo. You can also anonymize names/emails in the JSON if you prefer.

---

## Getting your email dump

### Gmail (Google Takeout)
1. Go to <https://takeout.google.com>
2. Deselect all → select **Mail** only
3. Choose **All Mail** or specific labels
4. Download the `.zip` and extract — you'll find `.mbox` files inside

### Apple Mail
- **Mailbox → Export Mailbox…** → saves as a folder of `.eml` files

### Thunderbird
- Inbox/Sent folders are already plain mbox files at:
  - Linux: `~/.thunderbird/<profile>/Mail/`
  - macOS: `~/Library/Thunderbird/Profiles/<profile>/Mail/`
  - Windows: `%APPDATA%\Thunderbird\Profiles\<profile>\Mail\`

### Outlook / Office 365
- Add your account to Thunderbird → use **ImportExportTools NG** add-on to export as mbox

---

## Parser options

| Flag | Default | Description |
|------|---------|-------------|
| `--me` | *(required)* | Your email address |
| `--inbox` | — | Inbox mbox file or `.eml` folder |
| `--sent` | — | Sent mbox file or `.eml` folder |
| `--from` | *(required)* | Start date `YYYY-MM-DD` |
| `--to` | *(required)* | End date `YYYY-MM-DD` |
| `--out` | `email_data.json` | Output path |
| `--min-count` | `5` | Minimum total interactions to include |
| `--top-n` | `5` | Maximum contacts shown |
| `--verbose` | off | Print per-message debug info |

---

## JSON format

If you want to hand-edit or produce the JSON another way:

```json
{
  "me": "you@example.com",
  "period": { "from": "2024-03-01", "to": "2025-03-01" },
  "contacts": [
    {
      "email": "alice@example.com",
      "name":  "Alice Example",
      "sent":      34,
      "received":  28,
      "responded": 41
    }
  ]
}
```

- **sent** — threads where you sent a direct email to this person
- **received** — threads where they sent a direct email to you
- **responded** — threads counted in both sent *and* received (mutual exchange)
- CC/BCC are ignored throughout

---

## Dependencies

`email_parser.py` uses only Python standard library modules (`mailbox`, `email`,
`json`, `re`, `argparse`). Python 3.8+ required. No `pip install` needed.
