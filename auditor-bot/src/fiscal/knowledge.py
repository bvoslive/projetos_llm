"""Base de verdade do cliente (preços, políticas, frases de transbordo).

É contra ela que o bot é auditado: sem verdade de referência não existe "alucinação".
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from fiscal.textutil import norm, parse_brl

DEFAULT_HUMAN_REQUEST = [
    r"falar com (um |uma |o |a )?(atendente|humano|pessoa|alguem|gerente|responsavel)",
    r"(quero|preciso|prefiro) (de )?(um |uma )?(atendente|humano)",
    r"atendente humano",
    r"chama (um |uma )?(atendente|humano|pessoa)",
    r"\bprocon\b",
    r"reclamacao formal",
]
DEFAULT_HANDOFF = [
    r"vou te transferir",
    r"estou te transferindo",
    r"transferindo (voce|a conversa)",
    r"encaminh\w+ (voce |a conversa )?(para|pro) (um |uma |o |a )?(atendente|time|especialista|setor)",
    r"(um|uma) (atendente|especialista) (humano |humana )?(vai|ira|entrara|assumira)",
    r"chamando (um |uma )?atendente",
]


class Product(BaseModel):
    name: str
    price: float
    aliases: list[str] = Field(default_factory=list)


class Policy(BaseModel):
    """Uma regra de negócio com um número verificável (prazo, valor mínimo etc.)."""

    id: str
    name: str
    keywords: list[str]  # a mensagem precisa mencionar algum (texto normalizado)
    pattern: str  # regex com 1 grupo de captura numérico, aplicado ao texto normalizado
    value: float
    text: str = ""


class KnowledgeBase(BaseModel):
    business: str = "Empresa"
    products: list[Product] = Field(default_factory=list)
    policies: list[Policy] = Field(default_factory=list)
    allowed_values: list[float] = Field(default_factory=list)  # ex.: frete fixo
    max_installments: int = 12
    human_request_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_HUMAN_REQUEST))
    handoff_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_HANDOFF))

    @classmethod
    def load(cls, path: str | Path) -> KnowledgeBase:
        with open(path, encoding="utf-8") as f:
            return cls.model_validate(yaml.safe_load(f))

    def find_products(self, text: str) -> list[Product]:
        t = norm(text)
        hits = []
        for p in self.products:
            if any(norm(n) in t for n in [p.name, *p.aliases]):
                hits.append(p)
        return hits

    def allowed_amounts(self, products: list[Product]) -> set[float]:
        """Valores em R$ que o bot pode citar legitimamente ao falar desses produtos."""
        allowed: set[float] = set(self.allowed_values)
        allowed.update(p.value for p in self.policies)
        for p in products:
            for k in range(1, 6):  # até 5 unidades
                allowed.add(round(p.price * k, 2))
            for n in range(1, self.max_installments + 1):  # parcelas
                allowed.add(round(p.price / n, 2))
        return allowed

    def summary(self) -> str:
        """Resumo textual para o prompt do juiz LLM."""
        lines = [f"Empresa: {self.business}", "Produtos e preços oficiais:"]
        lines += [f"- {p.name}: R$ {p.price:.2f}".replace(".", ",", 1) for p in self.products]
        if self.allowed_values:
            vals = ", ".join(f"R$ {v:.2f}" for v in self.allowed_values)
            lines.append(f"Valores fixos permitidos (frete etc.): {vals}")
        lines.append("Políticas oficiais:")
        lines += [f"- {p.name}: {p.text}" for p in self.policies]
        return "\n".join(lines)


def parse_number(raw: str) -> float:
    return parse_brl(raw.strip().rstrip(".,"))
