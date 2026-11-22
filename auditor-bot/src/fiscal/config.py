"""Configuração via variáveis de ambiente (prefixo ``FISCAL_``) ou arquivo ``.env``."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FISCAL_", env_file=".env", extra="ignore")

    judge_backend: Literal["heuristic", "llm"] = "heuristic"
    judge_model: str = "anthropic:claude-haiku-5-5"
    escalation_model: str | None = None
    review_threshold: float = 0.75
    pii_salt: str = "dev-salt-troque-em-producao"
    db_path: str = "fiscal.db"
    kb_path: str | None = None
    webhook_verify_token: str = "troque-este-token"
    whatsapp_app_secret: str | None = None  # valida X-Hub-Signature-256 dos webhooks da Meta
    business_numbers: str = ""  # números do negócio (separados por vírgula) para marcar mensagens do bot
    api_key: str | None = None  # se definido, exige o header X-API-Key nos endpoints /v1


@lru_cache
def get_settings() -> Settings:
    return Settings()
