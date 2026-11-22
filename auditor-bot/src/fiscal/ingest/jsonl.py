"""Formato nativo: uma ``Conversation`` (JSON) por linha, ou um array JSON."""

from __future__ import annotations

import json
from pathlib import Path

from fiscal.schema import Conversation


def load_jsonl(path: str | Path) -> list[Conversation]:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        return [Conversation.model_validate(d) for d in json.loads(text)]
    return [Conversation.model_validate_json(line) for line in text.splitlines() if line.strip()]


def dump_jsonl(conversations: list[Conversation], path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8", newline="\n") as f:
        for c in conversations:
            f.write(c.model_dump_json() + "\n")
