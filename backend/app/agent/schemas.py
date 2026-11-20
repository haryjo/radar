"""Sorties structurées des LLM (validées par Pydantic).

Les validateurs « before » tolèrent les petites variations des modèles (liste renvoyée sous forme de
texte, score en chaîne, booléen « oui »...) pour éviter des échecs inutiles.
"""
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [part.strip(" -•\t") for part in re.split(r"[\n;,]", value) if part.strip(" -•\t")]
    if isinstance(value, (list, tuple)):
        return [v for v in value if v not in (None, "")]
    return [value]


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "oui", "yes", "1", "vrai")
    return bool(value)


class QueryPlan(BaseModel):
    queries: list[str] = Field(description="Requêtes de recherche web courtes (3 à 8 mots) et variées")

    @field_validator("queries", mode="before")
    @classmethod
    def _queries(cls, v: Any) -> list:
        return [str(q) for q in _as_list(v)]


class Triage(BaseModel):
    keep: list[int] = Field(description="Indices des résultats à lire, du plus prometteur au moins prometteur")

    @field_validator("keep", mode="before")
    @classmethod
    def _keep(cls, v: Any) -> list:
        return [int(re.sub(r"\D", "", str(i))) for i in _as_list(v) if re.search(r"\d", str(i))]


class ExtractedOffer(BaseModel):
    is_job_offer: bool = Field(description="true seulement si la page décrit UNE offre précise (emploi, stage, mission)")
    title: str = ""
    company: str = ""
    location: str = ""
    contract: str = Field("", description="CDI, CDD, stage, freelance, alternance...")
    remote: str = Field("", description="sur site, hybride, télétravail")
    salary: str = ""
    skills: list[str] = Field(default_factory=list, description="Compétences demandées, 10 maximum")
    summary: str = Field("", description="Résumé en français, 3 lignes maximum")
    published: str = Field("", description="Date de publication si visible")
    contact: str = Field("", description="Lien ou e-mail de candidature générique publié, sinon vide")

    @field_validator("is_job_offer", mode="before")
    @classmethod
    def _bool(cls, v: Any) -> bool:
        return _as_bool(v)

    @field_validator("title", "company", "location", "contract", "remote", "salary", "summary", "published",
                     "contact", mode="before")
    @classmethod
    def _text(cls, v: Any) -> str:
        return _as_text(v)

    @field_validator("skills", mode="before")
    @classmethod
    def _skills(cls, v: Any) -> list:
        return [str(s) for s in _as_list(v)][:10]


class OfferScore(BaseModel):
    score: int = Field(description="Pertinence de 0 à 100")
    reasons: list[str] = Field(description="2 à 4 raisons courtes")
    red_flags: list[str] = Field(default_factory=list, description="Points de vigilance éventuels")
    excluded: bool = Field(False, description="true si un critère d'exclusion de la veille s'applique")

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, v: Any) -> int:
        match = re.search(r"\d+(?:[.,]\d+)?", str(v))
        if not match:
            raise ValueError("score manquant")
        value = float(match.group(0).replace(",", "."))
        return max(0, min(100, round(value * 10 if value <= 10 and "/10" in str(v) else value)))

    @field_validator("reasons", "red_flags", mode="before")
    @classmethod
    def _lists(cls, v: Any) -> list:
        return [str(s) for s in _as_list(v)]

    @field_validator("excluded", mode="before")
    @classmethod
    def _bool(cls, v: Any) -> bool:
        return _as_bool(v)
