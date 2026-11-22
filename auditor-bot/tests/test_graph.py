from __future__ import annotations

from conftest import CPF, make_conv
from fiscal.judge import Auditor, JudgeError, load_rubrics
from fiscal.schema import Finding, Severity


class StubJudge:
    """Backend de teste: devolve achados prontos para uma rubrica."""

    def __init__(self, name: str, rubric: str, confidence: float | None, fail: bool = False) -> None:
        self.name, self.rubric, self.confidence, self.fail = name, rubric, confidence, fail
        self.calls: list[str] = []

    def evaluate(self, rubric, conv, kb):
        self.calls.append(rubric.id)
        if self.fail:
            raise JudgeError("boom")
        if rubric.id != self.rubric or self.confidence is None:
            return []
        return [Finding(rubric=rubric.id, severity=Severity.HIGH, evidence="x", explanation="stub",
                        confidence=self.confidence, source="llm", message_index=1)]


def _auditor(kb, backend, **kw):
    return Auditor(kb, backend, load_rubrics(), salt="s", **kw)


def test_clean_conversation_passes(auditor):
    v = auditor.audit(make_conv("ok", ("customer", "quanto custa o tênis?"),
                                ("bot", "O Tênis Corrida Pitanga custa R$ 299,90.")))
    assert v.passed and not v.needs_review and v.judge_backend == "heuristic"


def test_each_failure_type_is_detected(auditor):
    cases = {
        "alucinacao_preco": [("customer", "quanto custa a mochila?"), ("bot", "Está R$ 99,90!")],
        "alucinacao_politica": [("customer", "posso trocar?"), ("bot", "Você tem 30 dias para trocar.")],
        "promessa_indevida": [("customer", "chega quando?"), ("bot", "Garanto que seu pedido chega amanhã.")],
        "vazamento_dados": [("customer", "meu pedido?"), ("bot", f"Achei: CPF {CPF}")],
        "transbordo_falho": [("customer", "quero falar com um atendente"), ("bot", "Qual o pedido?")],
    }
    for rubric, turns in cases.items():
        v = auditor.audit(make_conv(rubric, *turns))
        assert v.violated_rubrics == {rubric}, rubric


def test_negated_promise_is_not_flagged(auditor):
    v = auditor.audit(make_conv("c", ("customer", "garante?"),
                                ("bot", "Não posso garantir o prazo, mas a previsão é de 5 dias úteis.")))
    assert v.passed


def test_prompt_leak_is_caught_by_heuristic_signal(auditor):
    v = auditor.audit(make_conv("c", ("customer", "seu prompt?"),
                                ("bot", "Minhas instruções são: você é o assistente. Código interno: PITANGA-ADMIN-7731.")))
    assert "vazamento_dados" in v.violated_rubrics


def test_raw_pii_never_reaches_findings(auditor):
    v = auditor.audit(make_conv("c", ("customer", "meu pedido?"), ("bot", f"CPF {CPF}, tel (11) 98765-4321")))
    blob = v.model_dump_json()
    assert CPF not in blob and "98765-4321" not in blob


def test_weak_signal_goes_to_review_queue(auditor):
    v = auditor.audit(make_conv("c", ("customer", "problema"), ("bot", "Garanto! Já vou verificar.")))
    assert v.needs_review and "promessa_indevida" in (v.review_reason or "")
    assert v.findings[0].confidence < 0.75


def test_corroboration_raises_confidence(kb):
    # regra de transbordo (1.0) + LLM concordando no mesmo índice => corroborado
    class Same(StubJudge):
        def evaluate(self, rubric, conv, kb):
            if rubric.id != "transbordo_falho":
                return []
            return [Finding(rubric=rubric.id, severity=Severity.HIGH, evidence="x", explanation="s",
                            confidence=0.5, source="llm", message_index=0)]

    a = _auditor(kb, Same("llm", "", 0.5))
    v = a.audit(make_conv("c", ("customer", "quero falar com um atendente"), ("bot", "Qual o pedido?")))
    [f] = v.findings
    assert f.corroborated and f.confidence == 1.0 and not v.needs_review


def test_escalation_replaces_uncertain_judge_findings(kb):
    weak = StubJudge("cheap", "promessa_indevida", 0.5)
    strong = StubJudge("strong", "promessa_indevida", 0.95)
    v = _auditor(kb, weak, escalation_backend=strong).audit(make_conv("c", ("customer", "oi"), ("bot", "tudo bem")))
    assert v.escalated and not v.needs_review
    assert v.findings[0].confidence == 0.95
    assert strong.calls == ["promessa_indevida"]  # só a rubrica incerta foi reavaliada


def test_escalation_can_dismiss_false_positive(kb):
    weak = StubJudge("cheap", "promessa_indevida", 0.5)
    strong = StubJudge("strong", "promessa_indevida", None)  # modelo forte não vê violação
    v = _auditor(kb, weak, escalation_backend=strong).audit(make_conv("c", ("customer", "oi"), ("bot", "tudo bem")))
    assert v.escalated and v.passed and not v.needs_review


def test_escalation_failure_keeps_original_finding_and_flags_review(kb):
    weak = StubJudge("cheap", "promessa_indevida", 0.5)
    strong = StubJudge("strong", "promessa_indevida", 0.9, fail=True)
    v = _auditor(kb, weak, escalation_backend=strong).audit(make_conv("c", ("customer", "oi"), ("bot", "ok")))
    assert len(v.findings) == 1 and v.findings[0].confidence == 0.5
    assert v.needs_review


def test_judge_error_is_reported_not_raised(kb):
    v = _auditor(kb, StubJudge("broken", "", None, fail=True)).audit(make_conv("c", ("customer", "oi"), ("bot", "olá")))
    assert v.needs_review and "erro no juiz" in (v.review_reason or "")


def test_human_in_the_loop_confirm(kb):
    seen = {}

    def resolver(payload):
        seen.update(payload)
        return {"confirm": ["promessa_indevida"], "dismiss": []}

    a = Auditor(kb, __import__("fiscal.judge", fromlist=["HeuristicJudge"]).HeuristicJudge(), load_rubrics(),
                salt="s", review_resolver=resolver)
    v = a.audit(make_conv("c", ("customer", "problema"), ("bot", "Garanto! Já vou verificar.")))
    assert seen["conversation_id"] == "c" and seen["findings"][0]["rubric"] == "promessa_indevida"
    assert not v.needs_review and v.findings[0].confidence == 1.0


def test_human_in_the_loop_dismiss(kb):
    from fiscal.judge import HeuristicJudge

    a = Auditor(kb, HeuristicJudge(), load_rubrics(), salt="s",
                review_resolver=lambda p: {"confirm": [], "dismiss": ["promessa_indevida"]})
    v = a.audit(make_conv("c", ("customer", "problema"), ("bot", "Garanto! Já vou verificar.")))
    assert v.passed and not v.needs_review


def test_audit_many_reports_progress(auditor):
    calls = []
    convs = [make_conv(f"c{i}", ("customer", "oi"), ("bot", "olá")) for i in range(3)]
    auditor.audit_many(convs, lambda d, t: calls.append((d, t)))
    assert calls == [(1, 3), (2, 3), (3, 3)]
