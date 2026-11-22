from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import make_conv
from fiscal.ingest import (
    ConversationBuffer,
    load_conversations,
    load_csv,
    load_jsonl,
    parse_evolution_webhook,
    parse_whatsapp_cloud_webhook,
)
from fiscal.ingest.jsonl import dump_jsonl
from fiscal.schema import Message, Role


def test_csv_with_semicolon_and_portuguese_headers(tmp_path):
    p = tmp_path / "export.csv"
    p.write_text(
        "ticket;data;remetente;mensagem;bot\n"
        "t1;2026-11-01T10:00:00;cliente;oi, quanto custa o tênis?;loja-a\n"
        "t1;2026-11-01T10:00:05;bot;R$ 299,90;loja-a\n"
        "t2;2026-11-01T11:00:00;cliente;quero um atendente;loja-b\n"
        "t2;2026-11-01T11:00:10;atendente;Oi, sou a Ana;loja-b\n",
        encoding="utf-8-sig",
    )
    convs = {c.id: c for c in load_csv(p)}
    assert [m.role for m in convs["t1"].messages] == [Role.CUSTOMER, Role.BOT]
    assert convs["t2"].messages[1].role == Role.HUMAN and convs["t2"].bot_id == "loja-b"


def test_csv_orders_by_timestamp(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text(
        "conversation_id,timestamp,sender,text\n"
        "a,2026-11-01T10:00:05,bot,segunda\n"
        "a,2026-11-01T10:00:00,customer,primeira\n",
        encoding="utf-8",
    )
    [c] = load_csv(p)
    assert [m.text for m in c.messages] == ["primeira", "segunda"]


def test_csv_errors_are_explicit(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("conversation_id,sender,text\na,alienigena,oi\n", encoding="utf-8")
    with pytest.raises(ValueError, match="remetente desconhecido"):
        load_csv(p)
    p.write_text("x,sender,text\na,bot,oi\n", encoding="utf-8")
    with pytest.raises(ValueError, match="id da conversa"):
        load_csv(p)


def test_jsonl_roundtrip_and_autodetect(tmp_path):
    convs = [make_conv("a", ("customer", "oi"), ("bot", "olá")), make_conv("b", ("customer", "x"))]
    p = tmp_path / "c.jsonl"
    dump_jsonl(convs, p)
    assert load_jsonl(p) == convs
    assert load_conversations(p) == convs
    with pytest.raises(ValueError):
        load_conversations(tmp_path / "c.xml")


def test_whatsapp_cloud_webhook_customer_and_business_messages():
    payload = {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "5511999990000"}],
        "messages": [
            {"from": "5511999990000", "type": "text", "text": {"body": "oi"}, "timestamp": "1762000000"},
            {"from": "5511888880000", "type": "text", "text": {"body": "olá!"}, "timestamp": "1762000005"},
            {"from": "5511999990000", "type": "audio", "timestamp": "1762000010"},
        ],
    }}]}]}
    pairs = parse_whatsapp_cloud_webhook(payload, business_numbers={"+5511888880000"})
    assert [(cid, m.role, m.text) for cid, m in pairs] == [
        ("5511999990000", Role.CUSTOMER, "oi"),
        ("5511999990000", Role.BOT, "olá!"),
        ("5511999990000", Role.CUSTOMER, "[áudio]"),
    ]


def test_evolution_webhook():
    payload = {"event": "MESSAGES_UPSERT", "data": {
        "key": {"remoteJid": "5511999990000@s.whatsapp.net", "fromMe": False},
        "message": {"conversation": "quero um desconto"}, "messageTimestamp": 1762000000}}
    [(cid, m)] = parse_evolution_webhook(payload)
    assert cid == "5511999990000" and m.role == Role.CUSTOMER and m.text == "quero um desconto"

    bot = {"event": "messages.upsert", "data": {
        "key": {"remoteJid": "5511999990000@s.whatsapp.net", "fromMe": True},
        "message": {"extendedTextMessage": {"text": "oi!"}}}}
    assert parse_evolution_webhook(bot)[0][1].role == Role.BOT

    group = {"event": "messages.upsert", "data": {"key": {"remoteJid": "123@g.us"}, "message": {"conversation": "x"}}}
    assert parse_evolution_webhook(group) == []
    assert parse_evolution_webhook({"event": "connection.update"}) == []


def test_buffer_splits_sessions_by_idle_time():
    from datetime import UTC, datetime

    t0 = datetime(2026, 11, 1, 10, tzinfo=UTC)
    buf = ConversationBuffer(bot_id="b", idle=timedelta(hours=1))
    buf.add("c1", Message(role=Role.CUSTOMER, text="a", timestamp=t0))
    buf.add("c1", Message(role=Role.BOT, text="b", timestamp=t0 + timedelta(minutes=5)))
    buf.add("c1", Message(role=Role.CUSTOMER, text="c", timestamp=t0 + timedelta(hours=3)))
    convs = buf.conversations()
    assert [c.id for c in convs] == ["c1-1", "c1-2"] and [len(c.messages) for c in convs] == [2, 1]
