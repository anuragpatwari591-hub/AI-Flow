import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from reelstudio import config
from reelstudio.config import Settings
from reelstudio.db import PublishJob
from reelstudio.setup import (SetupLock, SetupOptions, StateFile, db_state, render, run_setup, to_json, update_env_file)
from tests.fake_graph import FakeGraph

ROOT = Path(__file__).resolve().parents[1]
HOST_OK = httpx.Client(transport=httpx.MockTransport(
    lambda r: httpx.Response(200, json={"ok": True, "ffmpeg": True}) if r.url.path == "/healthz" else httpx.Response(404)))


def loader(env: Path, **extra):
    return lambda: Settings(_env_file=str(env), config_dir=ROOT / "config", **extra)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for k in list(os.environ):
        if k.startswith("RS_"):
            monkeypatch.delenv(k)
    config.get_settings.cache_clear()
    d = tmp_path / "data"
    return tmp_path, tmp_path / ".env", dict(data_dir=d, database_url=f"sqlite:///{d}/rs.db")


# ---------------------------------------------------------------- .env handling
def test_update_env_fills_only_missing_and_never_overwrites(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# comment\nRS_SECRET_KEY=keepme\nRS_DASHBOARD_TOKEN=\nOTHER=1\n")
    written = update_env_file(f, {"RS_SECRET_KEY": "NEW", "RS_DASHBOARD_TOKEN": "tok", "RS_META_APP_ID": "123"})
    assert sorted(written) == ["RS_DASHBOARD_TOKEN", "RS_META_APP_ID"]
    text = f.read_text()
    assert "RS_SECRET_KEY=keepme" in text and "NEW" not in text and "OTHER=1" in text and "# comment" in text
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert update_env_file(f, {"RS_SECRET_KEY": "x", "RS_DASHBOARD_TOKEN": "y"}) == []   # idempotent


def test_lock_prevents_concurrent_setup(tmp_path):
    with SetupLock(tmp_path / "l"):
        with pytest.raises(RuntimeError, match="already running"):
            with SetupLock(tmp_path / "l"):
                pass
    with SetupLock(tmp_path / "l"):   # released afterwards
        pass


# ---------------------------------------------------------------- the flow
def test_check_is_read_only_and_names_blockers(home):
    tmp, env, extra = home
    rep = run_setup(SetupOptions(mutate=False, live=False), env_path=env, load=loader(env, **extra))
    assert not env.exists() and not (tmp / "data").exists()            # nothing created
    assert rep.next_action != "READY" and "reelstudio setup" in rep.next_action and "gen-keys" not in rep.next_action
    out = render(rep)
    assert "STATUS: BLOCKED" in out and "PUBLISHING VERIFIED: no" in out
    assert "database" in out and "database file does not exist" in out


def test_setup_creates_secrets_migrates_and_blocks_on_hosting(home):
    tmp, env, extra = home
    rep = run_setup(SetupOptions(mutate=True, live=False, interactive=False), env_path=env, load=loader(env, **extra))
    text = env.read_text()
    kv = dict(l.split("=", 1) for l in text.splitlines() if "=" in l)
    Fernet(kv["RS_SECRET_KEY"].encode()); assert len(kv["RS_DASHBOARD_TOKEN"]) >= 40
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    out = render(rep)
    assert kv["RS_SECRET_KEY"] not in out and kv["RS_DASHBOARD_TOKEN"] not in out      # never printed
    assert db_state(loader(env, **extra)())[0] == "head"
    assert "RS_META_APP_ID" in out or "Instagram app ID" in rep.next_action
    st = StateFile(tmp / "data" / "setup_state.json")
    assert st.data["status"] == "blocked"


def test_setup_is_resumable_and_never_rotates_credentials(home):
    tmp, env, extra = home
    opts = SetupOptions(mutate=True, live=False)
    run_setup(opts, env_path=env, load=loader(env, **extra))
    before = env.read_text()
    (tmp / "data" / "setup_state.json").write_text(json.dumps({"status": "in_progress", "phase": "database"}))  # simulate crash
    rep = run_setup(opts, env_path=env, load=loader(env, **extra))
    assert env.read_text() == before                                  # same keys, untouched
    assert any("interrupted at phase 'database'" in d for _, n, d in rep.checks if n == "resume")
    assert db_state(loader(env, **extra)())[0] == "head"             # migrations not duplicated/broken


def test_interactive_prompts_fill_meta_credentials_hidden(home):
    tmp, env, extra = home
    asked = []
    rep = run_setup(SetupOptions(mutate=True, live=False, interactive=True, open_browser=False), env_path=env,
                    load=loader(env, **extra), prompt=lambda p: asked.append(p) or "1234567890",
                    secret_prompt=lambda p: asked.append(p) or "abcdef0123456789")
    text = env.read_text()
    assert "RS_META_APP_ID=1234567890" in text and "RS_META_APP_SECRET=abcdef0123456789" in text
    assert "abcdef0123456789" not in render(rep) and len(asked) == 2
    # unsafe characters are rejected instead of corrupting .env
    env.unlink()
    run_setup(SetupOptions(mutate=True, live=False, interactive=True), env_path=env, load=loader(env, **extra),
              prompt=lambda p: "bad value;rm -rf", secret_prompt=lambda p: "x y")
    assert "RS_META_APP_ID" not in env.read_text()


class NoClose:
    """Shares one test session but ignores close(), like a factory that hands out fresh sessions."""
    def __init__(self, s): self._s = s
    def __getattr__(self, n): return getattr(self._s, n)
    def close(self): pass


def full_env(home, **kw):
    tmp, env, extra = home
    base = dict(RS_DOMAIN_UNUSED="")  # noqa
    key = Fernet.generate_key().decode()
    return dict(secret_key=key, dashboard_token="t" * 40, meta_app_id="APPID", meta_app_secret="APPSECRET",
                meta_redirect_uri="https://studio.example.test/api/instagram/callback",
                public_base_url="https://studio.example.test", **extra, **kw)


def test_not_connected_gives_connect_url_as_single_action(home, session):
    tmp, env, extra = home
    s = full_env(home)
    fake = FakeGraph()
    from reelstudio.instagram.client import IGClient
    c = IGClient("APPID", "APPSECRET", s["meta_redirect_uri"], http=fake.client())
    os.environ["RS_SECRET_KEY"] = s["secret_key"]; config.get_settings.cache_clear()
    try:
        rep = run_setup(SetupOptions(mutate=True, live=True, interactive=False), env_path=env,
                        load=lambda: Settings(_env_file=None, config_dir=ROOT / "config", **s),
                        session_factory=lambda: session, ig_client=c, http=HOST_OK)
    finally:
        os.environ.pop("RS_SECRET_KEY")
    out = render(rep)
    assert "instagram.com/oauth/authorize" in out and "STATUS: BLOCKED" in out
    assert "log in to Instagram" in rep.next_action and "APPSECRET" not in out
    assert "Connect URL" not in to_json(rep) or "<omitted>" in to_json(rep)


def test_connected_but_publishing_off_then_ready(home, session, stack):
    tmp, env, extra = home
    s = full_env(home)
    from reelstudio import worker
    os.environ["RS_DATA_DIR"] = str(tmp / "data"); config.get_settings.cache_clear()
    try:
        s["secret_key"] = os.environ["RS_SECRET_KEY"]   # the key `stack` encrypted the stored token with
        stack.acct.publishing_enabled = False
        mk = lambda: Settings(_env_file=None, config_dir=ROOT / "config", **s)  # noqa: E731
        from reelstudio.setup import apply_migrations
        apply_migrations(mk(), "missing")                                     # the DB file the settings point at
        opts = SetupOptions(mutate=False, live=True)
        kw = dict(env_path=env, load=mk, session_factory=lambda: NoClose(stack.s), ig_client=stack.client, http=HOST_OK)
        rep = run_setup(opts, **kw)
        assert "Enable publishing" in rep.next_action                      # exact action, nothing auto-enabled
        assert not stack.acct.publishing_enabled
        stack.acct.publishing_enabled = True
        rep2 = run_setup(opts, **kw)
        assert "worker" in rep2.next_action.lower()                          # only the worker heartbeat is missing
        worker.touch_heartbeat()
        rep3 = run_setup(opts, **kw)
        out = render(rep3)
        assert rep3.next_action == "READY" and "STATUS: READY" in out and "PUBLISHING VERIFIED: no" in out
        assert stack.s.query(PublishJob).count() == 0                        # setup never created/published anything
        assert stack.fake.published == []
    finally:
        os.environ.pop("RS_DATA_DIR", None); config.get_settings.cache_clear()


def test_deploy_requires_confirmation_and_is_skipped_otherwise(tmp_path, monkeypatch):
    from reelstudio.doctor import Report
    from reelstudio.setup import deploy_compose
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docker-compose.yml").write_text("services: {}")
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/docker")
    calls = []
    run = lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, "", "")  # noqa: E731
    rep = Report(); deploy_compose(rep, SetupOptions(interactive=False), run=run)
    assert calls == [] and rep.checks[-1][0] == "SKIP"
    rep = Report(); deploy_compose(rep, SetupOptions(interactive=True), run=run, ask=lambda p: "n")
    assert calls == [] and "declined" in rep.checks[-1][2]
    rep = Report(); deploy_compose(rep, SetupOptions(interactive=True), run=run, ask=lambda p: "y")
    assert calls and calls[0][0][:3] == ["docker", "compose", "up"] and rep.checks[-1][0] == "OK"


# ---------------------------------------------------------------- CLI + API
def test_cli_setup_check_runs_and_is_read_only(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("RS_")}
    r = subprocess.run([sys.executable, "-m", "reelstudio.cli", "setup", "--check", "--offline", "--json"], cwd=tmp_path,
                       env={**env, "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True)
    data = json.loads(r.stdout)
    assert r.returncode == 1 and data["status"] == "BLOCKED" and data["next_action"]
    assert not (tmp_path / ".env").exists() and not (tmp_path / "data").exists()
    assert any(c["name"] == "ffmpeg encoders" and c["status"] == "OK" for c in data["checks"])


def test_api_setup_status_endpoint_never_leaks_secrets(env, monkeypatch, tmp_path):
    from reelstudio.api.app import create_app
    from reelstudio.db import init_db
    monkeypatch.setenv("RS_DASHBOARD_TOKEN", "tok123-" + "x" * 30)
    config.get_settings.cache_clear(); init_db("sqlite://")
    c = TestClient(create_app())
    assert c.get("/api/setup/status").status_code == 401
    r = c.get("/api/setup/status", headers={"Authorization": "Bearer tok123-" + "x" * 30})
    assert r.status_code == 200 and r.json()["status"] in ("READY", "BLOCKED")
    blob = r.text
    assert os.environ["RS_SECRET_KEY"] not in blob and "tok123" not in blob and "APPSECRET" not in blob


def test_wrong_secret_key_reports_reconnect_instead_of_crashing(home, session, stack):
    tmp, env, extra = home
    s = full_env(home); s["secret_key"] = Fernet.generate_key().decode()        # different from the stored token's key
    from reelstudio.setup import apply_migrations
    mk = lambda: Settings(_env_file=None, config_dir=ROOT / "config", **s)  # noqa: E731
    apply_migrations(mk(), "missing")
    rep = run_setup(SetupOptions(mutate=False, live=True), env_path=env, load=mk, session_factory=lambda: NoClose(stack.s),
                    ig_client=stack.client, http=HOST_OK)
    assert any("cannot be decrypted" in d for _, n, d in rep.checks) and "Connect URL" in render(rep)


def test_weak_existing_token_is_not_silently_rotated(home):
    tmp, env, extra = home
    env.write_text("RS_DASHBOARD_TOKEN=short\n")
    rep = run_setup(SetupOptions(mutate=True, live=False), env_path=env, load=loader(env, **extra))
    assert "RS_DASHBOARD_TOKEN=short" in env.read_text()                 # never overwritten
    assert "shorter than 24" in render(rep) and "gen-keys" in rep.next_action
