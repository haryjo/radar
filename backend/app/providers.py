"""Catalogue des fournisseurs LLM et réglages de routage (persistés dans DATA_DIR/llm_settings.json).

Les clés API restent dans .env et ne sont jamais renvoyées au navigateur.
Les identifiants de modèles changent souvent : ils sont modifiables dans l'interface (page Modèles).
"""
import json
import os
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .config import settings

Tier = Literal["fast", "strong"]
Routing = Literal["fixe", "intelligent", "performance"]


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    kind: Literal["openai", "anthropic"]  # "openai" = API compatible OpenAI
    base_url: str | None
    key_attr: str | None
    fast: str
    strong: str
    json_mode: bool = True          # response_format={"type": "json_object"} disponible
    send_temperature: bool = True   # les modèles de raisonnement OpenAI refusent temperature
    stream_usage: bool = False
    free_tier: bool = False
    note: str = ""
    keys_url: str = ""

    def api_key(self) -> str:
        if not self.key_attr:
            return "ollama"
        from . import secrets_store  # clé saisie dans l'app, sinon celle de .env
        return secrets_store.get(self.id)

    def configured(self) -> bool:
        return bool(self.api_key())

    def url(self) -> str | None:
        if self.id == "ollama":
            return settings.ollama_base_url.rstrip("/") + "/v1"
        return self.base_url

    @property
    def key_env(self) -> str | None:
        return self.key_attr.upper() if self.key_attr else None


PROVIDERS: dict[str, Provider] = {p.id: p for p in [
    Provider("groq", "Groq", "openai", "https://api.groq.com/openai/v1", "groq_api_key",
             fast="openai/gpt-oss-20b", strong="openai/gpt-oss-120b", stream_usage=True, free_tier=True,
             note="Très rapide, offre gratuite limitée en tokens par minute.",
             keys_url="https://console.groq.com/keys"),
    Provider("gemini", "Google Gemini", "openai", "https://generativelanguage.googleapis.com/v1beta/openai",
             "gemini_api_key", fast="gemini-flash-lite-latest", strong="gemini-flash-latest", free_tier=True,
             note="Offre gratuite généreuse, très long contexte.",
             keys_url="https://aistudio.google.com/apikey"),
    Provider("openai", "OpenAI (ChatGPT)", "openai", "https://api.openai.com/v1", "openai_api_key",
             fast="gpt-5.6-luna", strong="gpt-5.6-terra", send_temperature=False, stream_usage=True,
             note="Payant. Modèles de raisonnement : la température n'est pas envoyée.",
             keys_url="https://platform.openai.com/api-keys"),
    Provider("anthropic", "Anthropic (Claude)", "anthropic", None, "anthropic_api_key",
             fast="claude-haiku-5-5", strong="claude-sonnet-5-5", json_mode=False,
             note="Payant. Excellente qualité d'analyse et de rédaction.",
             keys_url="https://console.anthropic.com/settings/keys"),
    Provider("mistral", "Mistral AI", "openai", "https://api.mistral.ai/v1", "mistral_api_key",
             fast="mistral-small-latest", strong="mistral-large-latest", free_tier=True,
             note="Offre gratuite « Experiment », très bon en français.",
             keys_url="https://console.mistral.ai/api-keys"),
    Provider("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1", "openrouter_api_key",
             fast="openai/gpt-oss-20b:free", strong="openai/gpt-oss-120b:free", free_tier=True,
             note="Une clé pour des centaines de modèles, dont des modèles « :free ».",
             keys_url="https://openrouter.ai/keys"),
    Provider("ollama", "Ollama (local)", "openai", None, None,
             fast="qwen2.5:3b", strong="qwen2.5:7b", free_tier=True,
             note="Tourne sur ta machine : docker compose --profile local-llm up -d"),
]}

TASK_TIER: dict[str, Tier] = {
    "plan": "fast", "triage": "fast", "extract": "fast",
    "score": "strong", "digest": "strong", "chat": "strong", "test": "fast",
}

TASK_LABELS = {"plan": "Planification", "triage": "Tri", "extract": "Extraction", "score": "Notation",
               "digest": "Synthèse", "chat": "Assistant", "test": "Test"}


class LLMSettings(BaseModel):
    routing: Routing = "intelligent"
    chain: list[str] = Field(default_factory=list, description="Fournisseurs actifs, par ordre de priorité")
    models: dict[str, dict[str, str]] = Field(default_factory=dict, description="Modèles choisis par fournisseur")
    escalate_chars: int = Field(9000, ge=2000, le=200000)
    exploration: float = Field(0.1, ge=0, le=0.5)
    concurrency: int = Field(2, ge=1, le=8)

    @field_validator("chain")
    @classmethod
    def known_providers(cls, value: list[str]) -> list[str]:
        unknown = [p for p in value if p not in PROVIDERS]
        if unknown:
            raise ValueError(f"fournisseur inconnu : {', '.join(unknown)}")
        return list(dict.fromkeys(value))

    @field_validator("models")
    @classmethod
    def clean_models(cls, value: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        clean = {}
        for pid, tiers in value.items():
            if pid in PROVIDERS:
                clean[pid] = {t: m.strip()[:120] for t, m in tiers.items() if t in ("fast", "strong") and m.strip()}
        return clean

    def model_for(self, provider_id: str, tier: Tier) -> str:
        provider = PROVIDERS[provider_id]
        return self.models.get(provider_id, {}).get(tier) or (provider.fast if tier == "fast" else provider.strong)

    def active_providers(self) -> list[str]:
        return [p for p in self.chain if PROVIDERS[p].configured()]


def _settings_path():
    return settings.data_dir / "llm_settings.json"


def default_llm_settings() -> LLMSettings:
    primary = settings.llm_provider if settings.llm_provider in PROVIDERS else "groq"
    others = [pid for pid, p in PROVIDERS.items() if pid not in (primary, "ollama") and p.configured()]
    return LLMSettings(routing=settings.llm_routing if settings.llm_routing in ("fixe", "intelligent", "performance")
                       else "intelligent", chain=[primary, *others])


_cache: tuple[float, LLMSettings] | None = None


def load_llm_settings() -> LLMSettings:
    """Relu à chaque appel si le fichier a changé (partagé entre l'API et le serveur MCP)."""
    global _cache
    path = _settings_path()
    if not path.exists():
        return default_llm_settings()
    mtime = path.stat().st_mtime
    if _cache and _cache[0] == mtime:
        return _cache[1]
    try:
        loaded = LLMSettings.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        loaded = default_llm_settings()
    if not loaded.chain:
        loaded.chain = default_llm_settings().chain
    _cache = (mtime, loaded)
    return loaded


def save_llm_settings(new: LLMSettings) -> LLMSettings:
    if not new.chain:
        raise ValueError("Active au moins un fournisseur")
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(new.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return load_llm_settings()


def provider_public(pid: str, current: LLMSettings) -> dict:
    """Vue publique d'un fournisseur (jamais la clé)."""
    p = PROVIDERS[pid]
    return {
        "id": p.id, "label": p.label, "configured": p.configured(), "key_env": p.key_env,
        "free_tier": p.free_tier, "note": p.note, "keys_url": p.keys_url, "local": p.id == "ollama",
        "defaults": {"fast": p.fast, "strong": p.strong},
        "models": {"fast": current.model_for(pid, "fast"), "strong": current.model_for(pid, "strong")},
        "in_chain": pid in current.chain,
        "priority": current.chain.index(pid) if pid in current.chain else None,
    }


def describe_all(current: LLMSettings) -> list[dict]:
    order = {pid: i for i, pid in enumerate(current.chain)}
    return sorted((provider_public(pid, current) for pid in PROVIDERS),
                  key=lambda p: (order.get(p["id"], 99), not p["configured"], p["label"]))


def dumps_settings(current: LLMSettings) -> dict:
    return json.loads(current.model_dump_json())
