"""API HTTP: auditoria sob demanda e ingestão de webhooks (WhatsApp Cloud API e Evolution API).

Rodar: ``fiscal serve`` (ou ``uvicorn fiscal.api.app:app``). Documentação interativa em ``/docs``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from fiscal import __version__
from fiscal.api.store import Store
from fiscal.config import Settings, get_settings
from fiscal.factory import build_auditor, load_kb
from fiscal.ingest import parse_evolution_webhook, parse_whatsapp_cloud_webhook
from fiscal.judge import Auditor
from fiscal.report import AuditSummary, summarize
from fiscal.sampling import stratified_sample
from fiscal.schema import Conversation, Message, Role, Verdict


class AuditRequest(BaseModel):
    conversations: list[Conversation]


class AuditResponse(BaseModel):
    verdicts: list[Verdict]


class MessageIn(BaseModel):
    customer_id: str
    bot_id: str = "default"
    role: Role
    text: str
    timestamp: datetime | None = None


class RunRequest(BaseModel):
    bot_id: str | None = None
    idle_minutes: int = 360
    sample: int | None = None


def create_app(
    settings: Settings | None = None, auditor: Auditor | None = None, store: Store | None = None
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Fiscal de Bot", version=__version__, description=__doc__)
    state: dict[str, Any] = {"auditor": auditor, "store": store}

    def get_auditor() -> Auditor:
        if state["auditor"] is None:  # carregamento preguiçoso: a API sobe mesmo sem KB para /health
            state["auditor"] = build_auditor(load_kb(settings=settings), settings=settings)
        return state["auditor"]

    def get_store() -> Store:
        if state["store"] is None:
            state["store"] = Store(settings.db_path, settings.pii_salt)
        return state["store"]

    def require_key(x_api_key: str | None = Header(default=None)) -> None:
        if settings.api_key and not hmac.compare_digest(x_api_key or "", settings.api_key):
            raise HTTPException(status_code=401, detail="API key inválida")

    secured = [Depends(require_key)]

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/v1/audit", response_model=AuditResponse, dependencies=secured)
    def audit(req: AuditRequest) -> AuditResponse:
        """Audita conversas enviadas no corpo da requisição (dados pessoais são pseudonimizados)."""
        return AuditResponse(verdicts=get_auditor().audit_many(req.conversations))

    @app.post("/v1/messages", status_code=202, dependencies=secured)
    def add_message(msg: MessageIn) -> dict[str, str]:
        """Registra uma mensagem (use para as respostas do bot, que a Cloud API não envia ao webhook)."""
        get_store().add_message(msg.customer_id, msg.bot_id, Message(role=msg.role, text=msg.text, timestamp=msg.timestamp))
        return {"status": "accepted"}

    @app.post("/v1/webhooks/evolution", status_code=202, dependencies=secured)
    async def evolution(request: Request, bot_id: str = "default") -> dict[str, int]:
        pairs = parse_evolution_webhook(await request.json())
        for customer_id, message in pairs:
            get_store().add_message(customer_id, bot_id, message)
        return {"stored": len(pairs)}

    @app.get("/v1/webhooks/whatsapp", response_class=PlainTextResponse)
    def whatsapp_verify(
        mode: str = Query(alias="hub.mode"),
        token: str = Query(alias="hub.verify_token"),
        challenge: str = Query(alias="hub.challenge"),
    ) -> str:
        if mode != "subscribe" or not hmac.compare_digest(token, settings.webhook_verify_token):
            raise HTTPException(status_code=403, detail="token de verificação inválido")
        return challenge

    @app.post("/v1/webhooks/whatsapp", status_code=202)
    async def whatsapp(request: Request, bot_id: str = "default") -> dict[str, int]:
        raw = await request.body()
        if settings.whatsapp_app_secret:
            expected = "sha256=" + hmac.new(settings.whatsapp_app_secret.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(request.headers.get("x-hub-signature-256", ""), expected):
                raise HTTPException(status_code=401, detail="assinatura inválida")
        business = {n.strip() for n in settings.business_numbers.split(",") if n.strip()}
        pairs =parse_whatsapp_cloud_webhook(json.loads(raw or b"{}"), business)
        for customer_id, message in pairs:
            get_store().add_message(customer_id, bot_id, message)
        return {"stored": len(pairs)}

    @app.post("/v1/audit/run", response_model=AuditSummary, dependencies=secured)
    def run_stored(req: RunRequest) -> AuditSummary:
        """Audita as conversas acumuladas pelos webhooks e devolve o resumo com IC."""
        convs = get_store().conversations(req.bot_id, timedelta(minutes=req.idle_minutes))
        population = len(convs)
        if req.sample is not None:
            convs = stratified_sample(convs, req.sample, key=lambda c: c.bot_id)
        verdicts = get_auditor().audit_many(convs)
        get_store().save_verdicts(verdicts)
        return summarize(verdicts, get_auditor().rubrics, population=population)

    @app.get("/v1/verdicts", response_model=list[Verdict], dependencies=secured)
    def list_verdicts(limit: int = Query(default=100, le=1000)) -> list[Verdict]:
        return get_store().verdicts(limit)

    @app.get("/v1/summary", response_model=AuditSummary, dependencies=secured)
    def summary() -> AuditSummary:
        return summarize(get_store().verdicts(), get_auditor().rubrics)

    app.state.started_at = datetime.now(UTC)
    return app


app = create_app()
