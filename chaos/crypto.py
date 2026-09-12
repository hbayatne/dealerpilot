"""
Credential encryption at rest.

Integration secrets (IMAP app passwords, OAuth refresh tokens) are the most
dangerous data in the product: they are live keys to a customer's mailbox. They
are encrypted with AES-256-GCM before they touch the database, and the key comes
from the environment (`CHAOS_SECRET_KEY`), never from the database.

If no key is configured we refuse to store secrets rather than silently writing
plaintext. A feature that is off is recoverable; a leaked mailbox password is not.
"""
import base64
import hashlib
import os

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAVE_CRYPTO = True
except BaseException:                                # pragma: no cover
    # Broad on purpose: a broken native build raises a pyo3 PanicException, which
    # is not an Exception subclass. A missing cipher must disable the feature,
    # never take down import of the whole app.
    _HAVE_CRYPTO = False

_PREFIX = "v1:"


class SecretsUnavailable(RuntimeError):
    """Raised when a secret must be stored but no key/cipher is configured."""


def _key():
    raw = os.environ.get("CHAOS_SECRET_KEY")
    if not raw:
        return None
    # Any passphrase length works; we derive a stable 32-byte key from it.
    return hashlib.sha256(raw.encode()).digest()


def available():
    return bool(_HAVE_CRYPTO and _key())


def status():
    if not _HAVE_CRYPTO:
        return "unavailable: the `cryptography` package is not installed"
    if not _key():
        return "unavailable: set CHAOS_SECRET_KEY to store integration credentials"
    return "ready"


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        return None
    if not available():
        raise SecretsUnavailable(status())
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)
    return _PREFIX + base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt(blob: str) -> str:
    if not blob:
        return None
    if not blob.startswith(_PREFIX):
        raise SecretsUnavailable("stored credential is not in a recognized format")
    if not available():
        raise SecretsUnavailable(status())
    raw = base64.urlsafe_b64decode(blob[len(_PREFIX):].encode())
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], None).decode()
