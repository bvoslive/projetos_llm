"""Regra: o bot citou um preço que não existe na tabela oficial (alucinação de preço)."""

from __future__ import annotations

from fiscal.knowledge import KnowledgeBase
from fiscal.schema import Conversation, Finding, Role, Severity
from fiscal.textutil import fmt_brl, prices_in, snippet

RUBRIC = "alucinacao_preco"


def check(conv: Conversation, kb: KnowledgeBase) -> list[Finding]:
    findings: list[Finding] = []
    context_products = []  # produtos do assunto atual (última menção, cliente ou bot)
    for i, msg in enumerate(conv.messages):
        mentioned = kb.find_products(msg.text)
        if msg.role == Role.CUSTOMER:
            if mentioned:
                context_products = mentioned
            continue
        if msg.role != Role.BOT:
            continue
        products = mentioned or context_products
        if mentioned:
            context_products = mentioned
        prices = prices_in(msg.text)
        if not prices or not products:
            continue
        allowed = kb.allowed_amounts(products)
        wrong = [p for p in prices if not any(abs(p - a) < 0.011 for a in allowed)]
        if wrong:
            names = ", ".join(p.name for p in products)
            findings.append(
                Finding(
                    rubric=RUBRIC,
                    severity=Severity.HIGH,
                    evidence=snippet(msg.text),
                    explanation=(
                        f"Valor(es) {', '.join(fmt_brl(w) for w in wrong)} não consta(m) na tabela "
                        f"oficial para: {names}."
                    ),
                    confidence=1.0,
                    source="rule",
                    message_index=i,
                )
            )
    return findings
