"""Webhook da Evolution API (evento ``messages.upsert``).

Mensagens ``fromMe=true`` são do número conectado (o bot ou um atendente usando a mesma
instância); as demais são do cliente. Distinguir bot de humano exige marcar o remetente
no seu fluxo; aqui assumimos bot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fiscal.schema import Message, Role


def parse_evolution_webhook(payload: dict[str, Any]) -> list[tuple[str, Message]]:
    event = str(payload.get("event", "")).lower().replace("_", ".")
    if event != "messages.upsert":
        return []
    data = payload.get("data", {})
    items = data if isinstance(data, list) else [data]
    out: list[tuple[str, Message]] = []
    for item in items:
        key = item.get("key", {})
        jid = str(key.get("remoteJid", ""))
        if not jid or jid.endswith("@g.us"):  # ignora grupos
            continue
        message = item.get("message", {}) or {}
        text = message.get("conversation") or message.get("extendedTextMessage", {}).get("text")
        if text is None and "audioMessage" in message:
            text = "[áudio]"
        if text is None:
            continue
        ts = item.get("messageTimestamp")
        stamp = datetime.fromtimestamp(int(ts), tz=UTC) if ts else None
        role = Role.BOT if key.get("fromMe") else Role.CUSTOMER
        out.append((jid.split("@")[0], Message(role=role, text=text, timestamp=stamp)))
    return out
