"""Alvos de teste: qualquer coisa que receba uma mensagem e devolva uma resposta."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

import httpx


class BotTarget(Protocol):
    name: str

    def send(self, session_id: str, message: str) -> str: ...


class CallableTarget:
    """Adapta uma função ``(session_id, message) -> str`` (útil em testes e integrações Python)."""

    def __init__(self, fn: Callable[[str, str], str], name: str = "callable") -> None:
        self._fn = fn
        self.name = name

    def send(self, session_id: str, message: str) -> str:
        return self._fn(session_id, message)


class HTTPTarget:
    """Bot exposto por HTTP. Por padrão envia ``{"session_id", "message"}`` e lê ``reply``.

    ``response_field`` aceita caminho com pontos (ex.: ``data.answer``) para respostas aninhadas.
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        request_field: str = "message",
        session_field: str = "session_id",
        response_field: str = "reply",
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = url
        self.url = url
        self.headers = headers or {}
        self.request_field = request_field
        self.session_field = session_field
        self.response_field = response_field
        self._client = client or httpx.Client(timeout=timeout)

    def send(self, session_id: str, message: str) -> str:
        resp = self._client.post(
            self.url,
            json={self.session_field: session_id, self.request_field: message},
            headers=self.headers,
        )
        resp.raise_for_status()
        data = resp.json()
        for part in self.response_field.split("."):
            data = data[part]
        return str(data)
