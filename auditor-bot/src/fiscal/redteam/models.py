"""Modelos do red teaming."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fiscal.sampling import wilson_interval
from fiscal.schema import Conversation, Severity, Verdict


class Attack(BaseModel):
    id: str
    category: str
    severity: Severity
    title: str
    turns: list[str]  # mensagens do "cliente" enviadas em sequência
    # Regex (texto minúsculo e sem acentos) que, se casar numa resposta do bot, indica ataque bem-sucedido.
    fail_patterns: list[str] = Field(default_factory=list)
    # Rubricas que, se o juiz acusar na conversa, também indicam ataque bem-sucedido.
    target_rubrics: list[str] = Field(default_factory=list)


class AttackResult(BaseModel):
    attack: Attack
    conversation: Conversation
    verdict: Verdict
    success: bool  # True = o bot FALHOU (ataque funcionou)
    reasons: list[str] = Field(default_factory=list)
    error: str | None = None


class CategoryStat(BaseModel):
    category: str
    attacks: int
    successes: int
    rate: float


class RedTeamSummary(BaseModel):
    target: str
    total: int
    successes: int
    errors: int = 0
    rate: float
    ci_low: float
    ci_high: float
    by_category: list[CategoryStat]
    by_severity: dict[str, int]
    critical_failures: int
    failed_attacks: list[AttackResult]


def summarize_redteam(results: list[AttackResult], target: str, confidence: float = 0.95) -> RedTeamSummary:
    valid = [r for r in results if r.error is None]
    wins = [r for r in valid if r.success]
    lo, hi = wilson_interval(len(wins), len(valid), confidence)
    cats: dict[str, list[AttackResult]] = {}
    for r in valid:
        cats.setdefault(r.attack.category, []).append(r)
    by_cat = [
        CategoryStat(category=c, attacks=len(rs), successes=sum(r.success for r in rs),
                     rate=sum(r.success for r in rs) / len(rs))
        for c, rs in sorted(cats.items())
    ]
    by_sev: dict[str, int] = {}
    for r in wins:
        by_sev[r.attack.severity.value] = by_sev.get(r.attack.severity.value, 0) + 1
    ordered = sorted(wins, key=lambda r: -r.attack.severity.rank)
    return RedTeamSummary(
        target=target, total=len(valid), successes=len(wins), errors=len(results) - len(valid),
        rate=len(wins) / len(valid) if valid else 0.0, ci_low=lo, ci_high=hi, by_category=by_cat,
        by_severity=by_sev, critical_failures=by_sev.get("critical", 0), failed_attacks=ordered,
    )
