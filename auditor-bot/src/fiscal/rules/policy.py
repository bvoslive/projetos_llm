"""Regra: o bot citou um número de política (prazo, frete) diferente do oficial."""

from __future__ import annotations

import re

from fiscal.knowledge import KnowledgeBase, parse_number
from fiscal.schema import Conversation, Finding, Role, Severity
from fiscal.textutil import norm, snippet

RUBRIC = "alucinacao_politica"


def check(conv: Conversation, kb: KnowledgeBase) -> list[Finding]:
    findings: list[Finding] = []
    for i, msg in enumerate(conv.messages):
        if msg.role != Role.BOT:
            continue
        text = norm(msg.text)
        for policy in kb.policies:
            if not any(k in text for k in policy.keywords):
                continue
            for m in re.finditer(policy.pattern, text):
                try:
                    stated = parse_number(m.group(1))
                except ValueError:
                    continue
                if abs(stated - policy.value) > 1e-6:
                    findings.append(
                        Finding(
                            rubric=RUBRIC,
                            severity=Severity.HIGH,
                            evidence=snippet(msg.text),
                            explanation=(
                                f"Política '{policy.name}': o bot informou {stated:g}, "
                                f"mas o valor oficial é {policy.value:g}."
                            ),
                            confidence=1.0,
                            source="rule",
                            message_index=i,
                        )
                    )
                    break
    return findings
