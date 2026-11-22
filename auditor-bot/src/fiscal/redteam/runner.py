"""Executa a suíte de ataques contra um alvo e julga cada conversa resultante."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from importlib import resources
from pathlib import Path

import yaml

from fiscal.judge import Auditor
from fiscal.privacy import pseudonymize_conversation
from fiscal.redteam.models import Attack, AttackResult
from fiscal.redteam.targets import BotTarget
from fiscal.schema import Conversation, Message, Role, Verdict
from fiscal.textutil import norm


def load_attacks(
    directory: str | Path | None = None,
    categories: list[str] | None = None,
    ids: list[str] | None = None,
) -> list[Attack]:
    """Carrega os ataques do pacote (padrão) ou de uma pasta própria, com filtros opcionais."""
    paths = (
        sorted(Path(directory).glob("*.yaml"))
        if directory
        else sorted(p for p in resources.files("fiscal.redteam").joinpath("attacks").iterdir() if p.name.endswith(".yaml"))
    )
    attacks: list[Attack] = []
    for p in paths:
        for item in yaml.safe_load(p.read_text(encoding="utf-8")) or []:
            attack = Attack.model_validate(item)
            if categories and attack.category not in categories:
                continue
            if ids and attack.id not in ids:
                continue
            attacks.append(attack)
    return attacks


def run_attack(attack: Attack, target: BotTarget, auditor: Auditor) -> AttackResult:
    session_id = f"rt-{attack.id}-{uuid.uuid4().hex[:6]}"
    messages: list[Message] = []
    error: str | None = None
    try:
        for turn in attack.turns:
            messages.append(Message(role=Role.CUSTOMER, text=turn))
            messages.append(Message(role=Role.BOT, text=target.send(session_id, turn)))
    except Exception as exc:  # noqa: BLE001 - falha do alvo não pode derrubar a suíte inteira
        error = f"{type(exc).__name__}: {exc}"

    raw = Conversation(id=attack.id, bot_id=target.name, channel="redteam", messages=messages)
    if error:
        return AttackResult(
            attack=attack, conversation=pseudonymize_conversation(raw, auditor.salt),
            verdict=Verdict(conversation_id=attack.id, bot_id=target.name), success=False, error=error,
        )

    verdict = auditor.audit(raw)
    reasons: list[str] = []
    bot_text = [norm(m.text) for m in raw.messages if m.role == Role.BOT]
    for pattern in attack.fail_patterns:
        if any(re.search(pattern, t) for t in bot_text):
            reasons.append(f"resposta casa com o padrão de falha /{pattern}/")
    for rubric in attack.target_rubrics:
        if rubric in verdict.violated_rubrics:
            reasons.append(f"o juiz acusou a rubrica '{rubric}'")
    return AttackResult(
        attack=attack,
        conversation=pseudonymize_conversation(raw, auditor.salt),  # PII bruta nunca vai para o relatório
        verdict=verdict,
        success=bool(reasons),
        reasons=reasons,
    )


def run_suite(
    target: BotTarget,
    auditor: Auditor,
    attacks: list[Attack],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[AttackResult]:
    results = []
    for i, attack in enumerate(attacks, 1):
        results.append(run_attack(attack, target, auditor))
        if on_progress:
            on_progress(i, len(attacks))
    return results
