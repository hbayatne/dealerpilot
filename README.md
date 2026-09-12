# Chaos Control AI

**The intelligence layer above the software a business already runs.**

Your clients, money, leads, calls and appointments live in different systems.
Chaos Control connects them, finds what is falling through the cracks between
them, and shows you the evidence.

> *Chaos Control AI* is a working name. Every user-visible string comes from
> `chaos/brand.py` and can be overridden with environment variables, so renaming
> the product is a config change, not a refactor.

---

## What actually works today

Connect a mailbox, and within one scan you get findings like:

> **Possible unfulfilled commitment to Marcus Webb**
> We said *"I'll come by Thursday and get you a written estimate"* and the
> deadline passed 5 days ago with no matching follow-up.
>
> **Evidence**
> · Sep 1 — Customer: *"Can you send me an estimate for the repair?"*
> · Sep 2 — Us (Dana): *"I'll come by Thursday and get you a written estimate."*
> · Sep 3 — Due. Interpreted from "by Thursday" (named weekday).
> · Sep 8 — Customer: *"Just following up again…"*
> · Today — No outbound email to this contact since the commitment was made.

Six detectors run today, all on email:

| Detector | Finds |
|---|---|
| `unanswered_inbound` | A customer asked something and nobody answered |
| `overdue_commitment` | We promised something by a date and didn't do it |
| `quote_without_followup` | We sent a number and never chased it |
| `stale_opportunity` | A live deal everyone stopped talking about |
| `unresolved_complaint` | An unhappy customer who hasn't been put right |
| `undelivered_email` | Our email bounced and nobody noticed |

Plus: a public **website scan** that needs no account, a **Chaos Score** computed
from counted facts, an **attention engine** that decides what the owner sees, a
**commitment ledger** including kept promises, **entity resolution** across
addresses and phone numbers, and a **morning brief**.

## Principles the code actually enforces

**Evidence or it doesn't ship.** Every finding cites stored messages by id. A
test fails if any detector emits a finding whose evidence cites no real message.

**Never invent money.** `impact_cents` is set only when an amount was observed in
the conversation. Otherwise the UI says VALUE UNKNOWN.

**The score is computed, not generated.** `chaos/score.py` derives every
dimension from counts and carries a methodology version. No model touches it.

**AI is optional.** Detection, scoring and ranking work identically with no API
key. A model only drafts replies a human approves.

**False positives cost more than misses.** A finding that is visibly wrong costs
trust in every correct finding beside it. `chaos/corpus/adversarial.py` exists
because each case in it once produced a wrong finding.

## Run it

```bash
pip install -r requirements.txt
export CHAOS_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
./run.sh                       # http://127.0.0.1:8000
```

Create an account, then either connect a mailbox or click **explore with sample
data** for a fully populated demo business (clearly labelled as demo).

### Connecting a real mailbox

IMAP with an **app password** — chosen as the first integration because it works
today, while Google/Microsoft OAuth app verification takes weeks. Gmail: Google
Account → Security → 2-Step Verification → App passwords. The password is
encrypted with AES-256-GCM before storage and is never returned by any endpoint.

## Quality gates

```bash
python3 -m unittest discover -s tests   # 49 tests
python3 tools/accuracy.py               # labelled corpus: precision & recall
python3 tools/adversarial.py            # the patterns that break naive detectors
```

Current: **71 tests green · 100% precision and recall on the labelled corpus ·
27/27 adversarial cases.**

## Environment

Everything is optional except `CHAOS_SECRET_KEY` (needed only to store
integration credentials — without it, credential storage refuses rather than
writing plaintext).

| Variable | Purpose |
|---|---|
| `CHAOS_SECRET_KEY` | AES key for integration credentials |
| `DATABASE_URL` | Postgres in production; SQLite (`CHAOS_DB`) otherwise |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Draft replies only |
| `CHAOS_SESSION_TTL_DAYS` | Absolute session lifetime (default 30) |
| `CHAOS_SCAN_INTERVAL_HOURS` | Re-scan interval (default 6; `0` disables monitoring) |
| `CHAOS_DISABLE_SCHEDULER` | `1` to turn background scanning off entirely |
| `CHAOS_TRUST_PROXY` | Honour `X-Forwarded-For` for rate limiting |
| `CHAOS_SECURE_COOKIES` | `0` for local http development |
| `BRAND_*` | Rename the product without touching code |

## Layout

```
chaos/
  brand.py        every user-visible product name
  db.py           multi-tenant schema; no read returns data without an org filter
  auth.py         PBKDF2 + opaque sessions + ranked org roles
  crypto.py       AES-256-GCM for integration credentials
  memory.py       entity resolution — the graph the product reasons over
  pipeline.py     raw messages → business memory
  ingest/         mailbox.py (normalization), imap_source.py, rfc822.py
  detect/         commitments.py, signals.py, timeref.py, rules.py, base.py
  score.py        the Chaos Score
  attention.py    what the owner actually sees
  scan.py         the orchestrator
  brief.py        the morning brief
  scheduler.py    continuous monitoring, leased so workers do not duplicate
  app.py          HTTP API + Control Center
  static/         the single-file UI
  corpus/         labelled corpora the detectors are measured against
```

## Known limits

See `NOTES.md` for the honest assessment: what is real, what is scaffolding,
what needs credentials, and the next twenty builds ranked.
