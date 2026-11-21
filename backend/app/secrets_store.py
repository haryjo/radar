"""Clés API saisies dans l'interface.

Sécurité :
- chiffrées sur disque (Fernet, AES-128 + HMAC) dans DATA_DIR/secrets.enc ;
- la clé de chiffrement vient de RADAR_SECRET_KEY (.env) si elle est définie, sinon d'un fichier
  DATA_DIR/secret.key créé au premier lancement avec des droits restreints (600) ;
- l'API ne renvoie JAMAIS une clé : seulement « définie ou non », sa provenance et ses 4 derniers caractères ;
- une clé saisie dans l'app est prioritaire sur celle de .env (on peut ainsi la remplacer sans redémarrer).
"""
import json
import logging
import os
import threading

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

log = logging.getLogger("radar.secrets")

# nom interne -> (libellé, attribut de settings utilisé comme valeur de repli)
SECRETS: dict[str, tuple[str, str]] = {
    "groq": ("Groq", "groq_api_key"),
    "gemini": ("Google Gemini", "gemini_api_key"),
    "openai": ("OpenAI", "openai_api_key"),
    "anthropic": ("Anthropic", "anthropic_api_key"),
    "mistral": ("Mistral AI", "mistral_api_key"),
    "openrouter": ("OpenRouter", "openrouter_api_key"),
    "apify": ("Apify", "apify_token"),
    "telegram_bot_token": ("Bot Telegram", "telegram_bot_token"),
    "telegram_chat_id": ("Chat Telegram", "telegram_chat_id"),
}

_lock = threading.Lock()
_cache: tuple[float, dict[str, str]] | None = None


def _fernet() -> Fernet:
    env_key = os.environ.get("RADAR_SECRET_KEY", "").strip()
    if env_key:
        return Fernet(env_key.encode())
    path = settings.data_dir / "secret.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(Fernet.generate_key())
    return Fernet(path.read_bytes().strip())


def _store_path():
    return settings.data_dir / "secrets.enc"


def _load() -> dict[str, str]:
    global _cache
    path = _store_path()
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    if _cache and _cache[0] == mtime:
        return _cache[1]
    try:
        data = json.loads(_fernet().decrypt(path.read_bytes()))
    except (InvalidToken, ValueError) as exc:
        log.error("Clés illisibles (clé de chiffrement changée ?) : %s", exc)
        data = {}
    _cache = (mtime, data)
    return data


def _save(data: dict[str, str]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(_fernet().encrypt(json.dumps(data).encode()))
    os.replace(tmp, path)


def get(name: str) -> str:
    """Valeur utilisable par le serveur (jamais exposée par l'API)."""
    stored = _load().get(name, "")
    if stored:
        return stored
    attr = SECRETS.get(name, ("", ""))[1]
    value = (getattr(settings, attr, "") or "").strip() if attr else ""
    return "" if value.startswith("#") else value


def set_secret(name: str, value: str) -> None:
    if name not in SECRETS:
        raise KeyError(name)
    value = value.strip()
    if not value or len(value) > 500 or any(c.isspace() for c in value):
        raise ValueError("Valeur invalide : colle la clé sans espace ni retour à la ligne")
    with _lock:
        data = dict(_load())
        data[name] = value
        _save(data)


def delete_secret(name: str) -> None:
    with _lock:
        data = dict(_load())
        data.pop(name, None)
        _save(data)


def describe() -> list[dict]:
    stored = _load()
    out = []
    for name, (label, attr) in SECRETS.items():
        value = get(name)
        source = "app" if stored.get(name) else ("env" if value else None)
        out.append({"name": name, "label": label, "set": bool(value), "source": source,
                    "hint": f"…{value[-4:]}" if len(value) >= 12 else ("défini" if value else None),
                    "env": attr.upper()})
    return out
