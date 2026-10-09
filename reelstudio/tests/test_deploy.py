import re
import subprocess
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]


def sh(script: str) -> str:
    r = subprocess.run(["bash", "-c", f". {ROOT}/deploy/lib.sh; {script}"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_generated_key_is_valid_fernet_and_unique():
    k1, k2 = sh("gen_fernet_key"), sh("gen_fernet_key")
    Fernet(k1.encode())
    assert k1 != k2


def test_token_and_password_shapes():
    assert len(sh("gen_token")) >= 40 and re.fullmatch(r"[A-Za-z0-9]+", sh("gen_token"))
    assert re.fullmatch(r"[0-9a-f]{48}", sh("gen_password"))


@pytest.mark.parametrize("sub,ok", [("anurag-reels", True), ("a", True), ("A", False), ("-x", False), ("x-", False),
                                     ("a.b", False), ("a b", False), ("", False), ("a" * 61, False)])
def test_subdomain_validation(sub, ok):
    r = subprocess.run(["bash", "-c", f'. {ROOT}/deploy/lib.sh; valid_subdomain "$1"', "_", sub])
    assert (r.returncode == 0) == ok


def test_write_env_is_private_complete_and_never_overwrites(tmp_path):
    f = tmp_path / ".env"
    sh(f'write_env {f} anurag.duckdns.org 123456 abcDEF0123')
    assert oct(f.stat().st_mode)[-3:] == "600"
    text = f.read_text()
    kv = dict(line.split("=", 1) for line in text.splitlines())
    assert kv["RS_DOMAIN"] == "anurag.duckdns.org" and kv["RS_META_APP_ID"] == "123456"
    Fernet(kv["RS_SECRET_KEY"].encode())
    assert len(kv["RS_DASHBOARD_TOKEN"]) >= 40 and len(kv["POSTGRES_PASSWORD"]) == 48
    assert "RS_META_REDIRECT_URI" not in kv and "RS_PUBLIC_BASE_URL" not in kv  # derived by compose
    r = subprocess.run(["bash", "-c", f". {ROOT}/deploy/lib.sh; write_env {f} x 1 2"], capture_output=True, text=True)
    assert r.returncode != 0 and f.read_text() == text


def test_setup_script_syntax_and_never_enables_publishing():
    assert subprocess.run(["bash", "-n", str(ROOT / "deploy/setup-vps.sh")]).returncode == 0
    body = (ROOT / "deploy/setup-vps.sh").read_text()
    assert "enable-publishing" not in body and "auto-publish" not in body
    assert "echo \"$MSEC\"" not in body and "RS_SECRET_KEY" not in body.replace("RS_SECRET_KEY=", "")


def test_compose_derives_urls_and_hides_db_and_api():
    import yaml
    c = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    env = c["x-app"]["environment"]
    assert env["RS_META_REDIRECT_URI"].endswith("/api/instagram/callback") and "RS_DOMAIN" in env["RS_PUBLIC_BASE_URL"]
    assert "ports" not in c["services"]["db"] and "ports" not in c["services"]["api"]
    assert c["services"]["caddy"]["ports"] == ["80:80", "443:443"]
    assert "logging" in c["x-app"]


def test_dockerfile_uses_editable_install_nonroot():
    d = (ROOT / "Dockerfile").read_text()
    assert "pip install --no-cache-dir -e" in d and "USER app" in d and "RS_CONFIG_DIR" in d
