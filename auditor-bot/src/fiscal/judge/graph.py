"""Grafo LangGraph de julgamento de UMA conversa.

    START → anonymize → run_rules → ┬─ judge_rubric (1 nó por rubrica, em paralelo via Send)
                                    └─→ consolidate ─┬─ (incerto) escalate ─→ consolidate
                                                     ├─ (incerto) review_gate → finalize
                                                     └─ finalize → END

* ``anonymize``: pseudonimiza PII antes de qualquer outra coisa.
* ``run_rules``: regras determinísticas (preço, política, PII, transbordo).
* ``judge_rubric``: juiz (heurístico ou LLM) avalia uma rubrica; roda em paralelo.
* ``consolidate``: funde achados duplicados, calcula confiança e define o que é incerto.
* ``escalate``: reavalia só as rubricas incertas com um modelo mais forte (opcional).
* ``review_gate``: o que continuar incerto vai para revisão humana. Em modo interativo usa
  ``interrupt`` (human-in-the-loop); caso contrário, só marca ``needs_review``.
"""

from __future__ import annotations

import operator
import uuid
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from fiscal.judge.backends import JudgeBackend, JudgeError
from fiscal.judge.rubrics import Rubric
from fiscal.knowledge import KnowledgeBase
from fiscal.privacy import pseudonymize_conversation
from fiscal.rules import run_rules
from fiscal.schema import Conversation, Finding, Verdict

ReviewResolver = Callable[[dict[str, Any]], dict[str, Any]]


class AuditState(TypedDict, total=False):
    conversation: Conversation
    masked: Conversation
    rule_findings: list[Finding]
    judge_findings: Annotated[list[Finding], operator.add]  # fan-in dos juízes paralelos
    errors: Annotated[list[str], operator.add]
    escalation_findings: list[Finding]
    escalated: bool
    escalated_rubrics: list[str]
    findings: list[Finding]
    uncertain: list[str]
    human_reviewed: bool
    verdict: Verdict


def merge_findings(findings: list[Finding]) -> list[Finding]:
    """Une achados da mesma rubrica na mesma mensagem.

    Fontes independentes que concordam aumentam a confiança (+0.15, máx. 1.0).
    """
    groups: dict[tuple[str, int | None], list[Finding]] = {}
    for f in findings:
        groups.setdefault((f.rubric, f.message_index), []).append(f)
    merged: list[Finding] = []
    for group in groups.values():
        best = max(group, key=lambda f: (f.source == "rule", f.confidence))
        sources = {f.source for f in group}
        if len(sources) > 1:
            best = best.model_copy(
                update={
                    "confidence": min(1.0, max(f.confidence for f in group) + 0.15),
                    "corroborated": True,
                    "severity": max((f.severity for f in group), key=lambda s: s.rank),
                }
            )
        merged.append(best)
    return sorted(merged, key=lambda f: (-f.severity.rank, f.message_index if f.message_index is not None else -1))


def build_graph(
    backend: JudgeBackend,
    kb: KnowledgeBase,
    rubrics: list[Rubric],
    *,
    salt: str,
    review_threshold: float = 0.75,
    escalation_backend: JudgeBackend | None = None,
    interactive_review: bool = False,
):
    rubric_by_id = {r.id: r for r in rubrics}

    def anonymize(state: AuditState) -> dict:
        return {"masked": pseudonymize_conversation(state["conversation"], salt)}

    def rules_node(state: AuditState) -> dict:
        return {"rule_findings": run_rules(state["masked"], kb)}

    def fan_out(state: AuditState) -> list[Send] | list[str]:
        if not rubrics:
            return ["consolidate"]
        return [Send("judge_rubric", {"rubric": r, "masked": state["masked"]}) for r in rubrics]

    def judge_rubric(payload: dict) -> dict:
        rubric: Rubric = payload["rubric"]
        try:
            return {"judge_findings": backend.evaluate(rubric, payload["masked"], kb)}
        except JudgeError as exc:
            return {"errors": [f"{rubric.id}: {exc}"]}

    def consolidate(state: AuditState) -> dict:
        escalated = set(state.get("escalated_rubrics", []))
        judge = [f for f in state.get("judge_findings", []) if f.rubric not in escalated]
        merged = merge_findings(state.get("rule_findings", []) + judge + state.get("escalation_findings", []))
        uncertain = sorted({f.rubric for f in merged if f.confidence < review_threshold})
        return {"findings": merged, "uncertain": uncertain}

    def route(state: AuditState) -> str:
        if not state.get("uncertain"):
            return "finalize"
        if escalation_backend is not None and not state.get("escalated"):
            return "escalate"
        return "review_gate"

    def escalate(state: AuditState) -> dict:
        out: list[Finding] = []
        errors: list[str] = []
        for rid in state["uncertain"]:
            try:
                out.extend(escalation_backend.evaluate(rubric_by_id[rid], state["masked"], kb))  # type: ignore[union-attr]
            except JudgeError as exc:
                errors.append(f"escalonamento {rid}: {exc}")
        # Se o modelo forte falhar, mantemos os achados originais (não zera a rubrica).
        failed = {e.split(":")[0].replace("escalonamento ", "") for e in errors}
        return {
            "escalation_findings": out,
            "escalated": True,
            "escalated_rubrics": [r for r in state["uncertain"] if r not in failed],
            "errors": errors,
        }

    def review_gate(state: AuditState) -> dict:
        if not interactive_review:
            return {}
        pending = [f for f in state["findings"] if f.confidence < review_threshold]
        decision = interrupt(
            {
                "conversation_id": state["conversation"].id,
                "transcript": state["masked"].transcript(),
                "findings": [f.model_dump(mode="json") for f in pending],
            }
        )
        confirm, dismiss = set(decision.get("confirm", [])), set(decision.get("dismiss", []))
        kept: list[Finding] = []
        for f in state["findings"]:
            uncertain = f.confidence < review_threshold
            if uncertain and f.rubric in dismiss:
                continue
            if uncertain and f.rubric in confirm:
                f = f.model_copy(update={"confidence": 1.0})
            kept.append(f)
        left = [r for r in state["uncertain"] if r not in confirm | dismiss]
        return {"findings": kept, "uncertain": left, "human_reviewed": True}

    def finalize(state: AuditState) -> dict:
        reasons = []
        if state.get("uncertain"):
            reasons.append("achados de baixa confiança em: " + ", ".join(state["uncertain"]))
        if state.get("errors"):
            reasons.append("erro no juiz: " + "; ".join(state["errors"]))
        verdict = Verdict(
            conversation_id=state["conversation"].id,
            bot_id=state["conversation"].bot_id,
            findings=state.get("findings", []),
            needs_review=bool(reasons),
            review_reason="; ".join(reasons) or None,
            judge_backend=backend.name,
            escalated=bool(state.get("escalated")),
        )
        return {"verdict": verdict}

    g = StateGraph(AuditState)
    g.add_node("anonymize", anonymize)
    g.add_node("run_rules", rules_node)
    g.add_node("judge_rubric", judge_rubric)
    g.add_node("consolidate", consolidate)
    g.add_node("escalate", escalate)
    g.add_node("review_gate", review_gate)
    g.add_node("finalize", finalize)

    g.add_edge(START, "anonymize")
    g.add_edge("anonymize", "run_rules")
    g.add_conditional_edges("run_rules", fan_out, ["judge_rubric", "consolidate"])
    g.add_edge("judge_rubric", "consolidate")
    g.add_conditional_edges("consolidate", route, ["escalate", "review_gate", "finalize"])
    g.add_edge("escalate", "consolidate")
    g.add_edge("review_gate", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=InMemorySaver() if interactive_review else None)


class Auditor:
    """Fachada: audita conversas com o grafo, em lote ou com revisão humana interativa."""

    def __init__(
        self,
        kb: KnowledgeBase,
        backend: JudgeBackend,
        rubrics: list[Rubric],
        *,
        salt: str,
        review_threshold: float = 0.75,
        escalation_backend: JudgeBackend | None = None,
        review_resolver: ReviewResolver | None = None,
    ) -> None:
        self.backend = backend
        self.rubrics = rubrics
        self.salt = salt
        self.review_resolver = review_resolver
        self.graph = build_graph(
            backend,
            kb,
            rubrics,
            salt=salt,
            review_threshold=review_threshold,
            escalation_backend=escalation_backend,
            interactive_review=review_resolver is not None,
        )

    def audit(self, conv: Conversation) -> Verdict:
        config = {"configurable": {"thread_id": f"{conv.id}-{uuid.uuid4().hex[:8]}"}}
        result = self.graph.invoke({"conversation": conv}, config)
        while "__interrupt__" in result and self.review_resolver is not None:
            payload = result["__interrupt__"][0].value
            result = self.graph.invoke(Command(resume=self.review_resolver(payload)), config)
        return result["verdict"]

    def audit_many(
        self, conversations: list[Conversation], on_progress: Callable[[int, int], None] | None = None
    ) -> list[Verdict]:
        verdicts = []
        for i, conv in enumerate(conversations, 1):
            verdicts.append(self.audit(conv))
            if on_progress:
                on_progress(i, len(conversations))
        return verdicts
