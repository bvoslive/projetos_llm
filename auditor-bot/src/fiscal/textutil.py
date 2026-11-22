"""Utilitários de texto: normalização para PT-BR e valores em reais."""

from __future__ import annotations

import re
import unicodedata

PRICE_RE = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?)", re.IGNORECASE)


def norm(text: str) -> str:
    """Minúsculas, sem acentos e com espaços colapsados (para casar regex em PT-BR)."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower()).strip()


def parse_brl(raw: str) -> float:
    """'1.299,90' -> 1299.9 ; '250' -> 250.0."""
    return float(raw.replace(".", "").replace(",", "."))


def prices_in(text: str) -> list[float]:
    return [parse_brl(m) for m in PRICE_RE.findall(text)]


def fmt_brl(value: float) -> str:
    s = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def snippet(text: str, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
