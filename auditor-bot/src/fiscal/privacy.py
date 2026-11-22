"""Detecção e pseudonimização de dados pessoais (LGPD).

Todo texto passa por aqui **antes** de qualquer regra, juiz ou armazenamento. Cada dado
pessoal vira um token estável ``[CPF#a1b2c3d4]`` calculado com HMAC-SHA256 e um sal secreto.
Isso resolve dois problemas ao mesmo tempo:

1. Nenhum dado pessoal bruto chega ao LLM, aos relatórios ou ao banco.
2. O mesmo dado gera o mesmo token, então ainda dá para detectar que o bot "falou" um CPF que o
   cliente nunca informou (vazamento), sem nunca ver o CPF.

Limitação conhecida: nomes próprios e endereços não são detectados (exigiria NER).
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass

from fiscal.schema import Conversation, Message

TOKEN_RE = re.compile(r"\[(CPF|CNPJ|EMAIL|TEL|CARTAO)#([0-9a-f]{8})\]")

_CPF_RE = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_CNPJ_RE = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<![\d.])(?:\+?55[\s-]?)?\(?\d{2}\)?[\s-]?9?\d{4}[\s-]?\d{4}(?!\d)")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def valid_cpf(value: str) -> bool:
    d = _digits(value)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        s = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def valid_cnpj(value: str) -> bool:
    d = _digits(value)
    if len(d) != 14 or len(set(d)) == 1:
        return False
    for n, weights in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]), (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        s = sum(int(d[i]) * weights[i] for i in range(n))
        r = s % 11
        if int(d[n]) != (0 if r < 2 else 11 - r):
            return False
    return True


def valid_luhn(value: str) -> bool:
    d = _digits(value)
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


@dataclass(frozen=True)
class PIIMatch:
    kind: str
    start: int
    end: int
    value: str


def find_pii(text: str) -> list[PIIMatch]:
    """Encontra PII sem sobreposição. A ordem de prioridade evita CPF virar telefone."""
    found: list[PIIMatch] = []

    def overlaps(s: int, e: int) -> bool:
        return any(s < m.end and e > m.start for m in found)

    specs = [
        ("EMAIL", _EMAIL_RE, lambda v: True),
        ("CNPJ", _CNPJ_RE, valid_cnpj),
        ("CPF", _CPF_RE, valid_cpf),
        ("CARTAO", _CARD_RE, valid_luhn),
        ("TEL", _PHONE_RE, lambda v: True),
    ]
    for kind, regex, validator in specs:
        for m in regex.finditer(text):
            if overlaps(m.start(), m.end()) or not validator(m.group()):
                continue
            found.append(PIIMatch(kind, m.start(), m.end(), m.group()))
    return sorted(found, key=lambda m: m.start)


def _token(kind: str, value: str, salt: str) -> str:
    canonical = value.lower() if kind == "EMAIL" else _digits(value)
    if kind == "TEL" and len(canonical) > 11:  # remove DDI 55
        canonical = canonical[-11:]
    digest = hmac.new(salt.encode(), f"{kind}:{canonical}".encode(), hashlib.sha256).hexdigest()
    return f"[{kind}#{digest[:8]}]"


def pseudonymize(text: str, salt: str) -> str:
    """Troca cada PII por um token estável. Idempotente: tokens existentes são preservados."""
    out, cursor = [], 0
    for m in find_pii(text):
        out.append(text[cursor : m.start])
        out.append(_token(m.kind, m.value, salt))
        cursor = m.end
    out.append(text[cursor:])
    return "".join(out)


def pseudonymize_conversation(conv: Conversation, salt: str) -> Conversation:
    messages = [Message(role=m.role, text=pseudonymize(m.text, salt), timestamp=m.timestamp) for m in conv.messages]
    return conv.model_copy(update={"messages": messages})
