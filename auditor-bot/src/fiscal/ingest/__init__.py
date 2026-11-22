"""Adapters de entrada: transformam exports e webhooks no schema ``Conversation``."""

from __future__ import annotations

from pathlib import Path

from fiscal.ingest.buffer import ConversationBuffer
from fiscal.ingest.csv_export import load_csv
from fiscal.ingest.evolution import parse_evolution_webhook
from fiscal.ingest.jsonl import load_jsonl
from fiscal.ingest.whatsapp_cloud import parse_whatsapp_cloud_webhook
from fiscal.schema import Conversation

__all__ = [
    "ConversationBuffer",
    "load_conversations",
    "load_csv",
    "load_jsonl",
    "parse_evolution_webhook",
    "parse_whatsapp_cloud_webhook",
]


def load_conversations(path: str | Path) -> list[Conversation]:
    """Detecta o formato pela extensão (.csv ou .jsonl/.json)."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".csv":
        return load_csv(p)
    if suffix in {".jsonl", ".json", ".ndjson"}:
        return load_jsonl(p)
    raise ValueError(f"Formato não suportado: {suffix} (use .csv ou .jsonl)")
