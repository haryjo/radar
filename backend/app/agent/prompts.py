"""Construction des prompts. Ordre stable : règles système, instructions .md, veille, mémoire.
Un préfixe identique d'un appel à l'autre profite du cache de prompt des fournisseurs."""
import json
from datetime import datetime

from ..guardrails import SYSTEM_RULES, wrap_untrusted
from ..notify import escape
from ..watches import Watch


def build_system_prompt(instructions: str, watch: Watch, feedback: dict | None) -> str:
    cfg = watch.config
    params = [f"- Localisation : {cfg.localisation}" if cfg.localisation else "",
              f"- Fraîcheur : offres publiées depuis moins de {cfg.fraicheur_jours} jours",
              f"- Mots-clés : {', '.join(cfg.mots_cles)}" if cfg.mots_cles else "",
              f"- Sources suggérées : {', '.join(cfg.sources)}" if cfg.sources else "",
              f"- Exclure : {', '.join(cfg.exclure)}" if cfg.exclure else "",
              f"- Score minimum pour retenir une offre : {cfg.score_minimum}/100"]
    parts = [SYSTEM_RULES,
             "# Instructions générales\n" + (instructions or "(aucune)"),
             f"# Veille active : {cfg.nom}\n" + "\n".join(p for p in params if p) + "\n\n" + watch.body]
    if feedback and feedback.get("total_feedback"):
        memory = []
        if feedback.get("liked_companies"):
            memory.append(f"- Entreprises appréciées : {', '.join(feedback['liked_companies'])}")
        if feedback.get("ignored_companies"):
            memory.append(f"- Entreprises ignorées : {', '.join(feedback['ignored_companies'])}")
        if feedback.get("liked_skills"):
            memory.append(f"- Compétences des offres appréciées : {', '.join(feedback['liked_skills'])}")
        if memory:
            parts.append("# Mémoire (retours passés de l'utilisateur)\n" + "\n".join(memory))
    return "\n\n".join(parts)


def build_focus(watch: Watch) -> str:
    cfg = watch.config
    return f"{cfg.nom}. {' '.join(cfg.mots_cles)}. {cfg.localisation or ''}. {watch.body[:400]}"


def plan_prompt(watch: Watch, count: int, tried: list[str], last_round: dict | None) -> str:
    lines = [f"Génère {count} requêtes de recherche web pour trouver des offres récentes correspondant à la veille.",
             "Règles :",
             "- requêtes courtes (3 à 8 mots), variées : intitulés de poste, synonymes, « recrute », noms de job boards ou sites carrières",
             f"- langue : {watch.config.langue}",
             "- n'utilise pas d'opérateur site: vers LinkedIn, Facebook ou X"]
    if tried:
        lines.append("Requêtes déjà essayées, à ne pas répéter : " + " | ".join(tried))
    if last_round:
        lines.append(f"Tour précédent : {last_round['results']} résultats, {last_round['new']} nouveaux, "
                     f"{last_round['kept']} offres retenues. Change d'angle ou élargis.")
    return "\n".join(lines)


def triage_prompt(watch: Watch, candidates: list[dict], limit: int) -> str:
    listing = "\n".join(f"[{i}] {c.get('title', '')[:120]} | {c.get('snippet', '')[:220]} | {c['url'][:90]}"
                        for i, c in enumerate(candidates))
    wrapped, _ = wrap_untrusted(listing, "résultats de recherche")
    return (f"Voici des résultats de recherche. Garde au maximum {limit} indices qui ressemblent à UNE offre précise "
            "et compatible avec la veille. Écarte : listes génériques, articles, pages de connexion, offres expirées, "
            f"critères exclus ({', '.join(watch.config.exclure) or 'aucun'}).\n\n{wrapped}")


def extract_prompt(page: dict) -> tuple[str, int]:
    wrapped, flagged = wrap_untrusted(f"Titre : {page.get('title', '')}\nDate : {page.get('published', '')}\n\n"
                                      f"{page['content']}", page["url"])
    return ("Extrais l'offre décrite dans cette page. Si la page n'est pas une offre unique (liste, article, page "
            "expirée), mets is_job_offer à false. Laisse vides les champs absents. Pour le contact, uniquement un lien "
            f"ou un e-mail de candidature générique.\n\n{wrapped}"), flagged


def score_prompt(offer: dict, profile_chunks: list[dict], preferences: str) -> str:
    compact = {k: offer.get(k) for k in ("title", "company", "location", "contract", "remote", "salary",
                                         "skills", "summary", "published")}
    profile = "\n---\n".join(c["text"] for c in profile_chunks) or "(profil vide)"
    return ("Évalue la pertinence de cette offre pour le candidat, selon les critères de notation.\n\n"
            f"## Extraits pertinents du profil\n{profile}\n\n## Préférences\n{preferences or '(aucune)'}\n\n"
            f"## Offre\n{json.dumps(compact, ensure_ascii=False)}")


def digest_prompt(offers: list[dict]) -> str:
    lines = [f"- {o['title']} | {o.get('company') or '?'} | {o.get('location') or '?'} | score {o['score']}"
             for o in offers]
    return ("Écris une synthèse de 3 à 5 lignes, en français, des offres retenues : tendances, meilleure "
            "opportunité, action conseillée. Pas de liste, pas de titre.\n\n" + "\n".join(lines))


def render_report(watch: Watch, offers: list[dict], synthesis: str, stats: dict, run_id: int | None) -> str:
    date = datetime.now().strftime("%d/%m/%Y %H:%M")
    out = [f"# {watch.config.nom}", f"Exécution n° {run_id} du {date}", ""]
    if synthesis:
        out += ["## Synthèse", synthesis.strip(), ""]
    out.append(f"## Nouvelles offres ({len(offers)})")
    if offers:
        out += ["", "| Score | Poste | Entreprise | Lieu | Contrat |", "|---|---|---|---|---|"]
        for o in offers:
            title = o["title"].replace("|", "/")
            out.append(f"| {o['score']} | [{title}]({o['url']}) | {o.get('company') or ''} | "
                       f"{o.get('location') or ''} | {o.get('contract') or ''} |")
        for o in offers:
            out += ["", f"### {o['title']}", o.get("summary") or ""]
            if o.get("reasons"):
                out += [f"- ✅ {r}" for r in o["reasons"]]
            if o.get("red_flags"):
                out += [f"- ⚠️ {r}" for r in o["red_flags"]]
            out.append(f"- Source : {o['url']}")
    else:
        out.append("Aucune nouvelle offre pertinente.")
    out += ["", "## Mesures",
            f"- Tokens : {stats.get('tokens_in', 0) + stats.get('tokens_out', 0)}",
            f"- Pages lues : {stats.get('pages_fetched', 0)} (cache : {stats.get('page_cache_hits', 0)})",
            f"- URLs déjà vues ignorées : {stats.get('already_seen', 0)}",
            f"- Cache LLM : {stats.get('llm_cache_hits', 0)}, cache recherche : "
            f"{stats.get('search_cache_hits', 0) + stats.get('semantic_cache_hits', 0)}"]
    return "\n".join(out) + "\n"


def telegram_message(watch: Watch, offers: list[dict]) -> str:
    lines = [f"📡 <b>{escape(watch.config.nom)}</b> : {len(offers)} nouvelle(s) offre(s)", ""]
    for o in offers[:5]:
        lines.append(f"• <b>{escape(o['title'])}</b> ({escape(o.get('company') or '?')}) : {o['score']}/100\n"
                     f"  {escape(o['url'])}")
    return "\n".join(lines)
