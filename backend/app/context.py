"""Contexte d'exécution d'une veille : statistiques, budget de tokens, journal d'événements."""
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .db import now_iso


class BudgetExceeded(Exception):
    """Le budget de tokens de l'exécution est atteint."""


@dataclass
class RunContext:
    watch: str
    budget: int
    run_id: int | None = None
    emit: Callable[[dict], Awaitable[None]] | None = None
    stats: Counter = field(default_factory=Counter)
    events: list[dict] = field(default_factory=list)
    progress_state: dict | None = None
    live_offers: list[dict] = field(default_factory=list)

    def tokens_used(self) -> int:
        return self.stats["tokens_in"] + self.stats["tokens_out"]

    def check_budget(self) -> None:
        if self.tokens_used() >= self.budget:
            raise BudgetExceeded(f"Budget de {self.budget} tokens atteint")

    def add_usage(self, message: Any, size: str) -> None:
        usage = getattr(message, "usage_metadata", None) or {}
        self.stats["tokens_in"] += int(usage.get("input_tokens", 0))
        self.stats["tokens_out"] += int(usage.get("output_tokens", 0))
        self.stats["llm_calls"] += 1
        self.stats[f"llm_calls_{size}"] += 1

    async def log(self, kind: str, message: str, **data: Any) -> None:
        event = {"type": "event", "kind": kind, "message": message, "ts": now_iso()}
        if data:
            event["data"] = data
        self.events.append(event)
        if self.emit:
            await self.emit(event)

    async def progress(self, stage: str, done: int, total: int, label: str = "") -> None:
        """Avancement d'une étape (non stocké dans l'historique : seul le dernier état compte)."""
        self.progress_state = {"type": "progress", "stage": stage, "done": done, "total": total, "label": label,
                               "ts": now_iso()}
        if self.emit:
            await self.emit(self.progress_state)

    async def offer(self, offer: dict, kept: bool) -> None:
        """Offre notée : affichée en direct dans l'interface pendant l'exécution."""
        event = {"type": "offer", "kept": kept, "offer": {k: offer.get(k) for k in
                 ("title", "company", "location", "score", "url", "source", "reasons")}}
        self.live_offers.append(event)
        if self.emit:
            await self.emit(event)
