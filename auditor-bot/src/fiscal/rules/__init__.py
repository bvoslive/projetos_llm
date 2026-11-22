"""Regras determinísticas (sem LLM): baratas, exatas e auditáveis. Rodam antes dos juízes."""

from __future__ import annotations

from fiscal.knowledge import KnowledgeBase
from fiscal.rules import handoff, pii, policy, price
from fiscal.schema import Conversation, Finding


def run_rules(conv: Conversation, kb: KnowledgeBase) -> list[Finding]:
    """Executa todas as regras sobre uma conversa JÁ pseudonimizada."""
    findings: list[Finding] = []
    for module in (price, policy, pii, handoff):
        findings.extend(module.check(conv, kb))
    return findings
