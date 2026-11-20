"""Exécution des veilles en arrière-plan, avec diffusion des événements en direct (SSE)."""
import asyncio
import logging
import time

from . import repo
from .agent.watch_graph import watch_graph
from .config import settings
from .context import RunContext
from .watches import load_watch

log = logging.getLogger("radar.runner")


class RunManager:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._contexts: dict[int, RunContext] = {}
        self._subscribers: dict[int, list[asyncio.Queue]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._by_run: dict[int, asyncio.Task] = {}
        self._finished: set[int] = set()

    def is_running(self, slug: str) -> bool:
        lock = self._locks.get(slug)
        return bool(lock and lock.locked())

    async def start(self, slug: str, trigger: str = "manuel") -> int:
        watch = load_watch(slug)
        if watch is None:
            raise KeyError("Veille introuvable")
        if not watch.valid:
            raise ValueError(f"Veille invalide : {watch.error}")
        if self.is_running(slug):
            raise RuntimeError("Cette veille est déjà en cours d'exécution")
        lock = self._locks.setdefault(slug, asyncio.Lock())
        await lock.acquire()
        try:
            run_id = repo.create_run(slug, trigger)
        except Exception:
            lock.release()
            raise
        ctx = RunContext(watch=slug, run_id=run_id,
                         budget=watch.config.budget_tokens or settings.token_budget_per_run,
                         emit=lambda event: self._publish(run_id, event))
        self._contexts[run_id] = ctx
        task = asyncio.create_task(self._execute(run_id, watch, ctx, lock))
        self._tasks.add(task)
        self._by_run[run_id] = task
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(lambda _t, rid=run_id: self._by_run.pop(rid, None))
        return run_id

    async def _execute(self, run_id, watch, ctx: RunContext, lock: asyncio.Lock) -> None:
        started = time.monotonic()
        status, error, report_path = "success", None, None
        try:
            await ctx.log("start", f"Démarrage de la veille « {watch.config.nom} »")
            final = await watch_graph.ainvoke({}, config={"configurable": {"ctx": ctx, "watch": watch},
                                                          "recursion_limit": 60})
            report_path = final.get("report_path")
        except asyncio.CancelledError:
            status, error = "cancelled", "Arrêtée par l'utilisateur"
            await ctx.log("warning", "Exécution arrêtée par l'utilisateur : rien n'a été marqué comme vu")
        except Exception as exc:  # noqa: BLE001
            log.exception("Échec de la veille %s", watch.slug)
            status, error = "error", str(exc)[:500]
            await ctx.log("error", f"Échec : {error}")
        finally:
            ctx.stats["duration_s"] = round(time.monotonic() - started, 1)
            repo.finish_run(run_id, status, dict(ctx.stats), ctx.events, report_path, error)
            self._finished.add(run_id)
            await self._publish(run_id, {"type": "end", "status": status, "stats": dict(ctx.stats)})
            lock.release()
            asyncio.get_running_loop().call_later(60, self._cleanup, run_id)

    def live(self, slug: str) -> dict | None:
        """Avancement de l'exécution en cours d'une veille (pour les cartes et le tableau de bord)."""
        for run_id, ctx in self._contexts.items():
            if ctx.watch == slug and run_id not in self._finished:
                return {"run_id": run_id, "progress": ctx.progress_state,
                        "offers_kept": sum(1 for o in ctx.live_offers if o["kept"])}
        return None

    def cancel(self, run_id: int) -> bool:
        task = self._by_run.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def shutdown(self) -> None:
        """Arrêt du serveur : les exécutions en cours sont annulées proprement."""
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=5)

    async def _publish(self, run_id: int, event: dict) -> None:
        for queue in self._subscribers.get(run_id, []):
            queue.put_nowait(event)

    def _cleanup(self, run_id: int) -> None:
        self._contexts.pop(run_id, None)
        self._subscribers.pop(run_id, None)
        self._finished.discard(run_id)

    def subscribe(self, run_id: int) -> tuple[asyncio.Queue | None, list[dict]]:
        """Renvoie (file d'événements live, événements déjà émis). File None si l'exécution est terminée."""
        ctx = self._contexts.get(run_id)
        if ctx is None or run_id in self._finished:
            return None, []
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(run_id, []).append(queue)
        replay = list(ctx.events) + list(ctx.live_offers)
        if ctx.progress_state:
            replay.append(ctx.progress_state)
        return queue, replay

    def unsubscribe(self, run_id: int, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(run_id, [])
        if queue in subscribers:
            subscribers.remove(queue)
