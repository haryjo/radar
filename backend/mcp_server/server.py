"""Serveur MCP maison de Radar (FastMCP, transport streamable HTTP).

Utilisé par le graphe de veille et par l'agent conversationnel, et compatible avec tout client MCP
(Claude Desktop via mcp-remote, MCP Inspector...).
"""
import logging
from typing import Literal

import httpx
from mcp.server.fastmcp import FastMCP

from app import db, repo
from app.config import settings
from app.watches import load_watch, load_watches, read_instructions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# Le SDK journalise en ERROR la simple fermeture d'une session par le client (ClosedResourceError) :
# c'est le fonctionnement normal du transport HTTP, on masque ce bruit.
logging.getLogger("mcp.server.streamable_http").setLevel(logging.CRITICAL)

_kwargs = {"host": settings.mcp_host, "port": settings.mcp_port}
try:  # le serveur tourne derrière le réseau Docker : protection DNS rebinding gérée par le réseau privé
    from mcp.server.transport_security import TransportSecuritySettings
    _kwargs["transport_security"] = TransportSecuritySettings(enable_dns_rebinding_protection=False)
except ImportError:
    pass

mcp = FastMCP(
    "radar-veille",
    instructions="Serveur de Radar : veilles d'offres définies en Markdown, offres trouvées, "
                 "historique des URLs vues et retours de l'utilisateur.",
    **_kwargs,
)


# ------------------------------------------------------------------ outils

@mcp.tool()
def list_watches() -> list[dict]:
    """Liste les veilles (fichiers .md) avec leur statut et leur planning."""
    return [{"slug": w.slug, "nom": w.config.nom if w.config else w.slug, "valide": w.valid,
             "actif": bool(w.config and w.config.actif), "planning": w.config.planning if w.config else None,
             "erreur": w.error} for w in load_watches().values()]


@mcp.tool()
def filter_unseen(watch: str, urls: list[str]) -> list[str]:
    """Veille incrémentale : renvoie uniquement les URLs jamais traitées par cette veille."""
    return repo.filter_unseen(watch, urls[:500])


@mcp.tool()
def mark_seen(watch: str, urls: list[str]) -> dict:
    """Marque des URLs comme traitées pour qu'elles ne soient plus jamais relues."""
    return {"added": repo.mark_seen(watch, urls[:500])}


@mcp.tool()
def save_offers(watch: str, offers: list[dict], run_id: int | None = None) -> dict:
    """Enregistre des offres scorées. Les données personnelles sont filtrées côté serveur."""
    if load_watch(watch) is None:
        raise ValueError(f"Veille inconnue : {watch}")
    return repo.save_offers(watch, offers[:60], run_id)


@mcp.tool()
def get_new_offers(watch: str | None = None, min_score: int = 0, limit: int = 20) -> list[dict]:
    """Offres au statut 'new' (pas encore traitées par l'utilisateur), les plus récentes d'abord."""
    return [_compact(o) for o in repo.list_offers(watch=watch, status="new", min_score=min_score, limit=limit,
                                                  kept=True, sort="score")]


@mcp.tool()
def search_offers(text: str, limit: int = 20) -> list[dict]:
    """Recherche plein texte dans toutes les offres trouvées (titre, entreprise, résumé, compétences)."""
    return [_compact(o) for o in repo.list_offers(search=text, limit=limit)]


@mcp.tool()
def update_offer_status(offer_id: str, status: Literal["new", "interesse", "ignore", "postule", "entretien"]) -> dict:
    """Change le statut d'une offre. Ces retours alimentent la mémoire long terme de l'agent."""
    return _compact(repo.update_offer_status(offer_id, status))


@mcp.tool()
def get_feedback_summary(watch: str) -> dict:
    """Mémoire long terme : entreprises et compétences appréciées ou ignorées sur cette veille."""
    return repo.feedback_summary(watch)


@mcp.tool()
async def run_watch(watch: str) -> dict:
    """Déclenche immédiatement l'exécution d'une veille (via l'API Radar)."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{settings.api_url}/api/watches/{watch}/run")
    if resp.status_code >= 400:
        raise ValueError(resp.json().get("detail", resp.text))
    return resp.json()


def _compact(offer: dict) -> dict:
    keys = ("id", "watch", "title", "company", "location", "contract", "remote", "score", "summary",
            "reasons", "status", "url", "found_at", "source", "kept")
    return {k: offer.get(k) for k in keys}


# ------------------------------------------------------------------ resources

@mcp.resource("watch://{slug}")
def watch_resource(slug: str) -> str:
    """Contenu Markdown brut d'une veille."""
    watch = load_watch(slug)
    if watch is None:
        raise ValueError("Veille introuvable")
    return watch.raw


@mcp.resource("offers://new")
def new_offers_resource() -> str:
    """Nouvelles offres au format Markdown."""
    offers = repo.list_offers(status="new", limit=30)
    if not offers:
        return "Aucune nouvelle offre."
    return "\n".join(f"- [{o['score']}] {o['title']} ({o['company'] or '?'}) : {o['url']}" for o in offers)


# ------------------------------------------------------------------ prompts

@mcp.prompt()
def veille(slug: str) -> str:
    """Transforme un fichier de veille en prompt réutilisable dans n'importe quel client MCP."""
    watch = load_watch(slug)
    if watch is None or not watch.valid:
        return f"La veille {slug} est introuvable ou invalide."
    return (f"{read_instructions()}\n\n# Veille : {watch.config.nom}\n{watch.body}\n\n"
            "Utilise get_new_offers pour lister les offres trouvées par cette veille, puis résume les meilleures.")


if __name__ == "__main__":
    settings.ensure_dirs()
    db.init_db()
    mcp.run(transport="streamable-http")
