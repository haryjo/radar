"""Graphe LangGraph d'une exécution de veille.

load_context → plan_queries → search → filter_seen → triage → read_pages → extract → score
      ↑                                                                                │
      └──────────── next_round ◄──── (pas assez de résultats, budget OK) ◄─────────────┤
                                                                                       ▼
                                                              save → digest → notify → END
"""
import asyncio
from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..config import settings
from ..context import BudgetExceeded, RunContext
from ..db import normalize_url
from ..guardrails import is_blocked, matches_exclusion, redact_pii
from ..llm import LLMConfigError, LLMError, call_structured, call_text
from ..notify import send_telegram, telegram_enabled
from ..tools.mcp_client import mcp_call
from ..tools.profile_rag import profile_index
from ..tools.sources import CONNECTORS, connector_configured, run_connector
from ..tools.web import read_page, search_web, timelimit_for
from ..watches import Watch, read_instructions, read_preferences
from . import prompts
from .schemas import ExtractedOffer, OfferScore, QueryPlan, Triage


NEAR_MARGIN = 20  # une offre jusqu'à 20 points sous le score minimum est gardée comme « proche »


class WatchState(TypedDict, total=False):
    system: str
    focus: str
    round: int
    queries: list[str]
    tried: list[str]
    results: list[dict]
    candidates: list[dict]
    to_read: list[dict]
    pages: list[dict]
    prefilled: list[dict]
    extracted: list[dict]
    kept: list[dict]
    near: list[dict]
    seen_this_run: list[str]
    retry_urls: list[str]
    pages_read: int
    last_round: dict
    report_path: str


def _rt(config) -> tuple[RunContext, Watch]:
    conf = config["configurable"]
    return conf["ctx"], conf["watch"]


async def load_context(state: WatchState, config) -> dict:
    ctx, watch = _rt(config)
    try:
        feedback = await mcp_call("get_feedback_summary", {"watch": watch.slug})
    except Exception as exc:  # noqa: BLE001
        feedback = None
        await ctx.log("warning", f"Mémoire long terme indisponible ({exc.__class__.__name__})")
    system = prompts.build_system_prompt(read_instructions(), watch, feedback)
    await ctx.log("step", "Instructions chargées",
                  files=["AGENT.md", "scoring.md", f"veilles/{watch.slug}.md"],
                  memory_items=(feedback or {}).get("total_feedback", 0))
    return {"system": system, "focus": prompts.build_focus(watch), "round": 0, "tried": [], "kept": [],
            "seen_this_run": [], "retry_urls": [], "pages_read": 0}


async def plan_queries(state: WatchState, config) -> dict:
    ctx, watch = _rt(config)
    rnd = state.get("round", 0)
    count = settings.max_queries_per_round if rnd == 0 else max(2, settings.max_queries_per_round // 2)
    user = prompts.plan_prompt(watch, count, state.get("tried", []), state.get("last_round"))
    await ctx.progress("plan", 0, 1, "Préparation des requêtes" if rnd == 0 else "Reformulation des requêtes")
    try:
        queries = (await call_structured("plan", state["system"], user, QueryPlan, ctx)).queries
    except LLMConfigError:
        raise
    except LLMError as exc:
        if rnd == 0:
            raise LLMError(f"Aucun modèle LLM disponible, veille arrêtée sans rien marquer comme vu. {exc}") from exc
        await ctx.log("warning", f"Reformulation impossible : {str(exc)[:200]}")
        queries = []
    except BudgetExceeded as exc:
        await ctx.log("warning", f"Planification par défaut (mots-clés) : {str(exc)[:200]}")
        loc = watch.config.localisation or ""
        queries = [f"{kw} {loc}".strip() for kw in watch.config.mots_cles] or [watch.config.nom]
    tried = {q.lower() for q in state.get("tried", [])}
    clean: list[str] = []
    for q in queries:
        q = " ".join(str(q).split())[:120]
        if q and q.lower() not in tried and q.lower() not in {c.lower() for c in clean}:
            clean.append(q)
    clean = clean[:count]
    await ctx.log("step", f"Tour {rnd + 1} : {len(clean)} requêtes planifiées", queries=clean)
    return {"queries": clean}


async def search(state: WatchState, config) -> dict:
    """Recherche web et connecteurs structurés, tous en parallèle."""
    ctx, watch = _rt(config)
    cfg = watch.config
    timelimit = timelimit_for(cfg.fraicheur_jours)
    queries = state["queries"]
    connectors = [c for c in cfg.connecteurs if c != "web"]
    use_web = "web" in cfg.connecteurs
    # Connecteurs : deux requêtes suffisent (ils renvoient déjà des offres complètes)
    jobs: list[tuple[str, str]] = [("web", q) for q in queries] if use_web else []
    jobs += [(c, q) for c in connectors for q in queries[:2]]
    total, done = len(jobs), 0
    sem = asyncio.Semaphore(4)
    await ctx.progress("search", 0, total, "Recherche en cours")

    search_log: list[dict] = []

    async def one(source: str, query: str) -> tuple[str, str, list[dict]]:
        nonlocal done
        error = None
        started = asyncio.get_running_loop().time()
        async with sem:
            try:
                if source == "web":
                    found = await search_web(query, ctx=ctx, timelimit=timelimit)
                else:
                    if not connector_configured(source):
                        raise RuntimeError(f"{CONNECTORS[source]['key']} manquant dans .env")
                    found = await run_connector(source, query, limit=20, actor=cfg.apify_actor,
                                                actor_input=cfg.apify_input) if source == "apify" \
                        else await run_connector(source, query, limit=20)
                    ctx.stats[f"source:{source}"] += len(found)
            except Exception as exc:  # noqa: BLE001
                error = str(exc)[:160] or exc.__class__.__name__
                found = []
        search_log.append({"source": source, "label": CONNECTORS[source]["label"], "query": query,
                           "count": len(found), "error": error,
                           "ms": int((asyncio.get_running_loop().time() - started) * 1000)})
        done += 1
        await ctx.progress("search", done, total, f"{CONNECTORS[source]['label']} · {query}")
        return source, query, found

    batches = await asyncio.gather(*(one(s, q) for s, q in jobs))
    merged, blocked = {}, 0
    for source, query, batch in batches:
        for result in batch:
            url = result.get("url") or ""
            if not url.startswith("http"):
                continue
            if is_blocked(url):
                blocked += 1
                continue
            entry = dict(result) if source != "web" else {**result, "source": "web"}
            entry["query"] = query
            if source != "web":
                entry["structured"] = True
                entry.setdefault("snippet", result.get("summary", ""))
            merged.setdefault(normalize_url(url), entry)
    ctx.stats["search_results"] += sum(len(b) for _, _, b in batches)
    ctx.stats["blocked_domains"] += blocked
    ctx.stats["unique_results"] += len(merged)
    structured = sum(1 for r in merged.values() if r.get("structured"))
    failed = [s for s in search_log if s["error"]]
    await ctx.log("search", f"{len(search_log)} recherches, {len(failed)} en échec",
                  searches=sorted(search_log, key=lambda s: (s["source"], s["query"])))
    await ctx.log("step", f"{len(merged)} résultats uniques, dont {structured} offres structurées "
                          f"(sans lecture de page)", blocked=blocked)
    return {"results": list(merged.values()), "tried": state.get("tried", []) + queries}


async def filter_seen(state: WatchState, config) -> dict:
    """Veille incrémentale : une URL déjà traitée n'est jamais relue ni renvoyée au LLM."""
    ctx, watch = _rt(config)
    seen_run = set(state.get("seen_this_run", []))
    results = [r for r in state["results"] if normalize_url(r["url"]) not in seen_run]
    unseen = set(await mcp_call("filter_unseen", {"watch": watch.slug, "urls": [r["url"] for r in results]})) \
        if results else set()
    candidates = [r for r in results if r["url"] in unseen]
    skipped = len(state["results"]) - len(candidates)
    ctx.stats["already_seen"] += skipped
    await ctx.log("step", f"{len(candidates)} nouveaux, {skipped} déjà vus ignorés")
    return {"candidates": candidates}


async def triage(state: WatchState, config) -> dict:
    """Tri sur titre + extrait avec le modèle rapide : évite de lire ou noter des offres hors sujet."""
    ctx, watch = _rt(config)
    candidates = state.get("candidates", [])
    if not candidates:
        return {"to_read": []}
    await ctx.progress("triage", 0, 1, f"Tri de {len(candidates)} résultats")

    kept, excluded = [], []
    for c in candidates:
        (excluded if matches_exclusion(f"{c.get('title', '')} {c.get('snippet', '')}", watch.config.exclure)
         else kept).append(c)
    ctx.stats["excluded_rules"] += len(excluded)

    # Les pages web consomment le budget de lecture, pas les offres structurées
    web_budget = max(settings.max_pages_per_run - state.get("pages_read", 0), 0)
    limit = web_budget + sum(1 for c in kept if c.get("structured"))
    order: list[int] = []
    if kept and limit:
        try:
            result = await call_structured("triage", state["system"],
                                           prompts.triage_prompt(watch, kept, min(limit, 40)), Triage, ctx)
            order = [i for i in dict.fromkeys(result.keep) if 0 <= i < len(kept)]
        except LLMConfigError:
            raise
        except BudgetExceeded:
            order = []
        except LLMError:
            order = list(range(len(kept)))
    to_read, overflow, web_count = [], set(), 0
    for i in order:
        item = kept[i]
        if item.get("structured"):
            to_read.append(item)
        elif web_count < web_budget:
            to_read.append(item)
            web_count += 1
        else:
            overflow.add(item["url"])  # gardé pour une prochaine exécution
    newly_seen = [normalize_url(c["url"]) for c in candidates if c["url"] not in overflow]
    ctx.stats["triaged_out"] += len(kept) - len(order)
    ctx.stats["to_analyze"] += len(to_read)
    await ctx.progress("triage", 1, 1, f"{len(to_read)} retenus")
    await ctx.log("step", f"Tri : {len(to_read)} à analyser, {len(kept) - len(order)} écartés, "
                          f"{len(excluded)} exclus par règle")
    return {"to_read": to_read, "seen_this_run": state.get("seen_this_run", []) + newly_seen}


def _is_transient(error: str | None) -> bool:
    """Erreur passagère (réseau, quota, serveur) : la page sera relue à la prochaine exécution."""
    if not error:
        return False
    return error.startswith("erreur réseau") or error in ("HTTP 408", "HTTP 425", "HTTP 429") or \
        error.startswith("HTTP 5")


async def read_pages(state: WatchState, config) -> dict:
    """Lit uniquement les pages web ; les offres des connecteurs sont déjà structurées."""
    ctx, _ = _rt(config)
    to_read = state.get("to_read", [])
    prefilled = [r for r in to_read if r.get("structured")]
    web = [r for r in to_read if not r.get("structured")]
    sem = asyncio.Semaphore(settings.read_concurrency)
    done = 0

    async def one(result: dict) -> dict:
        nonlocal done
        async with sem:
            page = await read_page(result["url"], focus=state["focus"], ctx=ctx)
        page = {**page, "query": result.get("query", "")}
        done += 1
        await ctx.progress("read", done, len(web), page.get("title") or result.get("title", ""))
        return page

    if web:
        await ctx.progress("read", 0, len(web), "Lecture des pages")
    pages = await asyncio.gather(*(one(r) for r in web))
    ok = [p for p in pages if p.get("content") or p.get("structured")]
    errors = [{"url": p["url"], "error": p["error"]} for p in pages if p.get("error")]
    transient = [p["url"] for p in pages if _is_transient(p.get("error"))]
    jsonld = sum(1 for p in ok if p.get("structured"))
    ctx.stats["jsonld_offers"] += jsonld
    if web:
        await ctx.log("step", f"{len(ok)} pages lues" + (f", dont {jsonld} offres lues directement (JSON-LD)"
                                                          if jsonld else ""), errors=errors[:5])
    return {"pages": ok, "prefilled": prefilled, "pages_read": state.get("pages_read", 0) + len(web),
            "retry_urls": state.get("retry_urls", []) + transient}


async def extract(state: WatchState, config) -> dict:
    """Extraction : JSON-LD et connecteurs d'abord (sans LLM), le modèle rapide pour le reste."""
    ctx, watch = _rt(config)
    sem = asyncio.Semaphore(4)
    retry: list[str] = []
    pages = state.get("pages", [])
    llm_pages = [p for p in pages if not p.get("structured")]
    done = 0

    def finalize(data: dict, url: str, source: str) -> dict | None:
        data = {**data, "url": url, "source": source, "contact": redact_pii(data.get("contact", ""))}
        data["summary"] = redact_pii(data.get("summary", ""))
        if matches_exclusion(f"{data['title']} {data['summary']} {data.get('contract', '')}", watch.config.exclure):
            ctx.stats["excluded_rules"] += 1
            return None
        return data

    offers: list[dict] = []
    for item in state.get("prefilled", []):
        if (o := finalize({k: item.get(k, "") for k in ("title", "company", "location", "contract", "remote",
                                                         "salary", "skills", "summary", "published", "query")},
                          item["url"], item.get("source", "api"))):
            offers.append(o)
    for page in pages:
        if page.get("structured") and (o := finalize({**page["structured"], "query": page.get("query", "")},
                                                      page["url"], "jsonld")):
            offers.append(o)

    async def one(page: dict) -> dict | None:
        nonlocal done
        prompt, flagged = prompts.extract_prompt(page)
        if flagged:
            ctx.stats["injections_blocked"] += flagged
            await ctx.log("guardrail", f"{flagged} ligne(s) suspecte(s) retirée(s)", url=page["url"])
        async with sem:
            try:
                offer = await call_structured("extract", state["system"], prompt, ExtractedOffer, ctx)
            except LLMConfigError:
                raise
            except (BudgetExceeded, LLMError) as exc:
                retry.append(page["url"])
                if isinstance(exc, LLMError):
                    await ctx.log("warning", f"Extraction impossible, page gardée pour la prochaine fois : "
                                             f"{str(exc)[:180]}", url=page["url"])
                return None
            finally:
                done += 1
                await ctx.progress("extract", done, len(llm_pages), page.get("title", ""))
        if not offer.is_job_offer or not offer.title.strip():
            return None
        data = offer.model_dump()
        data["published"] = data["published"] or page.get("published", "")
        data["query"] = page.get("query", "")
        return finalize(data, page["url"], "web")

    if llm_pages:
        await ctx.progress("extract", 0, len(llm_pages), "Extraction par le LLM")
    ctx.stats["direct_offers"] += len(offers)  # connecteurs + JSON-LD : aucun appel LLM d'extraction
    offers += [o for o in await asyncio.gather(*(one(p) for p in llm_pages)) if o]
    ctx.stats["offers_extracted"] += len(offers)
    ctx.stats["llm_failures"] += len(retry)
    if pages or state.get("prefilled"):
        direct = sum(1 for o in offers if o.get("source") != "web")
        await ctx.log("step", f"{len(offers)} offres prêtes à noter ({direct} sans appel LLM d'extraction)")
    return {"extracted": offers, "retry_urls": state.get("retry_urls", []) + retry}


async def score(state: WatchState, config) -> dict:
    """Notation par le modèle puissant, avec les extraits du profil trouvés par le RAG hybride.
    Chaque offre notée est envoyée en direct à l'interface."""
    ctx, watch = _rt(config)
    preferences = read_preferences()
    sem = asyncio.Semaphore(4)
    retry: list[str] = []
    extracted = state.get("extracted", [])
    done = 0
    if extracted:
        await ctx.progress("score", 0, len(extracted), "Notation selon ton profil")

    async def one(offer: dict) -> dict | None:
        nonlocal done
        query = f"{offer['title']} {' '.join(offer.get('skills', []))} {offer.get('summary', '')}"
        chunks = await profile_index.asearch(query, k=3)
        async with sem:
            try:
                result = await call_structured("score", state["system"],
                                               prompts.score_prompt(offer, chunks, preferences), OfferScore, ctx)
            except LLMConfigError:
                raise
            except (BudgetExceeded, LLMError) as exc:
                retry.append(offer["url"])
                if isinstance(exc, LLMError):
                    await ctx.log("warning", f"Notation impossible, offre gardée pour la prochaine fois : "
                                             f"{str(exc)[:180]}", title=offer["title"])
                return None
            finally:
                done += 1
                await ctx.progress("score", done, len(extracted), offer["title"])
        scored = {**offer, "score": max(0, min(100, int(result.score))), "reasons": result.reasons[:4],
                  "red_flags": result.red_flags[:3], "excluded": result.excluded}
        await ctx.offer(scored, kept=not scored["excluded"] and scored["score"] >= watch.config.score_minimum)
        return scored

    scored = [o for o in await asyncio.gather(*(one(o) for o in extracted)) if o]
    minimum = watch.config.score_minimum
    new_kept = [o for o in scored if not o["excluded"] and o["score"] >= minimum]
    new_near = [o for o in scored if not o["excluded"] and max(minimum - NEAR_MARGIN, 0) <= o["score"] < minimum]
    kept = sorted(state.get("kept", []) + new_kept, key=lambda o: o["score"], reverse=True)
    near = sorted(state.get("near", []) + new_near, key=lambda o: o["score"], reverse=True)
    if scored:
        await ctx.log("step", f"{len(new_kept)} offres retenues (score ≥ {watch.config.score_minimum})",
                      top=[{"title": o["title"], "score": o["score"]} for o in new_kept[:5]])
    ctx.stats["llm_failures"] += len(retry)
    return {"kept": kept, "near": near, "retry_urls": state.get("retry_urls", []) + retry,
            "last_round": {"results": len(state.get("results", [])), "new": len(state.get("candidates", [])),
                           "kept": len(new_kept)}}


def has_queries(state: WatchState, config) -> str:
    return "search" if state.get("queries") else "save"


def decide(state: WatchState, config) -> str:
    ctx, watch = _rt(config)
    if len(state.get("kept", [])) >= watch.config.max_resultats:
        return "save"
    if state.get("round", 0) + 1 >= settings.max_rounds:
        return "save"
    if state.get("pages_read", 0) >= settings.max_pages_per_run:
        return "save"
    if ctx.tokens_used() >= 0.75 * ctx.budget:
        return "save"
    return "refine"


async def next_round(state: WatchState, config) -> dict:
    ctx, _ = _rt(config)
    await ctx.log("step", "Résultats insuffisants : l'agent reformule ses requêtes")
    return {"round": state.get("round", 0) + 1}


async def save(state: WatchState, config) -> dict:
    ctx, watch = _rt(config)
    await ctx.progress("save", 0, 1, "Enregistrement")
    all_kept = state.get("kept", [])
    kept = all_kept[: watch.config.max_resultats]
    # Pas marquées comme vues : échecs passagers et offres au-delà de la limite (revues la prochaine fois).
    later = {normalize_url(u) for u in state.get("retry_urls", [])}
    later |= {normalize_url(o["url"]) for o in all_kept[watch.config.max_resultats:]}
    fields = ("url", "title", "company", "location", "contract", "remote", "salary", "skills", "summary",
              "contact", "published", "score", "reasons", "red_flags", "source", "query")
    near = state.get("near", [])[:15]  # offres proches du seuil : visibles dans l'onglet « Proches »
    payload = [{**{k: o.get(k) for k in fields}, "kept": True} for o in kept] + \
              [{**{k: o.get(k) for k in fields}, "kept": False} for o in near]
    result = {"saved": 0}
    if payload:
        result = await mcp_call("save_offers", {"watch": watch.slug, "run_id": ctx.run_id, "offers": payload})
    ctx.stats["offers_near"] = len(near)
    seen = [u for u in state.get("seen_this_run", []) if u not in later]
    if seen:
        await mcp_call("mark_seen", {"watch": watch.slug, "urls": seen})
    ctx.stats["kept_for_later"] = len(later)
    if later:
        await ctx.log("step", f"{len(later)} page(s) gardée(s) pour la prochaine exécution")
    ctx.stats["offers_saved"] = min(int(result.get("saved", 0)), len(kept))
    await ctx.log("step", f"{ctx.stats['offers_saved']} offres retenues et {len(near)} proches enregistrées via MCP")
    return {"kept": kept}


async def digest(state: WatchState, config) -> dict:
    ctx, watch = _rt(config)
    kept = state.get("kept", [])
    synthesis = ""
    if kept:
        try:
            synthesis = await call_text("digest", state["system"], prompts.digest_prompt(kept), ctx)
        except (LLMError, BudgetExceeded):
            synthesis = ""
    report = prompts.render_report(watch, kept, synthesis, dict(ctx.stats), ctx.run_id)
    path = settings.reports_dir / f"{datetime.now():%Y-%m-%d}-{watch.slug}-{ctx.run_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    await ctx.log("step", f"Rapport écrit : rapports/{path.name}")
    return {"report_path": str(path)}


async def notify(state: WatchState, config) -> dict:
    ctx, watch = _rt(config)
    kept = state.get("kept", [])
    if watch.config.notification == "telegram" and kept:
        if not telegram_enabled():
            await ctx.log("warning", "Telegram non configuré (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)")
        elif await send_telegram(prompts.telegram_message(watch, kept)):
            await ctx.log("step", "Notification Telegram envoyée")
    return {}


def build_watch_graph():
    graph = StateGraph(WatchState)
    for name, fn in [("load_context", load_context), ("plan_queries", plan_queries), ("search", search),
                     ("filter_seen", filter_seen), ("triage", triage), ("read_pages", read_pages),
                     ("extract", extract), ("score", score), ("next_round", next_round), ("save", save),
                     ("digest", digest), ("notify", notify)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "load_context")
    for a, b in [("load_context", "plan_queries"), ("search", "filter_seen"),
                 ("filter_seen", "triage"), ("triage", "read_pages"), ("read_pages", "extract"),
                 ("extract", "score"), ("next_round", "plan_queries"), ("save", "digest"),
                 ("digest", "notify"), ("notify", END)]:
        graph.add_edge(a, b)
    graph.add_conditional_edges("plan_queries", has_queries, {"search": "search", "save": "save"})
    graph.add_conditional_edges("score", decide, {"refine": "next_round", "save": "save"})
    return graph.compile()


watch_graph = build_watch_graph()
