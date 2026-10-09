"""Account connection, eligibility, token lifecycle and revocation."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import IGAccount, audit, utcnow
from .client import REQUIRED_SCOPES, IGApiError, IGClient
from .secrets import TokenCipher

log = logging.getLogger(__name__)
ELIGIBLE_TYPES = {"BUSINESS", "MEDIA_CREATOR", "CREATOR"}  # professional accounts only
REFRESH_WITHIN_DAYS = 10


class AccountError(Exception):
    pass


def eligibility(me: dict[str, Any]) -> tuple[bool, list[str]]:
    problems = []
    if str(me.get("account_type", "")).upper() not in ELIGIBLE_TYPES:
        problems.append(f"account_type '{me.get('account_type')}' is not a professional (Business/Creator) account")
    if not me.get("user_id") and not me.get("id"):
        problems.append("no account id returned")
    return (not problems), problems


def connect_account(s: Session, client: IGClient, cipher: TokenCipher, code: str, actor: str = "owner") -> IGAccount:
    short = client.exchange_code(code)  # normalised: {access_token, user_id, permissions: list[str]}
    granted = short["permissions"]
    token = short["access_token"]
    ll = client.long_lived(token)
    token = ll["access_token"]
    me = client.me(token)
    ok, problems = eligibility(me)
    ig_id = str(me.get("user_id") or me.get("id") or short.get("user_id") or "")
    if not ig_id:
        raise AccountError("could not determine the Instagram account id")
    acct = s.scalar(select(IGAccount).where(IGAccount.ig_user_id == ig_id)) or IGAccount(ig_user_id=ig_id)
    acct.username = me.get("username", "")
    acct.account_type = me.get("account_type", "")
    acct.token_encrypted = cipher.encrypt(token)
    acct.token_expires_at = utcnow() + timedelta(seconds=int(ll.get("expires_in", 0)))
    acct.scopes = granted  # exactly what Meta reported; never assumed (empty = unreported)
    acct.revoked_at = None
    acct.publishing_enabled = False  # always requires explicit enabling after connect
    acct.is_destination = False
    s.add(acct)
    s.flush()
    missing = [x for x in REQUIRED_SCOPES if x not in granted]
    audit(s, "ig.connected", "account", acct.id, actor, username=acct.username, eligible=ok, problems=problems,
          granted=granted, missing_required=missing if granted else "unreported")
    return acct


def token_status(acct: IGAccount, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    if acct.revoked_at or not acct.token_encrypted:
        return {"state": "revoked", "days_left": None}
    if not acct.token_expires_at:
        return {"state": "unknown_expiry", "days_left": None}
    days = (acct.token_expires_at - now).total_seconds() / 86400
    state = "expired" if days <= 0 else "expiring_soon" if days <= REFRESH_WITHIN_DAYS else "ok"
    return {"state": state, "days_left": round(days, 1), "expires_at": acct.token_expires_at.isoformat()}


def get_token(acct: IGAccount, cipher: TokenCipher) -> str:
    st = token_status(acct)["state"]
    if st in ("revoked", "expired"):
        raise AccountError(f"token {st}: reconnect the account")
    return cipher.decrypt(acct.token_encrypted)


def refresh_if_needed(s: Session, client: IGClient, cipher: TokenCipher, acct: IGAccount) -> bool:
    st = token_status(acct)
    if st["state"] != "expiring_soon":
        return False
    try:
        res = client.refresh(cipher.decrypt(acct.token_encrypted))
    except IGApiError as e:
        audit(s, "ig.token_refresh_failed", "account", acct.id, error=str(e), kind=e.kind)
        return False
    acct.token_encrypted = cipher.encrypt(res["access_token"])
    acct.token_expires_at = utcnow() + timedelta(seconds=int(res.get("expires_in", 0)))
    audit(s, "ig.token_refreshed", "account", acct.id)
    return True


def enable_publishing(s: Session, client: IGClient, cipher: TokenCipher, acct: IGAccount,
                      confirm_username: str, actor: str = "owner") -> IGAccount:
    """Owner must type the destination username; eligibility and live token are verified first."""
    if confirm_username.strip().lstrip("@").lower() != acct.username.lower():
        raise AccountError("destination confirmation does not match the connected username")
    token = get_token(acct, cipher)
    me = client.me(token)
    ok, problems = eligibility(me)
    if not ok:
        raise AccountError("; ".join(problems))
    scopes = acct.scopes or []
    if scopes:
        missing = [x for x in REQUIRED_SCOPES if x not in scopes]
        if missing:
            raise AccountError(f"required permissions not granted: {missing}; reconnect and approve them")
    else:  # Meta did not report scopes: verify with a read-only call that needs publishing permission
        try:
            client.publishing_limit(acct.ig_user_id, token)
        except IGApiError as e:
            raise AccountError(f"could not confirm publishing permission ({e.kind}); reconnect the account") from e
    acct.is_destination = True
    acct.publishing_enabled = True
    audit(s, "ig.publishing_enabled", "account", acct.id, actor, username=acct.username)
    return acct


def revoke(s: Session, acct: IGAccount, actor: str = "owner") -> None:
    """Local revoke: wipe the stored token and disable publishing. Also remove the app in Instagram settings."""
    acct.token_encrypted, acct.revoked_at = "", utcnow()
    acct.publishing_enabled = acct.is_destination = False
    from ..db import PublishJob
    n = 0
    for j in s.scalars(select(PublishJob).where(PublishJob.account_id == acct.id,
                                                PublishJob.status.in_(["pending_approval", "approved", "scheduled"]))):
        j.status, j.last_error = "cancelled", "account access revoked"
        n += 1
    audit(s, "ig.revoked", "account", acct.id, actor, cancelled_jobs=n)
