"""
RFC-822/MIME parsing — raw bytes in, one flat dict out.

Shared by every source that hands us real email bytes (IMAP today, an .eml or
.mbox import, Gmail's raw format). Keeping it separate from the transports means
the hardest part of parsing is tested once, offline, with no network.
"""
import email
import email.header
import email.policy

from chaos.ingest import mailbox as M


def _decode_header(raw):
    if not raw:
        return ""
    try:
        parts = email.header.decode_header(raw)
        out = []
        for val, enc in parts:
            if isinstance(val, bytes):
                out.append(val.decode(enc or "utf-8", errors="replace"))
            else:
                out.append(val)
        return "".join(out).strip()
    except Exception:
        return str(raw)


def _body_of(msg):
    """Best text body: prefer text/plain, fall back to flattened HTML."""
    plain, html = [], []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if (part.get_content_disposition() or "") == "attachment":
                continue
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                text = payload.decode(part.get_content_charset() or "utf-8",
                                      errors="replace")
            except Exception:
                continue
            (plain if ctype == "text/plain" else html).append(text)
    else:
        try:
            payload = msg.get_payload(decode=True)
            text = (payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
                    if payload is not None else str(msg.get_payload()))
        except Exception:
            text = ""
        (plain if msg.get_content_type() != "text/html" else html).append(text)
    if plain and "".join(plain).strip():
        return "\n".join(plain)
    return M.html_to_text("\n".join(html))


def _attachments(msg):
    out = []
    if not msg.is_multipart():
        return out
    for part in msg.walk():
        if (part.get_content_disposition() or "") != "attachment":
            continue
        # Metadata only — we deliberately do not store attachment contents.
        out.append({"filename": _decode_header(part.get_filename() or ""),
                    "content_type": part.get_content_type()})
    return out


def parse(raw_bytes, source_id=None, folder=None):
    """Raw message bytes → the flat dict every downstream stage expects."""
    if isinstance(raw_bytes, str):
        raw_bytes = raw_bytes.encode("utf-8", errors="replace")
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.compat32)

    headers = {}
    for k, v in msg.items():
        headers.setdefault(k.lower(), _decode_header(v))

    subject = _decode_header(msg.get("Subject"))
    from_name, from_addr = M.parse_addr(_decode_header(msg.get("From")))
    to = M.parse_addr_list(_decode_header(msg.get("To")))
    cc = M.parse_addr_list(_decode_header(msg.get("Cc")))
    body = _body_of(msg)
    mid = (msg.get("Message-ID") or "").strip().strip("<>")

    return {
        "source_id": source_id or mid,
        "message_id": mid,
        "folder": folder,
        "headers": headers,
        "subject": subject,
        "from_name": from_name,
        "from_addr": from_addr,
        "to": to,
        "cc": cc,
        "date": _decode_header(msg.get("Date")),
        "body": body,
        "attachments": _attachments(msg),
    }
