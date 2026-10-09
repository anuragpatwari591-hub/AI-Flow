import httpx
import pytest
from cryptography.fernet import Fernet

from reelstudio.config import Settings
from reelstudio.doctor import build_report, render
from reelstudio.instagram.accounts import connect_account, enable_publishing
from reelstudio.instagram.client import IGClient
from reelstudio.instagram.secrets import TokenCipher
from tests.fake_graph import FakeGraph

KEY = Fernet.generate_key().decode()
GOOD = dict(secret_key=KEY, dashboard_token="x" * 40, meta_app_id="APPID", meta_app_secret="TOPSECRET_APP",
            meta_redirect_uri="https://studio.example.test/api/instagram/callback", public_base_url="https://studio.example.test")


def st(**kw):
    return Settings(_env_file=None, **{**GOOD, **kw})


def test_nothing_configured_gives_one_next_action_and_no_secrets():
    rep = build_report(Settings(_env_file=None))
    out = render(rep)
    assert rep.blocked and out.count("NEXT:") == 1 and "gen-keys" in rep.next_action


@pytest.mark.parametrize("kw,needle", [
    (dict(meta_redirect_uri="http://studio.example.test/api/instagram/callback"), "must be https"),
    (dict(meta_redirect_uri="https://studio.example.test/callback"), "path must be exactly"),
    (dict(meta_redirect_uri="https://other.example.test/api/instagram/callback"), "host differs"),
    (dict(meta_redirect_uri="https://studio.example.test/api/instagram/callback/"), "path must be exactly"),
    (dict(public_base_url="https://localhost"), "public https"),
    (dict(dashboard_token="short"), "shorter"),
    (dict(secret_key="notafernetkey"), "Fernet"),
    (dict(graph_version="21"), "not like"),
])
def test_config_problems_detected(kw, needle):
    out = render(build_report(st(**kw)))
    assert needle in out and "[FAIL]" in out


def test_report_never_contains_secret_values():
    out = render(build_report(st()))
    for secret in (KEY, GOOD["dashboard_token"], "TOPSECRET_APP"):
        assert secret not in out


def test_public_host_check(session):
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True, "ffmpeg": True})))
    down = httpx.Client(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x"))))
    assert "[OK  ] public host" in render(build_report(st(), None, live=True, http=ok))
    r = build_report(st(), None, live=True, http=down)
    assert "serve" in r.next_action and "[FAIL] public host" in render(r)


def test_not_connected_prints_connect_url_without_secrets(session, env):
    import os
    fake = FakeGraph()
    c = IGClient("APPID", "TOPSECRET_APP", GOOD["meta_redirect_uri"], http=fake.client())
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True, "ffmpeg": True})))
    rep = build_report(st(secret_key=os.environ["RS_SECRET_KEY"]), session, live=True, client=c, http=ok)
    out = render(rep)
    assert "instagram.com/oauth/authorize" in out and "client_id=APPID" in out and "TOPSECRET_APP" not in out
    assert "log in to Instagram" in rep.next_action


def test_connected_and_ready_flow(session, env):
    fake = FakeGraph()
    c = IGClient("APPID", "APPSECRET", "https://studio.example.test/api/instagram/callback", http=fake.client())
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True, "ffmpeg": True})))
    import os
    settings = st(secret_key=os.environ["RS_SECRET_KEY"])
    acct = connect_account(session, c, TokenCipher(), "CODE")
    rep = build_report(settings, session, live=True, client=c, http=ok)
    out = render(rep)
    assert "[OK  ] @ap_test required permissions: basic + content_publish granted" in out
    assert "[OK  ] @ap_test live publishing permission probe" in out and "OFF" in rep.next_action
    assert not rep.blocked and "LL_TOKEN_SECRET" not in out
    enable_publishing(session, c, TokenCipher(), acct, "ap_test")
    assert "ENABLED" in build_report(settings, session, live=False, client=c).next_action
    acct.scopes = ["instagram_business_basic"]
    r2 = build_report(settings, session, live=False, client=c)
    assert r2.blocked and "Connect URL" in render(r2)


def test_revoked_token_asks_to_reconnect(session, env):
    import os
    from reelstudio.instagram.accounts import revoke
    fake = FakeGraph(); c = IGClient("APPID", "APPSECRET", GOOD["meta_redirect_uri"], http=fake.client())
    acct = connect_account(session, c, TokenCipher(), "CODE")
    revoke(session, acct)
    rep = build_report(st(secret_key=os.environ["RS_SECRET_KEY"]), session, client=c)
    assert rep.blocked and "Connect URL" in render(rep)
