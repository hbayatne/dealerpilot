"""
Authentication + authorization.

Passwords: PBKDF2-HMAC-SHA256, 240k iterations, per-user salt, constant-time
compare. Sessions: 256-bit random opaque tokens in an HttpOnly cookie.

Authorization is org-scoped and lives in `require_role` — every route that
touches business data resolves (user, org) to a role first. There is no
"current org" global; the org id is always explicit.
"""
import datetime
import hashlib
import hmac
import os
import secrets

from chaos import db

_ITER = 240_000
_RESET_TTL_MIN = 60

# Ordered least → most privileged. `role_at_least` compares positions.
ROLES = ["readonly", "employee", "accountant", "marketing", "manager", "admin", "owner"]
_RANK = {r: i for i, r in enumerate(ROLES)}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2${_ITER}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def signup_code_required():
    """A deployed instance is reachable by anyone who finds the URL. Setting
    CHAOS_SIGNUP_CODE turns sign-up into an invite: the product holds a
    business's customer correspondence, so open registration next to it is a
    door, not a feature. Unset (local development), sign-up stays open."""
    return bool((os.environ.get("CHAOS_SIGNUP_CODE") or "").strip())


def signup(email, password, name=None, code=None):
    email = (email or "").strip().lower()
    wanted = (os.environ.get("CHAOS_SIGNUP_CODE") or "").strip()
    if wanted and not hmac.compare_digest((code or "").strip(), wanted):
        return None, None, "That invite code isn't right."
    if not email or "@" not in email or len(password or "") < 8:
        return None, None, "Enter a valid email and a password of at least 8 characters."
    uid = db.create_user(email, hash_password(password), name)
    if uid is None:
        return None, None, "An account with that email already exists."
    return _new_session(uid), uid, None


def login(email, password):
    user = db.get_user_by_email(email)
    if not user or not verify_password(password or "", user["password_hash"]):
        return None, None, "Incorrect email or password."
    return _new_session(user["id"]), user["id"], None


def change_password(user, current_password, new_password):
    if not verify_password(current_password or "", user["password_hash"]):
        return False, "Current password is incorrect."
    if len(new_password or "") < 8:
        return False, "New password must be at least 8 characters."
    db.set_password(user["id"], hash_password(new_password))
    db.delete_user_sessions(user["id"])
    return True, None


def request_reset(email):
    """Returns (token, user) or (None, None). Callers must respond identically
    either way so the endpoint can't be used to enumerate registered emails."""
    user = db.get_user_by_email(email or "")
    if not user:
        return None, None
    token = secrets.token_urlsafe(32)
    expires = (datetime.datetime.utcnow()
               + datetime.timedelta(minutes=_RESET_TTL_MIN)).isoformat()
    db.create_reset(token, user["id"], expires)
    return token, user


def reset_password(token, new_password):
    row = db.get_reset(token or "")
    if not row:
        return None, "This reset link is invalid or has already been used."
    try:
        expired = datetime.datetime.utcnow() > datetime.datetime.fromisoformat(row["expires_at"])
    except Exception:
        expired = True
    if expired:
        db.delete_reset(token)
        return None, "This reset link has expired — request a new one."
    if len(new_password or "") < 8:
        return None, "New password must be at least 8 characters."
    db.set_password(row["user_id"], hash_password(new_password))
    db.delete_reset(token)
    db.delete_user_sessions(row["user_id"])
    return row["user_id"], None


def role_at_least(role, minimum):
    return _RANK.get(role or "", -1) >= _RANK.get(minimum, 99)


def _new_session(user_id):
    token = secrets.token_urlsafe(32)
    db.create_session(token, user_id)
    return token
