"""Webhook da WhatsApp Cloud API (Meta).

A Cloud API só entrega ao webhook as mensagens RECEBIDAS do cliente. As respostas do bot saem
pela sua própria integração, então o integrador precisa registrá-las (ex.: ``POST /v1/messages``
ou nos logs) ou o payload deve conter mensagens com ``from`` igual ao número do negócio, passado
em ``business_numbers``. Áudios entram como ``[áudio]`` (transcrição: roadmap).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fiscal.schema import Message, Role


def parse_whatsapp_cloud_webhook(
    payload: dict[str, Any], business_numbers: set[str] | None = None
) -> list[tuple[str, Message]]:
    """Retorna pares ``(wa_id_do_cliente, Message)`` extraídos do payload."""
    business = {n.lstrip("+") for n in (business_numbers or set())}
    out: list[tuple[str, Message]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = [c.get("wa_id") for c in value.get("contacts", []) if c.get("wa_id")]
            for msg in value.get("messages", []):
                sender = str(msg.get("from", ""))
                is_bot = sender in business
                customer_id = (contacts[0] if contacts else None) if is_bot else sender
                if not customer_id:
                    continue
                kind = msg.get("type", "text")
                text = msg.get("text", {}).get("body") if kind == "text" else f"[{_label(kind)}]"
                if text is None:
                    continue
                ts = msg.get("timestamp")
                stamp = datetime.fromtimestamp(int(ts), tz=UTC) if ts else None
                out.append((customer_id, Message(role=Role.BOT if is_bot else Role.CUSTOMER, text=text, timestamp=stamp)))
    return out


def _label(kind: str) -> str:
    return {"audio": "áudio", "image": "imagem", "video": "vídeo", "document": "documento"}.get(kind, kind)
