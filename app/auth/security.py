"""Password hashing, opaque session tokens, and CSRF token helpers."""

import hashlib
import hmac
import secrets
from urllib.parse import urlsplit

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

password_hasher = PasswordHash.recommended()
_DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    """Hash a password with the configured Argon2id password hasher."""
    return password_hasher.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    """Verify a password, using a dummy hash for unknown usernames."""
    try:
        return password_hasher.verify(password, stored_hash or _DUMMY_PASSWORD_HASH)
    except (UnknownHashError, ValueError, TypeError):
        return False


def create_opaque_token() -> str:
    """Create an unguessable token for an administrator session or CSRF."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash an opaque token before storing it in the database."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches_hash(token: str, stored_hash: str) -> bool:
    """Compare a submitted token to its stored hash in constant time."""
    return hmac.compare_digest(hash_token(token), stored_hash)


def hash_rate_limit_key(key: str, security_key: str) -> str:
    """HMAC a login identity so raw usernames and client addresses are not stored."""
    return hmac.new(
        security_key.encode("utf-8"),
        key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def is_same_origin(origin: str | None, expected_origin: str) -> bool:
    """Compare two bare web origins, including default-port normalization."""
    if not origin or origin == "null":
        return False
    try:
        supplied = urlsplit(origin)
        expected = urlsplit(expected_origin)
        supplied_port = supplied.port
        expected_port = expected.port
    except ValueError:
        return False

    if (
        supplied.path not in {"", "/"}
        or supplied.query
        or supplied.fragment
        or supplied.username
        or supplied.password
        or expected.username
        or expected.password
    ):
        return False

    supplied_scheme = supplied.scheme.lower()
    expected_scheme = expected.scheme.lower()
    supplied_tuple = (
        supplied_scheme,
        (supplied.hostname or "").lower(),
        supplied_port or (443 if supplied_scheme == "https" else 80),
    )
    expected_tuple = (
        expected_scheme,
        (expected.hostname or "").lower(),
        expected_port or (443 if expected_scheme == "https" else 80),
    )
    return supplied_tuple == expected_tuple
