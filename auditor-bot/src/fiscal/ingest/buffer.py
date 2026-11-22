"""Agrupa mensagens de webhook em conversas (sessões separadas por inatividade)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fiscal.schema import Conversation, Message


class ConversationBuffer:
    def __init__(self, bot_id: str = "default", idle: timedelta = timedelta(hours=6)) -> None:
        self.bot_id = bot_id
        self.idle = idle
        self._sessions: dict[str, list[list[Message]]] = {}

    def add(self, customer_id: str, message: Message) -> None:
        sessions = self._sessions.setdefault(customer_id, [])
        now = message.timestamp or datetime.now(UTC)
        if sessions:
            last = sessions[-1][-1].timestamp
            if last is not None and now - last > self.idle:
                sessions.append([])
        if not sessions:
            sessions.append([])
        sessions[-1].append(message)

    def conversations(self) -> list[Conversation]:
        out = []
        for customer_id, sessions in self._sessions.items():
            for n, messages in enumerate(sessions, 1):
                if messages:
                    out.append(Conversation(id=f"{customer_id}-{n}", bot_id=self.bot_id, messages=messages))
        return out
