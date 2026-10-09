from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ConceptRequest:
    category: str
    count: int
    trends: list[dict[str, Any]] = field(default_factory=list)  # title, description, tags, score
    voice: dict[str, Any] = field(default_factory=dict)
    avoid_lines: list[str] = field(default_factory=list)
    account_insights: dict[str, Any] = field(default_factory=dict)
    cycle_seed: int = 0


class AIProvider(Protocol):
    """Pluggable text-generation backend. Must return raw concept dicts (see writing.engine.normalise)."""
    name: str

    def generate_concepts(self, req: ConceptRequest) -> list[dict[str, Any]]: ...
