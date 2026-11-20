"""Opérations métier sur les offres et les exécutions. Utilisé par l'API et par le serveur MCP."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import db
from .guardrails import redact_pii

OFFER_STATUSES = ("new", "interesse", "ignore", "postule", "entretien")
POSITIVE_STATUSES = ("interesse", "postule", "entretien")
OFFER_TEXT_FIELDS = {"title": 200, "company": 120, "location": 120, "contract": 60, "remote": 60,
                     "salary": 80, "summary": 800, "contact": 200, "published": 40}


def offer_id(watch: str, url: str) -> str:
    return hashlib.sha256(f"{watch}|{db.normalize_url(url)}".encode()).hexdigest()[:24]


def _row_to_offer(row) -> dict:
    offer = dict(row)
    offer["kept"] = bool(offer.get("kept", 1))
    for key in ("skills", "reasons", "red_flags"):
        offer[key] = json.loads(offer[key]) if offer.get(key) else []
    return offer


# ---------- Veille incrémentale ----------

def filter_unseen(watch: str, urls: list[str]) -> list[str]:
    if not urls:
        return []
    hashes = {db.url_hash(u): u for u in urls}
    with db.get_conn() as conn:
        placeholders = ",".join("?" * len(hashes))
        seen = {r["url_hash"] for r in conn.execute(
            f"SELECT url_hash FROM seen_urls WHERE watch = ? AND url_hash IN ({placeholders})",
            (watch, *hashes.keys()))}
    return [u for h, u in hashes.items() if h not in seen]


def mark_seen(watch: str, urls: list[str]) -> int:
    rows = [(db.url_hash(u), watch, u, db.now_iso()) for u in urls if u]
    with db.get_conn() as conn:
        before = conn.total_changes
        conn.executemany("INSERT OR IGNORE INTO seen_urls (url_hash, watch, url, first_seen) VALUES (?, ?, ?, ?)", rows)
        return conn.total_changes - before


# ---------- Offres ----------

def save_offers(watch: str, offers: list[dict], run_id: int | None = None) -> dict:
    saved, skipped = 0, 0
    with db.get_conn() as conn:
        for raw in offers:
            url = str(raw.get("url", ""))
            if not url.startswith(("http://", "https://")) or not raw.get("title"):
                skipped += 1
                continue
            values = {k: str(raw.get(k) or "")[:limit] for k, limit in OFFER_TEXT_FIELDS.items()}
            values["contact"] = redact_pii(values["contact"])
            values["summary"] = redact_pii(values["summary"])
            score = max(0, min(100, int(raw.get("score") or 0)))
            cursor = conn.execute(
                """INSERT OR IGNORE INTO offers (id, watch, url, title, company, location, contract, remote, salary,
                   skills, summary, contact, published, score, reasons, red_flags, status, found_at, run_id, source,
                   kept, query)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?)""",
                (offer_id(watch, url), watch, url, values["title"], values["company"], values["location"],
                 values["contract"], values["remote"], values["salary"],
                 json.dumps([str(s)[:40] for s in (raw.get("skills") or [])][:15], ensure_ascii=False),
                 values["summary"], values["contact"], values["published"], score,
                 json.dumps([str(s)[:200] for s in (raw.get("reasons") or [])][:5], ensure_ascii=False),
                 json.dumps([str(s)[:200] for s in (raw.get("red_flags") or [])][:5], ensure_ascii=False),
                 db.now_iso(), run_id, str(raw.get("source") or "web")[:20],
                 0 if raw.get("kept") is False else 1, str(raw.get("query") or "")[:200]))
            saved += cursor.rowcount
            skipped += 1 - cursor.rowcount
    return {"saved": saved, "skipped": skipped}


def list_offers(watch: str | None = None, status: str | None = None, min_score: int = 0,
                search: str | None = None, limit: int = 50, kept: bool | None = None,
                sort: str = "recent") -> list[dict]:
    """kept=True : offres retenues ; kept=False : offres proches du seuil ; None : toutes."""
    query, params = "SELECT * FROM offers WHERE score >= ?", [min_score]
    if kept is not None:
        query += " AND kept = ?"
        params.append(int(kept))
    if watch:
        query += " AND watch = ?"
        params.append(watch)
    if status:  # un statut ou plusieurs séparés par des virgules (ex. « postule,entretien »)
        statuses = [s for s in status.split(",") if s in OFFER_STATUSES]
        query += f" AND status IN ({','.join('?' * len(statuses))})" if statuses else " AND 0"
        params.extend(statuses)
    if search:
        query += " AND (title LIKE ? OR company LIKE ? OR summary LIKE ? OR skills LIKE ?)"
        params += [f"%{search}%"] * 4
    query += " ORDER BY score DESC, found_at DESC LIMIT ?" if sort == "score" else \
        " ORDER BY found_at DESC, score DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    with db.get_conn() as conn:
        return [_row_to_offer(r) for r in conn.execute(query, params)]


def update_offer_status(offer_id_: str, status: str) -> dict:
    if status not in OFFER_STATUSES:
        raise ValueError(f"Statut invalide. Valeurs possibles : {', '.join(OFFER_STATUSES)}")
    with db.get_conn() as conn:
        cursor = conn.execute("UPDATE offers SET status = ? WHERE id = ?", (status, offer_id_))
        if cursor.rowcount == 0:
            raise KeyError("Offre introuvable")
        row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id_,)).fetchone()
    return _row_to_offer(row)


def feedback_summary(watch: str) -> dict:
    """Mémoire long terme : ce que l'utilisateur a aimé ou ignoré sur cette veille."""
    with db.get_conn() as conn:
        rows = conn.execute("SELECT status, company, skills FROM offers WHERE watch = ? AND status != 'new'",
                            (watch,)).fetchall()
    liked_companies, ignored_companies, liked_skills = Counter(), Counter(), Counter()
    statuses = Counter()
    for row in rows:
        statuses[row["status"]] += 1
        skills = json.loads(row["skills"] or "[]")
        if row["status"] in POSITIVE_STATUSES:
            if row["company"]:
                liked_companies[row["company"]] += 1
            liked_skills.update(s.lower() for s in skills)
        elif row["status"] == "ignore" and row["company"]:
            ignored_companies[row["company"]] += 1
    return {
        "total_feedback": len(rows),
        "statuses": dict(statuses),
        "liked_companies": [c for c, _ in liked_companies.most_common(5)],
        "ignored_companies": [c for c, _ in ignored_companies.most_common(8)],
        "liked_skills": [s for s, _ in liked_skills.most_common(8)],
    }


# ---------- Exécutions ----------

def create_run(watch: str, trigger: str) -> int:
    with db.get_conn() as conn:
        cursor = conn.execute("INSERT INTO runs (watch, trigger, status, started_at) VALUES (?, ?, 'running', ?)",
                              (watch, trigger, db.now_iso()))
        return int(cursor.lastrowid)


def finish_run(run_id: int, status: str, stats: dict, events: list[dict],
               report_path: str | None, error: str | None) -> None:
    with db.get_conn() as conn:
        conn.execute("""UPDATE runs SET status = ?, finished_at = ?, stats = ?, events = ?, report_path = ?, error = ?
                        WHERE id = ?""",
                     (status, db.now_iso(), json.dumps(stats), json.dumps(events, ensure_ascii=False),
                      report_path, error, run_id))


def _row_to_run(row, with_events: bool = False) -> dict:
    run = dict(row)
    run["stats"] = json.loads(run["stats"]) if run.get("stats") else {}
    run["events"] = json.loads(run["events"]) if with_events and run.get("events") else []
    return run


def list_runs(watch: str | None = None, limit: int = 50) -> list[dict]:
    query, params = "SELECT * FROM runs", []
    if watch:
        query += " WHERE watch = ?"
        params.append(watch)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with db.get_conn() as conn:
        return [_row_to_run(r) for r in conn.execute(query, params)]


def get_run(run_id: int) -> dict | None:
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return _row_to_run(row, with_events=True) if row else None


def mark_interrupted_runs() -> None:
    """Au démarrage, une exécution restée 'running' a été interrompue par un redémarrage."""
    with db.get_conn() as conn:
        conn.execute("UPDATE runs SET status = 'error', error = 'Interrompue par un redémarrage', finished_at = ? "
                     "WHERE status = 'running'", (db.now_iso(),))


def timeline(days: int = 14) -> dict:
    """Données des graphiques : activité par jour (fuseau local) et distribution des scores."""
    from zoneinfo import ZoneInfo
    from .config import settings
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    keys = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    buckets = {k: Counter() for k in keys}
    since = (datetime.now(timezone.utc) - timedelta(days=days + 1)).isoformat(timespec="seconds")

    def local_day(iso: str) -> str:
        return datetime.fromisoformat(iso).astimezone(tz).date().isoformat()

    with db.get_conn() as conn:
        for row in conn.execute("SELECT found_at FROM offers WHERE found_at >= ?", (since,)):
            day = local_day(row["found_at"])
            if day in buckets:
                buckets[day]["offers"] += 1
        for row in conn.execute("SELECT started_at, stats FROM runs WHERE started_at >= ? AND status != 'running'",
                                (since,)):
            day = local_day(row["started_at"])
            if day not in buckets:
                continue
            stats = json.loads(row["stats"] or "{}")
            b = buckets[day]
            b["runs"] += 1
            b["tokens"] += stats.get("tokens_in", 0) + stats.get("tokens_out", 0)
            b["already_seen"] += stats.get("already_seen", 0)
            b["cache_hits"] += sum(stats.get(k, 0) for k in ("llm_cache_hits", "page_cache_hits",
                                                             "search_cache_hits", "semantic_cache_hits"))
        scores = [r["score"] or 0 for r in conn.execute("SELECT score FROM offers")]

    edges = [(0, 49, "< 50"), (50, 59, "50"), (60, 69, "60"), (70, 79, "70"), (80, 89, "80"), (90, 100, "90+")]
    return {
        "days": [{"date": k, **{f: buckets[k][f] for f in ("offers", "runs", "tokens", "already_seen", "cache_hits")}}
                 for k in keys],
        "scores": [{"label": label, "count": sum(lo <= s <= hi for s in scores)} for lo, hi, label in edges],
    }


def global_stats(days: int = 7) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with db.get_conn() as conn:
        runs = [json.loads(r["stats"] or "{}") for r in
                conn.execute("SELECT stats FROM runs WHERE started_at >= ? AND status != 'running'", (since,))]
        new_offers = conn.execute("SELECT COUNT(*) FROM offers WHERE status = 'new' AND kept = 1").fetchone()[0]
        week_offers = conn.execute("SELECT COUNT(*) FROM offers WHERE found_at >= ?", (since,)).fetchone()[0]
    total = Counter()
    for stats in runs:
        total.update({k: v for k, v in stats.items() if isinstance(v, (int, float))})
    cache_hits = total["llm_cache_hits"] + total["page_cache_hits"] + total["search_cache_hits"] + total["semantic_cache_hits"]
    lookups = cache_hits + total["llm_calls"] + total["pages_fetched"] + total["web_searches"]
    return {
        "days": days,
        "runs": len(runs),
        "new_offers": new_offers,
        "offers_found": week_offers,
        "tokens": total["tokens_in"] + total["tokens_out"],
        "cache_hit_rate": round(cache_hits / lookups, 3) if lookups else 0,
        "already_seen_skipped": total["already_seen"],
        "compression_rate": round(1 - total["sent_chars"] / total["html_chars"], 3) if total["html_chars"] else 0,
    }


# ---------- Entretien ----------

def cleanup(page_days: int, search_hours: int, keep_days: int = 45) -> dict:
    """Supprime les caches expirés et l'historique ancien : la base ne grossit plus sans limite."""
    now = datetime.now(timezone.utc)
    iso = lambda delta: (now - delta).isoformat(timespec="seconds")  # noqa: E731
    with db.get_conn() as conn:
        removed = {
            "page_cache": conn.execute("DELETE FROM page_cache WHERE fetched_at < ?",
                                       (iso(timedelta(days=page_days)),)).rowcount,
            "search_cache": conn.execute("DELETE FROM search_cache WHERE fetched_at < ?",
                                         (iso(timedelta(hours=search_hours)),)).rowcount,
            "llm_cache": conn.execute("DELETE FROM llm_cache WHERE created_at < ?",
                                      (iso(timedelta(days=keep_days)),)).rowcount,
            "llm_calls": conn.execute("DELETE FROM llm_calls WHERE ts < ?", (iso(timedelta(days=keep_days)),)).rowcount,
            "runs": conn.execute("UPDATE runs SET events = NULL WHERE started_at < ? AND events IS NOT NULL",
                                 (iso(timedelta(days=keep_days)),)).rowcount,
        }
    with db.get_conn() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return removed
