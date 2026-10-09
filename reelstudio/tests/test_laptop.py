import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from reelstudio import config

ROOT = Path(__file__).resolve().parents[1]
PS1 = ROOT / "deploy/windows/setup-laptop.ps1"
COMPOSE = ROOT / "docker-compose.laptop.yml"


# ---------------------------------------------------------------- compose
def load_compose():
    return yaml.safe_load(COMPOSE.read_text())


def test_laptop_compose_security_shape():
    c = load_compose()
    s = c["services"]
    assert s["api"]["ports"] == ["127.0.0.1:8000:8000"]                       # dashboard on loopback only
    for name in ("db", "worker", "gate", "cloudflared", "ngrok"):
        assert "ports" not in s[name]                                          # nothing else published on the host
    assert s["cloudflared"]["profiles"] == ["quick"] and s["ngrok"]["profiles"] == ["ngrok"]
    assert "gate:8080" in " ".join(s["cloudflared"]["command"].split()) and "gate:8080" in s["ngrok"]["command"]
    # tunnels reach only the gate, never the api directly
    assert not any("api:8000" in str(s[n]["command"]) for n in ("cloudflared", "ngrok"))
    # ngrok authtoken lives in its own env file and is never handed to the app containers
    assert s["ngrok"]["env_file"][0]["path"] == ".env.tunnel"
    assert s["api"]["env_file"] == ".env" and s["worker"]["env_file"] == ".env"
    assert "NGROK_AUTHTOKEN" not in COMPOSE.read_text().replace("env_file", "").split("ngrok:")[0]
    env = s["api"]["environment"]
    assert env["RS_META_REDIRECT_URI"] == "${RS_PUBLIC_URL}/api/instagram/callback"        # derived: cannot disagree
    assert env["RS_PUBLIC_BASE_URL"].startswith("${RS_PUBLIC_URL")
    assert "volumes" in c and set(c["volumes"]) == {"pgdata", "data"}                      # persistent storage
    assert all(s[n]["restart"] == "unless-stopped" for n in s)


@pytest.mark.skipif(subprocess.run(["which", "docker"], capture_output=True).returncode != 0, reason="docker CLI not installed")
@pytest.mark.parametrize("profile", ["quick", "ngrok"])
def test_laptop_compose_validates_with_docker(tmp_path, profile):
    (tmp_path / ".env").write_text("")
    for f in ("docker-compose.laptop.yml",):
        (tmp_path / f).write_text((ROOT / f).read_text())
    (tmp_path / "deploy").mkdir(); (tmp_path / "deploy/Caddyfile.tunnel").write_text((ROOT / "deploy/Caddyfile.tunnel").read_text())
    r = subprocess.run(["docker", "compose", "-f", "docker-compose.laptop.yml", "--profile", profile, "config", "-q"], cwd=tmp_path,
                       env={**os.environ, "POSTGRES_PASSWORD": "x", "RS_PUBLIC_URL": "https://a.example.test"}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # no .env.tunnel present: must still validate (required: false) for the quick profile
    assert not (tmp_path / ".env.tunnel").exists()


def test_gate_caddyfile_allowlist_text():
    cf = (ROOT / "deploy/Caddyfile.tunnel").read_text()
    assert "path /healthz /media/* /api/instagram/callback" in cf and "method GET HEAD" in cf
    assert "respond \"Not found\" 404" in cf and "auto_https off" in cf and "admin off" in cf
    assert cf.count("reverse_proxy") == 1


# ---------------------------------------------------------------- PowerShell script (static lint; cannot run Windows here)
def ps_text():
    return PS1.read_bytes().decode("utf-8")


def test_ps1_is_crlf_ascii_and_ps51_safe():
    raw = PS1.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and raw.decode("ascii")
    code = re.sub(r"<#.*?#>", "", ps_text(), flags=re.S)
    code = "\n".join(l for l in code.splitlines() if not l.strip().startswith("#"))
    for pat, why in [(r"\?\?", "null-coalescing (PS7)"), (r"\?\.", "null-conditional (PS7)"), (r"\)\s*\?\s*\S+\s*:", "ternary (PS7)"),
                     (r"&&", "pipeline chain (PS7)"), (r"\|\|", "pipeline chain (PS7)"), (r"-Parallel", "-Parallel (PS7)"),
                     (r"Invoke-RestMethod[^\n]*-SkipHttpErrorCheck", "-SkipHttpErrorCheck (PS7)"), (r"ConvertFrom-Json[^\n]*-AsHashtable", "AsHashtable (PS7)")]:
        assert not re.search(pat, code), why
    assert "#Requires -Version 5.1" in ps_text()


def test_ps1_never_prints_or_commits_secrets_and_never_publishes():
    t = ps_text()
    for m in re.finditer(r"Write-Host[^\n]*", t):
        line = m.group(0)
        assert not re.search(r"\$(sec|tok|id)\b|RS_SECRET_KEY|RS_DASHBOARD_TOKEN|RS_META_APP_SECRET|NGROK_AUTHTOKEN|POSTGRES_PASSWORD", line), line
    assert "Read-Host -Prompt $Prompt -AsSecureString" in t                                  # secrets typed hidden
    assert "UTF8Encoding($false)" in t and "Set-Content" not in t                           # BOM-free .env
    assert "icacls.exe $Path /inheritance:r" in t                                           # .env restricted to the user
    low = t.lower()
    assert "enable-publishing" not in low and "auto-publish" not in low and "/api/jobs" not in low and "/api/reels" not in low
    assert "invoke-restmethod -method post" not in low and "-method post" not in low           # never POSTs to the app at all
    assert "Set-Clipboard" in t and "if ($CopyToken)" in t                                  # token only copied on request
    assert "RandomNumberGenerator" in t                                                     # CSPRNG, not Get-Random
    assert "Get-Random" not in t


def test_ps1_checks_prereqs_in_order_and_verifies_gate():
    t = ps_text()
    order = [t.index(x) for x in ("Get-Command docker", "docker info", "WSL2|microsoft", "docker compose version",
                                  "up -d --build --wait", "healthz", "NOT reachable from the internet", "connect-url", "--wait 300")]
    assert order == sorted(order)
    assert "$local.ffmpeg" in t                                                              # rendering dependency verified
    assert "api.trycloudflare.com" in t                                                      # skip cloudflared's control endpoint


# ---------------------------------------------------------------- python side used by the script
def run_cli(args, env_extra, cwd):
    env = {k: v for k, v in os.environ.items() if not k.startswith("RS_")}
    env.update(PYTHONPATH=str(ROOT / "src"), **env_extra)
    return subprocess.run([sys.executable, "-m", "reelstudio.cli", *args], cwd=cwd, env=env, capture_output=True, text=True)


GOOD_ENV = dict(RS_SECRET_KEY="", RS_DASHBOARD_TOKEN="d" * 40, RS_META_APP_ID="APPID", RS_META_APP_SECRET="TOPSECRETVALUE",
                RS_META_REDIRECT_URI="https://abc.trycloudflare.com/api/instagram/callback", RS_PUBLIC_BASE_URL="https://abc.trycloudflare.com")


def test_connect_url_command(tmp_path):
    from cryptography.fernet import Fernet
    env = {**GOOD_ENV, "RS_SECRET_KEY": Fernet.generate_key().decode()}
    r = run_cli(["connect-url"], env, tmp_path)
    assert r.returncode == 0 and r.stdout.startswith("https://www.instagram.com/oauth/authorize?")
    assert "client_id=APPID" in r.stdout and "abc.trycloudflare.com" in r.stdout and "state=" in r.stdout
    assert "TOPSECRETVALUE" not in r.stdout + r.stderr and env["RS_SECRET_KEY"] not in r.stdout + r.stderr
    bad = run_cli(["connect-url"], {**env, "RS_META_REDIRECT_URI": "https://abc.trycloudflare.com/wrong"}, tmp_path)
    assert bad.returncode == 1 and "incomplete" in bad.stderr and bad.stdout == ""
    pending = run_cli(["connect-url"], {**env, "RS_PUBLIC_BASE_URL": "https://pending.invalid", "RS_META_REDIRECT_URI": "https://pending.invalid/api/instagram/callback"}, tmp_path)
    assert pending.returncode == 0 or "incomplete" in pending.stderr   # placeholder host is syntactically valid; reachability is checked elsewhere


# ---------------------------------------------------------------- API behaviour the gate and Instagram rely on
@pytest.fixture()
def client(env, monkeypatch, tmp_path):
    from reelstudio.api.app import create_app
    from reelstudio.db import init_db
    monkeypatch.setenv("RS_DASHBOARD_TOKEN", "x" * 40); config.get_settings.cache_clear()
    init_db("sqlite://")
    return TestClient(create_app())


def test_media_supports_head_and_range(stack):
    from reelstudio.api.app import create_app
    from reelstudio.publishing.media import public_url
    stack.s.commit()          # the API uses its own connection; Postgres only shows committed rows
    c = TestClient(create_app())
    url = public_url(stack.reel.id, "video", stack.reel.video_sha256, base="https://h.test").replace("https://h.test", "")
    size = Path(stack.reel.video_path).stat().st_size
    assert c.head(url).status_code == 200
    r = c.get(url, headers={"Range": "bytes=0-0"})
    assert r.status_code == 206 and r.headers["content-range"].endswith(f"/{size}") and r.headers["content-type"] == "video/mp4"
    cover = public_url(stack.reel.id, "cover", stack.reel.video_sha256, base="https://h.test").replace("https://h.test", "")
    assert c.get(cover).headers["content-type"] == "image/jpeg"


def test_callback_page_does_not_link_to_gated_paths(client):
    from reelstudio.api.app import make_state
    r = client.get("/api/instagram/callback?code=&state=" + make_state(), headers={})
    assert "href" not in r.text.lower()      # the public gate 404s "/", so the page must not send users there
