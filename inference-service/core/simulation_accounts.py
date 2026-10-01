"""Fictional NovaTrust accounts used only by the opt-in local simulation API.

The demo passwords are not stored in the source. Each comes from an environment variable
(NOVATRUST_DEMO_PASSWORD_ALICE, _BOB, _CAROL; see .env.example). When one is unset the account
gets a random password that nobody knows, so it simply cannot be logged into.
"""

import hashlib
import hmac
import logging
import os
import secrets

log = logging.getLogger(__name__)


def demo_password(env_name: str) -> str:
    """The password for a demo account from the environment, or an unguessable random one."""
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    log.warning("%s is not set; that demo account has a random password and cannot be logged into.", env_name)
    return secrets.token_urlsafe(24)


_SCRYPT_PREFIX = "scrypt$"


def hash_password(password: str) -> str:
    """A salted scrypt hash, stored instead of the password."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"{_SCRYPT_PREFIX}{salt.hex()}${digest.hex()}"


def is_hashed(stored: str) -> bool:
    return stored.startswith(_SCRYPT_PREFIX)


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check against a stored hash. A row that still holds a plain password (written before
    hashing was added) is compared in constant time as well, and is upgraded to a hash on the next start."""
    if is_hashed(stored):
        try:
            _, salt_hex, digest_hex = stored.split("$")
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2 ** 14, r=8, p=1, dklen=len(expected))
        except ValueError:
            return False
        return hmac.compare_digest(actual, expected)
    return hmac.compare_digest(password.encode("utf-8"), stored.encode("utf-8"))


def password_fingerprint(password: str) -> str:
    """What the brute-force counter remembers about an attempted password: only a digest, never the password."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


BANK_ACCOUNTS = {
    "normal1@novatrust.com": {
        "email": "normal1@novatrust.com",
        "password": demo_password("NOVATRUST_DEMO_PASSWORD_ALICE"),
        "user_id": "alice",
        "display_name": "Alice Johnson",
        "account_masked": "****4521",
        "balance": 12450.00,
    },
    "normal2@novatrust.com": {
        "email": "normal2@novatrust.com",
        "password": demo_password("NOVATRUST_DEMO_PASSWORD_BOB"),
        "user_id": "bob",
        "display_name": "Bob Carter",
        "account_masked": "****8314",
        "balance": 9820.42,
    },
    "admin@novatrust.com": {
        "email": "admin@novatrust.com",
        "password": demo_password("NOVATRUST_DEMO_PASSWORD_CAROL"),
        "user_id": "carol",
        "display_name": "Carol Admin",
        "account_masked": "****1108",
        "balance": 50124.77,
    },
}
