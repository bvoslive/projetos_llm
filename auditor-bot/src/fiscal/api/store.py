"""Persistência SQLite (stdlib). Guarda apenas texto JÁ pseudonimizado e ids anônimos."""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fiscal.ingest.buffer import ConversationBuffer
from fiscal.privacy import pseudonymize
from fiscal.schema import Conversation, Message, Role, Verdict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_key TEXT NOT NULL,
    bot_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_bot ON messages(bot_id, customer_key, ts);
CREATE TABLE IF NOT EXISTS verdicts (
    conversation_id TEXT PRIMARY KEY,
    bot_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path, salt: str) -> None:
        self.path = str(path)
        self.salt = salt
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def customer_key(self, customer_id: str) -> str:
        """Id anônimo e estável do cliente (o telefone nunca é gravado)."""
        digest = hmac.new(self.salt.encode(), f"cust:{customer_id}".encode(), hashlib.sha256).hexdigest()
        return f"c-{digest[:10]}"

    def add_message(self, customer_id: str, bot_id: str, message: Message) -> None:
        ts = (message.timestamp or datetime.now(UTC)).isoformat()
        with closing(self._conn()) as c, c:
            c.execute(
                "INSERT INTO messages(customer_key, bot_id, role, text, ts) VALUES (?,?,?,?,?)",
                (self.customer_key(customer_id), bot_id, message.role.value, pseudonymize(message.text, self.salt), ts),
            )

    def conversations(self, bot_id: str | None = None, idle: timedelta = timedelta(hours=6)) -> list[Conversation]:
        query = "SELECT customer_key, bot_id, role, text, ts FROM messages"
        args: tuple = ()
        if bot_id:
            query += " WHERE bot_id = ?"
            args = (bot_id,)
        query += " ORDER BY ts, id"
        with closing(self._conn()) as c:
            rows = c.execute(query, args).fetchall()
        buffers: dict[str, ConversationBuffer] = {}
        for customer_key, bot, role, text, ts in rows:
            buf = buffers.setdefault(bot, ConversationBuffer(bot_id=bot, idle=idle))
            buf.add(customer_key, Message(role=Role(role), text=text, timestamp=datetime.fromisoformat(ts)))
        return [conv for buf in buffers.values() for conv in buf.conversations()]

    def save_verdicts(self, verdicts: list[Verdict]) -> None:
        now = datetime.now(UTC).isoformat()
        with closing(self._conn()) as c, c:
            c.executemany(
                "INSERT OR REPLACE INTO verdicts(conversation_id, bot_id, payload, created_at) VALUES (?,?,?,?)",
                [(v.conversation_id, v.bot_id, v.model_dump_json(), now) for v in verdicts],
            )

    def verdicts(self, limit: int = 1000) -> list[Verdict]:
        with closing(self._conn()) as c:
            rows = c.execute("SELECT payload FROM verdicts ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [Verdict.model_validate_json(r[0]) for r in rows]
