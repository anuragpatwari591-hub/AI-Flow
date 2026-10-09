"""Approval queue, publishing scheduler, retry handling, duplicate prevention and audit trail.

Status machine (every transition is audited):
  pending_approval -> scheduled -> publishing -> published
  pending_approval|scheduled -> cancelled | rejected ; publishing -> scheduled (retry) | failed
Nothing reaches `publishing` without an approval record (human, or the explicit auto-publish policy).
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..audio.rights import clearance
from ..config import load_yaml
from ..db import Concept, IGAccount, PublishJob, Reel, audit, get_setting, set_setting, utcnow
from ..instagram.accounts import AccountError, get_token, refresh_if_needed, token_status
from ..instagram.client import IGApiError, IGClient
from ..instagram.secrets import TokenCipher
from .media import file_sha256, public_url

log = logging.getLogger(__name__)
TERMINAL = {"published", "failed", "cancelled", "rejected"}
ALLOWED = {
    "pending_approval": {"scheduled", "rejected", "cancelled"},
    "scheduled": {"publishing", "cancelled", "pending_approval"},
    "publishing": {"published", "scheduled", "failed"},
}


class QueueError(Exception):
    pass


def automation(s: Session) -> dict[str, Any]:
    base = load_yaml("automation.yaml")
    stored = get_setting(s, "automation")
    for k, v in stored.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def set_paused(s: Session, paused: bool, actor: str) -> None:
    cfg = get_setting(s, "automation")
    cfg["paused"] = paused
    set_setting(s, "automation", cfg, actor)


def transition(s: Session, job: PublishJob, new: str, actor: str = "system", **detail: Any) -> None:
    if new not in ALLOWED.get(job.status, set()):
        raise QueueError(f"illegal transition {job.status} -> {new}")
    old, job.status = job.status, new
    audit(s, f"job.{new}", "job", job.id, actor, from_status=old, **detail)
    if new == "failed":
        from ..alerts import notify
        notify("error", f"publish job {job.id} failed: {job.last_error}", job_id=job.id)


# ------------------------------------------------------------------ preflight
def preflight(s: Session, job: PublishJob, cipher: TokenCipher | None = None, *, for_publish: bool = False) -> list[str]:
    """Return a list of blocking problems (empty == OK)."""
    cfg = automation(s)
    reel, acct = job.reel, job.account
    problems: list[str] = []
    # media format
    if reel.render_status != "rendered" or not reel.video_path:
        problems.append("reel is not fully rendered")
    else:
        qa = reel.qa.get("video", {})
        if not qa.get("passed"):
            problems.append("media QA did not pass")
        p = Path(reel.video_path)
        if not p.exists():
            problems.append("video file missing on disk")
        elif file_sha256(p) != reel.video_sha256:
            problems.append("video file changed after rendering (hash mismatch); re-render and re-approve")
        if not (reel.cover_path and Path(reel.cover_path).exists()):
            problems.append("cover image missing")
    # caption
    cap = reel.caption or ""
    if not cap.strip():
        problems.append("caption is empty")
    if len(cap) > cfg["publishing"]["max_caption_chars"]:
        problems.append("caption exceeds Instagram's length limit")
    if len(re.findall(r"#\w+", cap)) > cfg["publishing"]["max_hashtags"]:
        problems.append("too many hashtags")
    for pat in cfg["caption_blocklist_patterns"]:
        if re.search(pat, cap, re.I):
            problems.append(f"caption matches private-info/risk pattern: {pat}")
    # audio rights
    audio = reel.audio
    ok, why = clearance(audio, "publish")
    if not ok:
        problems += [f"audio: {w}" for w in why]
    if reel.needs_native_audio and not job.approved_at:
        pass  # surfaced at approval via explicit acknowledgement
    # destination
    if acct.revoked_at or not acct.token_encrypted:
        problems.append("account access revoked")
    if not (acct.publishing_enabled and acct.is_destination):
        problems.append("publishing is not enabled/confirmed for this destination account")
    elif token_status(acct)["state"] in ("expired", "revoked"):
        problems.append("access token expired: reconnect the account")
    if for_publish:
        if job.approved_at is None or not job.approved_by:
            problems.append("no approval record")
        if automation(s).get("paused"):
            problems.append("scheduler is paused")
    return problems


# ------------------------------------------------------------------ submit / approve
def idem_key(reel: Reel, account_id: int) -> str:
    return hashlib.sha256(f"{account_id}|{reel.video_sha256 or reel.id}".encode()).hexdigest()[:40]


def submit_for_approval(s: Session, reel_id: int, account_id: int, actor: str = "system") -> PublishJob:
    reel, acct = s.get(Reel, reel_id), s.get(IGAccount, account_id)
    if reel is None or acct is None:
        raise QueueError("unknown reel or account")
    if reel.purpose != "organic":
        raise QueueError("ad creatives never enter the organic publishing queue")
    key = idem_key(reel, account_id)
    existing = s.scalar(select(PublishJob).where(PublishJob.idempotency_key == key))
    if existing and existing.status not in ("cancelled", "rejected", "failed"):
        raise QueueError(f"duplicate: job {existing.id} already exists for this media/account ({existing.status})")
    if existing:  # allow resubmission after a terminal negative state by freeing the key
        existing.idempotency_key = f"{key}:old{existing.id}"
        s.flush()
    job = PublishJob(reel_id=reel_id, account_id=account_id, status="pending_approval", idempotency_key=key)
    s.add(job)
    s.flush()
    audit(s, "job.created", "job", job.id, actor, reel_id=reel_id, account_id=account_id)
    return job


def approve(s: Session, job_id: int, actor: str, scheduled_for: datetime | None = None, *,
            acknowledge_no_native_audio: bool = False, cipher: TokenCipher | None = None) -> PublishJob:
    job = s.get(PublishJob, job_id)
    if job is None:
        raise QueueError("unknown job")
    if not actor or actor in ("system", "auto_policy"):
        raise QueueError("human approval requires a named approver")
    if job.status != "pending_approval":
        raise QueueError(f"job is {job.status}, not pending approval")
    if job.reel.needs_native_audio and not acknowledge_no_native_audio:
        raise QueueError("this reel was rendered WITHOUT its Instagram-native track (manual step). "
                         "Approve with acknowledge_no_native_audio=True to publish silent, or use the manual publishing package.")
    problems = preflight(s, job, cipher)
    if problems:
        raise QueueError("preflight failed: " + "; ".join(problems))
    job.approved_by, job.approved_at = actor, utcnow()
    job.scheduled_for = scheduled_for or utcnow()
    transition(s, job, "scheduled", actor, scheduled_for=job.scheduled_for.isoformat(), approval="human")
    return job


def reject(s: Session, job_id: int, actor: str, reason: str = "") -> PublishJob:
    job = s.get(PublishJob, job_id)
    transition(s, job, "rejected", actor, reason=reason)
    return job


def cancel(s: Session, job_id: int, actor: str, reason: str = "") -> PublishJob:
    job = s.get(PublishJob, job_id)
    if job is None:
        raise QueueError("unknown job")
    if job.status in TERMINAL:
        raise QueueError(f"job already {job.status}")
    if job.status == "publishing":
        raise QueueError("job is mid-publish; wait for it to finish or fail")
    transition(s, job, "cancelled", actor, reason=reason)
    return job


def maybe_auto_approve(s: Session, job: PublishJob) -> bool:
    """Auto-publish is off by default. It needs: enabled, a tested history, per-day limit, allowed category,
    min score, clean preflight, and no native-audio manual step."""
    cfg = automation(s)
    ap = cfg["auto_publish"]
    if cfg["mode"] != "auto_publish_limited" or not ap["enabled"] or cfg.get("paused"):
        return False
    concept: Concept = job.reel.concept
    human_ok = s.query(PublishJob).filter(PublishJob.status == "published", PublishJob.approved_by.notin_(["auto_policy", "system"])).count()
    if human_ok < ap["min_human_approved_publishes"]:
        return False
    if concept.category not in ap["allowed_categories"] or concept.score < ap["min_concept_score"] or job.reel.needs_native_audio:
        return False
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    if s.query(PublishJob).filter(PublishJob.approved_by == "auto_policy", PublishJob.approved_at >= day_start).count() >= ap["max_per_day"]:
        return False
    if preflight(s, job):
        return False
    job.approved_by, job.approved_at, job.scheduled_for = "auto_policy", utcnow(), utcnow()
    transition(s, job, "scheduled", "auto_policy", approval="auto_policy", policy=ap)
    return True


def enable_auto_publish(s: Session, actor: str, *, allowed_categories: list[str], max_per_day: int = 1,
                        min_concept_score: float = 0.7) -> None:
    cfg = automation(s)
    need = cfg["auto_publish"]["min_human_approved_publishes"]
    have = s.query(PublishJob).filter(PublishJob.status == "published", PublishJob.approved_by.notin_(["auto_policy", "system"])).count()
    if have < need:
        raise QueueError(f"auto-publishing needs {need} successful human-approved publishes first (have {have})")
    stored = get_setting(s, "automation")
    stored.update({"mode": "auto_publish_limited", "auto_publish": {
        "enabled": True, "allowed_categories": allowed_categories, "max_per_day": max_per_day,
        "min_concept_score": min_concept_score}})
    set_setting(s, "automation", stored, actor)


# ------------------------------------------------------------------ scheduler
def _backoff(cfg: dict[str, Any], attempts: int, rate_limited: bool) -> timedelta:
    p = cfg["publishing"]
    return timedelta(seconds=p["rate_limit_backoff_seconds"] if rate_limited else p["backoff_base_seconds"] * 2 ** max(attempts - 1, 0))


def _fail_or_retry(s: Session, job: PublishJob, e: IGApiError | Exception, cfg: dict[str, Any]) -> None:
    kind = e.kind if isinstance(e, IGApiError) else "permanent"
    job.last_error = str(e)[:500]
    if kind in ("transient", "rate_limited") and job.attempts < cfg["publishing"]["max_attempts"]:
        job.next_attempt_at = utcnow() + _backoff(cfg, job.attempts, kind == "rate_limited")
        transition(s, job, "scheduled", "scheduler", retry=True, kind=kind, error=job.last_error,
                   next_attempt_at=job.next_attempt_at.isoformat())
    else:
        transition(s, job, "failed", "scheduler", kind=kind, error=job.last_error)


def publish_job(s: Session, job: PublishJob, client: IGClient, cipher: TokenCipher,
                sleep: Callable[[float], None] = time.sleep) -> None:
    cfg = automation(s)
    acct, reel = job.account, job.reel
    problems = preflight(s, job, cipher, for_publish=True)
    if problems:
        job.last_error = "; ".join(problems)
        transition(s, job, "failed", "scheduler", preflight=problems)
        return
    try:
        refresh_if_needed(s, client, cipher, acct)
        token = get_token(acct, cipher)
        if not job.container_id:  # reuse container on retry: prevents duplicate uploads
            job.container_id = client.create_reel_container(
                acct.ig_user_id, token, video_url=public_url(reel.id, "video", reel.video_sha256),
                caption=reel.caption, cover_url=public_url(reel.id, "cover", reel.video_sha256))
            audit(s, "ig.container_created", "job", job.id, container_id=job.container_id)
        status = "IN_PROGRESS"
        for _ in range(cfg["publishing"]["container_poll_attempts"]):
            st = client.container_status(job.container_id, token)
            status = st.get("status_code", "")
            if status in ("FINISHED", "ERROR", "EXPIRED"):
                break
            sleep(cfg["publishing"]["container_poll_interval_seconds"])
        if status == "ERROR" or status == "EXPIRED":
            job.container_id = ""  # a failed container can't be reused
            raise IGApiError(f"container {status}: {st.get('status')}", status=400, code=-1)
        if status != "FINISHED":
            raise IGApiError("container still processing", status=0)  # transient -> retry later with same container
        job.ig_media_id = client.publish_container(acct.ig_user_id, token, job.container_id)
        try:
            job.permalink = client.media_info(job.ig_media_id, token).get("permalink", "")
        except IGApiError:
            pass
        job.published_at = utcnow()
        transition(s, job, "published", "scheduler", media_id=job.ig_media_id, permalink=job.permalink)
    except (IGApiError, AccountError) as e:
        if isinstance(e, IGApiError) and e.kind == "token":
            audit(s, "ig.token_invalid", "account", acct.id, error=str(e))
        _fail_or_retry(s, job, e, cfg)
    except ValueError as e:  # e.g. missing public base URL
        _fail_or_retry(s, job, e, cfg)


def run_due(s: Session, client: IGClient, cipher: TokenCipher, now: datetime | None = None,
            sleep: Callable[[float], None] = time.sleep) -> list[int]:
    """Process due jobs. Safe to call concurrently: each job is claimed with an atomic UPDATE."""
    now = now or utcnow()
    if automation(s).get("paused"):
        return []
    due = list(s.scalars(select(PublishJob).where(
        PublishJob.status == "scheduled", PublishJob.scheduled_for <= now).order_by(PublishJob.scheduled_for)))
    done: list[int] = []
    for job in due:
        if job.next_attempt_at and job.next_attempt_at > now:
            continue
        claimed = s.execute(update(PublishJob).where(PublishJob.id == job.id, PublishJob.status == "scheduled")
                            .values(status="publishing", attempts=PublishJob.attempts + 1)).rowcount
        if not claimed:
            continue
        s.refresh(job)
        audit(s, "job.publishing", "job", job.id, "scheduler", attempt=job.attempts)
        s.commit()
        publish_job(s, job, client, cipher, sleep)
        s.commit()
        done.append(job.id)
    return done


def mark_manually_published(s: Session, job_id: int, actor: str, permalink: str) -> PublishJob:
    """Manual path for steps the official API cannot do (e.g. native trending audio)."""
    if not permalink.startswith(("https://www.instagram.com/", "https://instagram.com/")):
        raise QueueError("permalink must be an https://www.instagram.com/ URL")
    job = s.get(PublishJob, job_id)
    if job.status not in ("scheduled", "pending_approval"):
        raise QueueError(f"job is {job.status}")
    job.approved_by = job.approved_by or actor
    job.approved_at = job.approved_at or utcnow()
    if job.status == "pending_approval":
        transition(s, job, "scheduled", actor, approval="manual_path")
    transition(s, job, "publishing", actor, manual=True)
    job.permalink, job.published_at = permalink, utcnow()
    transition(s, job, "published", actor, manual=True, permalink=permalink)
    return job


def manual_package(s: Session, job_id: int, dest: Path) -> Path:
    """Export video/cover/caption + exact manual steps for the owner to post in the Instagram app."""
    import shutil
    job = s.get(PublishJob, job_id)
    reel = job.reel
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(reel.video_path, dest / "reel.mp4")
    shutil.copy(reel.cover_path, dest / "cover.jpg")
    (dest / "caption.txt").write_text(reel.caption, encoding="utf-8")
    steps = ["1. Upload reel.mp4 as a Reel in the Instagram app.", "2. Set cover.jpg as the cover.",
             "3. Paste caption.txt."]
    if reel.needs_native_audio:
        steps.append(f"4. Add native audio in-app. Suggested mood: {reel.concept.audio_mood}. Check it's available for your account/region.")
    (dest / "MANUAL_STEPS.txt").write_text("\n".join(steps), encoding="utf-8")
    audit(s, "job.manual_package", "job", job.id)
    return dest
