"""Regra: o cliente pediu um humano e o bot não transferiu (transbordo falho)."""

from __future__ import annotations

import re

from fiscal.knowledge import KnowledgeBase
from fiscal.schema import Conversation, Finding, Role, Severity
from fiscal.textutil import norm, snippet

RUBRIC = "transbordo_falho"
LOOKAHEAD_BOT_MESSAGES = 2  # o bot tem até 2 respostas para iniciar a transferência


def _any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def check(conv: Conversation, kb: KnowledgeBase) -> list[Finding]:
    findings: list[Finding] = []
    msgs = conv.messages
    for i, msg in enumerate(msgs):
        if msg.role != Role.CUSTOMER or not _any(kb.human_request_patterns, norm(msg.text)):
            continue
        following = [m for m in msgs[i + 1 :] if m.role in (Role.BOT, Role.HUMAN)]
        # se um humano já assumiu logo em seguida, o transbordo aconteceu
        if following and following[0].role == Role.HUMAN:
            continue
        window = following[:LOOKAHEAD_BOT_MESSAGES]
        if not window:
            findings.append(_finding(i, msg.text, 0.7, "O cliente pediu atendimento humano e ficou sem resposta."))
            continue
        if not any(_any(kb.handoff_patterns, norm(m.text)) for m in window):
            findings.append(
                _finding(i, msg.text, 1.0, "O cliente pediu atendimento humano e o bot não iniciou a transferência.")
            )
    return findings


def _finding(index: int, evidence: str, confidence: float, explanation: str) -> Finding:
    return Finding(
        rubric=RUBRIC,
        severity=Severity.HIGH,
        evidence=snippet(evidence),
        explanation=explanation,
        confidence=confidence,
        source="rule",
        message_index=index,
    )
