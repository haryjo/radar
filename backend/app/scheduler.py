"""Planification : une tâche cron par fichier de veille, rechargée à chaque modification des .md."""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from .config import settings
from .runner import RunManager
from .tools.profile_rag import profile_index
from .watches import load_watches, tz

log = logging.getLogger("radar.scheduler")


class _MarkdownHandler(FileSystemEventHandler):
    def __init__(self, owner: "WatchScheduler") -> None:
        self.owner = owner

    def on_any_event(self, event) -> None:
        path = str(getattr(event, "dest_path", "") or event.src_path)
        if path.endswith(".md"):
            self.owner.notify_change(path)


class WatchScheduler:
    def __init__(self, runner: RunManager) -> None:
        self.runner = runner
        self.scheduler = AsyncIOScheduler(timezone=tz())
        self.observer = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, asyncio.TimerHandle] = {}

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.sync()
        # Entretien quotidien de la base (caches expirés, historique ancien)
        self.scheduler.add_job(self._maintenance, CronTrigger(hour=3, minute=17, timezone=tz()), id="__maintenance__",
                               replace_existing=True, coalesce=True)
        self.scheduler.start()
        self.observer = PollingObserver(timeout=2) if settings.watch_polling else Observer()
        self.observer.schedule(_MarkdownHandler(self), str(settings.config_dir), recursive=True)
        self.observer.start()
        log.info("Planificateur démarré, surveillance de %s", settings.config_dir)

    def shutdown(self) -> None:
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)
        self.scheduler.shutdown(wait=False)

    def notify_change(self, path: str) -> None:
        """Appelé depuis le thread watchdog : on repasse sur la boucle asyncio avec un anti-rebond d'1 s."""
        if self.loop is None:
            return
        kind = "profile" if "/profil/" in path.replace("\\", "/") else "watches"
        self.loop.call_soon_threadsafe(self._debounce, kind)

    def _debounce(self, kind: str) -> None:
        if handle := self._pending.get(kind):
            handle.cancel()
        action = self._reindex_profile if kind == "profile" else self.sync
        self._pending[kind] = self.loop.call_later(1.0, action)

    def _reindex_profile(self) -> None:
        log.info("Profil modifié : réindexation")
        profile_index.build_in_background()

    def sync(self) -> None:
        watches = load_watches()
        wanted = set()
        for slug, watch in watches.items():
            if not watch.valid:
                log.warning("Veille %s ignorée : %s", slug, watch.error)
                continue
            if not watch.config.actif:
                continue
            wanted.add(slug)
            self.scheduler.add_job(self._run_job, CronTrigger.from_crontab(watch.config.planning, timezone=tz()),
                                   id=slug, args=[slug], replace_existing=True, max_instances=1,
                                   coalesce=True, misfire_grace_time=900)
        for job in self.scheduler.get_jobs():
            if job.id not in wanted and not job.id.startswith("__"):
                job.remove()
        log.info("Veilles planifiées : %s", ", ".join(sorted(wanted)) or "aucune")

    async def _maintenance(self) -> None:
        from . import repo
        removed = await asyncio.to_thread(repo.cleanup, settings.page_cache_days, settings.search_cache_hours)
        log.info("Entretien de la base : %s", removed)

    async def _run_job(self, slug: str) -> None:
        try:
            await self.runner.start(slug, trigger="planning")
        except Exception as exc:  # noqa: BLE001
            log.warning("Exécution planifiée de %s ignorée : %s", slug, exc)

    def next_run(self, slug: str) -> str | None:
        job = self.scheduler.get_job(slug)
        return job.next_run_time.isoformat() if job and job.next_run_time else None
