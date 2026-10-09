"""`reelstudio doctor`: read-only readiness report. Never prints secret values; never publishes or mutates anything
except (optionally) nothing at all. Prints exactly one NEXT action."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Settings
from .instagram.client import REQUIRED_SCOPES, IGApiError, IGClient
from .instagram.secrets import SecretsError

CALLBACK_PATH = "/api/instagram/callback"
HOSTING_ACTION = ("Get a small Ubuntu server with a free DuckDNS name pointing at it, then run `bash deploy/setup-vps.sh` on it "
                  "(docs/DEPLOYMENT.md). `reelstudio setup` never signs you up for hosting or spends money.")


@dataclass
class Report:
    checks: list[tuple[str, str, str]] = field(default_factory=list)  # (status, name, detail)
    next_action: str = ""
    accounts: list[dict[str, Any]] = field(default_factory=list)

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.checks.append((status, name, detail))

    @property
    def blocked(self) -> bool:
        return any(s == "FAIL" for s, _, _ in self.checks)


def _set(v: str) -> str:
    return "SET" if v else "MISSING"


def check_config(st: Settings, rep: Report) -> str | None:
    """Returns the first config problem as a next action (or None)."""
    nxt: str | None = None
    cfg_ok = (st.config_dir / "trends.yaml").exists()
    rep.add("OK" if cfg_ok else "FAIL", "config directory", "found" if cfg_ok else f"{st.config_dir} has no trends.yaml (set RS_CONFIG_DIR / use an editable install)")
    if not cfg_ok:
        nxt = "Fix the config directory: set RS_CONFIG_DIR to the project's config/ folder."
    for name, val in (("RS_SECRET_KEY", st.secret_key), ("RS_DASHBOARD_TOKEN", st.dashboard_token),
                      ("RS_META_APP_ID", st.meta_app_id), ("RS_META_APP_SECRET", st.meta_app_secret),
                      ("RS_META_REDIRECT_URI", st.meta_redirect_uri), ("RS_PUBLIC_BASE_URL", st.public_base_url)):
        rep.add("OK" if val else "FAIL", name, _set(val))
    if st.secret_key:
        try:
            from .instagram.secrets import TokenCipher
            TokenCipher(st.secret_key)
        except Exception:  # noqa: BLE001
            rep.add("FAIL", "RS_SECRET_KEY format", "not a valid Fernet key (regenerate with `reelstudio gen-keys`)")
            nxt = nxt or "Run `reelstudio gen-keys` and put the new RS_SECRET_KEY line in .env."
    if st.dashboard_token and len(st.dashboard_token) < 24:
        rep.add("FAIL", "RS_DASHBOARD_TOKEN strength", "shorter than 24 characters; regenerate with `reelstudio gen-keys`")
        nxt = nxt or "Run `reelstudio gen-keys` and put the new RS_DASHBOARD_TOKEN line in .env."
    if not (st.secret_key and st.dashboard_token):
        nxt = nxt or "Run `reelstudio gen-keys` and put both printed lines into reelstudio/.env."
    if not (st.meta_app_id and st.meta_app_secret):
        nxt = nxt or ("In Meta dashboard → GenZ Reel Studio → Instagram → API setup with Instagram login, copy the "
                      "Instagram app ID and secret into .env as RS_META_APP_ID / RS_META_APP_SECRET (edit the file; never paste them in chat).")
    if not re.fullmatch(r"v\d+\.\d+", st.graph_version or ""):
        rep.add("FAIL", "RS_GRAPH_VERSION", f"'{st.graph_version}' is not like v23.0")
    else:
        rep.add("WARN", "RS_GRAPH_VERSION", f"{st.graph_version} (confirm it is a currently supported version in Meta's docs)")
    pb, ru = urlparse(st.public_base_url), urlparse(st.meta_redirect_uri)
    if st.public_base_url:
        ok = pb.scheme == "https" and bool(pb.netloc) and not pb.path.strip("/") and pb.hostname not in ("localhost", "127.0.0.1")
        rep.add("OK" if ok else "FAIL", "RS_PUBLIC_BASE_URL form", "public https origin, no path" if ok else "must be a public https:// origin (no path, not localhost)")
        if not ok:
            nxt = nxt or HOSTING_ACTION
    if st.meta_redirect_uri:
        problems = []
        if ru.scheme != "https":
            problems.append("must be https")
        if ru.path != CALLBACK_PATH:
            problems.append(f"path must be exactly {CALLBACK_PATH}")
        if ru.query or ru.fragment:
            problems.append("no query/fragment")
        if st.public_base_url and (ru.scheme, ru.netloc) != (pb.scheme, pb.netloc):
            problems.append("host differs from RS_PUBLIC_BASE_URL")
        rep.add("FAIL" if problems else "OK", "RS_META_REDIRECT_URI", "; ".join(problems) or f"https, path {CALLBACK_PATH}, same host as public URL")
        if problems:
            nxt = nxt or f"Set RS_META_REDIRECT_URI to <your public https origin>{CALLBACK_PATH} and make the identical URL the OAuth redirect URI in Meta."
    elif st.public_base_url:
        nxt = nxt or f"Set RS_META_REDIRECT_URI={st.public_base_url.rstrip('/')}{CALLBACK_PATH} and register that identical URL in Meta."
    if not (st.public_base_url and st.meta_redirect_uri):
        nxt = nxt or HOSTING_ACTION
    return nxt


def check_public_host(st: Settings, rep: Report, http: httpx.Client | None = None) -> str | None:
    if not st.public_base_url:
        return None
    http = http or httpx.Client(timeout=10)
    try:
        r = http.get(st.public_base_url.rstrip("/") + "/healthz")
        ok = r.status_code == 200 and r.json().get("ok") is True
        rep.add("OK" if ok else "FAIL", "public host /healthz", f"HTTP {r.status_code}" + (", ffmpeg " + str(r.json().get("ffmpeg")) if ok else ""))
        if ok:
            return None
    except (httpx.HTTPError, ValueError) as e:
        rep.add("FAIL", "public host /healthz", f"unreachable ({type(e).__name__})")
    return "Start `reelstudio serve` and your HTTPS tunnel/host, then confirm RS_PUBLIC_BASE_URL/healthz opens in a browser."


def check_accounts(st: Settings, rep: Report, session: Any, client: IGClient | None, live: bool) -> str | None:
    from sqlalchemy import select

    from .db import IGAccount
    from .instagram.accounts import eligibility, get_token, token_status
    from .instagram.secrets import TokenCipher
    accts = list(session.scalars(select(IGAccount)))
    if not accts:
        rep.add("FAIL", "Instagram account", "none connected")
        return "CONNECT"
    nxt = None
    for a in accts:
        ts = token_status(a)
        scopes = a.scopes or []
        missing = [x for x in REQUIRED_SCOPES if x not in scopes]
        info = {"username": a.username, "type": a.account_type, "token": ts["state"], "days_left": ts.get("days_left"),
                "scopes": scopes, "missing_required": missing if scopes else "unreported",
                "publishing_enabled": a.publishing_enabled, "destination_confirmed": a.is_destination}
        rep.accounts.append(info)
        rep.add("OK" if ts["state"] in ("ok", "expiring_soon") else "FAIL", f"@{a.username} token", f"{ts['state']} ({ts.get('days_left')} days)")
        rep.add("OK" if a.account_type.upper() in ("BUSINESS", "MEDIA_CREATOR", "CREATOR") else "FAIL", f"@{a.username} account type", a.account_type)
        if scopes:
            rep.add("FAIL" if missing else "OK", f"@{a.username} required permissions", f"missing {missing}" if missing else "basic + content_publish granted")
            rep.add("OK" if "instagram_business_manage_insights" in scopes else "WARN", f"@{a.username} insights (optional)", "granted" if "instagram_business_manage_insights" in scopes else "not granted; analytics unavailable")
        else:
            rep.add("WARN", f"@{a.username} permissions", "Meta did not report scopes; will be probed live when enabling publishing")
        if ts["state"] in ("revoked", "expired") or missing:
            nxt = nxt or "CONNECT"
        if live and client and ts["state"] in ("ok", "expiring_soon"):
            try:
                tok = get_token(a, TokenCipher(st.secret_key))
                me = client.me(tok)
                ok, probs = eligibility(me)
                rep.add("OK" if ok else "FAIL", f"@{a.username} live /me", "reachable; eligible" if ok else "; ".join(probs))
                client.publishing_limit(a.ig_user_id, tok)
                rep.add("OK", f"@{a.username} live publishing permission probe", "content_publishing_limit readable (read-only)")
            except IGApiError as e:
                rep.add("FAIL", f"@{a.username} live check", f"{e.kind}: {str(e)[:120]}")
                nxt = nxt or "CONNECT"
            except SecretsError as e:
                rep.add("FAIL", f"@{a.username} stored token", f"{e} (RS_SECRET_KEY changed or token corrupted)")
                nxt = nxt or "CONNECT"
        rep.add("OK" if a.publishing_enabled else "INFO", f"@{a.username} publishing", "ENABLED (every post still needs your approval)" if a.publishing_enabled else "OFF")
    return nxt


def build_report(st: Settings, session: Any = None, *, live: bool = False, client: IGClient | None = None,
                 http: httpx.Client | None = None) -> Report:
    rep = Report()
    nxt = check_config(st, rep)
    if live:
        nxt = nxt or check_public_host(st, rep, http)
    if nxt is None and session is not None:
        client = client or IGClient(st.meta_app_id, st.meta_app_secret, st.meta_redirect_uri, st.graph_version)
        acct_next = check_accounts(st, rep, session, client, live)
        if acct_next == "CONNECT":
            from .api.app import make_state
            url = client.authorize_url(make_state())
            rep.add("INFO", "Connect URL (valid 10 min; contains no secrets)", url)
            nxt = ("Open the Connect URL above in a browser, log in to Instagram as your Creator account yourself, "
                   "and approve the permissions; then re-run `reelstudio doctor --live`.")
        else:
            enabled = any(a["publishing_enabled"] for a in rep.accounts)
            nxt = ("READY: connection verified. Publishing is " + ("ENABLED; every post still requires your approval in the queue."
                   if enabled else "OFF. When you decide to, dashboard → Account & tokens → type @username → Enable publishing."))
    rep.next_action = nxt or "Fix the FAIL items above."
    return rep


def render(rep: Report) -> str:
    lines = [f"[{s:4}] {n}" + (f": {d}" if d else "") for s, n, d in rep.checks]
    lines.append("")
    lines.append("NEXT: " + rep.next_action)
    return "\n".join(lines)
