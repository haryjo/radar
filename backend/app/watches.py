"""Chargement et validation des fichiers Markdown (veilles, instructions, profil)."""
import os
import re
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import frontmatter
from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .config import settings

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")
MAX_BODY_CHARS = 8000


def tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def next_fire_times(planning: str, count: int = 3) -> list[datetime]:
    trigger = CronTrigger.from_crontab(planning, timezone=tz())
    times, previous, now = [], None, datetime.now(tz())
    for _ in range(count):
        fire = trigger.get_next_fire_time(previous, now)
        if fire is None:
            break
        times.append(fire)
        previous, now = fire, fire + timedelta(seconds=1)
    return times


class WatchConfig(BaseModel):
    """En-tête YAML d'un fichier de veille. Les champs inconnus sont refusés."""
    model_config = ConfigDict(extra="forbid")

    nom: str = Field(min_length=3, max_length=80)
    planning: str = Field(description="Expression cron à 5 champs, ex. '0 8 * * 1-5'")
    actif: bool = True
    max_resultats: int = Field(10, ge=1, le=30)
    score_minimum: int = Field(60, ge=0, le=100)
    mots_cles: list[str] = Field(default_factory=list, max_length=15)
    localisation: str | None = Field(None, max_length=120)
    fraicheur_jours: int = Field(7, ge=1, le=60)
    sources: list[str] = Field(default_factory=list, max_length=10)
    exclure: list[str] = Field(default_factory=list, max_length=20)
    notification: Literal["app", "telegram", "aucune"] = "app"
    budget_tokens: int | None = Field(None, ge=5000, le=200000)
    langue: str = "fr"
    connecteurs: list[Literal["web", "jobicy", "arbeitnow", "remoteok", "himalayas", "apify"]] = Field(
        default_factory=lambda: ["web"], min_length=1, description="Sources de recherche utilisées")
    apify_actor: str | None = Field(None, max_length=120, description="Actor Apify, ex. misceres/indeed-scraper")
    apify_input: dict | None = Field(None, description="Entrée de l'Actor ; {requete} est remplacé par la requête")

    @field_validator("connecteurs")
    @classmethod
    def unique_connectors(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @field_validator("planning")
    @classmethod
    def check_planning(cls, value: str) -> str:
        try:
            times = next_fire_times(value, count=6)
        except ValueError as exc:
            raise ValueError(f"expression cron invalide ({exc})") from exc
        gaps = [(b - a).total_seconds() / 3600 for a, b in zip(times, times[1:])]
        if gaps and min(gaps) < settings.min_interval_hours:
            raise ValueError(f"fréquence trop élevée : au moins {settings.min_interval_hours} h entre deux exécutions")
        return value


class Watch(BaseModel):
    slug: str
    raw: str
    body: str = ""
    config: WatchConfig | None = None
    error: str | None = None
    updated_at: float | None = None

    @property
    def valid(self) -> bool:
        return self.config is not None and self.error is None


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "en-tête"
        message = err["msg"].removeprefix("Value error, ")
        if err["type"] == "extra_forbidden":
            message = "champ inconnu"
        elif err["type"] == "missing":
            message = "champ obligatoire"
        lines.append(f"{field} : {message}")
    return " ; ".join(lines)


def parse_watch(slug: str, raw: str, updated_at: float | None = None) -> Watch:
    try:
        post = frontmatter.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return Watch(slug=slug, raw=raw, error=f"En-tête YAML illisible : {exc}", updated_at=updated_at)
    body = post.content.strip()
    try:
        config = WatchConfig.model_validate(post.metadata)
    except ValidationError as exc:
        return Watch(slug=slug, raw=raw, body=body, error=_format_errors(exc), updated_at=updated_at)
    if not body:
        return Watch(slug=slug, raw=raw, config=config, error="Le corps du fichier (instructions) est vide",
                     updated_at=updated_at)
    if len(body) > MAX_BODY_CHARS:
        return Watch(slug=slug, raw=raw, body=body, config=config,
                     error=f"Instructions trop longues (max {MAX_BODY_CHARS} caractères)", updated_at=updated_at)
    return Watch(slug=slug, raw=raw, body=body, config=config, updated_at=updated_at)


def check_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise ValueError("Identifiant invalide : lettres minuscules, chiffres et tirets uniquement")
    return slug


def watch_path(slug: str):
    return settings.watches_dir / f"{check_slug(slug)}.md"


def load_watches() -> dict[str, Watch]:
    watches = {}
    for path in sorted(settings.watches_dir.glob("*.md")):
        slug = path.stem
        if not SLUG_RE.match(slug):
            continue
        watches[slug] = parse_watch(slug, path.read_text(encoding="utf-8"), path.stat().st_mtime)
    return watches


def load_watch(slug: str) -> Watch | None:
    path = watch_path(slug)
    if not path.exists():
        return None
    return parse_watch(slug, path.read_text(encoding="utf-8"), path.stat().st_mtime)


def save_watch(slug: str, raw: str) -> Watch:
    """Valide AVANT d'écrire : un fichier invalide n'est jamais enregistré via l'API."""
    watch = parse_watch(slug, raw)
    if not watch.valid:
        raise ValueError(watch.error)
    path = watch_path(slug)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(raw, encoding="utf-8")
    os.replace(tmp, path)
    return load_watch(slug)


def delete_watch(slug: str) -> bool:
    path = watch_path(slug)
    if path.exists():
        path.unlink()
        return True
    return False


def _read_md(path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def read_instructions() -> str:
    """Instructions générales, dans un ordre stable (favorise le cache de prompt)."""
    parts = []
    for name in ("AGENT.md", "scoring.md"):
        text = _read_md(settings.instructions_dir / name)
        if text:
            parts.append(f"<!-- {name} -->\n{text}")
    return "\n\n".join(parts)


def read_preferences() -> str:
    return _read_md(settings.profile_dir / "preferences.md")


WATCH_TEMPLATE = """---
nom: Nouvelle veille
planning: "0 8 * * 1-5"
actif: true
max_resultats: 10
score_minimum: 65
mots_cles: [développeur python, stage IA]
localisation: Antananarivo ou télétravail
fraicheur_jours: 7
exclure: [stage non rémunéré]
connecteurs: [web, jobicy, himalayas]
notification: app
---

# Objectif
Décris ici ce que tu cherches.

# Priorités
- Ce qui augmente l'intérêt d'une offre

# Instructions
- Règles particulières que l'agent doit suivre
"""
