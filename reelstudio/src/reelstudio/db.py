"""SQLAlchemy models + session helpers. SQLite for dev/tests, PostgreSQL in production."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy.types import TypeDecorator
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TZDateTime(TypeDecorator):
    """Timezone-aware datetime: stored as UTC, always returned tz-aware (SQLite drops tzinfo)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value, dialect):  # noqa: ANN001
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def _dt() -> Mapped[datetime]:
    return mapped_column(TZDateTime(), default=utcnow)


# ---------------------------------------------------------------- trends / references
class Trend(Base):
    __tablename__ = "trends"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))  # format|audio|typography|topic|seasonal|creator_example
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(120))
    source_url: Mapped[str] = mapped_column(String(500), default="")
    discovered_at: Mapped[datetime] = _dt()
    # each signal: {"value": float|None, "kind": "measured"|"estimate"|"unavailable", "note": str}
    signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence: Mapped[list[Any]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    lifecycle_stage: Mapped[str] = mapped_column(String(24), default="unknown")  # emerging|rising|peak|declining|evergreen|unknown
    audience_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    rights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)


class ReferenceItem(Base):
    __tablename__ = "reference_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(120), default="")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    local_file: Mapped[str] = mapped_column(String(500), default="")
    file_sha256: Mapped[str] = mapped_column(String(64), default="")
    added_at: Mapped[datetime] = _dt()
    notes: Mapped[str] = mapped_column(Text, default="")
    measurements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # measured by tooling
    observations: Mapped[list[Any]] = mapped_column(JSON, default=list)  # human/analyst notes w/ inspected flag


# ---------------------------------------------------------------- concepts / reels
class Concept(Base):
    __tablename__ = "concepts"
    id: Mapped[int] = mapped_column(primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(40), index=True)
    trend_id: Mapped[int | None] = mapped_column(ForeignKey("trends.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(40))
    hook: Mapped[str] = mapped_column(Text)
    lines: Mapped[list[Any]] = mapped_column(JSON)  # [{text, start, end}]
    payoff: Mapped[str] = mapped_column(Text, default="")
    loop_strategy: Mapped[str] = mapped_column(Text, default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    audio_mood: Mapped[str] = mapped_column(String(80), default="")
    style: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # typography/animation spec
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provider: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(24), default="candidate")  # candidate|selected|rejected|published
    created_at: Mapped[datetime] = _dt()


class PublishedLine(Base):
    """Every line ever approved/published, used to prevent accidental repetition."""
    __tablename__ = "published_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    normalized: Mapped[str] = mapped_column(Text, index=True)
    concept_id: Mapped[int | None] = mapped_column(ForeignKey("concepts.id"), nullable=True)
    created_at: Mapped[datetime] = _dt()


class AudioAsset(Base):
    __tablename__ = "audio_assets"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    artist: Mapped[str] = mapped_column(String(200), default="")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    local_file: Mapped[str] = mapped_column(String(500), default="")
    # original|licensed|royalty_free|unverified|instagram_native
    rights_status: Mapped[str] = mapped_column(String(24), default="unverified")
    license_ref: Mapped[str] = mapped_column(String(300), default="")
    attribution: Mapped[str] = mapped_column(String(300), default="")
    allow_offplatform_render: Mapped[bool] = mapped_column(default=False)
    allow_commercial_ads: Mapped[bool] = mapped_column(default=False)
    allow_automated_publish: Mapped[bool] = mapped_column(default=False)
    mood: Mapped[str] = mapped_column(String(80), default="")
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    beats: Mapped[list[Any]] = mapped_column(JSON, default=list)
    trend_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = _dt()


class Reel(Base):
    __tablename__ = "reels"
    id: Mapped[int] = mapped_column(primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concepts.id"))
    audio_id: Mapped[int | None] = mapped_column(ForeignKey("audio_assets.id"), nullable=True)
    template: Mapped[str] = mapped_column(String(80), default="")
    render_spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    preview_path: Mapped[str] = mapped_column(String(500), default="")
    video_path: Mapped[str] = mapped_column(String(500), default="")
    cover_path: Mapped[str] = mapped_column(String(500), default="")
    video_sha256: Mapped[str] = mapped_column(String(64), default="")
    render_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|rendering|rendered|failed
    render_error: Mapped[str] = mapped_column(Text, default="")
    qa: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    caption: Mapped[str] = mapped_column(Text, default="")
    needs_native_audio: Mapped[bool] = mapped_column(default=False)
    purpose: Mapped[str] = mapped_column(String(12), default="organic")  # organic|ad (kept strictly separate)
    created_at: Mapped[datetime] = _dt()
    concept: Mapped[Concept] = relationship()
    audio: Mapped[AudioAsset | None] = relationship()


# ---------------------------------------------------------------- instagram / publishing
class IGAccount(Base):
    __tablename__ = "ig_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    ig_user_id: Mapped[str] = mapped_column(String(64), unique=True)
    username: Mapped[str] = mapped_column(String(120), default="")
    account_type: Mapped[str] = mapped_column(String(40), default="")
    token_encrypted: Mapped[str] = mapped_column(Text, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    scopes: Mapped[list[Any]] = mapped_column(JSON, default=list)
    publishing_enabled: Mapped[bool] = mapped_column(default=False)
    is_destination: Mapped[bool] = mapped_column(default=False)  # explicitly confirmed publish destination
    connected_at: Mapped[datetime] = _dt()
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class PublishJob(Base):
    __tablename__ = "publish_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    reel_id: Mapped[int] = mapped_column(ForeignKey("reels.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("ig_accounts.id"))
    # draft|pending_approval|approved|scheduled|publishing|published|failed|cancelled|rejected
    status: Mapped[str] = mapped_column(String(24), default="pending_approval", index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    approved_by: Mapped[str] = mapped_column(String(120), default="")
    approved_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    container_id: Mapped[str] = mapped_column(String(64), default="")
    ig_media_id: Mapped[str] = mapped_column(String(64), default="")
    permalink: Mapped[str] = mapped_column(String(300), default="")
    published_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = _dt()
    reel: Mapped[Reel] = relationship()
    account: Mapped[IGAccount] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = _dt()
    actor: Mapped[str] = mapped_column(String(120), default="system")
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity: Mapped[str] = mapped_column(String(40), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------- analytics
class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("publish_jobs.id"), index=True)
    taken_at: Mapped[datetime] = _dt()
    age_hours: Mapped[float] = mapped_column(Float, default=0.0)
    # metric -> value; metrics the API did not return are simply absent (never invented)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    unavailable: Mapped[list[Any]] = mapped_column(JSON, default=list)
    followers: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------- ads (separate from organic)
class AdCampaign(Base):
    __tablename__ = "ad_campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(String(60), default="")
    destination_url: Mapped[str] = mapped_column(String(500), default="")
    audience_notes: Mapped[str] = mapped_column(Text, default="")
    budget: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {amount, currency, period}
    ad_account: Mapped[str] = mapped_column(String(80), default="")
    # draft|ready_for_review|approved_to_launch|exported|cancelled — launch itself is always manual
    status: Mapped[str] = mapped_column(String(24), default="draft")
    approvals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # item -> {by, at}
    created_at: Mapped[datetime] = _dt()
    variants: Mapped[list["AdVariant"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class AdVariant(Base):
    __tablename__ = "ad_variants"
    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("ad_campaigns.id"))
    reel_id: Mapped[int | None] = mapped_column(ForeignKey("reels.id"), nullable=True)
    label: Mapped[str] = mapped_column(String(40))
    hook: Mapped[str] = mapped_column(Text)
    cta: Mapped[str] = mapped_column(String(80))
    test_dimension: Mapped[str] = mapped_column(String(40), default="hook")
    export_path: Mapped[str] = mapped_column(String(500), default="")
    audio_cleared_for_ads: Mapped[bool] = mapped_column(default=False)
    campaign: Mapped[AdCampaign] = relationship(back_populates="variants")


# ---------------------------------------------------------------- engine helpers
_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def make_engine(url: str | None = None):
    url = url or get_settings().database_url
    kwargs: dict[str, Any] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url == "sqlite://":
            from sqlalchemy.pool import StaticPool
            kwargs["poolclass"] = StaticPool
    eng = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _pragma(dbapi_con, _):  # noqa: ANN001
            dbapi_con.execute("PRAGMA foreign_keys=ON")
    return eng


def init_db(url: str | None = None, create_all: bool = True) -> None:
    """Initialise global engine. Production uses `alembic upgrade head`; create_all is for dev/tests."""
    global _engine, _SessionLocal
    _engine = make_engine(url)
    _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    if create_all:
        s = get_settings()
        if _engine.url.get_backend_name() == "sqlite" and _engine.url.database not in (None, ":memory:"):
            from pathlib import Path
            Path(_engine.url.database).parent.mkdir(parents=True, exist_ok=True)
        Base.metadata.create_all(_engine)
        del s


def get_session_factory() -> sessionmaker[Session]:
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    s = get_session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def audit(s: Session, action: str, entity: str = "", entity_id: int | None = None,
          actor: str = "system", **detail: Any) -> None:
    s.add(AuditLog(action=action, entity=entity, entity_id=entity_id, actor=actor, detail=detail))


def get_setting(s: Session, key: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    row = s.get(Setting, key)
    return dict(row.value) if row else dict(default or {})


def set_setting(s: Session, key: str, value: dict[str, Any], actor: str = "system") -> None:
    row = s.get(Setting, key)
    if row:
        row.value = value
    else:
        s.add(Setting(key=key, value=value))
    audit(s, "setting.changed", "setting", None, actor, key=key, value=value)
