"""Routeur LLM multi-fournisseurs.

- Fournisseurs : Groq, Gemini, OpenAI, Claude, Mistral, OpenRouter, Ollama (voir providers.py).
- Routage :
    fixe         -> premier fournisseur actif uniquement, sans bascule ;
    intelligent  -> tâche simple = modèle rapide, tâche complexe ou entrée longue = modèle puissant,
                    bascule automatique sur le fournisseur suivant en cas d'erreur ;
    performance  -> classe les modèles selon leurs résultats réels (succès, JSON valide, latence),
                    avec un peu d'exploration pour continuer à mesurer les autres.
- Sorties structurées : JSON demandé dans le prompt (+ mode JSON natif si disponible), validé par
  Pydantic, une tentative de réparation, puis bascule. Fonctionne avec tous les fournisseurs.
- Erreurs classées (quota, clé invalide, modèle retiré, délai, serveur) avec disjoncteur par modèle.
"""
import asyncio
import hashlib
import json
import logging
import random
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from . import db
from .config import settings
from .context import BudgetExceeded, RunContext
from .providers import PROVIDERS, TASK_TIER, LLMSettings, Tier, load_llm_settings

log = logging.getLogger("radar.llm")
T = TypeVar("T", bound=BaseModel)


# ------------------------------------------------------------------ erreurs

class LLMError(Exception):
    """Échec définitif après avoir essayé tous les modèles prévus."""


class LLMConfigError(LLMError):
    """Configuration impossible à utiliser (aucune clé, aucun fournisseur actif)."""


class LLMCallError(Exception):
    def __init__(self, kind: str, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


KIND_LABELS = {
    "rate_limit": "quota atteint", "auth": "clé API refusée", "not_found": "modèle introuvable ou retiré",
    "bad_request": "requête refusée", "timeout": "délai dépassé", "server": "erreur du fournisseur",
    "invalid_output": "réponse illisible", "network": "réseau injoignable", "unknown": "erreur inconnue",
}


def _status_of(exc: Exception) -> int | None:
    for candidate in (getattr(exc, "status_code", None), getattr(getattr(exc, "response", None), "status_code", None)):
        if isinstance(candidate, int):
            return candidate
    return None


def _retry_after(exc: Exception, text: str) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        if headers.get("retry-after"):
            return float(headers["retry-after"])
    except (TypeError, ValueError):
        pass
    match = re.search(r"(?:try again|retry) in (?:about )?([\d.]+)\s*(ms|s|m)", text)
    if match:
        value = float(match.group(1))
        return value / 1000 if match.group(2) == "ms" else value * 60 if match.group(2) == "m" else value
    return None


def classify(exc: Exception) -> LLMCallError:
    if isinstance(exc, LLMCallError):
        return exc
    text = f"{exc.__class__.__name__}: {exc}"
    lowered = text.lower()
    status = _status_of(exc)
    short = re.sub(r"\s+", " ", str(exc))[:240]
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "timeout" in lowered or "timed out" in lowered:
        return LLMCallError("timeout", "délai dépassé")
    if status == 429 or "rate limit" in lowered or "rate_limit" in lowered or "quota" in lowered \
            or "resource_exhausted" in lowered:
        return LLMCallError("rate_limit", short, _retry_after(exc, lowered))
    if status in (401, 403) or "invalid api key" in lowered or "authentication" in lowered \
            or "permission" in lowered:
        return LLMCallError("auth", short)
    if status == 404 or any(s in lowered for s in ("model_not_found", "decommissioned", "does not exist",
                                                   "not found", "no longer supported", "deprecated")):
        return LLMCallError("not_found", short)
    if status == 400 or status == 422:
        return LLMCallError("bad_request", short)
    if status and status >= 500:
        return LLMCallError("server", short)
    if "connect" in lowered or "network" in lowered or "name or service" in lowered:
        return LLMCallError("network", short)
    return LLMCallError("unknown", short)


# ------------------------------------------------------------------ cibles et disjoncteur

@dataclass(frozen=True)
class Target:
    provider: str
    model: str
    tier: Tier

    @property
    def label(self) -> str:
        return f"{PROVIDERS[self.provider].label} · {self.model}"

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"


_blocked_until: dict[str, float] = {}
_block_reason: dict[str, str] = {}


def _block(target: Target, seconds: float, reason: str) -> None:
    _blocked_until[target.key] = time.monotonic() + seconds
    _block_reason[target.key] = reason


def _is_blocked(target: Target) -> bool:
    return _blocked_until.get(target.key, 0) > time.monotonic()


def reset_breakers() -> None:
    _blocked_until.clear()
    _block_reason.clear()


_semaphores: dict[str, asyncio.Semaphore] = {}


def _semaphore(provider: str, limit: int) -> asyncio.Semaphore:
    key = f"{provider}:{limit}"
    if key not in _semaphores:
        _semaphores[key] = asyncio.Semaphore(limit)
    return _semaphores[key]


# ------------------------------------------------------------------ statistiques (routage par performance)

def record_call(target: Target, task: str, ok: bool, latency_ms: int, message: Any = None,
                error: str | None = None) -> None:
    usage = getattr(message, "usage_metadata", None) or {}
    try:
        with db.get_conn() as conn:
            conn.execute("INSERT INTO llm_calls (ts, provider, model, task, ok, latency_ms, tokens_in, tokens_out, error)"
                         " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (db.now_iso(), target.provider, target.model, task, int(ok), latency_ms,
                          int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)),
                          (error or "")[:300] or None))
    except Exception as exc:  # noqa: BLE001
        log.warning("Statistique LLM non enregistrée : %s", exc)
    _perf_cache.clear()


_perf_cache: dict[str, tuple[float, dict]] = {}


def _perf_score(ok: int, calls: int, latency_s: float) -> float:
    """Succès lissé (a priori 1 succès / 1 échec) au carré, pénalisé par la latence médiane."""
    success = (ok + 1) / (calls + 2)
    return round(success ** 2 / (1 + latency_s / 4), 4)


def performance_table(window: int = 40) -> dict[str, dict]:
    """Score par modèle sur ses `window` derniers appels : succès² / (1 + latence/4 s)."""
    cached = _perf_cache.get("all")
    if cached and time.monotonic() - cached[0] < 30:
        return cached[1]
    with db.get_conn() as conn:
        rows = conn.execute("SELECT provider, model, ok, latency_ms FROM llm_calls ORDER BY id DESC LIMIT 4000").fetchall()
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        key = f"{row['provider']}/{row['model']}"
        if len(grouped[key]) < window:
            grouped[key].append(row)
    table = {}
    for key, items in grouped.items():
        oks = sum(r["ok"] for r in items)
        latencies = sorted(r["latency_ms"] or 0 for r in items if r["ok"])
        median = latencies[len(latencies) // 2] / 1000 if latencies else 4.0
        table[key] = {"calls": len(items), "success": oks / len(items), "latency_s": median,
                      "score": _perf_score(oks, len(items), median)}
    _perf_cache["all"] = (time.monotonic(), table)
    return table


# ------------------------------------------------------------------ choix des modèles

def plan_targets(task: str, input_chars: int, cfg: LLMSettings | None = None) -> list[Target]:
    cfg = cfg or load_llm_settings()
    providers = cfg.active_providers()
    if not providers:
        missing = ", ".join(PROVIDERS[p].key_env or p for p in cfg.chain) or "GROQ_API_KEY"
        raise LLMConfigError(f"Aucun fournisseur LLM utilisable : renseigne une clé API dans .env ({missing}) "
                             "ou active un autre fournisseur dans la page Modèles.")
    tier: Tier = TASK_TIER.get(task, "fast")
    if cfg.routing != "fixe" and tier == "fast" and input_chars > cfg.escalate_chars:
        tier = "strong"  # entrée longue : on monte en gamme
    targets = [Target(p, cfg.model_for(p, tier), tier) for p in providers]

    if cfg.routing == "fixe":
        return targets[:1]
    if cfg.routing == "performance":
        perf = performance_table()

        neutral = _perf_score(0, 0, 4.0)  # modèle jamais mesuré : score neutre, il sera essayé

        def rank(t: Target) -> tuple:
            stats = perf.get(t.key)
            return (-(stats["score"] if stats else neutral), providers.index(t.provider))
        targets.sort(key=rank)
        if len(targets) > 1 and random.random() < cfg.exploration:
            explore = random.choice(targets[1:])
            targets.remove(explore)
            targets.insert(0, explore)
    if cfg.routing == "intelligent" and tier == "fast":
        # dernier recours : le modèle puissant du fournisseur principal
        targets.append(Target(providers[0], cfg.model_for(providers[0], "strong"), "strong"))
    unique: dict[str, Target] = {}
    for target in targets:  # un même modèle n'apparaît qu'une fois, même s'il sert aux deux niveaux
        unique.setdefault(target.key, target)
    return list(unique.values())


# ------------------------------------------------------------------ construction des modèles

_models: dict[tuple, Any] = {}


def build_chat_model(target: Target, json_mode: bool = False, for_tools: bool = False):
    key = (target.provider, target.model, json_mode, for_tools)
    if key in _models:
        return _models[key]
    provider = PROVIDERS[target.provider]
    timeout = settings.llm_timeout_s
    if provider.kind == "anthropic":
        from langchain_anthropic import ChatAnthropic
        model = ChatAnthropic(model=target.model, api_key=provider.api_key(), max_tokens=4096, temperature=0,
                              timeout=timeout, max_retries=2 if for_tools else 0)
    else:
        from langchain_openai import ChatOpenAI
        kwargs: dict[str, Any] = {"model": target.model, "api_key": provider.api_key(), "base_url": provider.url(),
                                  "timeout": timeout, "max_retries": 2 if for_tools else 0}
        if provider.send_temperature:
            kwargs["temperature"] = 0
        if provider.stream_usage:
            kwargs["stream_usage"] = True
        if provider.id == "openrouter":
            kwargs["default_headers"] = {"HTTP-Referer": "http://localhost:3000", "X-Title": "Radar Veille"}
        model = ChatOpenAI(**kwargs)
        if json_mode:
            model = model.bind(response_format={"type": "json_object"})
    _models[key] = model
    return model


def clear_model_cache() -> None:
    _models.clear()


# ------------------------------------------------------------------ texte et JSON

def content_text(message: Any) -> str:
    """Texte d'un message, quel que soit le format (chaîne ou blocs Anthropic/OpenAI)."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in ("text", "output_text"):
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content or "")


def parse_json(text: str) -> Any:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, flags=re.S)
    if fence:
        cleaned = fence.group(1).strip()
    if not cleaned.startswith(("{", "[")):
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("aucun objet JSON dans la réponse")
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def _format_instructions(schema: type[BaseModel]) -> str:
    return ("\n\n# Format de réponse\nRéponds UNIQUEMENT avec un objet JSON valide (pas de texte autour, pas de "
            "bloc de code), conforme à ce schéma JSON :\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False))


# ------------------------------------------------------------------ cache exact des réponses

def _cache_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _cache_get(key: str) -> str | None:
    with db.get_conn() as conn:
        row = conn.execute("SELECT value FROM llm_cache WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _cache_set(key: str, value: str) -> None:
    with db.get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO llm_cache (key, value, created_at) VALUES (?, ?, ?)",
                     (key, value, db.now_iso()))


# ------------------------------------------------------------------ appel bas niveau

async def _invoke(target: Target, messages: list[BaseMessage], json_mode: bool, task: str,
                  ctx: RunContext | None, cfg: LLMSettings) -> tuple[AIMessage, int]:
    if ctx:
        ctx.check_budget()
    model = build_chat_model(target, json_mode=json_mode)
    started = time.monotonic()
    try:
        async with _semaphore(target.provider, cfg.concurrency):
            message = await asyncio.wait_for(model.ainvoke(messages), timeout=settings.llm_timeout_s + 5)
    except Exception as exc:  # noqa: BLE001
        error = classify(exc)
        record_call(target, task, False, int((time.monotonic() - started) * 1000), error=f"{error.kind}: {error}")
        raise error from exc
    latency = int((time.monotonic() - started) * 1000)
    if ctx:
        ctx.add_usage(message, target.tier)
        ctx.stats[f"model:{target.key}"] += 1
    return message, latency


async def _structured_once(target: Target, system: str, user: str, schema: type[T], task: str,
                           ctx: RunContext | None, cfg: LLMSettings) -> T:
    provider = PROVIDERS[target.provider]
    messages: list[BaseMessage] = [SystemMessage(system + _format_instructions(schema)), HumanMessage(user)]
    json_mode = provider.json_mode
    try:
        message, latency = await _invoke(target, messages, json_mode, task, ctx, cfg)
    except LLMCallError as err:
        if not (json_mode and err.kind == "bad_request"):
            raise
        message, latency = await _invoke(target, messages, False, task, ctx, cfg)  # mode JSON non supporté

    text = content_text(message)
    try:
        result = schema.model_validate(parse_json(text))
    except (ValueError, ValidationError) as first_error:
        # Une tentative de réparation : on montre l'erreur au modèle.
        detail = str(first_error).splitlines()[0][:300]
        repair = messages + [AIMessage(text[:6000]), HumanMessage(
            f"Ta réponse n'est pas valide ({detail}). Renvoie uniquement l'objet JSON corrigé, conforme au schéma.")]
        message, latency2 = await _invoke(target, repair, False, task, ctx, cfg)
        latency += latency2
        try:
            result = schema.model_validate(parse_json(content_text(message)))
        except (ValueError, ValidationError) as second_error:
            record_call(target, task, False, latency, message, f"invalid_output: {str(second_error)[:200]}")
            raise LLMCallError("invalid_output", "réponse JSON invalide après réparation") from second_error
        if ctx:
            ctx.stats["json_repairs"] += 1
    record_call(target, task, True, latency, message)
    return result


async def _text_once(target: Target, system: str, user: str, task: str,
                     ctx: RunContext | None, cfg: LLMSettings) -> str:
    message, latency = await _invoke(target, [SystemMessage(system), HumanMessage(user)], False, task, ctx, cfg)
    text = content_text(message).strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if not text:
        record_call(target, task, False, latency, message, "invalid_output: réponse vide")
        raise LLMCallError("invalid_output", "réponse vide")
    record_call(target, task, True, latency, message)
    return text


async def _route(task: str, input_chars: int, ctx: RunContext | None, runner) -> Any:
    """Essaie les modèles prévus dans l'ordre ; gère quotas, disjoncteur et bascule."""
    cfg = load_llm_settings()
    targets = plan_targets(task, input_chars, cfg)
    errors: list[str] = []
    usable = [t for t in targets if not _is_blocked(t)] or targets  # si tout est bloqué, on réessaie quand même
    for index, target in enumerate(usable):
        for attempt in range(2):
            try:
                return await runner(target, cfg)
            except BudgetExceeded:
                raise
            except LLMCallError as err:
                if err.kind == "rate_limit":
                    wait = err.retry_after or 0
                    if attempt == 0 and 0 < wait <= 20:
                        await asyncio.sleep(wait + 0.5)
                        continue
                    _block(target, max(wait, 45), KIND_LABELS[err.kind])
                elif err.kind in ("auth", "not_found"):
                    _block(target, 900, KIND_LABELS[err.kind])
                elif err.kind in ("timeout", "server", "network"):
                    if attempt == 0:
                        await asyncio.sleep(2)
                        continue
                    _block(target, 60, KIND_LABELS[err.kind])
                errors.append(f"{target.label} : {KIND_LABELS.get(err.kind, err.kind)}")
                log.warning("LLM %s (%s) : %s", target.label, err.kind, err)
                if ctx and index + 1 < len(usable):
                    await ctx.log("llm", f"{target.label} : {KIND_LABELS.get(err.kind, err.kind)}, "
                                         f"bascule vers {usable[index + 1].label}")
                break
    raise LLMError("Aucun modèle n'a répondu. " + " ; ".join(errors[-4:]))


# ------------------------------------------------------------------ API publique

async def call_structured(task: str, system: str, user: str, schema: type[T],
                          ctx: RunContext | None = None, use_cache: bool = True) -> T:
    key = _cache_key("structured", task, schema.__name__, json.dumps(schema.model_json_schema(), sort_keys=True),
                     system, user)
    if use_cache and (hit := _cache_get(key)):
        try:
            result = schema.model_validate_json(hit)
            if ctx:
                ctx.stats["llm_cache_hits"] += 1
            return result
        except ValidationError:
            pass
    result = await _route(task, len(system) + len(user), ctx,
                          lambda target, cfg: _structured_once(target, system, user, schema, task, ctx, cfg))
    _cache_set(key, result.model_dump_json())
    return result


async def call_text(task: str, system: str, user: str, ctx: RunContext | None = None,
                    use_cache: bool = True) -> str:
    key = _cache_key("text", task, system, user)
    if use_cache and (hit := _cache_get(key)):
        if ctx:
            ctx.stats["llm_cache_hits"] += 1
        return hit
    text = await _route(task, len(system) + len(user), ctx,
                        lambda target, cfg: _text_once(target, system, user, task, ctx, cfg))
    _cache_set(key, text)
    return text


def chat_runnable(tools: list) -> tuple[Any, list[Target]]:
    """Modèle de l'assistant avec outils, et bascule native LangChain vers les fournisseurs suivants."""
    cfg = load_llm_settings()
    targets = [t for t in plan_targets("chat", 0, cfg) if not _is_blocked(t)] or plan_targets("chat", 0, cfg)
    bound = [build_chat_model(t, for_tools=True).bind_tools(tools) for t in targets]
    runnable = bound[0].with_fallbacks(bound[1:]) if len(bound) > 1 else bound[0]
    return runnable, targets


async def test_model(provider_id: str, model: str) -> dict:
    target = Target(provider_id, model, "fast")
    cfg = load_llm_settings()
    if not PROVIDERS[provider_id].configured():
        return {"ok": False, "error": f"Clé manquante : {PROVIDERS[provider_id].key_env}", "latency_ms": 0}
    try:
        message, latency = await _invoke(target, [HumanMessage("Réponds uniquement par le mot OK.")], False,
                                         "test", None, cfg)
    except LLMCallError as err:
        return {"ok": False, "error": f"{KIND_LABELS.get(err.kind, err.kind)} : {err}", "latency_ms": 0}
    record_call(target, "test", True, latency, message)
    _blocked_until.pop(target.key, None)
    return {"ok": True, "reply": content_text(message)[:80], "latency_ms": latency}


def blocked_status() -> dict[str, dict]:
    now = time.monotonic()
    return {key: {"reason": _block_reason.get(key, ""), "seconds": int(until - now)}
            for key, until in _blocked_until.items() if until > now}
