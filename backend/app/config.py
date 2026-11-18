"""Configuration centralisée, lue depuis les variables d'environnement (.env)."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM : fournisseur principal par défaut et mode de routage (modifiables dans la page Modèles)
    llm_provider: str = "groq"
    llm_routing: str = "intelligent"
    llm_timeout_s: int = 90

    # Clés API (laisser vide pour désactiver un fournisseur)
    groq_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    mistral_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_base_url: str = "http://ollama:11434"

    # Chemins (montés par docker compose)
    config_dir: Path = Path("/config")
    data_dir: Path = Path("/data")
    models_dir: Path = Path("/models")
    timezone: str = "Indian/Antananarivo"

    # Services
    mcp_url: str = "http://mcp:8001/mcp"
    api_url: str = "http://api:8000"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8001
    cors_origins: str = "http://localhost:3000"

    # RAG
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    reranker_model: str = "ms-marco-MultiBERT-L-12"

    # Garde-fous et budgets
    min_interval_hours: int = 6
    max_queries_per_round: int = 6
    max_rounds: int = 2
    max_pages_per_run: int = 15
    token_budget_per_run: int = 60000
    page_max_chars: int = 5000
    domain_delay_seconds: float = 1.0
    read_concurrency: int = 8
    reader_fallback: str = "jina"   # "jina" (pages en JavaScript) ou "aucun"
    apify_token: str = ""

    # Cache
    page_cache_days: int = 7
    search_cache_hours: int = 6
    semantic_cache_threshold: float = 0.92

    # Surveillance des fichiers .md (polling = fiable avec les volumes Docker sous Windows/macOS)
    watch_polling: bool = True

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "radar.db"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "rapports"

    @property
    def watches_dir(self) -> Path:
        return self.config_dir / "veilles"

    @property
    def instructions_dir(self) -> Path:
        return self.config_dir / "instructions"

    @property
    def profile_dir(self) -> Path:
        return self.config_dir / "profil"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.reports_dir, self.models_dir, self.watches_dir,
                     self.instructions_dir, self.profile_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
