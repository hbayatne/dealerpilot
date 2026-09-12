"""
IMAP mailbox source — stdlib `imaplib`, no SDK, no OAuth app review.

Chosen as the first email integration deliberately. Gmail and Microsoft 365 both
support IMAP with an app password today, which means a real business can connect
a real mailbox and get real findings now, while Google/Microsoft OAuth app
verification (weeks) proceeds in parallel. `gmail_source.py` implements the same
interface for when those credentials land.

Sync is incremental: we remember the highest UID seen per folder and ask only
for what is newer. UIDVALIDITY is checked, because a server that changes it has
renumbered everything and our cursor is meaningless.
"""
import imaplib
import json
import re
import socket

from chaos.ingest import rfc822

DEFAULT_PORT = 993
FETCH_CHUNK = 50

# Well-known hosts so a user only has to give us an email address and password.
PROVIDERS = {
    "gmail.com": ("imap.gmail.com", 993), "googlemail.com": ("imap.gmail.com", 993),
    "outlook.com": ("outlook.office365.com", 993), "hotmail.com": ("outlook.office365.com", 993),
    "live.com": ("outlook.office365.com", 993), "office365.com": ("outlook.office365.com", 993),
    "yahoo.com": ("imap.mail.yahoo.com", 993), "aol.com": ("imap.aol.com", 993),
    "icloud.com": ("imap.mail.me.com", 993), "me.com": ("imap.mail.me.com", 993),
    "zoho.com": ("imap.zoho.com", 993), "fastmail.com": ("imap.fastmail.com", 993),
}


def guess_host(email_addr):
    """Best-guess IMAP host for an address. Google Workspace and Microsoft 365
    custom domains are the common case, so we fall back to imap.<domain>."""
    dom = (email_addr or "").rsplit("@", 1)[-1].lower()
    if dom in PROVIDERS:
        return PROVIDERS[dom]
    return (f"imap.{dom}", DEFAULT_PORT) if dom else (None, DEFAULT_PORT)


class ImapError(RuntimeError):
    pass


def _connect(host, port, user, password, timeout=30):
    try:
        socket.setdefaulttimeout(timeout)
        conn = imaplib.IMAP4_SSL(host, port or DEFAULT_PORT)
    except Exception as e:
        raise ImapError(f"Could not reach {host}:{port or DEFAULT_PORT} — {e}")
    try:
        conn.login(user, password)
    except imaplib.IMAP4.error as e:
        detail = str(e)
        hint = ""
        if "gmail" in (host or "") or "google" in (host or ""):
            hint = (" Gmail requires an App Password (Google Account → Security → "
                    "2-Step Verification → App passwords), not your normal password.")
        elif "office365" in (host or "") or "outlook" in (host or ""):
            hint = (" Microsoft 365 may require an app password, and IMAP must be "
                    "enabled for the mailbox.")
        raise ImapError(f"Login refused by {host}: {detail}.{hint}")
    return conn


def check(host, port, user, password):
    """Verify credentials without ingesting anything. Returns (ok, detail)."""
    try:
        conn = _connect(host, port, user, password)
    except ImapError as e:
        return False, str(e)
    try:
        typ, data = conn.list()
        folders = len(data or []) if typ == "OK" else 0
        return True, f"Connected. {folders} folders visible."
    finally:
        try:
            conn.logout()
        except Exception:
            pass


_FOLDER_RE = re.compile(r'\(([^)]*)\)\s+"[^"]*"\s+(?:"([^"]*)"|(\S+))')


def list_folders(conn):
    """Folder names worth syncing, with the noise (spam/trash/drafts) dropped."""
    typ, data = conn.list()
    if typ != "OK":
        return ["INBOX"]
    out = []
    for raw in data or []:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        m = _FOLDER_RE.search(line)
        if not m:
            continue
        flags = (m.group(1) or "").lower()
        name = m.group(2) or m.group(3) or ""
        if any(f in flags for f in ("\\noselect", "\\junk", "\\trash", "\\drafts", "\\all")):
            continue
        if re.search(r"(spam|junk|trash|deleted|draft|bin)", name, re.I):
            continue
        out.append(name)
    return out or ["INBOX"]


def _folders_to_sync(conn, configured):
    if configured:
        return configured
    names = list_folders(conn)
    # Inbox plus whatever the server calls Sent — outbound mail is half the
    # evidence, and "nobody replied" is unanswerable without it.
    keep = [n for n in names if re.search(r"^(inbox|sent|sent items|sent mail|\[gmail\]/sent)",
                                          n, re.I)]
    return keep or ["INBOX"]


def _decode_cursor(raw):
    try:
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def fetch(host, port, user, password, cursor=None, folders=None, limit=1000,
          since_days=180):
    """Pull messages newer than the cursor.

    Returns (messages, new_cursor). Messages are the flat dicts `rfc822.parse`
    produces, each tagged with its folder so the pipeline can tell Sent from
    Inbox. The cursor is a JSON blob of per-folder {uidvalidity, uid} so the next
    run only asks for what arrived since.
    """
    state = _decode_cursor(cursor)
    conn = _connect(host, port, user, password)
    out = []
    try:
        for folder in _folders_to_sync(conn, folders):
            if len(out) >= limit:
                break
            try:
                typ, data = conn.select(f'"{folder}"', readonly=True)
                if typ != "OK":
                    continue
            except Exception:
                continue
            try:
                uidv = int((conn.response("UIDVALIDITY")[1] or [b"0"])[0] or 0)
            except Exception:
                uidv = 0
            prev = state.get(folder) or {}
            # A changed UIDVALIDITY means the server renumbered — our saved UID
            # no longer refers to the same message, so start the folder over.
            last_uid = prev.get("uid", 0) if prev.get("uidvalidity") == uidv else 0

            if last_uid:
                crit = f"UID {last_uid + 1}:*"
            else:
                crit = f"SINCE {_since(since_days)}" if since_days else "ALL"
            try:
                typ, data = conn.uid("SEARCH", None, crit)
                uids = [int(u) for u in (data[0] or b"").split()] if typ == "OK" else []
            except Exception:
                uids = []
            uids = [u for u in uids if u > last_uid]
            uids.sort()
            uids = uids[: max(0, limit - len(out))]

            high = last_uid
            for i in range(0, len(uids), FETCH_CHUNK):
                chunk = uids[i:i + FETCH_CHUNK]
                seq = ",".join(str(u) for u in chunk)
                try:
                    typ, data = conn.uid("FETCH", seq, "(RFC822)")
                except Exception:
                    break
                if typ != "OK":
                    break
                for item in data or []:
                    if not isinstance(item, tuple) or len(item) < 2:
                        continue
                    meta = item[0].decode("utf-8", errors="replace") if isinstance(
                        item[0], bytes) else str(item[0])
                    m = re.search(r"UID (\d+)", meta)
                    uid = int(m.group(1)) if m else None
                    try:
                        parsed = rfc822.parse(item[1], folder=folder)
                    except Exception:
                        continue
                    parsed["uid"] = uid
                    parsed["source_id"] = parsed.get("message_id") or f"{folder}:{uid}"
                    out.append(parsed)
                    if uid and uid > high:
                        high = uid
            state[folder] = {"uidvalidity": uidv, "uid": high}
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return out, json.dumps(state)


def _since(days):
    import datetime
    d = datetime.date.today() - datetime.timedelta(days=int(days))
    return d.strftime("%d-%b-%Y")
