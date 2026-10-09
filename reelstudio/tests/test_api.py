import pytest
from fastapi.testclient import TestClient

from reelstudio import config
from reelstudio.api.app import check_state, create_app, make_state
from reelstudio.db import init_db
from tests.fake_graph import FakeGraph

H = {"Authorization": "Bearer tok123"}


@pytest.fixture()
def api(env, monkeypatch, tmp_path):
    monkeypatch.setenv("RS_DASHBOARD_TOKEN", "tok123")
    config.get_settings.cache_clear()
    db_file = tmp_path / "t.db"
    from tests.conftest import test_db_url
    url = test_db_url()
    init_db(url if not url.startswith("sqlite") else f"sqlite:///{db_file}")
    if not url.startswith("sqlite"):
        from reelstudio import db
        db.Base.metadata.drop_all(db._engine); db.Base.metadata.create_all(db._engine)
    fake = FakeGraph()
    from reelstudio.instagram.client import IGClient
    app = create_app(IGClient("APPID", "APPSECRET", "https://studio.example.test/cb", http=fake.client()), sync_render=True)
    return TestClient(app), fake


def test_auth_required_and_locked_without_token(api, monkeypatch):
    c, _ = api
    assert c.get("/api/overview").status_code == 401
    assert c.get("/api/overview", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/overview", headers=H).status_code == 200
    assert c.get("/healthz").json()["ffmpeg"] is True
    monkeypatch.setenv("RS_DASHBOARD_TOKEN", ""); config.get_settings.cache_clear()
    assert c.get("/api/overview", headers=H).status_code == 503


def test_dashboard_served_with_all_ten_screens(api):
    html = api[0].get("/").text
    for label in ["Trend radar", "Reference library", "Concepts & scripts", "Reels & renders", "Audio & rights",
                  "Approval queue", "Calendar", "Published & analytics", "Account & tokens", "Automation & pause"]:
        assert label in html


def test_oauth_state_and_callback(api):
    c, fake = api
    assert check_state(make_state()) and not check_state("1.2.bad") and not check_state("garbage")
    assert c.get("/api/instagram/callback?code=abc&state=forged").status_code == 400
    r = c.get(f"/api/instagram/callback?code=abc&state={make_state()}")
    assert r.status_code == 200 and "ap_test" in r.text
    accts = c.get("/api/accounts", headers=H).json()
    assert accts[0]["username"] == "ap_test" and "token_encrypted" not in accts[0] and not accts[0]["publishing_enabled"]
    url = c.get("/api/instagram/connect-url", headers=H).json()["url"]
    assert "instagram.com/oauth/authorize" in url


def test_full_flow_through_api_to_published(api, tmp_path):
    c, fake = api
    c.get(f"/api/instagram/callback?code=abc&state={make_state()}")
    aid = c.get("/api/accounts", headers=H).json()[0]["id"]
    assert c.post(f"/api/accounts/{aid}/enable-publishing", headers=H, json={"confirm_username": "nope"}).status_code == 422
    assert c.post(f"/api/accounts/{aid}/enable-publishing", headers=H, json={"confirm_username": "@ap_test"}).status_code == 200
    concepts = c.post("/api/concepts/generate", headers=H, json={"categories": ["situationship"], "per_category": 1}).json()
    r = c.post("/api/reels/render", headers=H, json={"concept_id": concepts[0]["id"], "overrides": {"canvas": {"fps": 12, "preset": "ultrafast"}, "duration_override": 5}})
    assert r.status_code == 202 and r.json()["render_status"] == "rendered", r.json()
    reel = c.get("/api/reels", headers=H).json()[0]
    # signed media URL works without bearer, tampered one does not
    assert c.get(reel["preview_url"]).status_code == 200
    assert c.get(reel["preview_url"][:-3] + "abc").status_code == 403
    job = c.post("/api/jobs", headers=H, json={"reel_id": reel["id"], "account_id": aid}).json()
    assert c.post("/api/jobs", headers=H, json={"reel_id": reel["id"], "account_id": aid}).status_code == 409
    c.post("/api/automation/pause", headers=H, json={"paused": True})
    assert c.get("/api/overview", headers=H).json()["paused"] is True
    assert c.post(f"/api/jobs/{job['id']}/approve", headers=H, json={}).status_code == 200
    # worker tick (paused -> nothing; resumed -> publishes)
    from reelstudio.db import session_scope
    from reelstudio.instagram.secrets import TokenCipher
    from reelstudio.publishing.queue import run_due
    with session_scope() as s:
        assert run_due(s, c.app.state.ig_client, TokenCipher(), sleep=lambda _: None) == []
    c.post("/api/automation/pause", headers=H, json={"paused": False})
    with session_scope() as s:
        assert run_due(s, c.app.state.ig_client, TokenCipher(), sleep=lambda _: None) == [job["id"]]
    audit = c.get(f"/api/jobs/{job['id']}/audit", headers=H).json()
    assert [a["action"] for a in audit][-1] == "job.published"
    assert c.post(f"/api/jobs/{job['id']}/cancel", headers=H, json={}).status_code == 409
    assert c.post("/api/analytics/collect", headers=H).status_code == 200
    a = c.get("/api/analytics", headers=H).json()
    assert a["reels"][0]["assessment"]["verdict"] in ("no_data", "insufficient_baseline")
    assert c.get("/api/calendar", headers=H).json()[0]["status"] == "published"
    c.post(f"/api/accounts/{aid}/revoke", headers=H)
    assert c.get("/api/accounts", headers=H).json()[0]["token"]["state"] == "revoked"


def test_reference_observation_rule_enforced_via_api(api):
    c, _ = api
    r = c.post("/api/references", headers=H, data={"account": "salzr", "source_url": "https://www.instagram.com/salzr/"})
    rid = r.json()["id"]
    assert c.post(f"/api/references/{rid}/observations", headers=H, json={"text": "serif", "inspected": False, "evidence": ""}).status_code == 422


def test_ads_endpoints_require_all_approvals(api):
    c, _ = api
    r = c.post("/api/ads", headers=H, json={"name": "n", "objective": "o"})
    assert r.status_code == 200
    assert c.post(f"/api/ads/{r.json()['id']}/approve/budget", headers=H).status_code == 422
