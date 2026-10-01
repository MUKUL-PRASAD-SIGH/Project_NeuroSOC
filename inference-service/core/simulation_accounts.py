"""Fictional NovaTrust accounts used only by the opt-in local simulation API.

The demo passwords are not stored in the source. Each comes from an environment variable
(NOVATRUST_DEMO_PASSWORD_ALICE, _BOB, _CAROL; see .env.example). When one is unset the account
gets a random password that nobody knows, so it simply cannot be logged into.
"""

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
