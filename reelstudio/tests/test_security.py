import json
import logging

import pytest
from fastapi.testclient import TestClient

from reelstudio import config
from reelstudio.api import app as appmod
from reelstudio.instagram.secrets import SecretsError
from reelstudio.logging_setup import JsonFormatter, redact, setup_logging
from reelstudio.publishing.media import sign_media
from tests.test_api import H, api  # noqa: F401  (fixture)


def test_secrets_redacted_from_logs():
    assert "SECRET" not in redact("GET https://graph.instagram.com/me?fields=x&access_token=SECRET123&y=1")
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "client_secret=SECRET code=ABC", None, None)
    out = json.loads(JsonFormatter().format(rec))["msg"]
    assert "SECRET" not in out and "ABC" not in out


def test_httpx_url_logging_silenced():
    setup_logging()
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_no_signing_without_secret(monkeypatch):
    monkeypatch.setenv("RS_SECRET_KEY", ""); config.get_settings.cache_clear()
    with pytest.raises(SecretsError):
        sign_media(1, "video", "x")
    config.get_settings.cache_clear()


def test_headers_and_throttle(api):
    c, _ = api
    appmod._FAILS.clear()
    r = c.get("/api/overview", headers=H)
    assert r.headers["x-content-type-options"] == "nosniff" and "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    for _ in range(10):
        assert c.get("/api/overview", headers={"Authorization": "Bearer bad"}).status_code == 401
    assert c.get("/api/overview", headers={"Authorization": "Bearer bad"}).status_code == 429
    appmod._FAILS.clear()


def test_paths_restricted_to_data_dir(api, tmp_path):
    c, _ = api
    appmod._FAILS.clear()
    r = c.post("/api/audio", headers=H, json={"title": "x", "local_file": "/etc/passwd", "rights_status": "original"})
    assert r.status_code == 422
    r = c.post("/api/reels/render", headers=H, json={"concept_id": 1, "overrides": {"background": {"type": "footage", "footage": "/etc/passwd"}}})
    assert r.status_code == 422


def test_manual_permalink_must_be_instagram_https(api):
    c, _ = api
    appmod._FAILS.clear()
    r = c.post("/api/jobs/1/manual-published", headers=H, json={"permalink": "javascript:alert(1)"})
    assert r.status_code == 422


def test_dashboard_never_uses_innerhtml():
    html = (appmod.STATIC / "index.html").read_text()
    assert "innerHTML" not in html and "document.write" not in html and "eval(" not in html


def test_no_secrets_committed():
    import subprocess, pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    out = subprocess.run(["grep", "-rIlE", r"(sk-ant-|IGAA[A-Za-z0-9]{20,}|EAA[A-Za-z0-9]{30,})", str(root / "src"), str(root / "config")],
                         capture_output=True, text=True).stdout
    assert out.strip() == ""
