"""
Data layer — multi-tenant, no ORM, stdlib-first.

SQLite for dev, Postgres in production (set DATABASE_URL). The same `?`-style
SQL runs on both via the `_Conn` wrapper.

Tenancy rule, enforced everywhere in this module: **every** business row carries
an `org_id` and every read takes it as an argument. There is no query in this
file that returns business data without an org_id filter. Never add one.
"""
import datetime
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CHAOS_DB", os.path.join(HERE, "chaos.db"))

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
IS_PG = bool(DATABASE_URL)

if IS_PG:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg import errors as _pg_errors
    _INTEGRITY_ERRORS = (sqlite3.IntegrityError, _pg_errors.UniqueViolation)
else:
    _INTEGRITY_ERRORS = (sqlite3.IntegrityError,)


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(
        tzinfo=None).isoformat(timespec="seconds")


class _Conn:
    """Same SQL on SQLite and Postgres; rows are dict-accessible on both."""

    def __init__(self):
        if IS_PG:
            self.raw = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        else:
            self.raw = sqlite3.connect(DB_PATH)
            self.raw.row_factory = sqlite3.Row
            self.raw.execute("PRAGMA foreign_keys=ON")

    def execute(self, sql, params=()):
        cur = self.raw.cursor()
        cur.execute(sql.replace("?", "%s") if IS_PG else sql, params)
        return cur

    def executescript(self, sql):
        if IS_PG:
            cur = self.raw.cursor()
            for stmt in (s.strip() for s in sql.split(";")):
                if stmt:
                    cur.execute(stmt)
        else:
            self.raw.executescript(sql)

    def insert_id(self, sql, params):
        if IS_PG:
            q = sql.replace("?", "%s")
            if "returning" not in q.lower():
                q += " RETURNING id"
            cur = self.raw.cursor()
            cur.execute(q, params)
            return cur.fetchone()["id"]
        cur = self.raw.cursor()
        cur.execute(sql, params)
        return cur.lastrowid

    def commit(self):
        self.raw.commit()

    def close(self):
        self.raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *_):
        if exc_type is None:
            self.raw.commit()
        else:
            self.raw.rollback()
        self.raw.close()
        return False


def _conn():
    return _Conn()


def _j(v):
    """JSON column → Python, tolerant of NULL and of Postgres' native json."""
    if v is None or v == "":
        return None
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return None


SCHEMA_VERSION = 1


def init():
    c = _conn()
    pk = "BIGSERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    c.executescript(f"""
    CREATE TABLE IF NOT EXISTS users (
        id {pk},
        email TEXT UNIQUE NOT NULL,
        name TEXT,
        password_hash TEXT NOT NULL,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS password_resets (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at TEXT NOT NULL
    );

    -- ---------------- tenancy ----------------
    CREATE TABLE IF NOT EXISTS orgs (
        id {pk},
        name TEXT NOT NULL,
        website TEXT,
        industry TEXT,
        timezone TEXT DEFAULT 'UTC',
        domains TEXT DEFAULT '[]',     -- company email domains: "us" vs "them"
        plan TEXT DEFAULT 'scan',
        settings TEXT DEFAULT '{{}}',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS memberships (
        id {pk},
        org_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL DEFAULT 'owner',
        created_at TEXT
    );

    -- ---------------- integrations ----------------
    CREATE TABLE IF NOT EXISTS integrations (
        id {pk},
        org_id INTEGER NOT NULL,
        kind TEXT NOT NULL,            -- imap | gmail | calendar | quickbooks ...
        label TEXT,
        status TEXT DEFAULT 'connected',
        config TEXT DEFAULT '{{}}',     -- non-secret settings
        secret TEXT,                   -- encrypted credential blob
        cursor TEXT,                   -- incremental sync position
        last_sync_at TEXT,
        last_error TEXT,
        created_at TEXT
    );

    -- ---------------- business memory ----------------
    CREATE TABLE IF NOT EXISTS entities (
        id {pk},
        org_id INTEGER NOT NULL,
        kind TEXT NOT NULL,            -- person | company
        display_name TEXT,
        role TEXT,                     -- customer | prospect | vendor | employee | unknown
        confidence REAL DEFAULT 0.5,
        meta TEXT DEFAULT '{{}}',
        first_seen_at TEXT,
        last_seen_at TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS identities (
        id {pk},
        org_id INTEGER NOT NULL,
        entity_id INTEGER NOT NULL,
        kind TEXT NOT NULL,            -- email | phone | domain | crm_id | name
        value TEXT NOT NULL,
        confidence REAL DEFAULT 1.0,
        source TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS entity_links (
        id {pk},
        org_id INTEGER NOT NULL,
        from_id INTEGER NOT NULL,
        to_id INTEGER NOT NULL,
        relation TEXT NOT NULL,        -- works_at | contacted | about
        confidence REAL DEFAULT 0.5,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS merge_decisions (
        id {pk},
        org_id INTEGER NOT NULL,
        a_id INTEGER NOT NULL,
        b_id INTEGER NOT NULL,
        decision TEXT NOT NULL,        -- same | not_same
        user_id INTEGER,
        created_at TEXT
    );

    -- ---------------- communications ----------------
    CREATE TABLE IF NOT EXISTS conversations (
        id {pk},
        org_id INTEGER NOT NULL,
        source TEXT NOT NULL,
        source_id TEXT,                -- provider thread id
        subject TEXT,
        entity_id INTEGER,             -- the external counterparty
        first_at TEXT,
        last_at TEXT,
        msg_count INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS conversation_keys (
        id {pk},
        org_id INTEGER NOT NULL,
        conversation_id INTEGER NOT NULL,
        key TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS messages (
        id {pk},
        org_id INTEGER NOT NULL,
        conversation_id INTEGER,
        source TEXT NOT NULL,
        source_id TEXT,
        direction TEXT,                -- in | out | internal
        from_addr TEXT,
        from_name TEXT,
        to_addrs TEXT DEFAULT '[]',
        cc_addrs TEXT DEFAULT '[]',
        sent_at TEXT,
        subject TEXT,
        body TEXT,                     -- retention-governed, see privacy.py
        snippet TEXT,
        automated TEXT,                -- why we think it is machine-generated
        auto_kind TEXT,                -- bounce | out_of_office | bulk
        attachments INTEGER DEFAULT 0,
        thread_key TEXT,
        entity_id INTEGER,
        actor_entity_id INTEGER,       -- the employee on our side
        created_at TEXT
    );

    -- ---------------- event ledger ----------------
    CREATE TABLE IF NOT EXISTS events (
        id {pk},
        org_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        occurred_at TEXT,
        source TEXT,
        source_id TEXT,
        entity_id INTEGER,
        ref_kind TEXT,
        ref_id INTEGER,
        confidence REAL DEFAULT 1.0,
        payload TEXT DEFAULT '{{}}',
        created_at TEXT
    );

    -- ---------------- commitments ----------------
    CREATE TABLE IF NOT EXISTS commitments (
        id {pk},
        org_id INTEGER NOT NULL,
        message_id INTEGER,
        conversation_id INTEGER,
        entity_id INTEGER,             -- who it was promised to
        promiser TEXT,                 -- email address of who promised
        direction TEXT,                -- out = we promised, in = they promised
        text TEXT,
        quote TEXT,
        due_at TEXT,
        due_basis TEXT,
        state TEXT DEFAULT 'open',     -- open | fulfilled | likely_fulfilled | overdue | unknown
        confidence REAL DEFAULT 0.5,
        detector TEXT,
        created_at TEXT
    );

    -- ---------------- findings ----------------
    CREATE TABLE IF NOT EXISTS findings (
        id {pk},
        org_id INTEGER NOT NULL,
        dedupe_key TEXT,
        category TEXT NOT NULL,
        subcategory TEXT,
        title TEXT,
        summary TEXT,
        severity TEXT DEFAULT 'medium',
        confidence REAL DEFAULT 0.5,
        impact_cents INTEGER,
        impact_basis TEXT,
        impact_low_cents INTEGER,
        impact_high_cents INTEGER,
        urgency REAL DEFAULT 0.5,
        attention REAL DEFAULT 0,
        entity_id INTEGER,
        owner TEXT,
        source_systems TEXT DEFAULT '[]',
        recommended_action TEXT,
        ai_actionable INTEGER DEFAULT 0,
        approval_required INTEGER DEFAULT 1,
        risk TEXT DEFAULT 'low',
        status TEXT DEFAULT 'new',
        resolution TEXT,
        detector TEXT,
        detected_at TEXT,
        updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS evidence (
        id {pk},
        org_id INTEGER NOT NULL,
        finding_id INTEGER NOT NULL,
        seq INTEGER DEFAULT 0,
        occurred_at TEXT,
        label TEXT,
        detail TEXT,
        ref_kind TEXT,
        ref_id INTEGER
    );
    CREATE TABLE IF NOT EXISTS finding_feedback (
        id {pk},
        org_id INTEGER NOT NULL,
        finding_id INTEGER NOT NULL,
        user_id INTEGER,
        verdict TEXT,                  -- useful | false_positive | not_now
        note TEXT,
        created_at TEXT
    );

    -- ---------------- scores & scans ----------------
    CREATE TABLE IF NOT EXISTS scores (
        id {pk},
        org_id INTEGER NOT NULL,
        score INTEGER,
        band TEXT,
        methodology TEXT,
        dimensions TEXT DEFAULT '{{}}',
        coverage TEXT DEFAULT '{{}}',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS scans (
        id {pk},
        org_id INTEGER,
        kind TEXT,                     -- website | full
        target TEXT,
        status TEXT DEFAULT 'queued',
        progress INTEGER DEFAULT 0,
        step TEXT,
        result TEXT,
        error TEXT,
        share_token TEXT,
        shared INTEGER DEFAULT 0,
        created_at TEXT,
        finished_at TEXT
    );

    CREATE TABLE IF NOT EXISTS job_runs (
        id {pk},
        org_id INTEGER,
        job TEXT NOT NULL,
        status TEXT,                   -- running | ok | error
        detail TEXT,
        started_at TEXT,
        finished_at TEXT
    );
    CREATE TABLE IF NOT EXISTS job_leases (
        name TEXT PRIMARY KEY,
        holder TEXT,
        expires_at TEXT
    );

    -- ---------------- platform ----------------
    CREATE TABLE IF NOT EXISTS analytics_events (
        id {pk},
        org_id INTEGER,
        user_id INTEGER,
        name TEXT NOT NULL,
        props TEXT DEFAULT '{{}}',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS audit_log (
        id {pk},
        org_id INTEGER,
        user_id INTEGER,
        action TEXT NOT NULL,
        target TEXT,
        detail TEXT,
        created_at TEXT
    );
    """)
    for stmt in (
        "CREATE INDEX IF NOT EXISTS ix_msg_org_sent ON messages(org_id, sent_at)",
        "CREATE INDEX IF NOT EXISTS ix_msg_conv ON messages(org_id, conversation_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_msg_src ON messages(org_id, source, source_id)",
        "CREATE INDEX IF NOT EXISTS ix_conv_org ON conversations(org_id, last_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_conv_src ON conversations(org_id, source, source_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_convkey ON conversation_keys(org_id, key)",
        "CREATE INDEX IF NOT EXISTS ix_ident ON identities(org_id, kind, value)",
        "CREATE INDEX IF NOT EXISTS ix_ent_org ON entities(org_id, kind)",
        "CREATE INDEX IF NOT EXISTS ix_ev_org ON events(org_id, occurred_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_find_dedupe ON findings(org_id, dedupe_key)",
        "CREATE INDEX IF NOT EXISTS ix_find_org ON findings(org_id, status, attention)",
        "CREATE INDEX IF NOT EXISTS ix_evid_find ON evidence(org_id, finding_id, seq)",
        "CREATE INDEX IF NOT EXISTS ix_commit_org ON commitments(org_id, state)",
        "CREATE INDEX IF NOT EXISTS ix_member ON memberships(user_id)",
        "CREATE INDEX IF NOT EXISTS ix_jobrun ON job_runs(org_id, job, id)",
    ):
        try:
            c.execute(stmt)
        except Exception:
            pass
    c.commit()
    c.close()


# ============================ users / sessions ============================
def create_user(email, password_hash, name=None):
    c = _conn()
    try:
        uid = c.insert_id(
            "INSERT INTO users (email, name, password_hash, created_at) VALUES (?,?,?,?)",
            ((email or "").strip().lower(), name, password_hash, now()))
        c.commit()
        return uid
    except _INTEGRITY_ERRORS:
        return None
    finally:
        c.close()


def get_user_by_email(email):
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE email=?",
                      ((email or "").strip().lower(),)).fetchone()
        return dict(r) if r else None


def get_user(uid):
    with _conn() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(r) if r else None


def set_password(uid, password_hash):
    with _conn() as c:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, uid))


def create_session(token, user_id):
    with _conn() as c:
        c.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?,?,?)",
                  (token, user_id, now()))


SESSION_TTL_DAYS = int(os.environ.get("CHAOS_SESSION_TTL_DAYS", "30"))


def user_for_session(token):
    """Resolve a session cookie, honouring an absolute lifetime.

    Sessions expire server-side, not merely in the cookie: a cookie's max-age is
    a request to the browser, and a stolen token would otherwise be valid
    forever. An expired row is deleted on the way past so the table self-cleans.
    """
    if not token:
        return None
    cutoff = (datetime.datetime.utcnow()
              - datetime.timedelta(days=SESSION_TTL_DAYS)).isoformat(timespec="seconds")
    with _conn() as c:
        r = c.execute(
            """SELECT u.*, s.created_at AS session_started FROM sessions s
               JOIN users u ON u.id=s.user_id WHERE s.token=?""", (token,)).fetchone()
        if not r:
            return None
        if (r["session_started"] or "") < cutoff:
            c.execute("DELETE FROM sessions WHERE token=?", (token,))
            return None
        d = dict(r)
        d.pop("session_started", None)
        return d


def purge_expired_sessions():
    cutoff = (datetime.datetime.utcnow()
              - datetime.timedelta(days=SESSION_TTL_DAYS)).isoformat(timespec="seconds")
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE created_at < ?", (cutoff,))


def delete_session(token):
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (token,))


def delete_user_sessions(uid):
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))


def create_reset(token, user_id, expires_at):
    with _conn() as c:
        c.execute("INSERT INTO password_resets (token,user_id,expires_at) VALUES (?,?,?)",
                  (token, user_id, expires_at))


def get_reset(token):
    with _conn() as c:
        r = c.execute("SELECT * FROM password_resets WHERE token=?", (token,)).fetchone()
        return dict(r) if r else None


def delete_reset(token):
    with _conn() as c:
        c.execute("DELETE FROM password_resets WHERE token=?", (token,))


# ============================ orgs / membership ============================
def _row_to_org(r):
    d = dict(r)
    d["domains"] = _j(d.get("domains")) or []
    d["settings"] = _j(d.get("settings")) or {}
    return d


def create_org(name, website="", industry="", user_id=None, timezone="UTC", domains=None):
    c = _conn()
    try:
        oid = c.insert_id(
            """INSERT INTO orgs (name, website, industry, timezone, domains, created_at)
               VALUES (?,?,?,?,?,?)""",
            (name, website or "", industry or "", timezone or "UTC",
             json.dumps(domains or []), now()))
        if user_id:
            c.execute("""INSERT INTO memberships (org_id,user_id,role,created_at)
                         VALUES (?,?,?,?)""", (oid, user_id, "owner", now()))
        c.commit()
        return oid
    finally:
        c.close()


def get_org(org_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM orgs WHERE id=?", (org_id,)).fetchone()
        return _row_to_org(r) if r else None


def update_org(org_id, **fields):
    allowed = {"name", "website", "industry", "timezone", "plan"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
        elif k == "domains":
            sets.append("domains=?")
            params.append(json.dumps(v or []))
        elif k == "settings":
            sets.append("settings=?")
            params.append(json.dumps(v or {}))
    if not sets:
        return
    params.append(org_id)
    with _conn() as c:
        c.execute(f"UPDATE orgs SET {', '.join(sets)} WHERE id=?", params)


def orgs_for_user(user_id):
    with _conn() as c:
        rows = c.execute(
            """SELECT o.*, m.role FROM memberships m JOIN orgs o ON o.id=m.org_id
               WHERE m.user_id=? ORDER BY o.id""", (user_id,)).fetchall()
        return [dict(_row_to_org(r), role=r["role"]) for r in rows]


def membership(user_id, org_id):
    """The authorization primitive. Returns the role, or None when the user has
    no access to this org. Every org-scoped route must call this."""
    with _conn() as c:
        r = c.execute("SELECT role FROM memberships WHERE user_id=? AND org_id=?",
                      (user_id, org_id)).fetchone()
        return r["role"] if r else None


def add_member(org_id, user_id, role="employee"):
    with _conn() as c:
        c.execute("INSERT INTO memberships (org_id,user_id,role,created_at) VALUES (?,?,?,?)",
                  (org_id, user_id, role, now()))


def members(org_id):
    with _conn() as c:
        rows = c.execute(
            """SELECT u.id, u.email, u.name, m.role FROM memberships m
               JOIN users u ON u.id=m.user_id WHERE m.org_id=? ORDER BY u.id""",
            (org_id,)).fetchall()
        return [dict(r) for r in rows]


# ============================ integrations ============================
def _row_to_integration(r):
    d = dict(r)
    d["config"] = _j(d.get("config")) or {}
    d.pop("secret", None)          # never leaves the server
    d.pop("cursor", None)
    return d


def upsert_integration(org_id, kind, label=None, config=None, secret=None, status="connected"):
    c = _conn()
    try:
        r = c.execute("SELECT id FROM integrations WHERE org_id=? AND kind=?",
                      (org_id, kind)).fetchone()
        if r:
            c.execute("""UPDATE integrations SET label=?, config=?, secret=COALESCE(?,secret),
                         status=?, last_error=NULL WHERE id=?""",
                      (label, json.dumps(config or {}), secret, status, r["id"]))
            c.commit()
            return r["id"]
        iid = c.insert_id(
            """INSERT INTO integrations (org_id,kind,label,status,config,secret,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (org_id, kind, label, status, json.dumps(config or {}), secret, now()))
        c.commit()
        return iid
    finally:
        c.close()


def integrations(org_id):
    with _conn() as c:
        rows = c.execute("SELECT * FROM integrations WHERE org_id=? ORDER BY id",
                         (org_id,)).fetchall()
        return [_row_to_integration(r) for r in rows]


def integration(org_id, kind):
    """Internal use — includes the secret. Never return this to a client."""
    with _conn() as c:
        r = c.execute("SELECT * FROM integrations WHERE org_id=? AND kind=?",
                      (org_id, kind)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["config"] = _j(d.get("config")) or {}
        return d


def mark_sync(org_id, kind, cursor=None, error=None):
    with _conn() as c:
        c.execute("""UPDATE integrations SET last_sync_at=?, cursor=COALESCE(?,cursor),
                     last_error=?, status=? WHERE org_id=? AND kind=?""",
                  (now(), cursor, error, "error" if error else "connected", org_id, kind))


def delete_integration(org_id, kind):
    with _conn() as c:
        c.execute("DELETE FROM integrations WHERE org_id=? AND kind=?", (org_id, kind))


# ============================ jobs ============================
def acquire_lease(name, holder, ttl_seconds):
    """Claim a named lease, or return False if someone else holds a live one.

    The scheduler runs inside the web process, so N workers means N schedulers
    all syncing the same mailboxes. A lease in the shared database is the only
    coordination point they all have; without it the duplicate work is invisible
    and the provider rate-limits are hit N times faster.
    """
    now_s = datetime.datetime.utcnow()
    expires = (now_s + datetime.timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
    cutoff = now_s.isoformat(timespec="seconds")
    c = _conn()
    try:
        r = c.execute("SELECT holder, expires_at FROM job_leases WHERE name=?",
                      (name,)).fetchone()
        if r is None:
            try:
                c.execute("INSERT INTO job_leases (name,holder,expires_at) VALUES (?,?,?)",
                          (name, holder, expires))
                c.commit()
                return True
            except _INTEGRITY_ERRORS:
                return False
        if r["holder"] == holder or (r["expires_at"] or "") < cutoff:
            # Ours to renew, or the previous holder's lease has lapsed.
            cur = c.execute(
                """UPDATE job_leases SET holder=?, expires_at=?
                   WHERE name=? AND (holder=? OR expires_at < ?)""",
                (holder, expires, name, holder, cutoff))
            c.commit()
            return cur.rowcount > 0
        return False
    finally:
        c.close()


def release_lease(name, holder):
    with _conn() as c:
        c.execute("DELETE FROM job_leases WHERE name=? AND holder=?", (name, holder))


def start_job(org_id, job):
    with _conn() as c:
        return c.insert_id(
            """INSERT INTO job_runs (org_id,job,status,started_at) VALUES (?,?,?,?)""",
            (org_id, job, "running", now()))


def finish_job(job_id, status, detail=None):
    with _conn() as c:
        c.execute("UPDATE job_runs SET status=?, detail=?, finished_at=? WHERE id=?",
                  (status, (detail or "")[:500], now(), job_id))


def job_history(org_id=None, limit=50):
    q = "SELECT * FROM job_runs"
    params = []
    if org_id is not None:
        q += " WHERE org_id=?"
        params.append(org_id)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(q, params).fetchall()]


def orgs_with_integrations(kind=None):
    """Orgs the scheduler should visit."""
    q = """SELECT DISTINCT org_id FROM integrations WHERE status != 'disabled'"""
    params = []
    if kind:
        q += " AND kind=?"
        params.append(kind)
    with _conn() as c:
        return [r["org_id"] for r in c.execute(q, params).fetchall()]


# ============================ analytics / audit ============================
def track(name, org_id=None, user_id=None, **props):
    try:
        with _conn() as c:
            c.execute("""INSERT INTO analytics_events (org_id,user_id,name,props,created_at)
                         VALUES (?,?,?,?,?)""",
                      (org_id, user_id, name, json.dumps(props or {}), now()))
    except Exception:
        pass  # analytics must never break a request


def funnel(org_id=None):
    q = "SELECT name, COUNT(*) n FROM analytics_events"
    params = ()
    if org_id:
        q += " WHERE org_id=?"
        params = (org_id,)
    q += " GROUP BY name"
    with _conn() as c:
        return {r["name"]: r["n"] for r in c.execute(q, params).fetchall()}


def audit(org_id, user_id, action, target=None, detail=None):
    with _conn() as c:
        c.execute("""INSERT INTO audit_log (org_id,user_id,action,target,detail,created_at)
                     VALUES (?,?,?,?,?,?)""", (org_id, user_id, action, target, detail, now()))


def audit_trail(org_id, limit=100):
    with _conn() as c:
        rows = c.execute("""SELECT a.*, u.email FROM audit_log a
                            LEFT JOIN users u ON u.id=a.user_id
                            WHERE a.org_id=? ORDER BY a.id DESC LIMIT ?""",
                         (org_id, limit)).fetchall()
        return [dict(r) for r in rows]


# ============================ business memory ============================
def _row_to_entity(r):
    d = dict(r)
    d["meta"] = _j(d.get("meta")) or {}
    return d


def create_entity(org_id, kind, display_name=None, role="unknown", confidence=0.5, meta=None,
                  seen_at=None):
    with _conn() as c:
        return c.insert_id(
            """INSERT INTO entities (org_id,kind,display_name,role,confidence,meta,
                                     first_seen_at,last_seen_at,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (org_id, kind, display_name, role, confidence, json.dumps(meta or {}),
             seen_at, seen_at, now()))


def get_entity(org_id, entity_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM entities WHERE org_id=? AND id=?",
                      (org_id, entity_id)).fetchone()
        return _row_to_entity(r) if r else None


def update_entity(org_id, entity_id, **fields):
    allowed = {"display_name", "role", "confidence", "kind", "first_seen_at", "last_seen_at"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
        elif k == "meta":
            sets.append("meta=?")
            params.append(json.dumps(v or {}))
    if not sets:
        return
    params += [org_id, entity_id]
    with _conn() as c:
        c.execute(f"UPDATE entities SET {', '.join(sets)} WHERE org_id=? AND id=?", params)


def touch_entity(org_id, entity_id, seen_at):
    """Widen an entity's first/last-seen window. Cheap, called per message."""
    if not seen_at:
        return
    with _conn() as c:
        c.execute("""UPDATE entities
                     SET last_seen_at = CASE WHEN last_seen_at IS NULL OR last_seen_at < ?
                                             THEN ? ELSE last_seen_at END,
                         first_seen_at = CASE WHEN first_seen_at IS NULL OR first_seen_at > ?
                                              THEN ? ELSE first_seen_at END
                     WHERE org_id=? AND id=?""",
                  (seen_at, seen_at, seen_at, seen_at, org_id, entity_id))


def add_identity(org_id, entity_id, kind, value, confidence=1.0, source=None):
    with _conn() as c:
        existing = c.execute(
            "SELECT id FROM identities WHERE org_id=? AND kind=? AND value=? AND entity_id=?",
            (org_id, kind, value, entity_id)).fetchone()
        if existing:
            return existing["id"]
        return c.insert_id(
            """INSERT INTO identities (org_id,entity_id,kind,value,confidence,source,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (org_id, entity_id, kind, value, confidence, source, now()))


def find_by_identity(org_id, kind, value):
    with _conn() as c:
        r = c.execute(
            """SELECT e.* FROM identities i JOIN entities e ON e.id=i.entity_id
               WHERE i.org_id=? AND i.kind=? AND i.value=? ORDER BY i.confidence DESC LIMIT 1""",
            (org_id, kind, value)).fetchone()
        return _row_to_entity(r) if r else None


def identities_for(org_id, entity_id):
    with _conn() as c:
        rows = c.execute("SELECT * FROM identities WHERE org_id=? AND entity_id=? ORDER BY id",
                         (org_id, entity_id)).fetchall()
        return [dict(r) for r in rows]


def entities(org_id, kind=None, role=None, limit=500):
    q = "SELECT * FROM entities WHERE org_id=?"
    params = [org_id]
    if kind:
        q += " AND kind=?"
        params.append(kind)
    if role:
        q += " AND role=?"
        params.append(role)
    q += " ORDER BY last_seen_at DESC NULLS LAST" if IS_PG else " ORDER BY last_seen_at DESC"
    q += " LIMIT ?"
    params.append(limit)
    with _conn() as c:
        return [_row_to_entity(r) for r in c.execute(q, params).fetchall()]


def link_entities(org_id, from_id, to_id, relation, confidence=0.5):
    with _conn() as c:
        r = c.execute("""SELECT id FROM entity_links WHERE org_id=? AND from_id=? AND to_id=?
                         AND relation=?""", (org_id, from_id, to_id, relation)).fetchone()
        if r:
            return r["id"]
        return c.insert_id(
            """INSERT INTO entity_links (org_id,from_id,to_id,relation,confidence,created_at)
               VALUES (?,?,?,?,?,?)""", (org_id, from_id, to_id, relation, confidence, now()))


def links_for(org_id, entity_id):
    with _conn() as c:
        rows = c.execute(
            """SELECT l.*, e.display_name, e.kind FROM entity_links l
               JOIN entities e ON e.id=l.to_id
               WHERE l.org_id=? AND l.from_id=?""", (org_id, entity_id)).fetchall()
        return [dict(r) for r in rows]


def record_merge_decision(org_id, a_id, b_id, decision, user_id=None):
    a, b = sorted((int(a_id), int(b_id)))
    with _conn() as c:
        c.execute("""INSERT INTO merge_decisions (org_id,a_id,b_id,decision,user_id,created_at)
                     VALUES (?,?,?,?,?,?)""", (org_id, a, b, decision, user_id, now()))


def merge_decision(org_id, a_id, b_id):
    a, b = sorted((int(a_id), int(b_id)))
    with _conn() as c:
        r = c.execute("""SELECT decision FROM merge_decisions WHERE org_id=? AND a_id=? AND b_id=?
                         ORDER BY id DESC LIMIT 1""", (org_id, a, b)).fetchone()
        return r["decision"] if r else None


def merge_entities(org_id, keep_id, drop_id):
    """Fold `drop_id` into `keep_id`. Identities, messages, conversations,
    findings and commitments all re-point. Recorded so it can be reviewed."""
    if int(keep_id) == int(drop_id):
        return
    with _conn() as c:
        for tbl in ("identities", "entity_links"):
            col = "entity_id" if tbl == "identities" else "from_id"
            c.execute(f"UPDATE {tbl} SET {col}=? WHERE org_id=? AND {col}=?",
                      (keep_id, org_id, drop_id))
        c.execute("UPDATE entity_links SET to_id=? WHERE org_id=? AND to_id=?",
                  (keep_id, org_id, drop_id))
        for tbl in ("messages", "conversations", "events", "commitments", "findings"):
            c.execute(f"UPDATE {tbl} SET entity_id=? WHERE org_id=? AND entity_id=?",
                      (keep_id, org_id, drop_id))
        c.execute("UPDATE messages SET actor_entity_id=? WHERE org_id=? AND actor_entity_id=?",
                  (keep_id, org_id, drop_id))
        c.execute("DELETE FROM entities WHERE org_id=? AND id=?", (org_id, drop_id))
    record_merge_decision(org_id, keep_id, drop_id, "same")


# ============================ communications ============================
def _row_to_message(r):
    d = dict(r)
    d["to_addrs"] = _j(d.get("to_addrs")) or []
    d["cc_addrs"] = _j(d.get("cc_addrs")) or []
    return d


def resolve_conversation(org_id, source, keys, subject=None, entity_id=None):
    """Find (or open) the conversation these thread keys belong to.

    A message can be identified by several keys — the root it references, its own
    id, a subject hash. Any one of them matching an existing thread means this
    message belongs to that thread, and the remaining keys become aliases for it.
    That is what keeps a reply with the original instead of opening a second
    conversation nobody can reason across.
    """
    keys = [k for k in (keys or []) if k]
    if not keys:
        return None
    c = _conn()
    try:
        cid = None
        for k in keys:
            r = c.execute("SELECT conversation_id FROM conversation_keys WHERE org_id=? AND key=?",
                          (org_id, k)).fetchone()
            if r:
                cid = r["conversation_id"]
                break
        if cid is None:
            r = c.execute("SELECT id FROM conversations WHERE org_id=? AND source=? AND source_id=?",
                          (org_id, source, keys[0])).fetchone()
            if r:
                cid = r["id"]
            else:
                cid = c.insert_id(
                    """INSERT INTO conversations (org_id,source,source_id,subject,entity_id,
                                                  created_at) VALUES (?,?,?,?,?,?)""",
                    (org_id, source, keys[0], subject, entity_id, now()))
        for k in keys:
            try:
                c.execute("""INSERT INTO conversation_keys (org_id,conversation_id,key)
                             VALUES (?,?,?)""", (org_id, cid, k))
            except _INTEGRITY_ERRORS:
                pass          # already an alias, possibly of another thread
        if entity_id:
            c.execute("UPDATE conversations SET entity_id=COALESCE(entity_id,?) WHERE id=?",
                      (entity_id, cid))
        if subject:
            c.execute("UPDATE conversations SET subject=COALESCE(subject,?) WHERE id=?",
                      (subject, cid))
        c.commit()
        return cid
    finally:
        c.close()


def upsert_conversation(org_id, source, source_id, subject=None, entity_id=None):
    return resolve_conversation(org_id, source, [source_id], subject, entity_id)


def add_message(org_id, **m):
    """Insert one normalized message. Idempotent on (org_id, source, source_id):
    re-syncing the same mailbox never duplicates. Returns the id, or None when
    the message was already stored."""
    c = _conn()
    try:
        mid = c.insert_id(
            """INSERT INTO messages (org_id,conversation_id,source,source_id,direction,
                   from_addr,from_name,to_addrs,cc_addrs,sent_at,subject,body,snippet,
                   automated,auto_kind,attachments,thread_key,entity_id,
                   actor_entity_id,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (org_id, m.get("conversation_id"), m.get("source", "email"), m.get("source_id"),
             m.get("direction"), m.get("from_addr"), m.get("from_name"),
             json.dumps(m.get("to_addrs") or []), json.dumps(m.get("cc_addrs") or []),
             m.get("sent_at"), m.get("subject"),
             m.get("body"), m.get("snippet"), m.get("automated"), m.get("auto_kind"),
             int(m.get("attachments") or 0), m.get("thread_key"), m.get("entity_id"),
             m.get("actor_entity_id"), now()))
        c.commit()
        return mid
    except _INTEGRITY_ERRORS:
        return None
    finally:
        c.close()


def refresh_conversation(org_id, conversation_id):
    """Recompute a thread's rollup (counts + window) from its messages."""
    with _conn() as c:
        r = c.execute("""SELECT COUNT(*) n, MIN(sent_at) f, MAX(sent_at) l
                         FROM messages WHERE org_id=? AND conversation_id=?""",
                      (org_id, conversation_id)).fetchone()
        c.execute("UPDATE conversations SET msg_count=?, first_at=?, last_at=? WHERE id=?",
                  (r["n"], r["f"], r["l"], conversation_id))


def conversations(org_id, limit=500):
    with _conn() as c:
        rows = c.execute("""SELECT * FROM conversations WHERE org_id=?
                            ORDER BY last_at DESC LIMIT ?""", (org_id, limit)).fetchall()
        return [dict(r) for r in rows]


def conversation(org_id, cid):
    with _conn() as c:
        r = c.execute("SELECT * FROM conversations WHERE org_id=? AND id=?",
                      (org_id, cid)).fetchone()
        return dict(r) if r else None


def messages_in(org_id, conversation_id):
    with _conn() as c:
        rows = c.execute("""SELECT * FROM messages WHERE org_id=? AND conversation_id=?
                            ORDER BY sent_at, id""", (org_id, conversation_id)).fetchall()
        return [_row_to_message(r) for r in rows]


def get_message(org_id, mid):
    with _conn() as c:
        r = c.execute("SELECT * FROM messages WHERE org_id=? AND id=?", (org_id, mid)).fetchone()
        return _row_to_message(r) if r else None


def last_outbound_to(org_id, entity_id, before=None, after=None):
    """The most recent outbound message to one contact, bounded in time."""
    q = """SELECT * FROM messages WHERE org_id=? AND entity_id=? AND direction='out'"""
    params = [org_id, entity_id]
    if before:
        q += " AND sent_at <= ?"
        params.append(before)
    if after:
        q += " AND sent_at > ?"
        params.append(after)
    q += " ORDER BY sent_at DESC LIMIT 1"
    with _conn() as c:
        r = c.execute(q, params).fetchone()
        return _row_to_message(r) if r else None


def message_count(org_id):
    with _conn() as c:
        return c.execute("SELECT COUNT(*) n FROM messages WHERE org_id=?",
                         (org_id,)).fetchone()["n"]


# ============================ event ledger ============================
def add_event(org_id, kind, occurred_at=None, source=None, source_id=None, entity_id=None,
              ref_kind=None, ref_id=None, confidence=1.0, payload=None):
    with _conn() as c:
        return c.insert_id(
            """INSERT INTO events (org_id,kind,occurred_at,source,source_id,entity_id,
                                   ref_kind,ref_id,confidence,payload,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (org_id, kind, occurred_at or now(), source, source_id, entity_id,
             ref_kind, ref_id, confidence, json.dumps(payload or {}), now()))


def events(org_id, kind=None, since=None, limit=500):
    q = "SELECT * FROM events WHERE org_id=?"
    params = [org_id]
    if kind:
        q += " AND kind=?"
        params.append(kind)
    if since:
        q += " AND occurred_at >= ?"
        params.append(since)
    q += " ORDER BY occurred_at DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        return [dict(r, payload=_j(r["payload"]) or {}) for r in c.execute(q, params).fetchall()]


# ============================ commitments ============================
def upsert_commitment(org_id, **k):
    """One commitment per (message, quote). Re-running the detector updates
    state rather than piling up duplicates."""
    c = _conn()
    try:
        r = c.execute("""SELECT id FROM commitments WHERE org_id=? AND message_id=? AND quote=?""",
                      (org_id, k.get("message_id"), k.get("quote"))).fetchone()
        if r:
            c.execute("""UPDATE commitments SET state=?, due_at=?, due_basis=?, confidence=?
                         WHERE id=?""",
                      (k.get("state", "open"), k.get("due_at"), k.get("due_basis"),
                       k.get("confidence", 0.5), r["id"]))
            c.commit()
            return r["id"]
        cid = c.insert_id(
            """INSERT INTO commitments (org_id,message_id,conversation_id,entity_id,promiser,
                   direction,text,quote,due_at,due_basis,state,confidence,detector,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (org_id, k.get("message_id"), k.get("conversation_id"), k.get("entity_id"),
             k.get("promiser"), k.get("direction"), k.get("text"), k.get("quote"),
             k.get("due_at"), k.get("due_basis"), k.get("state", "open"),
             k.get("confidence", 0.5), k.get("detector"), now()))
        c.commit()
        return cid
    finally:
        c.close()


def commitments(org_id, state=None, limit=500):
    q = "SELECT * FROM commitments WHERE org_id=?"
    params = [org_id]
    if state:
        q += " AND state=?"
        params.append(state)
    q += " ORDER BY due_at LIMIT ?"
    params.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(q, params).fetchall()]


def set_commitment_state(org_id, cid, state):
    with _conn() as c:
        c.execute("UPDATE commitments SET state=? WHERE org_id=? AND id=?", (state, org_id, cid))


# ============================ findings & evidence ============================
def _row_to_finding(r):
    d = dict(r)
    d["source_systems"] = _j(d.get("source_systems")) or []
    d["ai_actionable"] = bool(d.get("ai_actionable"))
    d["approval_required"] = bool(d.get("approval_required"))
    return d


def upsert_finding(org_id, dedupe_key, **f):
    """Findings are idempotent on `dedupe_key`. Re-running detection refreshes a
    finding in place — it does not create a second copy, and it never resurrects
    one a human already dismissed."""
    c = _conn()
    try:
        r = c.execute("SELECT * FROM findings WHERE org_id=? AND dedupe_key=?",
                      (org_id, dedupe_key)).fetchone()
        if r:
            if r["status"] in ("dismissed", "false_positive", "resolved"):
                return r["id"], False
            c.execute(
                """UPDATE findings SET title=?, summary=?, severity=?, confidence=?,
                       impact_cents=?, impact_basis=?, impact_low_cents=?, impact_high_cents=?,
                       urgency=?, attention=?, entity_id=?, owner=?, source_systems=?,
                       recommended_action=?, ai_actionable=?, approval_required=?, risk=?,
                       detected_at=?, updated_at=? WHERE id=?""",
                (f.get("title"), f.get("summary"), f.get("severity", "medium"),
                 f.get("confidence", 0.5), f.get("impact_cents"), f.get("impact_basis"),
                 f.get("impact_low_cents"), f.get("impact_high_cents"),
                 f.get("urgency", 0.5), f.get("attention", 0), f.get("entity_id"),
                 f.get("owner"), json.dumps(f.get("source_systems") or []),
                 f.get("recommended_action"), 1 if f.get("ai_actionable") else 0,
                 0 if f.get("approval_required") is False else 1, f.get("risk", "low"),
                 f.get("detected_at") or now(), now(), r["id"]))
            c.execute("DELETE FROM evidence WHERE org_id=? AND finding_id=?", (org_id, r["id"]))
            c.commit()
            return r["id"], False
        fid = c.insert_id(
            """INSERT INTO findings (org_id,dedupe_key,category,subcategory,title,summary,
                   severity,confidence,impact_cents,impact_basis,impact_low_cents,
                   impact_high_cents,urgency,attention,entity_id,owner,source_systems,
                   recommended_action,ai_actionable,approval_required,risk,status,detector,
                   detected_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (org_id, dedupe_key, f.get("category"), f.get("subcategory"), f.get("title"),
             f.get("summary"), f.get("severity", "medium"), f.get("confidence", 0.5),
             f.get("impact_cents"), f.get("impact_basis"), f.get("impact_low_cents"),
             f.get("impact_high_cents"), f.get("urgency", 0.5), f.get("attention", 0),
             f.get("entity_id"), f.get("owner"), json.dumps(f.get("source_systems") or []),
             f.get("recommended_action"), 1 if f.get("ai_actionable") else 0,
             0 if f.get("approval_required") is False else 1, f.get("risk", "low"),
             "new", f.get("detector"), f.get("detected_at") or now(), now()))
        c.commit()
        return fid, True
    finally:
        c.close()


def add_evidence(org_id, finding_id, items):
    """Replace a finding's evidence with `items` (ordered). Evidence is never
    generated prose — each item points at a real stored record."""
    with _conn() as c:
        for i, e in enumerate(items or []):
            c.execute(
                """INSERT INTO evidence (org_id,finding_id,seq,occurred_at,label,detail,
                                         ref_kind,ref_id) VALUES (?,?,?,?,?,?,?,?)""",
                (org_id, finding_id, i, e.get("occurred_at"), e.get("label"),
                 e.get("detail"), e.get("ref_kind"), e.get("ref_id")))


def evidence_for(org_id, finding_id):
    with _conn() as c:
        rows = c.execute("""SELECT * FROM evidence WHERE org_id=? AND finding_id=?
                            ORDER BY seq""", (org_id, finding_id)).fetchall()
        return [dict(r) for r in rows]


def findings(org_id, status=None, category=None, limit=200, offset=0, open_only=True):
    q = "SELECT * FROM findings WHERE org_id=?"
    params = [org_id]
    if status:
        q += " AND status=?"
        params.append(status)
    elif open_only:
        q += " AND status NOT IN ('dismissed','false_positive','resolved')"
    if category:
        q += " AND category=?"
        params.append(category)
    q += " ORDER BY attention DESC, id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _conn() as c:
        return [_row_to_finding(r) for r in c.execute(q, params).fetchall()]


def get_finding(org_id, fid):
    with _conn() as c:
        r = c.execute("SELECT * FROM findings WHERE org_id=? AND id=?", (org_id, fid)).fetchone()
        return _row_to_finding(r) if r else None


def set_finding_status(org_id, fid, status, resolution=None):
    with _conn() as c:
        c.execute("""UPDATE findings SET status=?, resolution=COALESCE(?,resolution),
                     updated_at=? WHERE org_id=? AND id=?""",
                  (status, resolution, now(), org_id, fid))


def add_feedback(org_id, fid, user_id, verdict, note=None):
    with _conn() as c:
        c.execute("""INSERT INTO finding_feedback (org_id,finding_id,user_id,verdict,note,
                     created_at) VALUES (?,?,?,?,?,?)""",
                  (org_id, fid, user_id, verdict, note, now()))


def feedback_stats(org_id):
    """False-positive rate per detector — the signal that tells us which
    detectors are earning their place."""
    with _conn() as c:
        rows = c.execute(
            """SELECT f.detector, fb.verdict, COUNT(*) n
               FROM finding_feedback fb JOIN findings f ON f.id=fb.finding_id
               WHERE fb.org_id=? GROUP BY f.detector, fb.verdict""", (org_id,)).fetchall()
    out = {}
    for r in rows:
        d = out.setdefault(r["detector"] or "unknown", {"useful": 0, "false_positive": 0,
                                                        "not_now": 0})
        if r["verdict"] in d:
            d[r["verdict"]] += r["n"]
    for d in out.values():
        total = d["useful"] + d["false_positive"]
        d["fp_rate"] = round(d["false_positive"] / total, 3) if total else None
    return out


def finding_counts(org_id):
    with _conn() as c:
        rows = c.execute("""SELECT category, COUNT(*) n FROM findings
                            WHERE org_id=? AND status NOT IN
                              ('dismissed','false_positive','resolved')
                            GROUP BY category""", (org_id,)).fetchall()
        return {r["category"]: r["n"] for r in rows}


# ============================ scores & scans ============================
def save_score(org_id, score, band, methodology, dimensions, coverage):
    with _conn() as c:
        return c.insert_id(
            """INSERT INTO scores (org_id,score,band,methodology,dimensions,coverage,created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (org_id, score, band, methodology, json.dumps(dimensions or {}),
             json.dumps(coverage or {}), now()))


def latest_score(org_id):
    with _conn() as c:
        r = c.execute("SELECT * FROM scores WHERE org_id=? ORDER BY id DESC LIMIT 1",
                      (org_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["dimensions"] = _j(d["dimensions"]) or {}
        d["coverage"] = _j(d["coverage"]) or {}
        return d


def score_history(org_id, limit=60):
    with _conn() as c:
        rows = c.execute("""SELECT score, band, created_at FROM scores WHERE org_id=?
                            ORDER BY id DESC LIMIT ?""", (org_id, limit)).fetchall()
        return [dict(r) for r in rows][::-1]


def create_scan(org_id, kind, target, share_token=None):
    with _conn() as c:
        return c.insert_id(
            """INSERT INTO scans (org_id,kind,target,status,share_token,created_at)
               VALUES (?,?,?,?,?,?)""", (org_id, kind, target, "queued", share_token, now()))


def update_scan(scan_id, **f):
    allowed = {"status", "progress", "step", "error", "shared"}
    sets, params = [], []
    for k, v in f.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
        elif k == "result":
            sets.append("result=?")
            params.append(json.dumps(v))
    if f.get("status") in ("done", "error"):
        sets.append("finished_at=?")
        params.append(now())
    if not sets:
        return
    params.append(scan_id)
    with _conn() as c:
        c.execute(f"UPDATE scans SET {', '.join(sets)} WHERE id=?", params)


def get_scan(scan_id, org_id=None):
    q = "SELECT * FROM scans WHERE id=?"
    params = [scan_id]
    if org_id is not None:
        q += " AND org_id=?"
        params.append(org_id)
    with _conn() as c:
        r = c.execute(q, params).fetchone()
        if not r:
            return None
        d = dict(r)
        d["result"] = _j(d["result"])
        return d


def scan_by_token(token):
    """Public share lookup. Only ever returns a scan explicitly marked shared."""
    if not token:
        return None
    with _conn() as c:
        r = c.execute("SELECT * FROM scans WHERE share_token=? AND shared=1", (token,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["result"] = _j(d["result"])
        return d


def scans(org_id, limit=25):
    with _conn() as c:
        rows = c.execute("""SELECT id,kind,target,status,progress,step,created_at,finished_at
                            FROM scans WHERE org_id=? ORDER BY id DESC LIMIT ?""",
                         (org_id, limit)).fetchall()
        return [dict(r) for r in rows]
