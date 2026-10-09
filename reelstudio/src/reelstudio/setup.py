"""`reelstudio setup` / `reelstudio setup --check`: one orchestrated, resumable readiness flow.

Principles
- `--check` is read-only (no writes, no prompts); it names the exact remaining blockers.
- `setup` is idempotent: every phase is check-then-act, so it can be re-run after an interruption. It only FILLS missing
  or empty values, never overwrites an existing credential, and never prints a secret.
- It never deploys to anything without an explicit y/N (or --yes) and only to the Docker host you run it on; it never
  signs up for, or pays for, hosting. It never enables publishing and never publishes.
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx
from sqlalchemy import create_engine, inspect as sa_inspect, select
from sqlalchemy.orm import Session, sessionmaker

from . import doctor
from .config import PROJECT_ROOT, Settings, get_settings
from .doctor import Report

MODULES = ["fastapi", "uvicorn", "sqlalchemy", "alembic", "pydantic", "pydantic_settings", "PIL", "numpy", "httpx",
           "yaml", "cryptography"]
HOSTING_TOOLS = ["docker", "flyctl", "fly", "cloudflared", "ngrok", "caddy", "vercel", "railway", "heroku", "systemctl"]
SAFE_VALUE = re.compile(r"^[A-Za-z0-9._:-]+$")
HOSTING_ACTION = doctor.HOSTING_ACTION


# ----------------------------------------------------------------------------- small helpers
def gen_fernet_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def gen_token() -> str:
    return secrets.token_urlsafe(36)


def in_container() -> bool:
    return Path("/.dockerenv").exists()


def update_env_file(path: Path, updates: dict[str, str]) -> list[str]:
    """Fill KEY=VALUE for keys that are absent or EMPTY; never touch a key that already has a value.
    Writes atomically, keeps chmod 600. Returns the keys written (names only)."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    written: list[str] = []
    for key, value in updates.items():
        pat = re.compile(rf"^\s*{re.escape(key)}\s*=(.*)$")
        idx = next((i for i, l in enumerate(lines) if pat.match(l)), None)
        if idx is None:
            lines.append(f"{key}={value}")
            written.append(key)
        elif not pat.match(lines[idx]).group(1).strip().strip("\"'"):   # type: ignore[union-attr]
            lines[idx] = f"{key}={value}"
            written.append(key)
    if written:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    return written


class SetupLock:
    """Prevents two concurrent `setup` runs (flock; released automatically if the process dies)."""

    def __init__(self, path: Path) -> None:
        self.path, self.fh = path, None

    def __enter__(self) -> "SetupLock":
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            raise RuntimeError("another `reelstudio setup` is already running")
        return self

    def __exit__(self, *exc: Any) -> None:
        import fcntl
        if self.fh:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()


class StateFile:
    """Non-secret progress record so an interrupted run is recognised and resumed."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.data = json.loads(path.read_text())
        except (OSError, ValueError):
            self.data = {}

    @property
    def interrupted(self) -> bool:
        return self.data.get("status") == "in_progress"

    def mark(self, status: str, phase: str = "") -> None:
        self.data.update(status=status, phase=phase, at=datetime.now(timezone.utc).isoformat())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data))


# ----------------------------------------------------------------------------- inspections
def check_python(rep: Report) -> str | None:
    import importlib.util
    missing = []
    for m in MODULES:
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
    if not (importlib.util.find_spec("multipart") or importlib.util.find_spec("python_multipart")):
        missing.append("python-multipart")
    rep.add("FAIL" if missing else "OK", "python dependencies", f"missing: {missing}" if missing else f"{len(MODULES)} modules importable (Python {sys.version_info.major}.{sys.version_info.minor})")
    if sys.version_info < (3, 11):
        rep.add("FAIL", "python version", "3.11+ required")
        return "Install Python 3.11 or newer."
    return "Run `pip install -e '.[postgres]'` in the project folder." if missing else None


def check_ffmpeg(rep: Report) -> str | None:
    exe = shutil.which("ffmpeg")
    if not exe:
        rep.add("FAIL", "ffmpeg", "not installed")
        return "Install FFmpeg (Ubuntu: `sudo apt-get install -y ffmpeg`)."
    try:
        enc = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        enc = ""
    ok = "libx264" in enc and re.search(r"\baac\b", enc) is not None
    rep.add("OK" if ok else "FAIL", "ffmpeg encoders", "libx264 + aac available" if ok else "needs libx264 and aac encoders")
    return None if ok else "Install an FFmpeg build with libx264 and AAC (Ubuntu's `ffmpeg` package has both)."


def check_fonts(rep: Report) -> str | None:
    from .render.fonts import FontError, font_record
    from .render.spec import list_templates, load_template
    bad = []
    for t in list_templates():
        try:
            font_record(load_template(t).text.font)
        except (FontError, OSError, ValueError) as e:
            bad.append(f"{t}: {e}")
    rep.add("FAIL" if bad else "OK", "fonts (licensed, per template)", "; ".join(bad)[:300] if bad else "all template fonts found with licence records")
    return "Install fonts (Ubuntu: `sudo apt-get install -y fonts-inter fonts-liberation2`) or register your own in config/fonts.yaml." if bad else None


def detect_hosting(rep: Report) -> dict[str, Any]:
    tools = {t: bool(shutil.which(t)) for t in HOSTING_TOOLS}
    info = {"tools": [t for t, ok in tools.items() if ok], "in_container": in_container()}
    compose = False
    if tools["docker"] and not in_container():
        try:
            compose = subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            compose = False
    info["docker_compose"] = compose
    rep.add("INFO", "hosting tools detected", ", ".join(info["tools"]) or "none")
    rep.add("INFO", "supported deployment target", "Docker Compose + Caddy (automatic HTTPS) on a server you control" +
            (" — Docker Compose available here" if compose else ""))
    return info


# ----------------------------------------------------------------------------- database / migrations
def _alembic_cfg(st: Settings):
    from alembic.config import Config
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    return cfg


def db_state(st: Settings) -> tuple[str, str]:
    """('missing'|'unversioned'|'behind'|'head'|'error', detail) without creating anything."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    url = st.database_url
    if url.startswith("sqlite") and ":memory:" not in url and "///" in url:
        if not Path(url.split("///", 1)[1]).exists():
            return "missing", "database file does not exist yet"
    try:
        eng = create_engine(url, future=True)
        with eng.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
            tables = sa_inspect(conn).get_table_names()
        eng.dispose()
    except Exception as e:  # noqa: BLE001
        return "error", f"cannot connect ({type(e).__name__})"
    head = ScriptDirectory.from_config(_alembic_cfg(st)).get_current_head()
    if current == head:
        return "head", f"at migration {head}"
    if current is None and tables and "reels" in tables:
        return "unversioned", "tables exist but are not under migration control"
    return "behind", f"at {current or 'empty'}, head is {head}"


def apply_migrations(st: Settings, state: str) -> None:
    from alembic import command
    if st.database_url.startswith("sqlite") and ":memory:" not in st.database_url and "///" in st.database_url:
        Path(st.database_url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    cfg = _alembic_cfg(st)
    cfg.set_main_option("sqlalchemy.url", st.database_url.replace("%", "%%"))   # explicit; no env-var side effects
    command.stamp(cfg, "head") if state == "unversioned" else command.upgrade(cfg, "head")


def check_database(st: Settings, rep: Report, mutate: bool) -> str | None:
    state, detail = db_state(st)
    if state in ("missing", "behind", "unversioned") and mutate:
        try:
            apply_migrations(st, state)
            state, detail = db_state(st)
            detail = "migrations applied; " + detail
        except Exception as e:  # noqa: BLE001
            rep.add("FAIL", "database migrations", f"failed ({type(e).__name__}): {str(e)[:150]}")
            return "Fix the database connection in RS_DATABASE_URL, then re-run `reelstudio setup`."
    ok = state == "head"
    rep.add("OK" if ok else "FAIL", "database", detail)
    if ok:
        return None
    if state == "error":
        return "Fix RS_DATABASE_URL / start the database, then re-run `reelstudio setup`."
    return "Run `reelstudio setup` (it applies migrations)."


# ----------------------------------------------------------------------------- public host / media route / worker
def check_media_route(st: Settings, rep: Report, http: httpx.Client | None = None) -> None:
    """A bogus signature must be refused by OUR app via the PUBLIC URL (proves /media is routed to this app)."""
    http = http or httpx.Client(timeout=10, follow_redirects=False)
    try:
        r = http.get(st.public_base_url.rstrip("/") + "/media/0/video/00000000000000000000000000000000")
        ok = r.status_code in (403, 404)
        rep.add("OK" if ok else "FAIL", "public /media route", "reaches the app (bogus signature refused)" if ok else f"unexpected HTTP {r.status_code}")
    except httpx.HTTPError as e:
        rep.add("FAIL", "public /media route", f"unreachable ({type(e).__name__})")


def worker_status(rep: Report, ready_so_far: bool) -> str | None:
    from .worker import heartbeat_age
    age = heartbeat_age()
    if age is None:
        rep.add("FAIL" if ready_so_far else "INFO", "worker", "no heartbeat yet (worker not running?)")
        return "Start the worker: `docker compose up -d worker` (or `reelstudio worker`)." if ready_so_far else None
    ok = age < 180
    rep.add("OK" if ok else "FAIL", "worker", f"last heartbeat {int(age)}s ago")
    return None if ok else "The worker has stopped: `docker compose restart worker` (or restart `reelstudio worker`)."


# ----------------------------------------------------------------------------- the orchestration
@dataclass
class SetupOptions:
    mutate: bool = False
    live: bool = True
    interactive: bool = False
    open_browser: bool = True
    wait_seconds: int = 0
    deploy: bool = False
    assume_yes: bool = False


def _sessions(st: Settings, factory: sessionmaker[Session] | None) -> Iterator[Session]:
    if factory is not None:
        s = factory()
    else:
        eng = create_engine(st.database_url, future=True)
        s = sessionmaker(eng, expire_on_commit=False)()
    try:
        yield s
        s.commit()
    finally:
        s.close()


def deploy_compose(rep: Report, opts: SetupOptions, run: Callable[..., Any] = subprocess.run,
                   ask: Callable[[str], str] = input) -> None:
    """Opt-in: `docker compose up -d --build` on THIS host. Never silent; own Docker host only."""
    if not (Path("docker-compose.yml").exists() and shutil.which("docker")):
        rep.add("SKIP", "deploy", "no docker / compose file here")
        return
    if not opts.assume_yes:
        if not opts.interactive:
            rep.add("SKIP", "deploy", "needs confirmation; re-run interactively or with --yes")
            return
        if ask("Run `docker compose up -d --build` on this machine now? [y/N] ").strip().lower() != "y":
            rep.add("SKIP", "deploy", "declined")
            return
    r = run(["docker", "compose", "up", "-d", "--build"], capture_output=True, text=True)
    rep.add("OK" if r.returncode == 0 else "FAIL", "deploy (docker compose)", "started" if r.returncode == 0 else f"failed: {(r.stderr or '')[-200:]}")


def run_setup(opts: SetupOptions, *, env_path: Path | None = None,
              load: Callable[[], Settings] | None = None,
              session_factory: sessionmaker[Session] | None = None,
              ig_client: Any = None, http: httpx.Client | None = None,
              prompt: Callable[[str], str] = input, secret_prompt: Callable[[str], str] = getpass.getpass) -> Report:
    env_path = env_path or Path(".env")
    load = load or (lambda: Settings(_env_file=str(env_path)))
    rep = Report()
    nxt: str | None = None

    def block(action: str | None) -> None:
        nonlocal nxt
        nxt = nxt or action

    st = load()
    state = StateFile(st.data_dir / "setup_state.json")
    if opts.mutate and state.interrupted:
        rep.add("INFO", "resume", f"previous setup was interrupted at phase '{state.data.get('phase')}'; continuing")
    if opts.mutate:
        state.mark("in_progress", "start")

    block(check_python(rep))
    block(check_ffmpeg(rep))
    block(check_fonts(rep))
    host = detect_hosting(rep)

    # data dir
    if opts.mutate:
        try:
            st.data_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    writable = st.data_dir.is_dir() and os.access(st.data_dir, os.W_OK)
    rep.add("OK" if writable else ("INFO" if not opts.mutate else "FAIL"), "persistent data directory",
            f"{st.data_dir} writable" if writable else f"{st.data_dir} missing/not writable" + ("" if opts.mutate else " (setup will create it)"))
    if not writable and opts.mutate:
        block(f"Make {st.data_dir} writable (RS_DATA_DIR).")

    # secrets (only fill what is missing; never overwrite)
    if opts.mutate:
        state.mark("in_progress", "secrets")
        updates: dict[str, str] = {}
        if not st.secret_key:
            updates["RS_SECRET_KEY"] = gen_fernet_key()
        if not st.dashboard_token:
            updates["RS_DASHBOARD_TOKEN"] = gen_token()
        if opts.interactive and not st.meta_app_id:
            v = prompt("Instagram app ID (Meta dashboard → Instagram → API setup with Instagram login): ").strip()
            if SAFE_VALUE.match(v):
                updates["RS_META_APP_ID"] = v
        if opts.interactive and not st.meta_app_secret:
            v = secret_prompt("Instagram app secret (hidden): ").strip()
            if SAFE_VALUE.match(v):
                updates["RS_META_APP_SECRET"] = v
        if updates:
            if in_container():
                rep.add("FAIL", "secrets", f"missing {sorted(updates)} inside a container; set them in the host .env and `docker compose up -d`")
                block("Add the missing values to .env on the host, then `docker compose up -d`.")
            else:
                written = update_env_file(env_path, updates)
                rep.add("OK", "secrets written to .env (chmod 600, values not shown)", ", ".join(written))
                get_settings.cache_clear()
                st = load()

    # config validity (also checks redirect URI/public URL shape)
    cfg_action = doctor.check_config(st, rep)
    if cfg_action and "gen-keys" in cfg_action and not (st.secret_key and st.dashboard_token):
        cfg_action = "Run `reelstudio setup` (it generates RS_SECRET_KEY and RS_DASHBOARD_TOKEN for you, never printing them)."
    elif cfg_action and "Instagram app ID" in cfg_action:
        cfg_action = ("Run `reelstudio setup` in a terminal: it asks (hidden) for the Instagram app ID and secret from Meta dashboard → "
                      "GenZ Reel Studio → Instagram → API setup with Instagram login. Never paste them into chat.")
    block(cfg_action)

    # database
    state.mark("in_progress", "database") if opts.mutate else None
    block(check_database(st, rep, opts.mutate))
    db_ok = any(n == "database" and s == "OK" for s, n, _ in rep.checks)

    if opts.mutate and opts.deploy:
        deploy_compose(rep, opts, ask=prompt)

    # hosting reachability
    host_ok = False
    if st.public_base_url.startswith("https://"):
        if opts.live:
            hint = doctor.check_public_host(st, rep, http)
            if hint is None:
                check_media_route(st, rep, http)
                host_ok = all(s != "FAIL" for s, n, _ in rep.checks if n.startswith("public"))
            block(hint)
        else:
            rep.add("SKIP", "public host reachability", "offline mode")
    else:
        block(HOSTING_ACTION)
        rep.add("FAIL", "public HTTPS host", "RS_PUBLIC_BASE_URL not set to an https:// URL; Instagram needs it for login and video download")

    # instagram account
    connected_ok = False
    if db_ok and st.secret_key and st.meta_app_id and st.meta_app_secret and (host_ok or not opts.live):
        state.mark("in_progress", "instagram") if opts.mutate else None
        from .instagram.client import IGClient
        client = ig_client or IGClient(st.meta_app_id, st.meta_app_secret, st.meta_redirect_uri, st.graph_version)
        sess_iter = _sessions(st, session_factory)
        s = next(sess_iter)
        try:
            res = doctor.check_accounts(st, rep, s, client, opts.live)
            if res == "CONNECT":
                from .api.app import make_state
                get_settings.cache_clear()
                url = client.authorize_url(make_state())
                rep.add("INFO", "Connect URL (valid 10 min; contains no secrets)", url)
                connect_action = ("Open the Connect URL in your browser, log in to Instagram as your Creator account and approve the "
                                  "permissions yourself; then re-run `reelstudio setup`.")
                if opts.mutate and opts.interactive and opts.open_browser:
                    try:
                        webbrowser.open(url)
                    except Exception:  # noqa: BLE001
                        pass
                if opts.mutate and opts.wait_seconds:
                    from .db import IGAccount
                    deadline = time.time() + opts.wait_seconds
                    while time.time() < deadline:
                        s.expire_all()
                        s.commit()
                        if s.scalar(select(IGAccount).where(IGAccount.token_encrypted != "")):
                            break
                        time.sleep(3)
                    rep.checks[:] = [c for c in rep.checks if not c[1].startswith("@") and c[1] not in ("Instagram account", "Connect URL (valid 10 min; contains no secrets)")]
                    rep.accounts.clear()
                    res = doctor.check_accounts(st, rep, s, client, opts.live)
                    if res == "CONNECT":
                        block(connect_action)
                else:
                    block(connect_action)
            connected_ok = res != "CONNECT"
            if connected_ok:
                enabled = any(a["publishing_enabled"] and a["destination_confirmed"] for a in rep.accounts)
                if not enabled:
                    rep.add("FAIL", "publishing enabled", "OFF (you must enable it yourself)")
                    block("Dashboard → Account & tokens → type your @username → Enable publishing. (Every post will still need your approval.)")
                else:
                    rep.add("OK", "publishing enabled", "ON — every post still requires your explicit approval")
            from .db import PublishJob
            n = s.query(PublishJob).filter(PublishJob.status == "published", PublishJob.ig_media_id != "").count()
            rep.add("OK" if n else "INFO", "publishing verified end-to-end", f"{n} post(s) published via the official API" if n else "no post published via the API yet (needs your first approved post)")
        finally:
            try:
                next(sess_iter)
            except StopIteration:
                pass

    all_good = not any(s == "FAIL" for s, _, _ in rep.checks)
    block(worker_status(rep, all_good and connected_ok and opts.live))
    all_good = not any(s == "FAIL" for s, _, _ in rep.checks)
    rep.next_action = "READY" if all_good else (nxt or "Resolve the FAIL items above.")
    if opts.mutate:
        state.mark("complete" if all_good else "blocked", "end")
    return rep


def render(rep: Report) -> str:
    out = doctor.render(rep).rsplit("\n\nNEXT:", 1)[0]
    ready = rep.next_action == "READY"
    out += f"\n\nSTATUS: {'READY' if ready else 'BLOCKED'}"
    if not ready:
        out += f"\nNEXT: {rep.next_action}"
    pv = next((d for s, n, d in rep.checks if n == "publishing verified end-to-end"), "")
    out += f"\nPUBLISHING VERIFIED: {'yes' if pv.startswith('1') or (pv and pv[0].isdigit() and pv[0] != '0') else 'no'}"
    return out


def to_json(rep: Report) -> str:
    ready = rep.next_action == "READY"
    return json.dumps({"status": "READY" if ready else "BLOCKED", "next_action": None if ready else rep.next_action,
                       "checks": [{"status": s, "name": n, "detail": d if "Connect URL" not in n else "<omitted>"} for s, n, d in rep.checks]}, indent=2)
