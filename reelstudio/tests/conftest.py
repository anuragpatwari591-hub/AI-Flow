import pytest

from reelstudio import db


import os


def test_db_url(tmp_path=None) -> str:
    """SQLite in-memory by default; set RS_TEST_DATABASE_URL to run the whole suite on PostgreSQL."""
    return os.environ.get("RS_TEST_DATABASE_URL", "sqlite://")


@pytest.fixture()
def session():
    url = test_db_url()
    db.init_db(url)
    if not url.startswith("sqlite"):
        db.Base.metadata.drop_all(db._engine)
        db.Base.metadata.create_all(db._engine)
    with db.session_scope() as s:
        yield s


from cryptography.fernet import Fernet  # noqa: E402

from reelstudio import config  # noqa: E402


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("RS_SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("RS_PUBLIC_BASE_URL", "https://studio.example.test")
    monkeypatch.setenv("RS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("RS_META_APP_ID", "APPID")
    monkeypatch.setenv("RS_META_APP_SECRET", "APPSECRET")
    monkeypatch.setenv("RS_META_REDIRECT_URI", "https://studio.example.test/api/instagram/callback")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture()
def stack(session, env, tmp_path):
    """A connected+enabled account and one fully rendered reel, all against the fake Graph API."""
    from reelstudio.instagram.accounts import connect_account, enable_publishing
    from reelstudio.instagram.client import IGClient
    from reelstudio.instagram.secrets import TokenCipher
    from reelstudio.render.service import render_reel
    from reelstudio.writing.engine import run_cycle
    from tests.fake_graph import FakeGraph

    fake = FakeGraph()
    client = IGClient("APPID", "APPSECRET", "https://studio.example.test/cb", http=fake.client())
    cipher = TokenCipher()
    acct = connect_account(session, client, cipher, "CODE")
    enable_publishing(session, client, cipher, acct, "@ap_test")
    concept = run_cycle(session, categories=["situationship"], per_category=1)[0]
    reel = render_reel(session, concept.id, overrides={"canvas": {"fps": 12, "preset": "ultrafast"}, "duration_override": 5},
                       out_root=tmp_path / "renders")
    assert reel.render_status == "rendered", reel.render_error
    return type("Stack", (), dict(s=session, fake=fake, client=client, cipher=cipher, acct=acct, reel=reel, concept=concept))


@pytest.fixture(autouse=True)
def _no_real_media_fetch(monkeypatch):
    """Tests never hit the network for media checks; dedicated tests exercise verify_public_media directly."""
    from reelstudio.publishing import queue
    monkeypatch.setattr(queue, "verify_public_media", lambda *a, **k: None)
