from __future__ import annotations

import pytest

from conftest import make_conv
from fiscal.judge import JudgeError, LLMJudge, load_rubrics
from fiscal.judge.backends import LLMJudgeOutput, LLMViolation, build_backend


class FakeChat:
    """Imita um chat model do LangChain com saída estruturada."""

    def __init__(self, output=None, error: Exception | None = None) -> None:
        self.output, self.error, self.prompts = output, error, []

    def with_structured_output(self, schema):
        assert schema is LLMJudgeOutput
        return self

    def invoke(self, messages):
        self.prompts.append(messages)
        if self.error:
            raise self.error
        return self.output


def _rubric(rid="promessa_indevida"):
    return next(r for r in load_rubrics() if r.id == rid)


def test_llm_judge_maps_violations_to_findings(kb):
    chat = FakeChat(LLMJudgeOutput(violations=[
        LLMViolation(message_index=1, evidence="o dinheiro volta hoje", explanation="promete reembolso", confidence=0.8)
    ]))
    conv = make_conv("c", ("customer", "e o reembolso?"), ("bot", "Pode ficar tranquilo, o dinheiro volta hoje."))
    [f] = LLMJudge(chat_model=chat).evaluate(_rubric(), conv, kb)
    assert f.rubric == "promessa_indevida" and f.source == "llm" and f.confidence == 0.8 and f.message_index == 1


def test_prompt_contains_rubric_kb_and_numbered_transcript(kb):
    chat = FakeChat(LLMJudgeOutput())
    conv = make_conv("c", ("customer", "oi"), ("bot", "olá"))
    LLMJudge(chat_model=chat).evaluate(_rubric(), conv, kb)
    system, human = chat.prompts[0]
    assert "DADOS" in system[1] or "dados" in system[1].lower()
    assert "Promessa indevida" in human[1] and "Tênis Corrida Pitanga" in human[1]
    assert "[0] CLIENTE: oi" in human[1] and "[1] BOT: olá" in human[1]


def test_hallucinated_message_index_is_discarded(kb):
    chat = FakeChat(LLMJudgeOutput(violations=[
        LLMViolation(message_index=99, evidence="x", explanation="y", confidence=0.9),
        LLMViolation(message_index=-1, evidence="x", explanation="y", confidence=0.9),
    ]))
    assert LLMJudge(chat_model=chat).evaluate(_rubric(), make_conv("c", ("bot", "oi")), kb) == []


def test_provider_error_becomes_judge_error(kb):
    chat = FakeChat(error=TimeoutError("rede"))
    with pytest.raises(JudgeError, match="TimeoutError"):
        LLMJudge(chat_model=chat).evaluate(_rubric(), make_conv("c", ("bot", "oi")), kb)


def test_dict_output_is_validated(kb):
    chat = FakeChat({"violations": [{"message_index": 0, "evidence": "e", "explanation": "x", "confidence": 0.7}]})
    [f] = LLMJudge(chat_model=chat).evaluate(_rubric(), make_conv("c", ("bot", "oi")), kb)
    assert f.confidence == 0.7


def test_constructor_requires_model_or_chat():
    with pytest.raises(ValueError):
        LLMJudge()


def test_build_backend():
    assert build_backend("heuristic").name == "heuristic"
    assert build_backend("llm", "anthropic:claude-haiku-5-5").name == "llm"  # lazy: não conecta
    with pytest.raises(ValueError):
        build_backend("nope")


def test_llm_findings_flow_through_full_graph(kb):
    from fiscal.judge import Auditor

    chat = FakeChat(LLMJudgeOutput(violations=[
        LLMViolation(message_index=1, evidence="dinheiro volta hoje", explanation="promessa", confidence=0.9)
    ]))
    a = Auditor(kb, LLMJudge(chat_model=chat), [_rubric()], salt="s")
    v = a.audit(make_conv("c", ("customer", "reembolso?"), ("bot", "o dinheiro volta hoje")))
    assert v.violated_rubrics == {"promessa_indevida"} and v.judge_backend == "llm"
