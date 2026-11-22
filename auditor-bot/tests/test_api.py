from __future__ import annotations

import hashlib
import hmac
import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fiscal.api.app import create_app  # noqa: E402
from fiscal.api.store import Store  # noqa: E402
from fiscal.config import Settings  # noqa: E402

CPF = "529.982.247-25"


@pytest.fixture
def client_factory(auditor, tmp_path):
    def make(**overrides):
        settings = Settings(pii_salt="s", db_path=str(tmp_path / "t.db"), **overrides)
        store = Store(settings.db_path, settings.pii_salt)
        return TestClient(create_app(settings, auditor=auditor, store=store)), store

    return make


def test_health(client_factory):
    client, _ = client_factory()
    assert client.get("/health").json()["status"] == "ok"


def test_audit_endpoint(client_factory):
    client, _ = client_factory()
    body = {"conversations": [{"id": "c1", "messages": [
        {"role": "customer", "text": "quanto custa a mochila?"}, {"role": "bot", "text": "R$ 99,90"}]}]}
    r = client.post("/v1/audit", json=body)
    assert r.status_code == 200
    assert r.json()["verdicts"][0]["findings"][0]["rubric"] == "alucinacao_preco"


def test_api_key_is_enforced_when_configured(client_factory):
    client, _ = client_factory(api_key="segredo")
    assert client.post("/v1/audit", json={"conversations": []}).status_code == 401
    assert client.post("/v1/audit", json={"conversations": []}, headers={"X-API-Key": "errada"}).status_code == 401
    assert client.post("/v1/audit", json={"conversations": []}, headers={"X-API-Key": "segredo"}).status_code == 200
    assert client.get("/health").status_code == 200  # health é público


def test_webhook_to_audit_flow_stores_no_raw_pii(client_factory, tmp_path):
    client, store = client_factory()
    evo = lambda text, from_me: {"event": "messages.upsert", "data": {  # noqa: E731
        "key": {"remoteJid": "5511999990000@s.whatsapp.net", "fromMe": from_me},
        "message": {"conversation": text}, "messageTimestamp": 1762000000 + (5 if from_me else 0)}}
    assert client.post("/v1/webhooks/evolution?bot_id=loja", json=evo("meu pedido?", False)).json() == {"stored": 1}
    client.post("/v1/webhooks/evolution?bot_id=loja", json=evo(f"Achei! CPF {CPF}, tel (11) 98765-4321", True))

    raw_db = (tmp_path / "t.db").read_bytes()
    assert b"5511999990000" not in raw_db and CPF.encode() not in raw_db and b"98765-4321" not in raw_db

    summary = client.post("/v1/audit/run", json={"bot_id": "loja"}).json()
    assert summary["n_audited"] == 1 and summary["conversations_with_failure"] == 1
    verdicts = client.get("/v1/verdicts").json()
    assert verdicts[0]["findings"][0]["rubric"] == "vazamento_dados"
    assert verdicts[0]["conversation_id"].startswith("c-")  # id anônimo, não o telefone
    assert client.get("/v1/summary").json()["n_audited"] == 1


def test_messages_endpoint_for_bot_replies(client_factory):
    client, store = client_factory()
    client.post("/v1/messages", json={"customer_id": "55119", "bot_id": "b", "role": "customer", "text": "quero um atendente"})
    r = client.post("/v1/messages", json={"customer_id": "55119", "bot_id": "b", "role": "bot", "text": "Qual o pedido?"})
    assert r.status_code == 202
    [conv] = store.conversations("b")
    assert [m.role.value for m in conv.messages] == ["customer", "bot"]


def test_whatsapp_verification_handshake(client_factory):
    client, _ = client_factory(webhook_verify_token="tok")
    ok = client.get("/v1/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "123"})
    assert ok.status_code == 200 and ok.text == "123"
    bad = client.get("/v1/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "x", "hub.challenge": "123"})
    assert bad.status_code == 403


def test_whatsapp_signature_validation(client_factory):
    client, _ = client_factory(whatsapp_app_secret="app-secret")
    payload = {"entry": [{"changes": [{"value": {"contacts": [{"wa_id": "5511"}], "messages": [
        {"from": "5511", "type": "text", "text": {"body": "oi"}, "timestamp": "1762000000"}]}}]}]}
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"app-secret", raw, hashlib.sha256).hexdigest()
    headers = {"content-type": "application/json"}
    assert client.post("/v1/webhooks/whatsapp", content=raw, headers=headers).status_code == 401
    assert client.post("/v1/webhooks/whatsapp", content=raw, headers={**headers, "x-hub-signature-256": "sha256=0"}).status_code == 401
    ok = client.post("/v1/webhooks/whatsapp", content=raw, headers={**headers, "x-hub-signature-256": sig})
    assert ok.status_code == 202 and ok.json() == {"stored": 1}
