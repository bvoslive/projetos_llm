"""Export CSV de plataformas de atendimento (estilo Blip) e planilhas.

Colunas (nomes aceitos, sem diferenciar maiúsculas):
    conversation_id | ticket | session   -> id da conversa
    timestamp | data | created_at        -> opcional, ISO 8601
    sender | remetente | role | autor    -> quem falou
    text | texto | mensagem | content    -> conteúdo
    bot_id | bot                         -> opcional
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from fiscal.schema import Conversation, Message, Role

_ID = ("conversation_id", "ticket", "session", "id_conversa", "conversa")
_TS = ("timestamp", "data", "created_at", "datahora")
_SENDER = ("sender", "remetente", "role", "autor", "from")
_TEXT = ("text", "texto", "mensagem", "content", "message")
_BOT = ("bot_id", "bot")

ROLE_MAP = {
    "customer": Role.CUSTOMER, "cliente": Role.CUSTOMER, "user": Role.CUSTOMER, "usuario": Role.CUSTOMER,
    "bot": Role.BOT, "assistant": Role.BOT, "ia": Role.BOT, "agente_ia": Role.BOT, "robo": Role.BOT,
    "human": Role.HUMAN, "atendente": Role.HUMAN, "agent": Role.HUMAN, "humano": Role.HUMAN,
}


def _pick(row: dict[str, str], names: tuple[str, ...]) -> str | None:
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return None


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.strip())
    except ValueError:
        return None


def load_csv(path: str | Path) -> list[Conversation]:
    p = Path(path)
    with p.open(encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(f, delimiter=delimiter)
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        conv_id = _pick(row, _ID)
        if conv_id is None:
            raise ValueError(f"{p.name}: coluna de id da conversa ausente (esperado um de {_ID})")
        grouped.setdefault(conv_id, []).append(row)

    conversations = []
    for conv_id, items in grouped.items():
        messages = []
        for row in items:
            sender = (_pick(row, _SENDER) or "").lower()
            text = _pick(row, _TEXT)
            if sender not in ROLE_MAP:
                raise ValueError(f"{p.name}: remetente desconhecido {sender!r} (aceitos: {sorted(ROLE_MAP)})")
            if text is None:
                continue
            messages.append(Message(role=ROLE_MAP[sender], text=text, timestamp=_parse_ts(_pick(row, _TS))))
        # sort estável: sem data, preserva a ordem do arquivo
        messages.sort(key=lambda m: m.timestamp.replace(tzinfo=None) if m.timestamp else datetime.min)
        conversations.append(
            Conversation(id=conv_id, bot_id=_pick(items[0], _BOT) or "default", messages=messages)
        )
    return conversations
