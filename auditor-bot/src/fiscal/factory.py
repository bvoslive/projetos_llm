"""Monta um ``Auditor`` a partir da configuração (env/.env) e opções explícitas."""

from __future__ import annotations

from pathlib import Path

from fiscal.config import Settings, get_settings
from fiscal.judge import Auditor, build_backend, load_rubrics
from fiscal.judge.graph import ReviewResolver
from fiscal.knowledge import KnowledgeBase

DEFAULT_KB = Path("data/loja_pitanga/kb.yaml")


def load_kb(path: str | Path | None = None, settings: Settings | None = None) -> KnowledgeBase:
    settings = settings or get_settings()
    chosen = path or settings.kb_path or DEFAULT_KB
    if not Path(chosen).exists():
        raise FileNotFoundError(
            f"Base de conhecimento não encontrada: {chosen}. Use --kb ou defina FISCAL_KB_PATH."
        )
    return KnowledgeBase.load(chosen)


def build_auditor(
    kb: KnowledgeBase,
    *,
    backend: str | None = None,
    model: str | None = None,
    escalation_model: str | None = None,
    rubrics_dir: str | Path | None = None,
    review_resolver: ReviewResolver | None = None,
    settings: Settings | None = None,
) -> Auditor:
    settings = settings or get_settings()
    backend_name = backend or settings.judge_backend
    judge = build_backend(backend_name, model or settings.judge_model)
    escalate_to = escalation_model or settings.escalation_model
    escalation = build_backend("llm", escalate_to) if escalate_to else None
    return Auditor(
        kb,
        judge,
        load_rubrics(rubrics_dir),
        salt=settings.pii_salt,
        review_threshold=settings.review_threshold,
        escalation_backend=escalation,
        review_resolver=review_resolver,
    )
