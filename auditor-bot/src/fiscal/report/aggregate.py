"""Agrega veredictos em métricas por rubrica, com intervalo de confiança."""

from __future__ import annotations

from collections import Counter, defaultdict

from pydantic import BaseModel, Field

from fiscal.judge.rubrics import Rubric
from fiscal.sampling import wilson_interval
from fiscal.schema import Conversation, Finding, Severity, Verdict


class RubricStat(BaseModel):
    rubric_id: str
    name: str
    failures: int
    n: int
    rate: float
    ci_low: float
    ci_high: float
    severities: dict[str, int] = Field(default_factory=dict)


class ExampleFailure(BaseModel):
    conversation_id: str
    bot_id: str
    rubric: str
    severity: Severity
    confidence: float
    evidence: str
    explanation: str
    source: str


class AuditSummary(BaseModel):
    title: str = "Auditoria de atendimento"
    n_audited: int
    population: int | None = None
    confidence: float = 0.95
    judge_backend: str = "heuristic"
    conversations_with_failure: int
    overall_rate: float
    overall_ci: tuple[float, float]
    needs_review: int
    rubrics: list[RubricStat]
    by_bot: dict[str, dict[str, float]] = Field(default_factory=dict)
    examples: list[ExampleFailure] = Field(default_factory=list)


def summarize(
    verdicts: list[Verdict],
    rubrics: list[Rubric],
    *,
    population: int | None = None,
    confidence: float = 0.95,
    max_examples: int = 15,
    title: str = "Auditoria de atendimento",
) -> AuditSummary:
    n = len(verdicts)
    names = {r.id: r.name for r in rubrics}
    stats: list[RubricStat] = []
    for rid in names:
        failing = [v for v in verdicts if rid in v.violated_rubrics]
        sev = Counter(f.severity.value for v in failing for f in v.findings if f.rubric == rid)
        lo, hi = wilson_interval(len(failing), n, confidence)
        stats.append(
            RubricStat(
                rubric_id=rid, name=names[rid], failures=len(failing), n=n,
                rate=len(failing) / n if n else 0.0, ci_low=lo, ci_high=hi, severities=dict(sev),
            )
        )
    failing_any = [v for v in verdicts if v.findings]
    lo, hi = wilson_interval(len(failing_any), n, confidence)

    per_bot: dict[str, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        per_bot[v.bot_id].append(v)
    by_bot = {
        bot: {"n": float(len(vs)), "failure_rate": sum(1 for v in vs if v.findings) / len(vs)}
        for bot, vs in per_bot.items()
    }

    flat: list[tuple[Verdict, Finding]] = [(v, f) for v in verdicts for f in v.findings]
    flat.sort(key=lambda vf: (-vf[1].severity.rank, -vf[1].confidence))
    examples = [
        ExampleFailure(
            conversation_id=v.conversation_id, bot_id=v.bot_id, rubric=f.rubric, severity=f.severity,
            confidence=f.confidence, evidence=f.evidence, explanation=f.explanation, source=f.source,
        )
        for v, f in flat[:max_examples]
    ]
    backend = verdicts[0].judge_backend if verdicts else "heuristic"
    return AuditSummary(
        title=title, n_audited=n, population=population, confidence=confidence, judge_backend=backend,
        conversations_with_failure=len(failing_any), overall_rate=len(failing_any) / n if n else 0.0,
        overall_ci=(lo, hi), needs_review=sum(1 for v in verdicts if v.needs_review),
        rubrics=stats, by_bot=by_bot, examples=examples,
    )


def conversations_by_id(conversations: list[Conversation]) -> dict[str, Conversation]:
    return {c.id: c for c in conversations}
