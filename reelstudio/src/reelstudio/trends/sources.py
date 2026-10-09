"""Pluggable trend sources. Only authorised APIs, public sources and user-supplied exports.

No scraping of Instagram/TikTok. A source that cannot run (no credentials) reports itself as
unavailable instead of inventing data.
"""
from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from .models import Signal, TrendCandidate, unavailable


class TrendSource(Protocol):
    name: str

    def fetch(self) -> list[TrendCandidate]: ...


class SourceUnavailable(Exception):
    pass


def _parse_dt(v: Any) -> datetime | None:
    if not v:
        return None
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class ManualFileSource:
    """Reads trends from a JSON list or CSV export that a human (or licensed provider export) supplied.

    Fields: kind, title, description, source_url, observed_at, lifecycle_stage, tags (list or ';'-sep),
    views, likes, comments, shares, views_prev (earlier measurement, enables measured momentum),
    audio_rights (licensed|original|royalty_free|unverified), originality (0-1 analyst estimate).
    """

    def __init__(self, path: str | Path, name: str = "manual_export") -> None:
        self.path = Path(path)
        self.name = name

    def _rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            raise SourceUnavailable(f"file not found: {self.path}")
        if self.path.suffix == ".json":
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else data.get("trends", [])
        with open(self.path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    @staticmethod
    def _num(v: Any) -> float | None:
        try:
            return float(v) if v not in (None, "") else None
        except ValueError:
            return None

    def fetch(self) -> list[TrendCandidate]:
        out: list[TrendCandidate] = []
        for row in self._rows():
            tags = row.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(";") if t.strip()]
            views, prev = self._num(row.get("views")), self._num(row.get("views_prev"))
            likes, comments, shares = (self._num(row.get(k)) for k in ("likes", "comments", "shares"))
            c = TrendCandidate(
                kind=row.get("kind") or "topic", title=row["title"], source=self.name,
                description=row.get("description", ""), source_url=row.get("source_url", ""),
                observed_at=_parse_dt(row.get("observed_at")),
                lifecycle_stage=row.get("lifecycle_stage") or "unknown", tags=tags,
                raw_metrics={k: v for k, v in dict(views=views, views_prev=prev, likes=likes,
                                                   comments=comments, shares=shares).items() if v is not None},
            )
            if views and prev and prev > 0:
                growth = (views - prev) / prev
                c.signals["momentum"] = Signal(min(max(growth, 0.0), 2.0) / 2.0, "measured",
                                               f"views {prev:.0f}->{views:.0f} between two supplied measurements")
            else:
                c.signals["momentum"] = unavailable("needs two dated view measurements")
            if views and likes is not None and views > 0:
                er = (likes + (comments or 0) + (shares or 0)) / views
                c.signals["engagement"] = Signal(min(er / 0.10, 1.0), "measured",
                                                 f"interaction rate {er:.3%} (10% = 1.0)")
            else:
                c.signals["engagement"] = unavailable("no views+likes supplied")
            if row.get("originality") not in (None, ""):
                c.signals["originality"] = Signal(float(row["originality"]), "estimate", "analyst-supplied estimate")
            rights = (row.get("audio_rights") or "").strip()
            if c.kind == "audio":
                c.rights = {"audio_rights": rights or "unverified"}
            if row.get("source_url"):
                c.evidence.append({"type": "url", "ref": row["source_url"]})
            c.evidence.append({"type": "export", "ref": str(self.path.name)})
            out.append(c)
        return out


class SeasonalCalendarSource:
    """Upcoming events from the configured calendar. Dates are facts; resonance is an estimate."""

    name = "seasonal_calendar"

    def __init__(self, events: list[dict[str, Any]], today: date | None = None) -> None:
        self.events, self.today = events, today or date.today()

    def fetch(self) -> list[TrendCandidate]:
        out = []
        for ev in self.events:
            for year in (self.today.year, self.today.year + 1):
                try:
                    d = date(year, ev["month"], ev["day"])
                except ValueError:
                    continue
                days_left = (d - self.today).days
                if 0 <= days_left <= ev.get("lead_days", 10):
                    c = TrendCandidate(
                        kind="seasonal", title=ev["name"], source=self.name,
                        description=f"{days_left} day(s) until {d.isoformat()}",
                        observed_at=datetime.now(timezone.utc), lifecycle_stage="emerging",
                        evidence=[{"type": "calendar", "ref": d.isoformat(),
                                   "approximate": bool(ev.get("approximate"))}],
                    )
                    c.signals["momentum"] = Signal(1 - days_left / max(ev.get("lead_days", 10), 1), "measured",
                                                   "proximity to dated event (not social-platform data)")
                    c.signals["engagement"] = unavailable("calendar events carry no engagement data")
                    out.append(c)
                    break
        return out


class RssSource:
    """Public RSS/Atom feed headlines as topic hints (no engagement data)."""

    def __init__(self, name: str, url: str, client: httpx.Client | None = None, limit: int = 15) -> None:
        self.name, self.url, self.limit = name, url, limit
        self.client = client or httpx.Client(timeout=15)

    def fetch(self) -> list[TrendCandidate]:
        try:
            r = self.client.get(self.url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"{self.name}: {e}") from e
        root = ET.fromstring(r.text)
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        out = []
        for it in items[: self.limit]:
            title = (it.findtext("title") or it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link = (it.findtext("link") or "").strip()
            if not link:
                le = it.find("{http://www.w3.org/2005/Atom}link")
                link = le.get("href", "") if le is not None else ""
            pub = it.findtext("pubDate") or it.findtext("{http://www.w3.org/2005/Atom}updated")
            observed = None
            if pub:
                try:
                    from email.utils import parsedate_to_datetime
                    observed = parsedate_to_datetime(pub)
                except (TypeError, ValueError):
                    observed = _parse_dt(pub)
            if title:
                c = TrendCandidate(kind="topic", title=title, source=self.name, source_url=link,
                                   observed_at=observed or datetime.now(timezone.utc),
                                   evidence=[{"type": "rss", "ref": link or self.url}])
                c.signals["momentum"] = unavailable("RSS has no velocity data")
                c.signals["engagement"] = unavailable("RSS has no engagement data")
                out.append(c)
        return out


class CredentialedApiSource:
    """Placeholder for licensed trend providers / authorised platform APIs.

    Without credentials it raises SourceUnavailable so the run report shows exactly what is missing.
    """

    def __init__(self, name: str, env_var: str, token: str = "") -> None:
        self.name, self.env_var, self.token = name, env_var, token

    def fetch(self) -> list[TrendCandidate]:
        if not self.token:
            raise SourceUnavailable(f"{self.name}: set {self.env_var} and implement the provider adapter")
        raise SourceUnavailable(f"{self.name}: adapter not implemented")
