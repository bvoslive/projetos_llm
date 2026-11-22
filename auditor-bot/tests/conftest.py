from __future__ import annotations

from pathlib import Path

import pytest

from fiscal.factory import build_auditor
from fiscal.judge import Auditor
from fiscal.knowledge import KnowledgeBase
from fiscal.schema import Conversation, Message, Role

ROOT = Path(__file__).resolve().parents[1]
KB_PATH = ROOT / "data" / "loja_pitanga" / "kb.yaml"

CPF = "529.982.247-25"  # CPF válido (dígitos verificadores corretos), usado só em testes


@pytest.fixture(scope="session")
def kb() -> KnowledgeBase:
    return KnowledgeBase.load(KB_PATH)


@pytest.fixture
def auditor(kb: KnowledgeBase) -> Auditor:
    return build_auditor(kb, backend="heuristic")


def make_conv(conv_id: str, *turns: tuple[str, str], bot_id: str = "bot-a") -> Conversation:
    """make_conv('c1', ('customer', 'oi'), ('bot', 'olá'))"""
    return Conversation(id=conv_id, bot_id=bot_id, messages=[Message(role=Role(r), text=t) for r, t in turns])
