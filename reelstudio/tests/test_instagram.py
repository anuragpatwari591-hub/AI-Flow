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


# ---- B1 regression: token-exchange response shapes & permission parsing
from reelstudio.instagram.client import parse_permissions, parse_token_response  # noqa: E402

PERMS = "instagram_business_basic,instagram_business_content_publish,instagram_business_manage_insights"


@pytest.mark.parametrize("raw,expected", [
    (PERMS, PERMS.split(",")),
    (PERMS.replace(",", ", "), PERMS.split(",")),          # spaces after commas
    (PERMS.split(","), PERMS.split(",")),                   # already a list
    ("instagram_business_basic", ["instagram_business_basic"]),  # single scope must NOT become characters
    ("a,,a,b", ["a", "b"]),                                 # dedupe, drop empties
    ("", []), (None, []), (123, []),
])
def test_parse_permissions(raw, expected):
    assert parse_permissions(raw) == expected


def test_parse_token_response_shapes():
    doc = {"data": [{"access_token": "T", "user_id": 99, "permissions": PERMS}]}
    flat = {"access_token": "T", "user_id": "99", "permissions": PERMS.split(",")}
    for raw in (doc, {"data": doc["data"][0]}, flat):
        r = parse_token_response(raw)
        assert r["access_token"] == "T" and r["user_id"] == "99" and len(r["permissions"]) == 3


@pytest.mark.parametrize("bad", [{}, {"data": []}, {"data": [{}]}, {"data": [{"access_token": ""}]}, {"data": "x"},
                                  {"access_token": 5}, [], None, "str"])
def test_parse_token_response_rejects_malformed_without_leaking(bad):
    with pytest.raises(IGApiError) as e:
        parse_token_response(bad)
    assert e.value.kind == "permanent" and "SECRET" not in str(e.value)


@pytest.mark.parametrize("shape", ["documented", "flat_list"])
def test_connect_with_each_shape_records_scopes(session, env, shape):
    fake = FakeGraph(); fake.token_shape = shape
    acct = connect_account(session, mk(fake), TokenCipher(), "CODE")
    assert acct.scopes == PERMS.split(",") and acct.ig_user_id == "111"
    enable_publishing(session, mk(fake), TokenCipher(), acct, "ap_test")


def test_connect_missing_publish_scope_refuses_enable(session, env):
    fake = FakeGraph()
    c = mk(fake); cipher = TokenCipher()
    acct = connect_account(session, c, cipher, "CODE")
    acct.scopes = ["instagram_business_basic"]
    with pytest.raises(AccountError, match="required permissions not granted"):
        enable_publishing(session, c, cipher, acct, "ap_test")
    acct.scopes = ["instagram_business_content_publish", "instagram_business_manage_insights"]  # basic missing
    with pytest.raises(AccountError, match="instagram_business_basic"):
        enable_publishing(session, c, cipher, acct, "ap_test")


def test_unreported_scopes_are_not_assumed_but_can_be_probed(session, env):
    fake = FakeGraph(); fake.token_shape = "flat_no_perms"
    c = mk(fake); cipher = TokenCipher()
    acct = connect_account(session, c, cipher, "CODE")
    assert acct.scopes == []                                   # not assumed
    fake.probe_ok = False
    with pytest.raises(AccountError, match="could not confirm publishing permission"):
        enable_publishing(session, c, cipher, acct, "ap_test")
    assert not acct.publishing_enabled
    fake.probe_ok = True
    enable_publishing(session, c, cipher, acct, "ap_test")
    assert acct.publishing_enabled


def test_connect_error_responses_and_secret_hygiene(session, env):
    import httpx
    def handler(req):
        if req.url.path == "/oauth/access_token":
            return httpx.Response(400, json={"error_type": "OAuthException", "code": 400, "error_message": "Invalid authorization code"})
        return httpx.Response(500)
    c = IGClient("APPID", "APPSECRET", "https://x/cb", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(IGApiError, match="Invalid authorization code"):
        connect_account(session, c, TokenCipher(), "BADCODE")
    assert session.query(IGAccount).count() == 0               # nothing stored on failure


def test_unexpected_long_lived_response_rejected(session, env):
    import httpx
    fake = FakeGraph(); inner = fake.handle
    def handler(req):
        return httpx.Response(200, json={"oops": 1}) if req.url.path == "/access_token" else inner(req)
    c = IGClient("APPID", "APPSECRET", "https://x/cb", http=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(IGApiError, match="long-lived"):
        connect_account(session, c, TokenCipher(), "CODE")
    assert session.query(IGAccount).count() == 0
