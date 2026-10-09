from datetime import timedelta

import httpx
import pytest

from reelstudio import worker
from reelstudio.db import AuditLog, utcnow
from reelstudio.publishing import queue as q
from reelstudio.publishing.media import MediaUnreachable, verify_public_media

nosleep = lambda _s: None  # noqa: E731


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def ok_handler(size=1000, ctype="video/mp4"):
    def h(req):
        assert req.headers.get("range") == "bytes=0-0"
        return httpx.Response(206, content=b"x", headers={"content-type": ctype, "content-range": f"bytes 0-0/{size}"})
    return h


def test_verify_public_media_accepts_correct_response():
    verify_public_media("https://h/m", 1000, "video/", client_for(ok_handler()))
    verify_public_media("https://h/m", 5, "video/", client_for(lambda r: httpx.Response(200, content=b"12345", headers={"content-type": "video/mp4"})))


@pytest.mark.parametrize("handler,needle", [
    (lambda r: httpx.Response(404), "HTTP 404"),
    (lambda r: httpx.Response(302, headers={"location": "https://x"}), "HTTP 302"),
    (ok_handler(ctype="text/html"), "content-type"),
    (ok_handler(size=999), "size"),
    (lambda r: (_ for _ in ()).throw(httpx.ConnectError("boom")), "not reachable"),
])
def test_verify_public_media_rejects(handler, needle):
    with pytest.raises(MediaUnreachable, match=needle):
        verify_public_media("https://h/m", 1000, "video/", client_for(handler))


def test_unreachable_media_blocks_container_creation_and_retries(stack, monkeypatch):
    s = stack.s
    def boom(*a, **k):
        raise MediaUnreachable("HTTP 404")
    monkeypatch.setattr(q, "verify_public_media", boom)
    job = q.approve(s, q.submit_for_approval(s, stack.reel.id, stack.acct.id).id, "yash")
    q.run_due(s, stack.client, stack.cipher, sleep=nosleep)
    s.refresh(job)
    assert job.status == "scheduled" and "not publicly accessible" in job.last_error and not job.container_id
    assert stack.fake.containers == {} and stack.fake.published == []     # nothing was sent to Instagram


def test_public_verification_is_audited_on_success(stack):
    s = stack.s
    job = q.approve(s, q.submit_for_approval(s, stack.reel.id, stack.acct.id).id, "yash")
    q.run_due(s, stack.client, stack.cipher, sleep=nosleep)
    acts = [a.action for a in s.query(AuditLog).filter_by(entity="job", entity_id=job.id)]
    assert "media.public_verified" in acts and acts.index("media.public_verified") < acts.index("ig.container_created")


def test_interrupted_publish_is_recovered_without_duplicate_container(stack):
    s = stack.s
    job = q.approve(s, q.submit_for_approval(s, stack.reel.id, stack.acct.id).id, "yash")
    # simulate a worker that claimed the job, created a container, then died
    job.status, job.attempts, job.container_id = "publishing", 1, "c1"
    job.next_attempt_at = utcnow() + timedelta(minutes=10)     # lease still valid -> must NOT be touched
    stack.fake.containers["c1"] = {"n": 0}
    s.flush()
    assert q.run_due(s, stack.client, stack.cipher, sleep=nosleep) == [] and job.status == "publishing"
    later = utcnow() + timedelta(minutes=20)                   # lease expired -> recovered and retried
    assert q.run_due(s, stack.client, stack.cipher, now=later, sleep=nosleep) == [job.id]
    s.refresh(job)
    assert job.status == "published" and len(stack.fake.containers) == 1 and len(stack.fake.published) == 1
    acts = [a.detail for a in s.query(AuditLog).filter_by(entity="job", entity_id=job.id)]
    assert any(d.get("recovered") for d in acts)


def test_recovery_runs_even_when_paused_but_does_not_publish(stack):
    s = stack.s
    job = q.approve(s, q.submit_for_approval(s, stack.reel.id, stack.acct.id).id, "yash")
    job.status, job.next_attempt_at = "publishing", utcnow() - timedelta(minutes=1)
    s.flush()
    q.set_paused(s, True, "yash")
    assert q.run_due(s, stack.client, stack.cipher, sleep=nosleep) == []
    s.refresh(job)
    assert job.status == "scheduled" and stack.fake.published == []


def test_worker_heartbeat(env):
    assert worker.heartbeat_age() is None
    worker.touch_heartbeat()
    age = worker.heartbeat_age()
    assert age is not None and age < 5
