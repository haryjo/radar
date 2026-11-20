"""Agent conversationnel : le LLM choisit lui-même ses outils.

Outils : recherche web, lecture de page, profil (RAG) et 4 outils du serveur MCP en lecture seule.
Les outils MCP sont enveloppés ici et renvoient toujours du texte : le format reste identique quel que
soit le fournisseur (certains refusent les contenus d'outil structurés).
"""
import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage, trim_messages
from langchain_core.tools import tool
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from ..guardrails import SYSTEM_RULES, wrap_untrusted
from ..llm import chat_runnable
from ..quick_search import quick_search, to_tool_text
from ..tools.mcp_client import mcp_call
from ..tools.profile_rag import profile_index
from ..tools.web import read_page, search_web
from ..watches import read_instructions

log = logging.getLogger("radar.chat")
MAX_HISTORY_TOKENS = 6000

CHAT_SYSTEM = SYSTEM_RULES + """

# Rôle
Tu es Radar, l'assistant de veille d'offres de l'utilisateur. Réponds en français, de façon concise et structurée.
- Pour chercher des offres maintenant (sans veille), utilise recherche_express, puis résume les meilleures
  en citant leur score et leur lien. Les offres s'affichent aussi en cartes dans l'interface.
- Pour les offres déjà trouvées par les veilles, utilise nouvelles_offres ou chercher_offres.
- Pour une information précise sur une page, utilise lire_page ; pour une recherche web libre, recherche_web.
- N'appelle QUE les outils fournis, avec leur nom exact.
- Pour juger l'adéquation avec le candidat, utilise chercher_profil.
- Cite toujours l'URL source d'une offre. N'invente jamais d'offre."""


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)[:12000]


@tool
async def recherche_web(requete: str) -> str:
    """Recherche web (DuckDuckGo). Renvoie titres, extraits et URLs."""
    try:
        results = await search_web(requete, max_results=6)
    except Exception as exc:  # noqa: BLE001
        return f"Recherche indisponible : {exc}"
    listing = "\n".join(f"- {r['title']} | {r['snippet'][:200]} | {r['url']}" for r in results) or "Aucun résultat"
    return wrap_untrusted(listing, "recherche web")[0]


@tool
async def lire_page(url: str) -> str:
    """Lit le contenu principal d'une page web (offre d'emploi, page carrières)."""
    page = await read_page(url, max_chars=4000)
    if page.get("error"):
        return f"Lecture impossible : {page['error']}"
    return wrap_untrusted(f"{page['title']}\n\n{page['content']}", url)[0]


@tool
async def chercher_profil(question: str) -> str:
    """Cherche dans le profil du candidat (CV, préférences) les passages utiles."""
    chunks = await profile_index.asearch(question, k=4)
    return "\n---\n".join(c["text"] for c in chunks) or "Profil vide ou index indisponible"


@tool
async def nouvelles_offres(veille: str = "", score_minimum: int = 0, limite: int = 10) -> str:
    """Offres non encore traitées trouvées par les veilles (serveur MCP). veille : identifiant optionnel."""
    return _json(await mcp_call("get_new_offers", {"watch": veille or None, "min_score": score_minimum,
                                                   "limit": max(1, min(limite, 30))}))


@tool
async def chercher_offres(texte: str, limite: int = 10) -> str:
    """Recherche plein texte dans toutes les offres trouvées (titre, entreprise, compétences)."""
    return _json(await mcp_call("search_offers", {"text": texte, "limit": max(1, min(limite, 30))}))


@tool
async def lister_veilles() -> str:
    """Liste les veilles configurées (fichiers Markdown) avec leur statut."""
    return _json(await mcp_call("list_watches", {}))


@tool
async def retours_utilisateur(veille: str) -> str:
    """Mémoire long terme : entreprises et compétences appréciées ou ignorées sur une veille."""
    return _json(await mcp_call("get_feedback_summary", {"watch": veille}))


@tool
async def recherche_express(requete: str, localisation: str = "", sources: list[str] | None = None) -> str:
    """Recherche d'offres immédiate, sans créer de veille : interroge en parallèle les API d'emploi et le web,
    puis note chaque offre selon le profil. À utiliser quand l'utilisateur veut chercher des offres maintenant.
    sources possibles : web, jobicy, himalayas, remoteok, arbeitnow (toutes par défaut)."""
    result = await quick_search(requete, localisation, sources)
    return to_tool_text(result)


# Garde-fou : aucun outil d'écriture n'est exposé à la conversation.
TOOLS = [recherche_express, recherche_web, lire_page, chercher_profil, nouvelles_offres, chercher_offres,
         lister_veilles, retours_utilisateur]
TOOL_NAMES = ", ".join(t.name for t in TOOLS)
INVALID_TOOL_MARKERS = ("tool call validation", "not in request.tools", "tool_use_failed",
                        "failed to call a function", "invalid tool", "unknown tool")


def _count_tokens(messages) -> int:
    try:
        from langchain_core.messages.utils import count_tokens_approximately
        return count_tokens_approximately(messages)
    except ImportError:
        return sum(len(str(m.content)) // 4 for m in messages)


def build_chat_graph(checkpointer):
    system = SystemMessage(CHAT_SYSTEM + "\n\n# Instructions générales\n" + read_instructions())

    async def agent(state: MessagesState):
        # Le modèle est résolu à chaque tour : un changement de réglages s'applique immédiatement.
        model, _ = chat_runnable(TOOLS)
        history = trim_messages(state["messages"], max_tokens=MAX_HISTORY_TOKENS, strategy="last",
                                token_counter=_count_tokens, start_on="human", include_system=False)
        messages = [system, *history]
        for attempt in range(3):
            try:
                return {"messages": [await model.ainvoke(messages)]}
            except Exception as exc:  # noqa: BLE001
                # Le modèle a inventé un outil (ex. « ouvrir_page ») : on lui rappelle la liste exacte.
                if attempt == 2 or not any(m in str(exc).lower() for m in INVALID_TOOL_MARKERS):
                    raise
                log.warning("Outil inexistant demandé par le modèle, nouvel essai : %s", str(exc)[:160])
                messages = [*messages, HumanMessage(
                    f"(Note système) Ton précédent appel d'outil était invalide. Outils disponibles, noms exacts : "
                    f"{TOOL_NAMES}. Réessaie avec l'un d'eux, ou réponds directement sans outil.")]

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS, handle_tool_errors=True))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)


def tool_preview(content) -> str:
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
    return text[:240]
