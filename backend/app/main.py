"""API FastAPI de Radar : veilles, exécutions (SSE), offres, statistiques, assistant."""
import asyncio
import csv
import io
import json
import os
import logging
from datetime import datetime, timedelta, timezone
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import db, repo
from . import llm, secrets_store
from .agent.chat_graph import build_chat_graph, tool_preview
from .config import settings
from .providers import (PROVIDERS, TASK_LABELS, LLMSettings, describe_all, dumps_settings, load_llm_settings,
                        save_llm_settings)
from .runner import RunManager
from .scheduler import WatchScheduler
from .tools.profile_rag import profile_index
from .tools.sources import CONNECTORS, connector_configured
from .watches import (WATCH_TEMPLATE, check_slug, delete_watch, load_watch, load_watches, next_fire_times,
                      parse_watch, save_watch)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("radar.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    db.init_db()
    repo.mark_interrupted_runs()
    stack = AsyncExitStack()
    app.state.checkpointer = await stack.enter_async_context(
        AsyncSqliteSaver.from_conn_string(str(settings.data_dir / "checkpoints.db")))
    app.state.chat_graph = build_chat_graph(app.state.checkpointer)
    app.state.runner = RunManager()
    app.state.scheduler = WatchScheduler(app.state.runner)
    app.state.scheduler.start(asyncio.get_running_loop())
    profile_index.build_in_background()  # télécharge le modèle d'embeddings sans bloquer le démarrage
    asyncio.create_task(asyncio.to_thread(repo.cleanup, settings.page_cache_days, settings.search_cache_hours))
    yield
    app.state.scheduler.shutdown()
    await app.state.runner.shutdown()
    await stack.aclose()


app = FastAPI(title="Radar Veille API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])


class WatchBody(BaseModel):
    content: str = Field(max_length=20000)


class NewWatchBody(WatchBody):
    slug: str


class StatusBody(BaseModel):
    status: str


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field("default", max_length=64)


def _watch_out(watch, with_raw: bool = False) -> dict:
    cfg = watch.config
    runs = repo.list_runs(watch.slug, limit=10)
    offers = repo.list_offers(watch=watch.slug, limit=200)
    out = {
        "slug": watch.slug,
        "nom": cfg.nom if cfg else watch.slug,
        "valid": watch.valid,
        "error": watch.error,
        "actif": bool(cfg and cfg.actif),
        "planning": cfg.planning if cfg else None,
        "notification": cfg.notification if cfg else None,
        "score_minimum": cfg.score_minimum if cfg else None,
        "next_run": app.state.scheduler.next_run(watch.slug),
        "running": app.state.runner.is_running(watch.slug),
        "live": app.state.runner.live(watch.slug),
        "connecteurs": cfg.connecteurs if cfg else [],
        "last_run": runs[0] if runs else None,
        "history": [r["stats"].get("offers_saved", 0) for r in reversed(runs) if r["status"] != "running"],
        "offers_total": len(offers),
        "offers_new": sum(1 for o in offers if o["status"] == "new" and o["kept"]),
        "offers_near": sum(1 for o in offers if not o["kept"]),
        "updated_at": watch.updated_at,
    }
    if with_raw:
        out["content"] = watch.raw
    return out


def _get_watch_or_404(slug: str):
    try:
        watch = load_watch(slug)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if watch is None:
        raise HTTPException(404, "Veille introuvable")
    return watch


@app.get("/api/health")
def health():
    current = load_llm_settings()
    active = current.active_providers()
    return {"status": "ok", "routing": current.routing,
            "provider": PROVIDERS[active[0]].label if active else None, "providers_ready": len(active)}


# ------------------------------------------------------------------ veilles

@app.get("/api/watches")
def list_watches_route():
    return [_watch_out(w) for w in load_watches().values()]


@app.get("/api/watches/template")
def watch_template():
    return {"content": WATCH_TEMPLATE}


@app.post("/api/watches/validate")
def validate_watch(body: WatchBody):
    watch = parse_watch("validation", body.content)
    next_runs = []
    if watch.config:
        try:
            next_runs = [t.isoformat() for t in next_fire_times(watch.config.planning, 3)]
        except ValueError:
            pass
    return {"valid": watch.valid, "error": watch.error, "next_runs": next_runs, "body": watch.body,
            "config": watch.config.model_dump() if watch.config else None}


@app.get("/api/connectors")
def list_connectors():
    return [{"id": cid, "label": spec["label"], "description": spec["description"], "free": spec["free"],
             "key": spec["key"], "speed": spec["speed"], "scope": spec["scope"],
             "configured": connector_configured(cid)} for cid, spec in CONNECTORS.items()]


@app.get("/api/watches/{slug}")
def get_watch(slug: str):
    return _watch_out(_get_watch_or_404(slug), with_raw=True)


@app.post("/api/watches", status_code=201)
def create_watch(body: NewWatchBody):
    try:
        check_slug(body.slug)
        if load_watch(body.slug):
            raise HTTPException(409, "Une veille porte déjà cet identifiant")
        watch = save_watch(body.slug, body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    app.state.scheduler.sync()
    return _watch_out(watch, with_raw=True)


@app.put("/api/watches/{slug}")
def update_watch(slug: str, body: WatchBody):
    _get_watch_or_404(slug)
    try:
        watch = save_watch(slug, body.content)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    app.state.scheduler.sync()
    return _watch_out(watch, with_raw=True)


@app.delete("/api/watches/{slug}", status_code=204)
def remove_watch(slug: str):
    _get_watch_or_404(slug)
    delete_watch(slug)
    app.state.scheduler.sync()


@app.post("/api/watches/{slug}/run", status_code=202)
async def run_watch(slug: str):
    try:
        run_id = await app.state.runner.start(slug, trigger="manuel")
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run_id}


# ------------------------------------------------------------------ exécutions

@app.get("/api/runs")
def list_runs(watch: str | None = None, limit: int = 50):
    return repo.list_runs(watch, min(limit, 200))


@app.get("/api/runs/{run_id}")
def get_run(run_id: int):
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Exécution introuvable")
    report = Path(run["report_path"]) if run.get("report_path") else None
    run["report"] = report.read_text(encoding="utf-8") if report and report.exists() else None
    return run


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: int):
    if not app.state.runner.cancel(run_id):
        raise HTTPException(409, "Cette exécution n'est pas en cours")
    return {"cancelled": True}


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: int, request: Request):
    runner: RunManager = app.state.runner
    queue, past = runner.subscribe(run_id)

    async def events():
        if queue is None:  # exécution terminée : on rejoue l'historique stocké
            run = repo.get_run(run_id)
            if run is None:
                yield {"data": json.dumps({"type": "end", "status": "unknown"})}
                return
            for event in run["events"]:
                yield {"data": json.dumps(event, ensure_ascii=False)}
            yield {"data": json.dumps({"type": "end", "status": run["status"], "stats": run["stats"]})}
            return
        try:
            for event in past:
                yield {"data": json.dumps(event, ensure_ascii=False)}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    continue
                yield {"data": json.dumps(event, ensure_ascii=False)}
                if event.get("type") == "end":
                    break
        finally:
            runner.unsubscribe(run_id, queue)

    return EventSourceResponse(events(), ping=10)


# ------------------------------------------------------------------ offres et stats

@app.get("/api/offers")
def list_offers(watch: str | None = None, status: str | None = None, min_score: int = 0,
                q: str | None = None, limit: int = 100, kept: bool | None = None, sort: str = "recent"):
    return repo.list_offers(watch=watch, status=status, min_score=min_score, search=q, limit=limit,
                            kept=kept, sort=sort)


class SaveOfferBody(BaseModel):
    url: str = Field(max_length=2000)
    title: str = Field(min_length=1, max_length=300)
    company: str = ""
    location: str = ""
    contract: str = ""
    remote: str = ""
    salary: str = ""
    skills: list[str] = Field(default_factory=list)
    summary: str = ""
    score: int = 0
    reasons: list[str] = Field(default_factory=list)
    source: str = "assistant"
    query: str = ""


@app.post("/api/offers", status_code=201)
def save_offer(body: SaveOfferBody):
    """Sauvegarde d'une offre trouvée par la recherche express de l'assistant."""
    result = repo.save_offers("assistant", [{**body.model_dump(), "kept": True}])
    if not result["saved"]:
        raise HTTPException(409, "Offre déjà enregistrée ou invalide")
    return {"saved": True}


@app.get("/api/offers/export.csv")
def export_offers(watch: str | None = None, status: str | None = None, min_score: int = 0, q: str | None = None,
                  kept: bool | None = None, sort: str = "recent"):
    """Export tableur (séparateur « ; » et BOM UTF-8 : s'ouvre directement dans Excel en français)."""
    offers = repo.list_offers(watch=watch, status=status, min_score=min_score, search=q, limit=200, kept=kept,
                              sort=sort)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Score", "Poste", "Entreprise", "Lieu", "Contrat", "Télétravail", "Salaire", "Compétences",
                     "Statut", "Retenue", "Veille", "Source", "Requête", "Trouvée le", "Lien", "Résumé"])
    for o in offers:
        writer.writerow([o["score"], o["title"], o["company"], o["location"], o["contract"], o["remote"], o["salary"],
                         ", ".join(o["skills"]), o["status"], "oui" if o["kept"] else "proche", o["watch"],
                         o.get("source") or "", o.get("query") or "", (o["found_at"] or "")[:10], o["url"],
                         (o["summary"] or "").replace("\n", " ")])
    filename = f"radar-offres-{datetime.now():%Y-%m-%d}.csv"
    return Response("\ufeff" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.patch("/api/offers/{offer_id}")
def update_offer(offer_id: str, body: StatusBody):
    try:
        return repo.update_offer_status(offer_id, body.status)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class FileBody(BaseModel):
    content: str = Field(max_length=30000)


def _editable(name: str):
    files = {"cv": settings.profile_dir / "cv.md", "preferences": settings.profile_dir / "preferences.md",
             "agent": settings.instructions_dir / "AGENT.md", "scoring": settings.instructions_dir / "scoring.md"}
    if name not in files:
        raise HTTPException(404, "Fichier inconnu")
    return files[name]


@app.get("/api/files/{name}")
def read_file(name: str):
    path = _editable(name)
    return {"name": name, "path": str(path.relative_to(settings.config_dir)),
            "content": path.read_text(encoding="utf-8") if path.exists() else ""}


@app.put("/api/files/{name}")
def write_file(name: str, body: FileBody):
    path = _editable(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(body.content, encoding="utf-8")
    os.replace(tmp, path)
    if name in ("cv", "preferences"):
        profile_index.build_in_background()  # réindexation du RAG
    return read_file(name)


@app.get("/api/setup")
def setup_status():
    """État de la configuration, pour la liste « Bien démarrer » de l'interface."""
    current = load_llm_settings()
    watches = list(load_watches().values())
    cv = settings.profile_dir / "cv.md"
    runs = repo.list_runs(limit=50)
    return {
        "llm": bool(current.active_providers()),
        "profile": cv.exists() and len(cv.read_text(encoding="utf-8").strip()) > 200,
        "watch": any(w.valid for w in watches),
        "run": any(r["status"] == "success" for r in runs),
        "telegram": bool(secrets_store.get("telegram_bot_token") and secrets_store.get("telegram_chat_id")),
    }


@app.get("/api/stats")
def stats(days: int = 7):
    data = repo.global_stats(days)
    watches = load_watches().values()
    data["watches_active"] = sum(1 for w in watches if w.valid and w.config.actif)
    data["watches_total"] = len(watches)
    return data


@app.get("/api/stats/timeline")
def stats_timeline(days: int = 14):
    return repo.timeline(max(7, min(days, 60)))


# ------------------------------------------------------------------ modèles LLM

class TestBody(BaseModel):
    provider: str
    model: str = Field(min_length=1, max_length=120)


def _llm_payload() -> dict:
    current = load_llm_settings()
    return {"settings": dumps_settings(current), "providers": describe_all(current),
            "blocked": llm.blocked_status(), "tasks": TASK_LABELS}


class SecretBody(BaseModel):
    value: str = Field(min_length=1, max_length=500)


@app.get("/api/secrets")
def list_secrets():
    """État des clés : jamais leur valeur, seulement « définie », la provenance et les 4 derniers caractères."""
    return secrets_store.describe()


@app.put("/api/secrets/{name}")
def put_secret(name: str, body: SecretBody):
    try:
        secrets_store.set_secret(name, body.value)
    except KeyError as exc:
        raise HTTPException(404, "Clé inconnue") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    llm.clear_model_cache()
    llm.reset_breakers()
    return next(s for s in secrets_store.describe() if s["name"] == name)


@app.delete("/api/secrets/{name}")
def delete_secret(name: str):
    if name not in secrets_store.SECRETS:
        raise HTTPException(404, "Clé inconnue")
    secrets_store.delete_secret(name)
    llm.clear_model_cache()
    return next(s for s in secrets_store.describe() if s["name"] == name)


@app.get("/api/llm")
def llm_overview():
    return _llm_payload()


@app.put("/api/llm/settings")
def llm_update(body: LLMSettings):
    try:
        save_llm_settings(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    llm.clear_model_cache()
    llm.reset_breakers()
    return _llm_payload()


@app.post("/api/llm/test")
async def llm_test(body: TestBody):
    if body.provider not in PROVIDERS:
        raise HTTPException(404, "Fournisseur inconnu")
    return await llm.test_model(body.provider, body.model.strip())


@app.get("/api/llm/providers/{provider_id}/models")
async def llm_models(provider_id: str):
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise HTTPException(404, "Fournisseur inconnu")
    if not provider.configured():
        raise HTTPException(422, f"Clé manquante : {provider.key_env}")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if provider.kind == "anthropic":
                resp = await client.get("https://api.anthropic.com/v1/models?limit=100",
                                        headers={"x-api-key": provider.api_key(), "anthropic-version": "2023-06-01"})
            else:
                resp = await client.get(f"{provider.url().rstrip('/')}/models",
                                        headers={"Authorization": f"Bearer {provider.api_key()}"})
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"{provider.label} injoignable : {exc.__class__.__name__}") from exc
    if resp.status_code >= 400:
        raise HTTPException(502, f"{provider.label} a répondu {resp.status_code}")
    data = resp.json()
    items = data.get("data") or data.get("models") or []
    ids = sorted({str(m.get("id") or m.get("name") or "").removeprefix("models/") for m in items if isinstance(m, dict)})
    return {"models": [i for i in ids if i][:300]}


@app.get("/api/llm/stats")
def llm_stats(days: int = 7):
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))).isoformat(timespec="seconds")
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT provider, model, COUNT(*) AS calls, SUM(ok) AS ok, AVG(CASE WHEN ok = 1 THEN latency_ms END) AS latency,
                      SUM(tokens_in) AS tokens_in, SUM(tokens_out) AS tokens_out
               FROM llm_calls WHERE ts >= ? GROUP BY provider, model ORDER BY calls DESC""", (since,)).fetchall()
        tasks = conn.execute("SELECT task, COUNT(*) AS calls, SUM(ok) AS ok FROM llm_calls WHERE ts >= ? GROUP BY task",
                             (since,)).fetchall()
        errors = conn.execute("SELECT provider, model, error, ts FROM llm_calls WHERE ok = 0 AND ts >= ? "
                              "ORDER BY id DESC LIMIT 8", (since,)).fetchall()
    perf = llm.performance_table()
    return {
        "models": [{"provider": r["provider"], "label": PROVIDERS[r["provider"]].label if r["provider"] in PROVIDERS
                    else r["provider"], "model": r["model"], "calls": r["calls"],
                    "success": round((r["ok"] or 0) / r["calls"], 3), "latency_ms": int(r["latency"] or 0),
                    "tokens": int((r["tokens_in"] or 0) + (r["tokens_out"] or 0)),
                    "score": perf.get(f"{r['provider']}/{r['model']}", {}).get("score")} for r in rows],
        "tasks": [{"task": r["task"], "label": TASK_LABELS.get(r["task"], r["task"]), "calls": r["calls"],
                   "success": round((r["ok"] or 0) / r["calls"], 3)} for r in tasks],
        "errors": [dict(r) for r in errors],
    }


# ------------------------------------------------------------------ assistant

@app.post("/api/chat")
async def chat(body: ChatBody):
    try:
        llm.plan_targets("chat", 0)
    except llm.LLMConfigError as exc:
        raise HTTPException(503, str(exc)) from exc
    graph = app.state.chat_graph

    async def events():
        config = {"configurable": {"thread_id": body.thread_id}, "recursion_limit": 12}
        streamed = False
        try:
            async for mode, data in graph.astream({"messages": [HumanMessage(body.message)]}, config=config,
                                                  stream_mode=["messages", "updates"]):
                if mode == "messages":
                    chunk, meta = data
                    if meta.get("langgraph_node") == "agent" and isinstance(chunk, AIMessageChunk):
                        text = llm.content_text(chunk)
                        if text:
                            streamed = True
                            yield {"data": json.dumps({"type": "token", "content": text})}
                elif mode == "updates":
                    for node, update in (data or {}).items():
                        for message in (update or {}).get("messages", []):
                            if node == "agent" and isinstance(message, AIMessage):
                                for call in message.tool_calls:
                                    streamed = False
                                    yield {"data": json.dumps({"type": "tool_call", "name": call["name"],
                                                               "args": call["args"]}, ensure_ascii=False)}
                                # Fournisseur sans streaming de jetons : on envoie la réponse entière.
                                if not message.tool_calls and not streamed and (text := llm.content_text(message)):
                                    yield {"data": json.dumps({"type": "token", "content": text})}
                            elif node == "tools" and isinstance(message, ToolMessage):
                                yield {"data": json.dumps({"type": "tool_result", "name": message.name,
                                                           "preview": tool_preview(message.content)},
                                                          ensure_ascii=False)}
                                if message.name == "recherche_express":
                                    # Les offres trouvées s'affichent en cartes dans le chat
                                    try:
                                        found = json.loads(llm.content_text(message))
                                        yield {"data": json.dumps({"type": "offers", **found}, ensure_ascii=False)}
                                    except (json.JSONDecodeError, TypeError):
                                        pass
        except GraphRecursionError:
            yield {"data": json.dumps({"type": "error", "message": "Limite d'étapes atteinte (garde-fou)."})}
        except Exception as exc:  # noqa: BLE001
            log.exception("Erreur assistant")
            if isinstance(exc, llm.LLMError):
                message = str(exc)
            else:
                error = llm.classify(exc)
                message = f"{llm.KIND_LABELS.get(error.kind, 'Erreur')} : {error}"
            yield {"data": json.dumps({"type": "error", "message": message[:400]}, ensure_ascii=False)}
        yield {"data": json.dumps({"type": "done"})}

    return EventSourceResponse(events())
