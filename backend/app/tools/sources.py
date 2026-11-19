"""Connecteurs de recherche structurés : ils renvoient des offres déjà découpées en champs.

Avantage : ni lecture de page ni extraction par le LLM, donc beaucoup plus rapide et sans tokens.
- jobicy, arbeitnow, remoteok, himalayas : API publiques gratuites, sans clé.
- apify : n'importe quel Actor Apify (clé APIFY_TOKEN), via run-sync-get-dataset-items.
Chaque connecteur est tolérant : un champ absent ou renommé ne fait pas échouer la veille.
"""
import asyncio
import html
import logging
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from .. import secrets_store

log = logging.getLogger("radar.sources")
UA = "RadarVeilleBot/1.0 (veille d'offres personnelle)"


def _clean(text: Any, limit: int = 600) -> str:
    if not text:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(text)))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _first(item: dict, *keys: str) -> Any:
    for key in keys:
        value = item
        for part in key.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value not in (None, "", [], {}):
            return value
    return None


def _date(value: Any) -> str:
    if isinstance(value, (int, float)) and value > 10**8:
        return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()
    return str(value or "")[:10]


def _salary(item: dict) -> str:
    low = _first(item, "annualSalaryMin", "salary_min", "minSalary", "salaryMin")
    high = _first(item, "annualSalaryMax", "salary_max", "maxSalary", "salaryMax")
    currency = _first(item, "salaryCurrency", "currency") or ""
    if low or high:
        return f"{low or ''}–{high or ''} {currency}".strip(" –")
    return _clean(_first(item, "salary"), 80)


def normalize(item: dict, source: str) -> dict | None:
    """Champs communs, quel que soit le format de la source."""
    url = _first(item, "url", "applicationLink", "apply_url", "jobUrl", "link", "applyUrl", "externalApplyLink")
    title = _first(item, "jobTitle", "title", "position", "positionName", "name")
    if not url or not title or not str(url).startswith("http"):
        return None
    tags = _first(item, "tags", "categories", "skills", "jobIndustry") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    location = _first(item, "jobGeo", "candidate_required_location", "location", "locationRestrictions",
                      "jobLocation", "city")
    if isinstance(location, list):
        location = ", ".join(str(x) for x in location[:4])
    contract = _first(item, "jobType", "job_type", "employmentType", "job_types", "contractType")
    if isinstance(contract, list):
        contract = ", ".join(str(x) for x in contract[:3])
    remote = _first(item, "remote", "isRemote", "workplaceType")
    return {
        "url": str(url),
        "title": _clean(title, 200),
        "company": _clean(_first(item, "companyName", "company_name", "company", "company.name", "hiringOrganization"), 120),
        "location": _clean(location, 120),
        "contract": _clean(contract, 60),
        "remote": "télétravail" if remote is True or source in ("jobicy", "remoteok", "himalayas") else _clean(remote, 40),
        "salary": _salary(item),
        "skills": [_clean(t, 40) for t in tags if t][:10],
        "summary": _clean(_first(item, "jobExcerpt", "excerpt", "description", "jobDescription", "descriptionText"), 600),
        "published": _date(_first(item, "pubDate", "created_at", "date", "epoch", "postedAt", "publishedAt", "datePosted")),
        "source": source,
    }


def _matches(offer: dict, query: str) -> bool:
    """Filtre local pour les API sans recherche : au moins un mot significatif de la requête."""
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 3]
    haystack = f"{offer['title']} {offer['summary']} {' '.join(offer['skills'])}".lower()
    return not words or any(w in haystack for w in words)


async def _get_json(client: httpx.AsyncClient, url: str, **kwargs) -> Any:
    resp = await client.get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()


# ------------------------------------------------------------------ connecteurs

async def jobicy(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    tag = " ".join(query.split()[:3])[:50]
    data = await _get_json(client, "https://jobicy.com/api/v2/remote-jobs",
                           params={"count": min(limit, 50), **({"tag": tag} if len(tag) >= 3 else {})})
    return [o for o in (normalize(j, "jobicy") for j in data.get("jobs", [])) if o]


async def arbeitnow(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    data = await _get_json(client, "https://www.arbeitnow.com/api/job-board-api")
    offers = [o for o in (normalize(j, "arbeitnow") for j in data.get("data", [])) if o]
    return [o for o in offers if _matches(o, query)][:limit]


async def remoteok(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    data = await _get_json(client, "https://remoteok.com/api")
    jobs = [j for j in data if isinstance(j, dict) and j.get("position")]  # le 1er élément est une mention légale
    offers = [o for o in (normalize(j, "remoteok") for j in jobs) if o]
    return [o for o in offers if _matches(o, query)][:limit]


async def himalayas(client: httpx.AsyncClient, query: str, limit: int) -> list[dict]:
    try:
        data = await _get_json(client, "https://himalayas.app/jobs/api/search", params={"q": query, "limit": limit})
    except httpx.HTTPError:
        data = await _get_json(client, "https://himalayas.app/jobs/api", params={"limit": 50})
    offers = [o for o in (normalize(j, "himalayas") for j in data.get("jobs", [])) if o]
    return [o for o in offers if _matches(o, query)][:limit]


async def apify(client: httpx.AsyncClient, query: str, limit: int, actor: str | None = None,
                actor_input: dict | None = None) -> list[dict]:
    token = secrets_store.get("apify")
    if not token:
        raise RuntimeError("APIFY_TOKEN manquant dans .env")
    if not actor:
        raise RuntimeError("Aucun Actor Apify défini (champ apify_actor de la veille)")
    payload = {k: (v.replace("{requete}", query) if isinstance(v, str) else v) for k, v in (actor_input or {}).items()}
    if not payload:
        payload = {"query": query, "maxItems": limit}
    resp = await client.post(f"https://api.apify.com/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items",
                             params={"token": token, "limit": limit, "clean": "true"},
                             json=payload, timeout=310)
    resp.raise_for_status()
    items = resp.json()
    return [o for o in (normalize(j, "apify") for j in items if isinstance(j, dict)) if o][:limit]


Connector = Callable[..., Awaitable[list[dict]]]

CONNECTORS: dict[str, dict] = {
    "web": {"label": "Recherche web", "description": "DuckDuckGo puis lecture des pages. Couvre tout, dont les sites malgaches, mais c'est le plus lent.",
            "free": True, "key": None, "speed": "lent", "scope": "Toutes les régions"},
    "jobicy": {"label": "Jobicy", "description": "API publique d'offres en télétravail, recherche par mot-clé.",
               "free": True, "key": None, "speed": "rapide", "scope": "Télétravail international", "fn": jobicy},
    "arbeitnow": {"label": "Arbeitnow", "description": "API publique, offres en Europe et en télétravail.",
                  "free": True, "key": None, "speed": "rapide", "scope": "Europe, télétravail", "fn": arbeitnow},
    "remoteok": {"label": "Remote OK", "description": "API publique, offres tech en télétravail.",
                 "free": True, "key": None, "speed": "rapide", "scope": "Tech, télétravail", "fn": remoteok},
    "himalayas": {"label": "Himalayas", "description": "API publique d'offres en télétravail.",
                  "free": True, "key": None, "speed": "rapide", "scope": "Télétravail international", "fn": himalayas},
    "apify": {"label": "Apify", "description": "N'importe quel Actor de scraping Apify (Indeed, Welcome to the Jungle...).",
              "free": False, "key": "APIFY_TOKEN", "speed": "moyen", "scope": "Selon l'Actor choisi", "fn": apify},
}


def connector_configured(cid: str) -> bool:
    return cid != "apify" or bool(secrets_store.get("apify"))


async def run_connector(cid: str, query: str, limit: int = 20, **kwargs) -> list[dict]:
    spec = CONNECTORS[cid]
    timeout = 310 if cid == "apify" else 20
    async with httpx.AsyncClient(headers={"User-Agent": UA, "Accept": "application/json"}, timeout=timeout,
                                 follow_redirects=True) as client:
        if cid == "apify":
            return await spec["fn"](client, query, limit, **kwargs)
        return await asyncio.wait_for(spec["fn"](client, query, limit), timeout=timeout + 5)
