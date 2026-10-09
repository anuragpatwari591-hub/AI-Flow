"""Trend candidate data structures. A Signal always says whether it is measured, estimated or unavailable."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

SignalKind = Literal["measured", "estimate", "unavailable"]

SIGNAL_NAMES = ["momentum", "freshness", "audience_relevance", "engagement",
                "originality", "feasibility", "rights_clearance"]


@dataclass
class Signal:
    value: float | None  # normalised 0..1; None when unavailable
    kind: SignalKind
    note: str = ""

    def __post_init__(self) -> None:
        if self.kind == "unavailable":
            self.value = None
        elif self.value is None:
            raise ValueError("measured/estimate signals need a value")
        elif not 0.0 <= self.value <= 1.0:
            raise ValueError(f"signal out of range: {self.value}")

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "kind": self.kind, "note": self.note}


def unavailable(note: str) -> Signal:
    return Signal(None, "unavailable", note)


@dataclass
class TrendCandidate:
    kind: str
    title: str
    source: str
    description: str = ""
    source_url: str = ""
    observed_at: datetime | None = None
    signals: dict[str, Signal] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    lifecycle_stage: str = "unknown"
    rights: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    raw_metrics: dict[str, Any] = field(default_factory=dict)  # e.g. views/likes as supplied by the source
