from datetime import timedelta

import pytest

from reelstudio.db import AuditLog, PublishJob, utcnow
from reelstudio.instagram.insights import collect_insights
from reelstudio.publishing import queue as q
from reelstudio.publishing.media import public_url, verify_media

nosleep = lambda _s: None  # noqa: E731


def audit_actions(s, job):
    return [a.action for a in s.query(AuditLog).filter_by(entity="job", entity_id=job.id).order_by(AuditLog.id)]


def test_happy_path_requires_human_approval_then_publishes(stack):
    s = stack.s
    job = q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    assert job.status == "pending_approval"
    assert q.run_due(s, stack.client, stack.cipher, sleep=nosleep) == []  # nothing publishes without approval
    q.approve(s, job.id, "yash")
    assert q.run_due(s, stack.client, stack.cipher, sleep=nosleep) == [job.id]
    s.refresh(job)
    assert job.status == "published" and job.ig_media_id == "m1" and "instagram.com" in job.permalink
    call = stack.fake.containers["c1"]
    assert call["media_type"] == "REELS" and call["video_url"].startswith("https://studio.example.test/media/")
    assert audit_actions(s, job) == ["job.created", "job.scheduled", "job.publishing", "media.public_verified", "ig.container_created", "job.published"]


def test_duplicate_submission_blocked_and_resubmit_after_cancel(stack):
    s = stack.s
    j1 = q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    with pytest.raises(q.QueueError, match="duplicate"):
        q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    q.cancel(s, j1.id, "yash")
    assert q.submit_for_approval(s, stack.reel.id, stack.acct.id).id != j1.id


def test_system_cannot_approve_and_unapproved_cannot_publish(stack):
    s = stack.s
    job = q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    with pytest.raises(q.QueueError):
        q.approve(s, job.id, "auto_policy")
    job.status = "scheduled"; job.scheduled_for = utcnow()  # simulate tampering: scheduled without approval
    s.flush()
    q.run_due(s, stack.client, stack.cipher, sleep=nosleep)
    s.refresh(job)
    assert job.status == "failed" and "no approval record" in job.last_error
    assert stack.fake.published == []


def test_pause_blocks_scheduler_and_resume_publishes(stack):
    s = stack.s
    job = q.approve(s, q.submit_for_approval(s, stack.reel.id, stack.acct.id).id, "yash")
    q.set_paused(s, True, "yash")
    assert q.run_due(s, stack.client, stack.cipher, sleep=nosleep) == []
    q.set_paused(s, False, "yash")
    assert q.run_due(s, stack.client, stack.cipher, sleep=nosleep) == [job.id]


def test_future_schedule_waits(stack):
    s = stack.s
    job = q.approve(s, q.submit_for_approval(s, stack.reel.id, stack.acct.id).id, "yash", utcnow() + timedelta(hours=2))
    assert q.run_due(s, stack.client, stack.cipher, sleep=nosleep) == []
    assert q.run_due(s, stack.client, stack.cipher, now=utcnow() + timedelta(hours=3), sleep=nosleep) == [job.id]


def test_transient_failure_retries_with_same_container_no_duplicate(stack):
    s = stack.s
    stack.fake.fail_publish_once = {"code": 2, "msg": "temporary", "status": 500}
    job = q.approve(s, q.submit_for_approval(s, stack.reel.id, stack.acct.id).id, "yash")
    q.run_due(s, stack.client, stack.cipher, sleep=nosleep)
    s.refresh(job)
    assert job.status == "scheduled" and job.attempts == 1 and job.next_attempt_at > utcnow()
    assert q.run_due(s, stack.client, stack.cipher, sleep=nosleep) == []  # backoff respected
    q.run_due(s, stack.client, stack.cipher, now=utcnow() + timedelta(minutes=10), sleep=nosleep)
    s.refresh(job)
    assert job.status == "published" and job.attempts == 2
    assert len(stack.fake.containers) == 1 and len(stack.fake.published) == 1  # one container, one post


def test_rate_limit_backs_off_an_hour_not_evaded(stack):
    s = stack.s
    stack.fake.fail_publish_once = {"code": 4, "msg": "rate limit", "status": 429}
    job = q.approve(s, q.submit_for_approval(s, stack.reel.id, stack.acct.id).id, "yash")
    q.run_due(s, stack.client, stack.cipher, sleep=nosleep)
    s.refresh(job)
    assert job.next_attempt_at - utcnow() > timedelta(minutes=55)


def test_permanent_failure_and_attempt_cap(stack):
    s = stack.s
    stack.fake.fail_publish_once = {"code": 100, "msg": "invalid media", "status": 400}
    job = q.approve(s, q.submit_for_approval(s, stack.reel.id, stack.acct.id).id, "yash")
    q.run_due(s, stack.client, stack.cipher, sleep=nosleep)
    s.refresh(job)
    assert job.status == "failed" and "invalid media" in job.last_error


def test_expired_token_blocks_at_preflight(stack):
    s = stack.s
    stack.acct.token_expires_at = utcnow() - timedelta(days=1)
    job = q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    with pytest.raises(q.QueueError, match="token expired"):
        q.approve(s, job.id, "yash")


def test_edited_video_after_render_is_blocked(stack):
    s = stack.s
    job = q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    with open(stack.reel.video_path, "ab") as f:
        f.write(b"x")
    with pytest.raises(q.QueueError, match="hash mismatch"):
        q.approve(s, job.id, "yash")


def test_caption_privacy_guard(stack):
    s = stack.s
    stack.reel.caption = "dm me at test@example.com or +1 415 555 0100"
    job = q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    with pytest.raises(q.QueueError, match="private-info"):
        q.approve(s, job.id, "yash")


def test_unverified_audio_blocks_publish(stack):
    from reelstudio.db import AudioAsset
    s = stack.s
    a = AudioAsset(title="hit", rights_status="unverified", local_file="x.wav"); s.add(a); s.flush()
    stack.reel.audio_id = a.id; s.flush(); s.refresh(stack.reel)
    job = q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    with pytest.raises(q.QueueError, match="audio"):
        q.approve(s, job.id, "yash")


def test_native_audio_reel_needs_explicit_acknowledgement(stack):
    s = stack.s
    stack.reel.needs_native_audio = True
    job = q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    with pytest.raises(q.QueueError, match="Instagram-native"):
        q.approve(s, job.id, "yash")
    q.approve(s, job.id, "yash", acknowledge_no_native_audio=True)


def test_auto_publish_gated(stack):
    s = stack.s
    with pytest.raises(q.QueueError, match="human-approved"):
        q.enable_auto_publish(s, "yash", allowed_categories=["situationship"])
    j = q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    assert q.maybe_auto_approve(s, j) is False and j.status == "pending_approval"  # default: review required


def test_manual_path_and_package(stack, tmp_path):
    s = stack.s
    job = q.submit_for_approval(s, stack.reel.id, stack.acct.id)
    d = q.manual_package(s, job.id, tmp_path / "pkg")
    assert (d / "reel.mp4").exists() and (d / "caption.txt").exists() and (d / "MANUAL_STEPS.txt").exists()
    q.mark_manually_published(s, job.id, "yash", "https://www.instagram.com/reel/abc/")
    assert job.status == "published" and job.permalink.endswith("abc/")
    assert audit_actions(s, job)[-1] == "job.published" and "job.manual_package" in audit_actions(s, job)


def test_insights_never_fabricate(stack):
    s = stack.s
    job = q.approve(s, q.submit_for_approval(s, stack.reel.id, stack.acct.id).id, "yash")
    q.run_due(s, stack.client, stack.cipher, sleep=nosleep); s.refresh(job)
    snap = collect_insights(s, stack.client, stack.cipher, job, now=utcnow() + timedelta(hours=24))
    assert snap.metrics["reach"] == 1200 and snap.followers == 1000
    assert "ig_reels_video_view_total_time" not in snap.metrics
    assert any(u["metric"] == "ig_reels_video_view_total_time" for u in snap.unavailable)
    assert 23 < snap.age_hours < 25


def test_signed_media_urls(env):
    from reelstudio import config
    url = public_url(7, "video", "abc", base="https://h.test")
    sig = url.rsplit("/", 1)[1]
    assert verify_media(7, "video", "abc", sig) and not verify_media(8, "video", "abc", sig)
    with pytest.raises(ValueError):
        public_url(7, "video", "abc", base="http://insecure")
