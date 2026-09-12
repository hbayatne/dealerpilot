# Chaos Control AI — working notes for engineers

Multi-tenant SaaS that reads the systems a business already uses (email first),
builds a memory of what is actually happening, and surfaces what is falling
through the cracks — with evidence.

## Stack

Python 3 + FastAPI, stdlib-first, no ORM, no frontend build step. SQLite for
development, Postgres in production via the same `?`-placeholder SQL
(`chaos/db.py::_Conn`). These conventions are inherited from `hbayatne/rank-pilot`,
which proved them over ~25k lines; don't reintroduce a framework without a reason
that survives contact with the existing code.

Dependencies are deliberately few (`fastapi`, `uvicorn`, `cryptography`,
`psycopg`). `cryptography` earns its place by encrypting mailbox credentials;
prefer the stdlib for anything else.

## Rules that are not negotiable

**Tenancy.** Every business row carries `org_id`, and every read in `db.py` takes
it. There is no query in that module returning business data without an org
filter — don't add one. Routes resolve `(user, org_id)` to a role through
`require_org`, which returns 404 (not 403) to a non-member, because 403 confirms
the organization exists. `tests/test_security.py` inspects the route table and
fails if a new endpoint skips either check.

**Evidence.** No finding without evidence, and evidence points at stored records
by id — never generated prose. `tests/test_detectors.py` enforces this.

**Money.** `impact_cents` only when an amount was actually observed. Nothing else
may populate it. VALUE UNKNOWN is a correct answer; a plausible guess is not.

**The score is computed.** `chaos/score.py` derives every dimension from counts
and stamps `METHODOLOGY`. If you change how a dimension is calculated, bump the
version — otherwise month-over-month comparisons silently lie.

**AI never decides.** Detection, ranking and scoring must work with no API key.
A model may phrase and draft; it may not determine whether a finding exists.
External content goes through `ai.fence()` and these calls are given no tools.

**Fail soft.** A missing key or unreachable integration disables a feature; it
never crashes the app.

## Detector work

Detectors are deterministic on purpose: testable, free per message, and able to
show their work. A rule that is right 80% of the time and quotes the sentence
beats a model that is right 90% and can't be checked.

Before and after any detector change:

```bash
python3 tools/accuracy.py      # labelled corpus — precision and recall
python3 tools/adversarial.py   # the patterns that break naive detectors
python3 -m unittest discover -s tests
```

**A change that raises recall while adding a false positive is not an
improvement.** A miss costs one finding. A visibly wrong finding costs the
owner's trust in every correct finding beside it.

When you fix a false positive, add the case to `chaos/corpus/adversarial.py`.
Every case in that file is there because it once produced a wrong finding.

Thresholds live at the top of `chaos/detect/rules.py` and are deliberately
conservative: firing early is a false accusation, and an owner forgives a miss
long before being told off for something they were about to do.

## Things that are subtle

- **Threading.** A message resolves under several keys (the root it references,
  its own id, a subject hash) via `db.resolve_conversation`. The root's *own*
  Message-ID must be a key or the first reply opens a second thread.
- **Quoted text.** `mailbox.clean_body` strips reply history. Without it, one
  promise is re-detected in every later reply.
- **Business hours.** Use `base.business_hours_between`, never wall-clock. Mail
  arriving Friday evening and answered Monday morning was answered promptly.
- **Automation.** `classify_automation`, `bounce_reason` and
  `out_of_office_reason` decide what is machine-generated. A bounce or an
  out-of-office makes "they never replied" a false statement.
- **Consolidation.** Several rules firing on one thread describe one situation.
  `rules.consolidate` keeps the one that best describes it and folds the rest in.
- **Entity merges.** Deterministic on email and phone; everything else is a
  *suggestion* a human confirms. A wrong silent merge fuses two customers'
  histories and is effectively unrecoverable for the user.

## Testing

`tests/` uses stdlib `unittest` with isolated temp databases. No linter is
configured. Run the whole suite before pushing — it is fast (about five seconds).
