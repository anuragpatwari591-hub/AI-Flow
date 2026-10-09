"""REST API + dashboard host. Every /api route requires the bearer token; /media uses signed URLs;
the Instagram OAuth callback is protected by a signed, expiring `state`."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, Request, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.orm import Session

from .. import __version__
from ..ads import service as ads
from ..analytics import service as an
from ..analytics.collector import collect_due
from ..audio.library import match_audio, register_audio
from ..config import get_settings, load_yaml
from ..db import (AdCampaign, AuditLog, AudioAsset, Concept, IGAccount, PublishJob, ReferenceItem, Reel, Trend,
                  audit, get_session_factory, session_scope)
from ..instagram.accounts import AccountError, connect_account, enable_publishing, refresh_if_needed, revoke, token_status
from ..instagram.client import IGApiError, IGClient
from ..instagram.secrets import SecretsError, TokenCipher
from ..publishing import queue as q
from ..publishing.media import verify_media
from ..reference.library import UninspectedObservation, add_observation, add_reference, principles_summary
from ..render.fonts import license_table
from ..render.service import AudioRightsError, render_reel
from ..render.spec import list_templates
from ..trends.service import ranked_trends, run_research
from ..trends.sources import ManualFileSource, RssSource, SeasonalCalendarSource
from ..writing.engine import record_published_lines, run_cycle
from ..writing.providers import get_provider

STATIC = Path(__file__).parent / "static"
MAX_UPLOAD = 200 * 1024 * 1024
PERMALINK_PREFIXES = ("https://www.instagram.com/", "https://instagram.com/")


async def read_capped(f: UploadFile) -> bytes:
    data = await f.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file too large")
    return data


def within_data_dir(p: str) -> bool:
    root = get_settings().data_dir.resolve()
    try:
        Path(p).resolve().relative_to(root)
        return True
    except ValueError:
        return False


_FAILS: dict[str, list[float]] = {}


def to_dict(obj: Any, exclude: tuple[str, ...] = ("token_encrypted",)) -> dict[str, Any]:
    out = {}
    for c in sa_inspect(obj).mapper.column_attrs:
        if c.key in exclude:
            continue
        v = getattr(obj, c.key)
        out[c.key] = v.isoformat() if isinstance(v, datetime) else v
    return out


def _state_sign(payload: str) -> str:
    if not get_settings().secret_key:
        raise HTTPException(503, "RS_SECRET_KEY is not set")
    return hmac.new(get_settings().secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_state() -> str:
    p = f"{int(time.time())}.{secrets.token_hex(8)}"
    return f"{p}.{_state_sign(p)}"


def check_state(state: str, max_age: int = 600) -> bool:
    try:
        ts, nonce, sig = state.split(".")
        return hmac.compare_digest(_state_sign(f"{ts}.{nonce}"), sig) and time.time() - int(ts) < max_age
    except ValueError:
        return False


def create_app(ig_client: IGClient | None = None, sync_render: bool = False) -> FastAPI:
    app = FastAPI(title="Reel Studio", version=__version__)
    app.state.sync_render = sync_render
    app.state.ig_client = ig_client

    def client() -> IGClient:
        if app.state.ig_client is None:
            st = get_settings()
            app.state.ig_client = IGClient(st.meta_app_id, st.meta_app_secret, st.meta_redirect_uri, st.graph_version)
        return app.state.ig_client

    def cipher() -> TokenCipher:
        try:
            return TokenCipher()
        except SecretsError as e:
            raise HTTPException(503, str(e))

    def auth(request: Request, authorization: str = Header(default="")) -> str:
        tok = get_settings().dashboard_token
        if not tok:
            raise HTTPException(503, "RS_DASHBOARD_TOKEN is not configured; the API is locked")
        ip = request.client.host if request.client else "?"
        now = time.time()
        recent = [x for x in _FAILS.get(ip, []) if now - x < 60]
        if len(recent) >= 10:
            raise HTTPException(429, "too many failed attempts; wait a minute")
        given = authorization.removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given.encode(), tok.encode()):
            _FAILS[ip] = recent + [now]
            raise HTTPException(401, "invalid token")
        return "owner"

    def db() -> Any:
        s = get_session_factory()()
        try:
            yield s
            s.commit()
        except HTTPException:
            s.rollback()
            raise
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def bad(e: Exception, code: int = 400) -> HTTPException:
        return HTTPException(code, str(e))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # noqa: ANN001
        resp = await call_next(request)
        resp.headers.update({
            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                       "img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            "Cache-Control": "no-store" if request.url.path.startswith("/api") else resp.headers.get("Cache-Control", "no-cache")})
        return resp

    # ------------------------------------------------------------------ public-ish
    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        import shutil
        with session_scope() as s:
            s.execute(select(1))
        return {"ok": True, "ffmpeg": bool(shutil.which("ffmpeg")), "version": __version__}

    @app.get("/media/{reel_id}/{kind}/{sig}")
    def media(reel_id: int, kind: str, sig: str) -> FileResponse:
        with session_scope() as s:
            reel = s.get(Reel, reel_id)
            if reel is None or kind not in ("video", "cover", "preview"):
                raise HTTPException(404)
            sha = reel.video_sha256 or "preview"
            try:
                good = verify_media(reel_id, kind, sha, sig)
            except SecretsError as e:
                raise HTTPException(503, str(e))
            if not good:
                raise HTTPException(403, "bad signature")
            path = {"video": reel.video_path, "cover": reel.cover_path, "preview": reel.preview_path}[kind]
        if not path or not Path(path).exists():
            raise HTTPException(404)
        return FileResponse(path, media_type="video/mp4" if kind != "cover" else "image/jpeg")

    @app.get("/api/instagram/callback", response_class=HTMLResponse)
    def ig_callback(code: str = "", state: str = "", error: str = "", s: Session = Depends(db)) -> str:
        if error or not code:
            return f"<h3>Instagram authorisation was not completed ({error or 'no code'}).</h3>"
        if not check_state(state):
            raise HTTPException(400, "invalid or expired state")
        try:
            acct = connect_account(s, client(), cipher(), code.removesuffix("#_"))
        except (IGApiError, SecretsError) as e:
            raise HTTPException(400, f"connection failed: {e}")
        return f"<h3>Connected @{acct.username}. Publishing stays OFF until you enable it in the dashboard.</h3><a href='/'>Back</a>"

    @app.get("/api/setup/status")
    def setup_status(live: bool = False, _: str = Depends(auth)) -> dict[str, Any]:
        """Same engine as `reelstudio setup --check` (read-only). Never includes secrets or the Connect URL."""
        from ..setup import run_setup, SetupOptions, to_json
        rep = run_setup(SetupOptions(mutate=False, live=live), load=get_settings, session_factory=get_session_factory(),
                        ig_client=app.state.ig_client)
        return json.loads(to_json(rep))

    # ------------------------------------------------------------------ overview
    @app.get("/api/overview")
    def overview(_: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        cfg = q.automation(s)
        counts = {st: s.query(PublishJob).filter(PublishJob.status == st).count()
                  for st in ("pending_approval", "scheduled", "publishing", "published", "failed")}
        return {"paused": cfg["paused"], "mode": cfg["mode"], "jobs": counts, "trends": s.query(Trend).count(),
                "concepts": s.query(Concept).count(), "reels": s.query(Reel).count(),
                "accounts": [{"id": a.id, "username": a.username, "token": token_status(a), "publishing_enabled": a.publishing_enabled}
                             for a in s.scalars(select(IGAccount))]}

    # ------------------------------------------------------------------ trends / references
    @app.get("/api/trends")
    def trends(kind: str | None = None, limit: int = 50, _: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        return [to_dict(t) for t in ranked_trends(s, limit, kind)]

    @app.post("/api/trends/run")
    def trends_run(_: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        cfg = load_yaml("trends.yaml")
        sources: list[Any] = [SeasonalCalendarSource(cfg.get("seasonal", []))]
        sources += [RssSource(f["name"], f["url"]) for f in cfg.get("rss_feeds", [])]
        imp = get_settings().data_dir / "trend_imports"
        sources += [ManualFileSource(p, p.stem) for p in sorted(imp.glob("*.json")) + sorted(imp.glob("*.csv"))] if imp.exists() else []
        return run_research(s, sources, cfg)

    @app.post("/api/trends/import")
    async def trends_import(file: UploadFile = File(...), _: str = Depends(auth)) -> dict[str, str]:
        d = get_settings().data_dir / "trend_imports"
        d.mkdir(parents=True, exist_ok=True)
        name = Path(file.filename or "import.json").name
        if Path(name).suffix not in (".json", ".csv"):
            raise HTTPException(400, "only .json or .csv exports")
        (d / name).write_bytes(await read_capped(file))
        return {"saved": name, "next": "POST /api/trends/run"}

    @app.get("/api/references")
    def refs(_: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        return {"items": [to_dict(r) for r in s.scalars(select(ReferenceItem))], "summary": principles_summary(s)}

    @app.post("/api/references")
    async def refs_add(account: str = Form(""), source_url: str = Form(""), notes: str = Form(""),
                       file: UploadFile | None = File(None), _: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        path = None
        if file and file.filename:
            d = get_settings().data_dir / "references"
            d.mkdir(parents=True, exist_ok=True)
            path = d / Path(file.filename).name
            path.write_bytes(await read_capped(file))
        return to_dict(add_reference(s, account=account, source_url=source_url, local_file=str(path) if path else None, notes=notes))

    @app.post("/api/references/{rid}/observations")
    def refs_obs(rid: int, body: dict[str, Any] = Body(...), _: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        try:
            return to_dict(add_observation(s, rid, body["text"], inspected=bool(body.get("inspected")), evidence=body.get("evidence", "")))
        except UninspectedObservation as e:
            raise bad(e, 422)

    # ------------------------------------------------------------------ concepts
    @app.get("/api/concepts")
    def concepts(cycle: str | None = None, _: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        qy = select(Concept).order_by(Concept.id.desc()).limit(100)
        if cycle:
            qy = qy.where(Concept.cycle_id == cycle)
        return [to_dict(c) for c in s.scalars(qy)]

    @app.post("/api/concepts/generate")
    def concepts_generate(body: dict[str, Any] = Body(default={}), _: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        voice = load_yaml("voice_guide.yaml")
        kw: dict[str, Any] = {"per_category": int(body.get("per_category", 2))}
        if body.get("categories"):
            kw["categories"] = body["categories"]
        if body.get("adaptive"):
            plan = an.adaptive_plan(s, list(voice["categories"]), int(body.get("total", 6)))
            kw.update(allocation=plan["allocation"], account_insights=plan["account_insights"], own_history_n=plan["own_history_n"])
        try:
            return [to_dict(c) for c in run_cycle(s, get_provider(get_settings()), **kw)]
        except RuntimeError as e:
            raise bad(e, 503)

    @app.post("/api/concepts/{cid}/status")
    def concept_status(cid: int, body: dict[str, Any] = Body(...), _: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        c = s.get(Concept, cid)
        if not c or body.get("status") not in ("candidate", "selected", "rejected"):
            raise HTTPException(400, "bad concept/status")
        c.status = body["status"]
        audit(s, "concept.status", "concept", cid, "owner", status=c.status)
        return to_dict(c)

    # ------------------------------------------------------------------ reels / audio
    def _render_bg(concept_id: int, kwargs: dict[str, Any]) -> None:
        with session_scope() as s:
            try:
                render_reel(s, concept_id, commit_early=True, **kwargs)
            except AudioRightsError:
                pass  # audited inside render_reel

    @app.post("/api/reels/render", status_code=202)
    def reels_render(body: dict[str, Any] = Body(...), _: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        kw = {k: body[k] for k in ("template", "audio_id", "preview_only", "music_branding", "overrides") if k in body}
        foot = ((kw.get("overrides") or {}).get("background") or {}).get("footage")
        if foot and not within_data_dir(foot):
            raise HTTPException(422, "background footage must live under RS_DATA_DIR")
        if app.state.sync_render:
            try:
                return to_dict(render_reel(s, int(body["concept_id"]), **kw))
            except (AudioRightsError, KeyError) as e:
                raise bad(e, 422)
        threading.Thread(target=_render_bg, args=(int(body["concept_id"]), kw), daemon=True).start()
        return {"accepted": True, "note": "poll GET /api/reels for render_status"}

    @app.get("/api/reels")
    def reels(_: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        out = []
        from ..publishing.media import sign_media
        if not get_settings().secret_key:
            raise HTTPException(503, "RS_SECRET_KEY is not set")
        for r in s.scalars(select(Reel).where(Reel.purpose == "organic").order_by(Reel.id.desc()).limit(100)):
            d = to_dict(r)
            sha = r.video_sha256 or "preview"
            d["preview_url"] = f"/media/{r.id}/preview/{sign_media(r.id, 'preview', sha)}" if r.preview_path else ""
            d["cover_url"] = f"/media/{r.id}/cover/{sign_media(r.id, 'cover', sha)}" if r.cover_path else ""
            d["hook"] = r.concept.hook
            out.append(d)
        return out

    @app.get("/api/templates")
    def templates(_: str = Depends(auth)) -> dict[str, Any]:
        return {"templates": list_templates(), "fonts": license_table()}

    @app.get("/api/audio")
    def audio_list(_: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        return [to_dict(a) for a in s.scalars(select(AudioAsset).order_by(AudioAsset.id.desc()))]

    @app.post("/api/audio")
    def audio_add(body: dict[str, Any] = Body(...), _: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        if body.get("local_file") and not within_data_dir(body["local_file"]):
            raise HTTPException(422, "local_file must live under RS_DATA_DIR (e.g. data/audio/)")
        try:
            return to_dict(register_audio(s, **body))
        except (ValueError, TypeError) as e:
            raise bad(e, 422)

    @app.get("/api/audio/match")
    def audio_match(concept_id: int, purpose: str = "render", _: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        c = s.get(Concept, concept_id)
        if not c:
            raise HTTPException(404)
        return match_audio(s, c, purpose)

    # ------------------------------------------------------------------ queue
    @app.get("/api/jobs")
    def jobs(status: str | None = None, _: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        qy = select(PublishJob).order_by(PublishJob.id.desc()).limit(200)
        if status:
            qy = qy.where(PublishJob.status == status)
        out = []
        for j in s.scalars(qy):
            d = to_dict(j)
            d["hook"], d["category"], d["needs_native_audio"] = j.reel.concept.hook, j.reel.concept.category, j.reel.needs_native_audio
            d["account"] = j.account.username
            d["caption"], d["lines"] = j.reel.caption, [l["text"] for l in j.reel.concept.lines]
            if j.reel.cover_path and get_settings().secret_key:
                from ..publishing.media import sign_media as _sm
                d["cover_url"] = f"/media/{j.reel.id}/cover/{_sm(j.reel.id, 'cover', j.reel.video_sha256 or 'preview')}"
            if j.reel.preview_path and get_settings().secret_key:
                from ..publishing.media import sign_media
                d["preview_url"] = f"/media/{j.reel.id}/preview/{sign_media(j.reel.id, 'preview', j.reel.video_sha256 or 'preview')}"
            d["preflight"] = q.preflight(s, j) if j.status in ("pending_approval", "scheduled") else []
            out.append(d)
        return out

    @app.post("/api/jobs")
    def jobs_create(body: dict[str, Any] = Body(...), _: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        try:
            return to_dict(q.submit_for_approval(s, int(body["reel_id"]), int(body["account_id"]), "owner"))
        except q.QueueError as e:
            raise bad(e, 409)

    def _job_action(fn: Callable[[], PublishJob]) -> dict[str, Any]:
        try:
            return to_dict(fn())
        except q.QueueError as e:
            raise bad(e, 409)

    @app.post("/api/jobs/{jid}/approve")
    def jobs_approve(jid: int, body: dict[str, Any] = Body(default={}), who: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        when = datetime.fromisoformat(body["scheduled_for"]) if body.get("scheduled_for") else None
        return _job_action(lambda: q.approve(s, jid, who, when, acknowledge_no_native_audio=bool(body.get("acknowledge_no_native_audio"))))

    @app.post("/api/jobs/{jid}/reject")
    def jobs_reject(jid: int, body: dict[str, Any] = Body(default={}), who: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        return _job_action(lambda: q.reject(s, jid, who, body.get("reason", "")))

    @app.post("/api/jobs/{jid}/cancel")
    def jobs_cancel(jid: int, body: dict[str, Any] = Body(default={}), who: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        return _job_action(lambda: q.cancel(s, jid, who, body.get("reason", "")))

    @app.post("/api/jobs/{jid}/manual-published")
    def jobs_manual(jid: int, body: dict[str, Any] = Body(...), who: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        if not str(body.get("permalink", "")).startswith(PERMALINK_PREFIXES):
            raise HTTPException(422, "permalink must be an https://www.instagram.com/ URL")
        return _job_action(lambda: q.mark_manually_published(s, jid, who, body["permalink"]))

    @app.get("/api/jobs/{jid}/audit")
    def jobs_audit(jid: int, _: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        return [to_dict(a) for a in s.scalars(select(AuditLog).where(AuditLog.entity == "job", AuditLog.entity_id == jid).order_by(AuditLog.id))]

    @app.get("/api/audit")
    def audit_all(limit: int = Query(200, le=1000), _: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        return [to_dict(a) for a in s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))]

    @app.post("/api/jobs/{jid}/lines-published")
    def jobs_lines(jid: int, _: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        j = s.get(PublishJob, jid)
        if not j or j.status != "published":
            raise HTTPException(409, "job not published")
        record_published_lines(s, j.reel.concept)
        j.reel.concept.status = "published"
        return {"ok": True}

    # ------------------------------------------------------------------ calendar / analytics
    @app.get("/api/calendar")
    def calendar(_: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        out = []
        for j in s.scalars(select(PublishJob).where(PublishJob.status.notin_(["cancelled", "rejected"])).order_by(PublishJob.scheduled_for)):
            out.append({"job_id": j.id, "status": j.status, "scheduled_for": j.scheduled_for.isoformat() if j.scheduled_for else None,
                        "hook": j.reel.concept.hook, "attempts": j.attempts, "last_error": j.last_error,
                        "published_at": j.published_at.isoformat() if j.published_at else None})
        return out

    @app.get("/api/analytics")
    def analytics(_: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        raw = an.reel_rows(s)
        rows = [{**r, "published_at": r["published_at"].isoformat(), "assessment": an.assess(raw, r)} for r in raw]
        dims = ("category", "hook_style", "length", "audio", "template")
        voice = load_yaml("voice_guide.yaml")
        return {"reels": rows,
                "breakdowns": {d: an.breakdown(raw, d) for d in dims},
                "winners": {d: an.declare_winners(raw, d) for d in dims},
                "recommended_mix": an.recommend_mix(raw, list(voice["categories"])),
                "rules": {"min_baseline_reels": an.MIN_BASELINE, "min_group": an.MIN_GROUP, "matched_age_hours": an.TARGET_AGE_H}}

    @app.post("/api/analytics/collect")
    def analytics_collect(_: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        try:
            return {"collected_for_jobs": collect_due(s, client(), cipher())}
        except (IGApiError, AccountError) as e:
            raise bad(e, 502)

    # ------------------------------------------------------------------ accounts
    @app.get("/api/accounts")
    def accounts(_: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        return [{**to_dict(a), "token": token_status(a)} for a in s.scalars(select(IGAccount))]

    @app.get("/api/instagram/connect-url")
    def connect_url(_: str = Depends(auth)) -> dict[str, str]:
        if not get_settings().meta_app_id:
            raise HTTPException(503, "RS_META_APP_ID / RS_META_APP_SECRET / RS_META_REDIRECT_URI not configured")
        return {"url": client().authorize_url(make_state())}

    def _acct(s: Session, aid: int) -> IGAccount:
        a = s.get(IGAccount, aid)
        if not a:
            raise HTTPException(404)
        return a

    @app.post("/api/accounts/{aid}/enable-publishing")
    def acct_enable(aid: int, body: dict[str, Any] = Body(...), who: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        try:
            return to_dict(enable_publishing(s, client(), cipher(), _acct(s, aid), body.get("confirm_username", ""), who))
        except (AccountError, IGApiError) as e:
            raise bad(e, 422)

    @app.post("/api/accounts/{aid}/revoke")
    def acct_revoke(aid: int, who: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        a = _acct(s, aid)
        revoke(s, a, who)
        return to_dict(a)

    @app.post("/api/accounts/{aid}/refresh")
    def acct_refresh(aid: int, _: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        a = _acct(s, aid)
        return {"refreshed": refresh_if_needed(s, client(), cipher(), a), "token": token_status(a)}

    # ------------------------------------------------------------------ automation
    @app.get("/api/automation")
    def automation_get(_: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        return q.automation(s)

    @app.post("/api/automation/pause")
    def automation_pause(body: dict[str, Any] = Body(default={"paused": True}), who: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        q.set_paused(s, bool(body.get("paused", True)), who)
        return q.automation(s)

    @app.post("/api/automation/auto-publish")
    def automation_auto(body: dict[str, Any] = Body(...), who: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        from ..db import get_setting, set_setting
        if not body.get("enabled"):
            cfg = get_setting(s, "automation")
            cfg.update({"mode": "review_required", "auto_publish": {"enabled": False}})
            set_setting(s, "automation", cfg, who)
        else:
            try:
                q.enable_auto_publish(s, who, allowed_categories=body.get("allowed_categories", []),
                                      max_per_day=int(body.get("max_per_day", 1)), min_concept_score=float(body.get("min_concept_score", 0.7)))
            except q.QueueError as e:
                raise bad(e, 409)
        return q.automation(s)

    # ------------------------------------------------------------------ ads (separate router)
    @app.get("/api/ads")
    def ads_list(_: str = Depends(auth), s: Session = Depends(db)) -> list[dict[str, Any]]:
        return [{**to_dict(c), "variants": [to_dict(v) for v in c.variants],
                 "missing_approvals": [i for i in ads.APPROVAL_ITEMS if i not in c.approvals]} for c in s.scalars(select(AdCampaign))]

    @app.post("/api/ads")
    def ads_create(body: dict[str, Any] = Body(...), who: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        return to_dict(ads.create_campaign(s, actor=who, **body))

    @app.post("/api/ads/{cid}/approve/{item}")
    def ads_approve(cid: int, item: str, who: str = Depends(auth), s: Session = Depends(db)) -> dict[str, Any]:
        try:
            return to_dict(ads.approve_item(s, s.get(AdCampaign, cid), item, who))
        except ads.AdsError as e:
            raise bad(e, 422)

    # ------------------------------------------------------------------ dashboard
    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC / "index.html").read_text(encoding="utf-8")

    return app
