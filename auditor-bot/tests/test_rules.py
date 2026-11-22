from conftest import CPF, make_conv
from fiscal.privacy import pseudonymize_conversation
from fiscal.rules import handoff, pii, policy, price


def masked(conv):
    return pseudonymize_conversation(conv, "teste")


# ---------------------------------------------------------------- preço
def test_price_ok_with_installments_and_multiples(kb):
    conv = make_conv(
        "c", ("customer", "quanto custa o tênis?"),
        ("bot", "O Tênis Corrida Pitanga custa R$ 299,90, ou 10x de R$ 29,99. Duas unidades: R$ 599,80."),
    )
    assert price.check(conv, kb) == []


def test_price_wrong_uses_customer_context(kb):
    conv = make_conv("c", ("customer", "quanto custa a mochila?"), ("bot", "Está R$ 99,90 hoje!"))
    [f] = price.check(conv, kb)
    assert f.rubric == "alucinacao_preco" and f.message_index == 1 and f.confidence == 1.0


def test_price_ignores_messages_without_product_context(kb):
    conv = make_conv("c", ("customer", "oi"), ("bot", "Nosso frete é R$ 19,90."))
    assert price.check(conv, kb) == []


def test_price_allows_fixed_values_and_policy_numbers(kb):
    conv = make_conv(
        "c", ("customer", "quanto custa o boné?"),
        ("bot", "O Boné Aba Curva custa R$ 59,90. Frete R$ 19,90, grátis acima de R$ 250,00."),
    )
    assert price.check(conv, kb) == []


# ---------------------------------------------------------------- política
def test_policy_wrong_days(kb):
    conv = make_conv("c", ("customer", "posso trocar?"), ("bot", "Você tem 30 dias para trocar."))
    [f] = policy.check(conv, kb)
    assert f.rubric == "alucinacao_politica"
    assert "7" in f.explanation


def test_policy_correct_and_business_days_do_not_collide(kb):
    conv = make_conv(
        "c", ("customer", "e a entrega?"),
        ("bot", "Troca em até 7 dias corridos."), ("bot", "A entrega leva 5 dias úteis."),
    )
    assert policy.check(conv, kb) == []


def test_policy_wrong_free_shipping_threshold(kb):
    conv = make_conv("c", ("customer", "frete?"), ("bot", "Frete grátis acima de R$ 100,00."))
    assert len(policy.check(conv, kb)) == 1


# ---------------------------------------------------------------- vazamento de PII
def test_pii_leak_detected_on_pseudonymized_text(kb):
    conv = masked(make_conv("c", ("customer", "meu pedido?"), ("bot", f"Achei: CPF {CPF}.")))
    [f] = pii.check(conv, kb)
    assert f.rubric == "vazamento_dados" and f.severity.value == "critical"
    assert CPF not in f.evidence  # a evidência nunca contém o dado bruto


def test_pii_echo_of_customer_provided_value_is_ok(kb):
    conv = masked(make_conv("c", ("customer", f"meu cpf é {CPF}"), ("bot", f"Localizei o CPF {CPF}.")))
    assert pii.check(conv, kb) == []


def test_pii_provided_after_bot_message_still_counts_as_leak(kb):
    conv = masked(make_conv("c", ("bot", f"CPF {CPF}"), ("customer", f"meu cpf é {CPF}")))
    assert len(pii.check(conv, kb)) == 1


# ---------------------------------------------------------------- transbordo
def test_handoff_failure(kb):
    conv = make_conv("c", ("customer", "quero falar com um atendente"), ("bot", "Qual o número do pedido?"))
    [f] = handoff.check(conv, kb)
    assert f.rubric == "transbordo_falho" and f.confidence == 1.0


def test_handoff_success_within_two_bot_messages(kb):
    conv = make_conv(
        "c", ("customer", "quero falar com um atendente"),
        ("bot", "Posso ajudar?"), ("customer", "não"), ("bot", "Certo, vou te transferir agora."),
    )
    assert handoff.check(conv, kb) == []


def test_handoff_human_takes_over(kb):
    conv = make_conv("c", ("customer", "preciso de um atendente humano"), ("human", "Oi, sou a Ana."))
    assert handoff.check(conv, kb) == []


def test_handoff_unanswered_has_lower_confidence(kb):
    conv = make_conv("c", ("customer", "quero falar com um atendente"))
    [f] = handoff.check(conv, kb)
    assert f.confidence < 1.0
