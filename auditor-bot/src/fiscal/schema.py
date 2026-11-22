"""Modelos de dados centrais (pydantic) usados por todo o pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Role(StrEnum):
    CUSTOMER = "customer"
    BOT = "bot"
    HUMAN = "human"  # atendente humano


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return ["low", "medium", "high", "critical"].index(self.value)


class Message(BaseModel):
    role: Role
    text: str
    timestamp: datetime | None = None


class Conversation(BaseModel):
    id: str
    bot_id: str = "default"
    channel: str = "whatsapp"
    messages: list[Message]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def transcript(self) -> str:
        """Transcrição numerada, usada nos prompts do juiz."""
        label = {Role.CUSTOMER: "CLIENTE", Role.BOT: "BOT", Role.HUMAN: "ATENDENTE"}
        return "\n".join(f"[{i}] {label[m.role]}: {m.text}" for i, m in enumerate(self.messages))


FindingSource = Literal["rule", "heuristic", "llm"]


class Finding(BaseModel):
    """Uma falha encontrada em uma mensagem do bot."""

    rubric: str
    severity: Severity
    evidence: str
    explanation: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: FindingSource = "rule"
    message_index: int | None = None
    corroborated: bool = False  # confirmado por mais de uma fonte


class Verdict(BaseModel):
    conversation_id: str
    bot_id: str = "default"
    findings: list[Finding] = Field(default_factory=list)
    needs_review: bool = False
    review_reason: str | None = None
    judge_backend: str = "heuristic"
    escalated: bool = False

    @property
    def passed(self) -> bool:
        return not self.findings

    @property
    def violated_rubrics(self) -> set[str]:
        return {f.rubric for f in self.findings}

    @property
    def max_severity(self) -> Severity | None:
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: s.rank)
