from __future__ import annotations

from collections import Counter

import pytest

from fiscal.redteam import (
    CallableTarget,
    DemoBot,
    HTTPTarget,
    load_attacks,
    run_attack,
    run_suite,
    summarize_redteam,
)
from fiscal.redteam.models import Attack
from fiscal.schema import Severity


def test_attack_suite_has_50_attacks_in_10_categories():
    attacks = load_attacks()
    assert len(attacks) == 50
    assert len({a.id for a in attacks}) == 50  # ids únicos
    assert Counter(a.category for a in attacks).most_common()[-1][1] == 5  # 5 por categoria
    assert len({a.category for a in attacks}) == 10


def test_every_attack_is_actionable():
    for a in load_attacks():
        assert a.turns and all(t.strip() for t in a.turns), a.id
        assert a.fail_patterns or a.target_rubrics, f"{a.id} não define como detectar sucesso"


def test_filters():
    assert {a.category for a in load_attacks(categories=["prompt_leak"])} == {"prompt_leak"}
    assert [a.id for a in load_attacks(ids=["RT-001"])] == ["RT-001"]


def test_vulnerable_bot_fails_most_attacks(kb, auditor):
    results = run_suite(DemoBot(kb, vulnerable=True), auditor, load_attacks())
    summary = summarize_redteam(results, "demo")
    assert summary.rate > 0.7
    assert summary.critical_failures >= 8
    assert {c.category for c in summary.by_category} == {a.category for a in load_attacks()}


def test_hardened_bot_resists_almost_everything(kb, auditor):
    results = run_suite(DemoBot(kb, vulnerable=False), auditor, load_attacks())
    summary = summarize_redteam(results, "demo-hardened")
    assert summary.successes <= 2
    # a falha conhecida: "reclamação formal no Procon" não é reconhecida como pedido de humano pelo demo
    assert "RT-034" in {r.attack.id for r in summary.failed_attacks}


def test_success_reasons_explain_why(kb, auditor):
    [r] = [run_attack(a, DemoBot(kb), auditor) for a in load_attacks(ids=["RT-016"])]
    assert r.success
    assert any("vazamento_dados" in reason for reason in r.reasons)


def test_report_never_contains_raw_pii(kb, auditor):
    [r] = [run_attack(a, DemoBot(kb), auditor) for a in load_attacks(ids=["RT-016"])]
    blob = r.model_dump_json()
    assert "529.982.247-25" not in blob and "98765-4321" not in blob and "marcos.lima@example.com" not in blob
    assert "[CPF#" in blob


def test_target_error_does_not_abort_suite(auditor):
    def broken(session_id: str, message: str) -> str:
        raise ConnectionError("fora do ar")

    results = run_suite(CallableTarget(broken, "quebrado"), auditor, load_attacks(ids=["RT-001", "RT-002"]))
    assert all(r.error and "ConnectionError" in r.error and not r.success for r in results)
    s = summarize_redteam(results, "quebrado")
    assert s.total == 0 and s.errors == 2


def test_multi_turn_attack_sends_each_turn_with_same_session(auditor):
    seen = []

    def echo(session_id: str, message: str) -> str:
        seen.append((session_id, message))
        return "ok"

    attack = Attack(id="X", category="c", severity=Severity.LOW, title="t", turns=["a", "b"], fail_patterns=["nunca"])
    r = run_attack(attack, CallableTarget(echo), auditor)
    assert [m for _, m in seen] == ["a", "b"] and len({s for s, _ in seen}) == 1
    assert not r.success and len(r.conversation.messages) == 4


def test_http_target_posts_and_reads_nested_field():
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        assert b'"message"' in body and request.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"data": {"answer": "olá!"}})

    target = HTTPTarget(
        "http://bot.test/chat", headers={"authorization": "Bearer k"}, response_field="data.answer",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert target.send("s1", "oi") == "olá!"


def test_http_target_raises_on_http_error():
    import httpx

    target = HTTPTarget("http://bot.test/chat", client=httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(httpx.HTTPStatusError):
        target.send("s", "oi")
