"""
Rate limiting for the endpoints that guess-ability makes dangerous.

Sign-in, sign-up and mailbox-credential checks are the three places where an
attacker gets unlimited free attempts unless something stops them. A fixed
window per (identifier, action) is enough to turn online password guessing from
practical into useless, which is the whole goal — this is not a DDoS defence.

Deliberately in-process, and honest about it: with more than one worker each
gets its own counter, so the effective limit multiplies by the worker count.
That is fine for a single-process deployment and must be swapped for Redis
before running several. The docstring is here so the next person finds out from
the code rather than from an incident.
"""
import os
import threading
import time

_LOCK = threading.Lock()
_HITS = {}

LIMITS = {
    "login": (8, 300),            # 8 attempts per 5 minutes
    # Signup is per source address, and a whole office can share one. Tight
    # enough to stop scripted account farming, loose enough that a small
    # business signing up several staff on one connection isn't locked out.
    "signup": (15, 3600),
    "imap_check": (10, 600),
    "website_scan": (20, 3600),
}

DISABLED = os.environ.get("CHAOS_DISABLE_RATE_LIMIT") == "1"


def check(action, identifier):
    """(allowed, retry_after_seconds). Never raises."""
    if DISABLED or action not in LIMITS:
        return True, 0
    cap, window = LIMITS[action]
    now = time.time()
    key = (action, identifier or "-")
    with _LOCK:
        hits = [t for t in _HITS.get(key, []) if now - t < window]
        if len(hits) >= cap:
            _HITS[key] = hits
            return False, int(window - (now - hits[0])) + 1
        hits.append(now)
        _HITS[key] = hits
        if len(_HITS) > 20000:                 # bound memory on a busy box
            _prune(now)
    return True, 0


def _prune(now):
    for key, hits in list(_HITS.items()):
        window = LIMITS.get(key[0], ("", 3600))[1]
        if not [t for t in hits if now - t < window]:
            _HITS.pop(key, None)


def reset():
    with _LOCK:
        _HITS.clear()
