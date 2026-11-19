"""Outils web : recherche (DuckDuckGo + cache sémantique) et lecture de page (trafilatura + compression)."""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from typing import Any
from urllib.robotparser import RobotFileParser

import httpx
import numpy as np

from .. import db
from ..config import settings
from ..context import RunContext
from ..guardrails import domain_of, is_blocked
from .embeddings import aembed

log = logging.getLogger("radar.web")
USER_AGENT = "RadarVeilleBot/1.0 (veille d'offres personnelle; respecte robots.txt)"
MAX_HTML_BYTES = 3_000_000


def timelimit_for(days: int) -> str:
    if days <= 1:
        return "d"
    if days <= 7:
        return "w"
    if days <= 31:
        return "m"
    return "y"


# ------------------------------------------------------------------ recherche

def _ddg_search(query: str, max_results: int, timelimit: str) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:  # ancien nom du paquet
        from duckduckgo_search import DDGS
    results = DDGS().text(query, region="fr-fr", timelimit=timelimit, max_results=max_results) or []
    return [{"url": r.get("href", ""), "title": r.get("title", ""), "snippet": r.get("body", "")} for r in results]


async def search_web(query: str, ctx: RunContext | None = None, max_results: int = 8,
                     timelimit: str = "w") -> list[dict]:
    """Recherche web avec deux niveaux de cache : exact puis sémantique (requêtes proches)."""
    query = " ".join(query.split())
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=settings.search_cache_hours)).isoformat(timespec="seconds")
    with db.get_conn() as conn:
        rows = conn.execute("SELECT query, embedding, results FROM search_cache "
                            "WHERE fetched_at >= ? AND timelimit = ? ORDER BY id DESC LIMIT 300",
                            (cutoff, timelimit)).fetchall()

    for row in rows:
        if row["query"].lower() == query.lower():
            if ctx:
                ctx.stats["search_cache_hits"] += 1
            return json.loads(row["results"])

    vector = None
    try:
        vector = (await aembed([query]))[0]
    except Exception as exc:  # noqa: BLE001
        log.warning("Embedding indisponible pour le cache sémantique : %s", exc)

    if vector is not None:
        best_row, best_sim = None, 0.0
        for row in rows:
            if row["embedding"]:
                sim = float(np.frombuffer(row["embedding"], dtype=np.float32) @ vector)
                if sim > best_sim:
                    best_row, best_sim = row, sim
        if best_row is not None and best_sim >= settings.semantic_cache_threshold:
            if ctx:
                ctx.stats["semantic_cache_hits"] += 1
                await ctx.log("cache", f"Cache sémantique : « {query} » ≈ « {best_row['query']} »",
                              similarity=round(best_sim, 3))
            return json.loads(best_row["results"])

    results = await asyncio.to_thread(_ddg_search, query, max_results, timelimit)
    if ctx:
        ctx.stats["web_searches"] += 1
    with db.get_conn() as conn:
        conn.execute("INSERT INTO search_cache (query, timelimit, embedding, results, fetched_at) VALUES (?, ?, ?, ?, ?)",
                     (query, timelimit, vector.astype(np.float32).tobytes() if vector is not None else None,
                      json.dumps(results, ensure_ascii=False), db.now_iso()))
    return results


# ------------------------------------------------------------------ lecture de page

_robots: dict[str, RobotFileParser | None] = {}
_host_locks: dict[str, asyncio.Lock] = {}
_last_hit: dict[str, float] = {}


async def _robots_allowed(client: httpx.AsyncClient, url: str) -> bool:
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}"
    if base not in _robots:
        try:
            resp = await client.get(base + "/robots.txt", timeout=8)
            if resp.status_code == 200:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
                _robots[base] = parser
            else:
                _robots[base] = None
        except httpx.HTTPError:
            _robots[base] = None
    parser = _robots[base]
    return True if parser is None else parser.can_fetch(USER_AGENT, url)


async def _polite_wait(host: str) -> None:
    """Délai minimal entre deux requêtes vers un même domaine."""
    lock = _host_locks.setdefault(host, asyncio.Lock())
    async with lock:
        wait = settings.domain_delay_seconds - (time.monotonic() - _last_hit.get(host, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        _last_hit[host] = time.monotonic()


def _iter_jsonld(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _iter_jsonld(item)
    elif isinstance(node, dict):
        yield node
        if "@graph" in node:
            yield from _iter_jsonld(node["@graph"])


def extract_jobposting(html_text: str, url: str) -> dict | None:
    """Offre décrite en JSON-LD schema.org/JobPosting : lue directement, sans LLM."""
    from .sources import _clean
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html_text, flags=re.S | re.I):
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for node in _iter_jsonld(data):
            kind = node.get("@type")
            if kind != "JobPosting" and not (isinstance(kind, list) and "JobPosting" in kind):
                continue
            org = node.get("hiringOrganization") or {}
            place = node.get("jobLocation") or {}
            place = place[0] if isinstance(place, list) and place else place
            address = place.get("address", {}) if isinstance(place, dict) else {}
            if isinstance(address, str):
                location = address
            else:
                location = ", ".join(str(address.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")
                                     if address.get(k) and isinstance(address.get(k), str))
            salary = node.get("baseSalary") or {}
            value = salary.get("value", {}) if isinstance(salary, dict) else {}
            if isinstance(value, dict) and (value.get("minValue") or value.get("value")):
                salary_text = f"{value.get('minValue') or value.get('value')}–{value.get('maxValue', '')} " \
                              f"{salary.get('currency', '')} {value.get('unitText', '')}".replace("– ", " ").strip()
            else:
                salary_text = ""
            employment = node.get("employmentType") or ""
            title = _clean(node.get("title"), 200)
            if not title:
                continue
            return {
                "is_job_offer": True, "title": title,
                "company": _clean(org.get("name") if isinstance(org, dict) else org, 120),
                "location": _clean(location, 120),
                "contract": _clean(", ".join(employment) if isinstance(employment, list) else employment, 60),
                "remote": "télétravail" if node.get("jobLocationType") == "TELECOMMUTE" else "",
                "salary": _clean(salary_text, 80),
                "skills": [_clean(s, 40) for s in (node.get("skills") or "").split(",") if s.strip()][:10]
                if isinstance(node.get("skills"), str) else [],
                "summary": _clean(node.get("description"), 600),
                "published": str(node.get("datePosted") or "")[:10],
                "contact": "",
            }
    return None


def _extract(html: str, url: str) -> tuple[str, str, str]:
    import trafilatura
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True, favor_recall=True) or ""
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else "") or ""
    published = (meta.date if meta and meta.date else "") or ""
    return title, published, text


async def compress(text: str, focus: str, max_chars: int) -> str:
    """Optimisation des tokens : ne garde que les passages les plus proches de l'objectif de la veille."""
    if len(text) <= max_chars:
        return text
    chunks, buffer = [], ""
    for para in (p.strip() for p in text.split("\n")):
        if not para:
            continue
        if buffer and len(buffer) + len(para) > 400:
            chunks.append(buffer)
            buffer = para
        else:
            buffer = f"{buffer}\n{para}" if buffer else para
    if buffer:
        chunks.append(buffer)
    try:
        vectors = await aembed([focus] + chunks)
    except Exception:  # noqa: BLE001
        return text[:max_chars]
    sims = vectors[1:] @ vectors[0]
    order = [0] + [int(i) for i in np.argsort(-sims) if int(i) != 0]  # le début (titre) est toujours gardé
    selected, total = set(), 0
    for i in order:
        if total + len(chunks[i]) > max_chars and selected:
            continue
        selected.add(i)
        total += len(chunks[i]) + 1
    return "\n".join(chunks[i] for i in sorted(selected))


async def read_page(url: str, focus: str = "", ctx: RunContext | None = None,
                    max_chars: int | None = None) -> dict:
    """Ne lève jamais d'exception : renvoie {url, title, published, content} ou {url, error}."""
    max_chars = max_chars or settings.page_max_chars
    if is_blocked(url):
        return {"url": url, "error": "domaine bloqué par les garde-fous"}

    key = db.url_hash(url)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.page_cache_days)).isoformat(timespec="seconds")
    with db.get_conn() as conn:
        cached = conn.execute("SELECT title, published, content, structured FROM page_cache "
                              "WHERE url_hash = ? AND fetched_at >= ?", (key, cutoff)).fetchone()
    structured = None
    if cached:
        if ctx:
            ctx.stats["page_cache_hits"] += 1
        title, published, text = cached["title"], cached["published"], cached["content"]
        structured = json.loads(cached["structured"]) if cached["structured"] else None
        html_chars = len(text)
    else:
        try:
            async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT, "Accept-Language": "fr,en;q=0.8"},
                                         follow_redirects=True, timeout=15) as client:
                if not await _robots_allowed(client, url):
                    return {"url": url, "error": "interdit par robots.txt"}
                await _polite_wait(domain_of(url))
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            return {"url": url, "error": f"erreur réseau : {exc.__class__.__name__}"}
        if resp.status_code >= 400:
            return {"url": url, "error": f"HTTP {resp.status_code}"}
        if "html" not in resp.headers.get("content-type", "html"):
            return {"url": url, "error": "contenu non HTML"}
        html = resp.text[:MAX_HTML_BYTES]
        html_chars = len(html)
        title, published, text = await asyncio.to_thread(_extract, html, url)
        structured = await asyncio.to_thread(extract_jobposting, html, url)
        if ctx:
            ctx.stats["pages_fetched"] += 1
        if len(text) < 300 and not structured and settings.reader_fallback == "jina":
            # Page rendue en JavaScript : lecture par Jina Reader (gratuit, sans clé)
            rendered = await _read_with_jina(url)
            if rendered:
                text = rendered
                if ctx:
                    ctx.stats["jina_reads"] += 1
        if not text and not structured:
            return {"url": url, "error": "aucun contenu exploitable"}
        with db.get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO page_cache (url_hash, url, title, published, content, structured, "
                         "fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (key, url, title, published, text[:50000],
                          json.dumps(structured, ensure_ascii=False) if structured else None, db.now_iso()))

    if structured:
        # Offre lue en JSON-LD : rien n'est envoyé au LLM pour l'extraction
        if ctx:
            ctx.stats["html_chars"] += html_chars
        return {"url": url, "title": title, "published": published, "content": "", "structured": structured}
    content = await compress(text, focus or title, max_chars)
    if ctx:
        ctx.stats["html_chars"] += html_chars
        ctx.stats["sent_chars"] += len(content)
    return {"url": url, "title": title, "published": published, "content": content}


async def _read_with_jina(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=25, headers={"Accept": "text/plain", "X-Return-Format": "text"}) as client:
            resp = await client.get(f"https://r.jina.ai/{url}")
        return resp.text[:50000] if resp.status_code == 200 else ""
    except httpx.HTTPError:
        return ""
