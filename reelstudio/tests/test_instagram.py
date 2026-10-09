from datetime import timedelta

import pytest

from reelstudio.db import AuditLog, IGAccount, utcnow
from reelstudio.instagram.accounts import AccountError, connect_account, enable_publishing, refresh_if_needed, revoke, token_status
from reelstudio.instagram.client import IGApiError, IGClient
from reelstudio.instagram.secrets import SecretsError, TokenCipher
from tests.fake_graph import FakeGraph


def mk(fake):
    return IGClient("APPID", "APPSECRET", "https://x/cb", http=fake.client())


def test_authorize_url_has_required_scopes():
    u = IGClient("APPID", "S", "https://x/cb").authorize_url("st8")
    assert "client_id=APPID" in u and "instagram_business_content_publish" in u and "state=st8" in u


def test_token_encrypted_at_rest_and_never_plain(session, env):
    fake = FakeGraph()
    acct = connect_account(session, mk(fake), TokenCipher(), "CODE")
    assert "LL_TOKEN_SECRET" not in acct.token_encrypted and acct.token_encrypted
    assert TokenCipher().decrypt(acct.token_encrypted) == "LL_TOKEN_SECRET"
    assert not acct.publishing_enabled  # must be explicitly enabled
    blob = " ".join(str(a.detail) for a in session.query(AuditLog))
    assert "LL_TOKEN_SECRET" not in blob and "SHORT123" not in blob


def test_missing_secret_key_refuses_storage(monkeypatch):
    from reelstudio import config
    monkeypatch.setenv("RS_SECRET_KEY", ""); config.get_settings.cache_clear()
    with pytest.raises(SecretsError):
        TokenCipher()
    config.get_settings.cache_clear()


def test_personal_account_not_eligible_for_publishing(session, env):
    fake = FakeGraph(account_type="PERSONAL")
    c = mk(fake); cipher = TokenCipher()
    acct = connect_account(session, c, cipher, "CODE")
    with pytest.raises(AccountError, match="professional"):
        enable_publishing(session, c, cipher, acct, "ap_test")


def test_enable_requires_exact_destination_confirmation(session, env):
    fake = FakeGraph(); c = mk(fake); cipher = TokenCipher()
    acct = connect_account(session, c, cipher, "CODE")
    with pytest.raises(AccountError, match="confirmation"):
        enable_publishing(session, c, cipher, acct, "someone_else")
    enable_publishing(session, c, cipher, acct, "@AP_TEST")
    assert acct.publishing_enabled and acct.is_destination


def test_token_expiry_and_refresh(session, env):
    fake = FakeGraph(token_expires=3 * 86400); c = mk(fake); cipher = TokenCipher()
    acct = connect_account(session, c, cipher, "CODE")
    assert token_status(acct)["state"] == "expiring_soon"
    assert refresh_if_needed(session, c, cipher, acct)
    assert cipher.decrypt(acct.token_encrypted) == "LL_TOKEN_REFRESHED" and token_status(acct)["state"] == "ok"
    acct.token_expires_at = utcnow() - timedelta(days=1)
    assert token_status(acct)["state"] == "expired"


def test_revoke_wipes_token_and_cancels_jobs(stack):
    from reelstudio.publishing.queue import submit_for_approval
    job = submit_for_approval(stack.s, stack.reel.id, stack.acct.id)
    revoke(stack.s, stack.acct)
    assert stack.acct.token_encrypted == "" and job.status == "cancelled" and not stack.acct.publishing_enabled


def test_error_classification():
    assert IGApiError("x", code=190).kind == "token"
    assert IGApiError("x", code=4, status=400).kind == "rate_limited"
    assert IGApiError("x", status=503).kind == "transient"
    assert IGApiError("x", code=100, status=400).kind == "permanent"
