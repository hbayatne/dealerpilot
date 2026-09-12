# Chaos Control AI — honest status

Written at the end of the first build session. The point of this document is to
be accurate rather than encouraging. Anything described as working has been run;
anything that hasn't been run says so.

---

## What exists and has been run

| Area | Status |
|---|---|
| Multi-tenant foundation, RBAC, audit log | **Working.** Tenant isolation is tested by inspecting the route table, not by example. |
| Email ingestion (IMAP) | **Code complete, never run against a real mailbox.** No credentials were available. |
| Normalization (threading, quoted text, automation, bounces) | **Working**, tested offline against real RFC-822 bytes. |
| Business memory + entity resolution | **Working.** Deterministic merges applied; probabilistic ones only suggested. |
| Six detectors | **Working.** 100% precision/recall on the labelled corpus; 10/10 adversarial. |
| Commitment ledger | **Working**, including kept promises. |
| Chaos Score | **Working.** Computed from counts, versioned methodology, explicit coverage. |
| Attention engine | **Working.** |
| Website scan | **Logic verified offline; the network path was never exercised** — this environment's proxy denies arbitrary outbound hosts. Standard `urllib`; will work where egress is allowed. |
| Control Center UI | **Working.** Verified in Chromium, 15/15 journey steps, no page errors, mobile clean. |
| Morning brief | **Working.** |
| Assignment + workload | **Working.** Manager-gated, audited, and grouped by work rather than by person. |
| Background scheduler | **Working.** Leased in the database so multiple workers cannot duplicate a sync; every run recorded and visible to the customer. |
| CI | **Working.** Tests on 3.11/3.12, both corpora as their own gate, and a boot-and-probe job. |
| Prompt-injection defense | **Working** (fence, neutralised markers, no tools offered). |
| Credential encryption | **Working** (AES-256-GCM; refuses to store without a key). |
| Session expiry, rate limiting | **Working**, tested. |
| Entitlements | **Working** as capability gates. No billing behind them. |
| Product analytics | **Working** (funnel events recorded). |

## What does not exist

- **Billing.** No Stripe, no subscriptions, no payment. Entitlements gate features
  but nothing charges anyone. This is the single largest gap to being sellable.
- **Outbound email.** Password reset exists in `auth.py` but has no transport and
  is not routed in the API. No briefs are delivered; the brief is pull-only.
- **Every integration except IMAP.** Calendar, QuickBooks, CRM, phone, reviews,
  Search Console, ads are named in the UI as "coming soon" and nothing more.
- **Cross-system reconciliation.** The strongest differentiator in the brief, and
  it needs a second system before it can exist at all.
- **Deployment.** Procfile and Postgres support exist; nothing is deployed.

## Verification honestly stated

```
79 tests                                   pass
labelled corpus (12 threads)               100% precision, 100% recall
adversarial corpus (27 cases)              27/27
browser journey on a clean database        15/15 steps, 0 page errors
```

**The important caveat:** both corpora were written by the same author as the
detectors. They contain cases that once broke the detectors, which makes them
real regression tests, but they are not a substitute for real mail. The first
run against a genuine mailbox will find false positives these corpora cannot.
Expect the true precision on real data to be meaningfully lower than 100%, and
treat the "This isn't right" feedback loop as the primary instrument for the
first weeks rather than a nice-to-have.

## Scores

Where a score is below 8, the line says exactly what prevents an 8.

| Category | Score | What prevents a higher score |
|---|---|---|
| Chaos Scan usefulness | **6** | Email only. Seven of twelve dimensions report "not analyzed". The scan is genuinely useful about communication and commitments and silent about money, which is what owners care about most. |
| Finding accuracy | **7** | Perfect on corpora I wrote — now 27 adversarial cases asserting *which* detector fires, not merely that one did — but zero minutes against real mail. The guards are good and the evidence is checkable; the number stays unearned until a real mailbox has run through it. |
| Business Memory | **6** | Resolves people and companies from email and phone well. No CRM or accounting identifiers, no relationship inference beyond "works at", no workflow discovery. The graph is thin because only one system feeds it. |
| Installation simplicity | **7** | Genuinely easy — account, business, app password, scan. But app passwords require the user to already have 2FA set up, which is a real cliff for the messiest businesses, and OAuth isn't built. |
| UX | **7** | Calm, fast, evidence-first, works on a phone, and findings can now be handed to a person. Missing: search, bulk actions, and any notification preferences — and nothing tells an assignee they have been given something, because there is no outbound email. |
| Security | **7** | Strong fundamentals, all tested. Held back by: no CSRF token (relies on SameSite), an in-process rate limiter that breaks across workers, PBKDF2 rather than Argon2, no key rotation, no 2FA, and no independent review. |
| SaaS readiness | **5** | Monitoring is now continuous and CI gates the quality bar, which lifts this from 4. Still no billing, no outbound email, and nothing deployed — the multi-tenant core is sound, the commercial machinery around it does not exist. |
| Subscription value | **5** | A business would get real value from the findings today, but "email hygiene" is a hard thing to charge meaningfully for. The pricing story needs the money dimensions — receivables, leakage — which need QuickBooks. |
| Differentiation | **8** | Evidence-first proactive detection is genuinely different from both dashboards and chatbots, and commitment detection is something no CRM does. Not a 9 or 10 because the deepest moat — cross-system reconciliation — is described but not built. |
| Growth potential | **5** | The free website scan works and is shareable. Nothing else exists: no SEO pages, no free tools, no referral loop, no nurture. Acquisition is currently a single unlinked page. |
| Technical maturity | **7** | Clean architecture, 79 tests, quality harnesses gating CI, honest docs. No linter, no migration framework, no metrics or tracing, never load-tested. |
| **Overall sellability** | **5** | The core experience is real and would demo convincingly. It cannot be sold: nothing takes money, nothing runs on a schedule, and it has not met real data. This is a strong V1 core, not a product. |

## Known defects and risks

1. **False-positive risk on real mail is untested.** Highest risk in the product.
2. **Forwarded messages** are treated as ordinary mail. A customer complaint
   forwarded internally is correctly ignored as internal chatter, but the
   original complaint is then only visible if we also have the original thread.
3. **Non-English mail** is unhandled. Commitment and complaint detection are
   English-only; a Spanish-speaking business gets silence, not an error.
4. **The IMAP cursor is per-folder UID.** A user who reorganizes folders will
   cause a re-scan. Idempotency means no duplicates, but it will be slow.
5. **`business_hours_between` assumes Mon–Fri 09:00–17:00 in the stored
   timezone.** The org has a timezone field that nothing reads yet. A business in
   another timezone will see response times skewed by the offset.
6. **The rate limiter is in-process.** With N workers the effective limit is N×.
7. **`_RUNNING` scan de-duplication is in-process.** The *scheduled* path is
   leased through the database and is safe across workers; a user pressing "Run
   a scan" on two workers at once is not. Harmless (ingestion is idempotent) but
   wasteful.
8. **No pagination on the entity list** beyond a 500-row cap.
9. **Demo data is labelled in the UI but shares the findings tables.** A user with
   both a demo and a real org sees them separately, which is correct, but an
   export would need to exclude demo orgs explicitly.

## Credentials and decisions needed

| Needed | For | Who decides |
|---|---|---|
| A real mailbox + app password | The first honest accuracy measurement | Founder |
| `CHAOS_SECRET_KEY` in the deploy env | Storing integration credentials | Founder |
| Stripe account | Billing | Founder |
| Google Cloud OAuth client | Gmail/Calendar/Search Console without app passwords | Founder — verification takes weeks, start early |
| Intuit developer account | QuickBooks | Founder |
| SMTP or a transactional email provider | Password reset, briefs | Founder |
| Trademark/domain search on "Chaos Control" | Naming | Founder — **not done, and deliberately not done autonomously** |
| Call-recording consent policy per state | Phone integration later | Legal |
| DPA / subprocessor list | Selling to anyone with a compliance function | Legal |

## The next twenty builds, ranked

Ranked by (user value × revenue impact × differentiation) ÷ build cost.

| # | Build | Value | Revenue | Diff. | Cost |
|---|---|---|---|---|---|
| 1 | **Run against a real mailbox and fix what breaks** | Critical | High | — | Low |
| 2 | Stripe billing + trial | Med | **Critical** | Low | Med |
| 3 | Outbound email (brief delivery, password reset) | High | High | Low | Low |
| 4 | QuickBooks — receivables, aging, the money dimensions | **Critical** | **Critical** | High | High |
| 5 | Cross-system reconciliation (needs #4) — the real moat | High | High | **Critical** | Med |
| 6 | Google Calendar — missed appointments, promised meetings | High | Med | Med | Med |
| 7 | Gmail/M365 OAuth — removes the app-password cliff | High | Med | Low | Med |
| 8 | Deploy to Railway with Postgres | Med | High | Low | Low |
| 9 | Search across memory (people, conversations, findings) | Med | Low | Low | Low |
| 10 | Notification policy (urgent / daily / weekly) | Med | Med | Low | Low |
| 11 | Weekly executive review | Med | Med | Med | Low |
| 12 | Free tools for acquisition (response-time, AR calculators) | Med | Med | Low | Low |
| 13 | CRM adapter (HubSpot first) | High | High | High | High |
| 14 | Phone/SMS (Twilio, CallRail) — missed calls | High | High | High | High |
| 15 | Google Business Profile — unanswered reviews | Med | Med | Med | Med |
| 16 | Industry packs (vertical terminology and rules) | Med | Med | High | Med |
| 17 | Value attribution — identified / influenced / recovered | Med | High | High | Med |
| 18 | Benchmarking across tenants (privacy-safe cohorts) | Med | Med | **Critical** | High |

**If only one thing happens next: number 1.** Every score above is capped by the
fact that this has never seen real mail, and no amount of further building raises
that ceiling.

## Naming

"Chaos Control AI" is a working name. No trademark search, domain purchase or
filing was done — deliberately, as those are commitments rather than code. All
user-visible strings come from `chaos/brand.py` and can be overridden with
`BRAND_*` environment variables, so a rename costs a config change. The emotional
arc (chaos → control) should survive whatever the brand becomes.
