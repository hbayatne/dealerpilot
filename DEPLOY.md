# Deploying Chaos Control

The app is one container: FastAPI on `$PORT`, SQLite by default, Postgres when
`DATABASE_URL` is set. Health check is `GET /api/health`.

## Render (no CLI, about three minutes)

1. [render.com](https://render.com) → **New +** → **Blueprint**.
2. Connect the GitHub repo `hbayatne/dealerpilot` and pick this branch.
3. Render reads `render.yaml`: it builds the `Dockerfile`, creates a Postgres
   instance, generates `CHAOS_SECRET_KEY` and `CHAOS_SIGNUP_CODE`, and wires
   them together. **Apply.**
4. First build takes a few minutes. When it's live, open the service →
   **Environment** → copy the generated `CHAOS_SIGNUP_CODE`.
5. Open the URL on your phone, **Create account**, paste that code.

Cost at the plans in the blueprint: about $7/month for the web service and
about $6/month for Postgres. To try it for nothing first, set the service to
the free plan and delete the `databases:` block and the `DATABASE_URL` entry —
it then runs on SQLite, which on a free instance means **the data resets on
every deploy and the service sleeps when idle** (about a minute to wake). Fine
for a demo, not for real mail.

## Railway

Railway reads the `Procfile` with no extra configuration: **New Project** →
**Deploy from GitHub repo** → add a Postgres plugin (it sets `DATABASE_URL`
itself), then set `CHAOS_SECRET_KEY`, `CHAOS_SIGNUP_CODE` and
`CHAOS_TRUST_PROXY=1` under **Variables**.

## Anywhere else

```bash
docker build -t chaos-control .
docker run -p 8000:8000 \
  -e CHAOS_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" \
  -e CHAOS_SIGNUP_CODE="pick-something" \
  -v chaos-data:/data \
  chaos-control
```

## The environment variables that matter

| Variable | Why it exists |
|---|---|
| `CHAOS_SECRET_KEY` | Encrypts mailbox credentials (AES-256-GCM). **Set it once and never change it** — a new key makes every stored credential unreadable. Without it the app runs and refuses to store credentials rather than writing them in the clear. |
| `CHAOS_SIGNUP_CODE` | Makes sign-up invite-only. A public URL with open registration, next to a business's customer correspondence, is a door. Unset means open sign-up — for local development only. |
| `DATABASE_URL` | Postgres. Unset means SQLite at `CHAOS_DB` (`/data/chaos.db` in the image). |
| `CHAOS_TRUST_PROXY` | Set to `1` **only** behind a proxy that sets `X-Forwarded-For` (Render, Railway, Fly all do). Login rate limiting is per-source and needs the real client address; trusting the header without a proxy in front lets anyone forge it. |
| `CHAOS_SCAN_INTERVAL_HOURS` | Background monitoring cadence. `0` disables it. |
| `ANTHROPIC_API_KEY` | Optional. Drafts and phrasing only — detection, ranking and the score are computed without it. |

## After it's up

Sign in, then **Explore with sample data** or **Sample dealership (with
inventory)** for a populated demo, both labelled DEMO DATA throughout. For
real data: **Connections** → connect a mailbox (IMAP, read-only) and upload a
DealerCenter *Active Inventory* export under **Inventory**.
