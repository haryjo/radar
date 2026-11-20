"""Recherche express (one shot) depuis l'assistant, sans créer de veille.

Toutes les sources sont interrogées en parallèle, les pages web les plus prometteuses sont lues (JSON-LD
en priorité), puis les offres sont notées en UN seul appel LLM groupé : rapide et économe en tokens.
"""
import asyncio
import json
import time

from pydantic import BaseModel, Field, field_validator

from .db import normalize_url
from .guardrails import SYSTEM_RULES, is_blocked, wrap_untrusted
from .llm import LLMError, call_structured
from .tools.profile_rag import profile_index
from .tools.sources import CONNECTORS, connector_configured, run_connector
from .tools.web import read_page, search_web
from .watches import read_preferences

DEFAULT_SOURCES = ["web", "jobicy", "himalayas", "remoteok", "arbeitnow"]


class ScoredItem(BaseModel):
    index: int
    score: int = Field(description="Pertinence de 0 à 100")
    reason: str = Field("", description="Raison principale, une phrase courte")

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, v) -> int:
        try:
            return max(0, min(100, int(float(str(v).split("/")[0]))))
        except ValueError:
            return 0


class BatchScore(BaseModel):
    items: list[ScoredItem]


async def quick_search(query: str, location: str = "", sources: list[str] | None = None, limit: int = 12) -> dict:
    started = time.monotonic()
    wanted = [s for s in (sources or DEFAULT_SOURCES) if s in CONNECTORS and s != "apify"] or ["web"]
    full_query = f"{query} {location}".strip()
    log: list[dict] = []

    async def run(source: str) -> list[dict]:
        t0 = time.monotonic()
        try:
            if source == "web":
                found = [{**r, "source": "web", "summary": r.get("snippet", "")}
                         for r in await search_web(f"{full_query} offre emploi", max_results=8)]
            elif not connector_configured(source):
                raise RuntimeError("clé manquante")
            else:
                found = await run_connector(source, query, limit=10)
            log.append({"source": source, "label": CONNECTORS[source]["label"], "query": full_query,
                        "count": len(found), "error": None, "ms": int((time.monotonic() - t0) * 1000)})
            return found
        except Exception as exc:  # noqa: BLE001
            log.append({"source": source, "label": CONNECTORS[source]["label"], "query": full_query,
                        "count": 0, "error": str(exc)[:120] or exc.__class__.__name__,
                        "ms": int((time.monotonic() - t0) * 1000)})
            return []

    batches = await asyncio.gather(*(run(s) for s in wanted))
    merged: dict[str, dict] = {}
    for batch in batches:
        for item in batch:
            url = item.get("url") or ""
            if url.startswith("http") and not is_blocked(url):
                merged.setdefault(normalize_url(url), item)
    candidates = list(merged.values())[:30]

    # Pages web : lecture rapide des 6 premières (offre JSON-LD complète si disponible)
    web = [c for c in candidates if c.get("source") == "web"][:6]
    pages = await asyncio.gather(*(read_page(c["url"], focus=full_query, max_chars=1200) for c in web))
    for item, page in zip(web, pages):
        if page.get("structured"):
            item.update({k: v for k, v in page["structured"].items() if v}, source="jsonld")
        elif page.get("content"):
            item["summary"] = page["content"][:400]

    scored = await _score_batch(query, location, candidates)
    scored.sort(key=lambda o: o.get("score", 0), reverse=True)
    return {"query": full_query, "duration_s": round(time.monotonic() - started, 1), "sources": log,
            "offers": scored[:limit], "total_found": len(candidates)}


async def _score_batch(query: str, location: str, items: list[dict]) -> list[dict]:
    if not items:
        return []
    chunks = await profile_index.asearch(query, k=3)
    profile = "\n---\n".join(c["text"] for c in chunks)[:3000]
    listing = "\n".join(
        f"[{i}] {o.get('title', '')[:120]} | {o.get('company', '')[:60]} | {o.get('location', '')[:60]} | "
        f"{str(o.get('summary', ''))[:220]}" for i, o in enumerate(items))
    wrapped, _ = wrap_untrusted(listing, "recherche express")
    user = (f"Recherche de l'utilisateur : « {query} » {('à ' + location) if location else ''}\n\n"
            f"## Profil\n{profile or '(vide)'}\n\n## Préférences\n{read_preferences() or '(aucune)'}\n\n"
            f"Note chaque offre de 0 à 100 selon sa pertinence pour cette recherche et ce profil, avec une raison "
            f"courte. Une page qui n'est pas une offre précise vaut moins de 20.\n\n{wrapped}")
    try:
        result = await call_structured("score", SYSTEM_RULES, user, BatchScore)
        scores = {s.index: s for s in result.items}
    except LLMError:
        scores = {}
    out = []
    for i, item in enumerate(items):
        s = scores.get(i)
        out.append({"title": item.get("title", ""), "company": item.get("company", ""),
                    "location": item.get("location", ""), "url": item["url"], "source": item.get("source", "web"),
                    "summary": str(item.get("summary", ""))[:300], "skills": item.get("skills", [])[:6],
                    "contract": item.get("contract", ""), "remote": item.get("remote", ""),
                    "score": s.score if s else 0, "reason": s.reason if s else ""})
    return out


def to_tool_text(result: dict) -> str:
    """Version compacte pour le LLM (les cartes complètes sont envoyées à l'interface à part)."""
    offers = [{k: o[k] for k in ("title", "company", "location", "score", "reason", "url", "source", "contract")}
              for o in result["offers"]]
    while True:  # JSON toujours valide : on retire des offres plutôt que de couper le texte
        text = json.dumps({**result, "offers": offers}, ensure_ascii=False)
        if len(text) <= 9000 or not offers:
            return text
        offers = offers[:-1]
