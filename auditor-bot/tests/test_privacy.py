from fiscal.privacy import TOKEN_RE, find_pii, pseudonymize, valid_cnpj, valid_cpf, valid_luhn

SALT = "teste"


def test_valid_documents():
    assert valid_cpf("529.982.247-25")
    assert not valid_cpf("529.982.247-26")
    assert not valid_cpf("111.111.111-11")
    assert valid_cnpj("11.222.333/0001-81")
    assert not valid_cnpj("11.222.333/0001-82")
    assert valid_luhn("4111 1111 1111 1111")
    assert not valid_luhn("4111 1111 1111 1112")


def test_find_pii_kinds():
    text = "CPF 529.982.247-25, tel (11) 98765-4321, mail a.b@example.com, cartão 4111 1111 1111 1111"
    kinds = [m.kind for m in find_pii(text)]
    assert kinds == ["CPF", "TEL", "EMAIL", "CARTAO"]


def test_invalid_cpf_is_not_masked():
    assert pseudonymize("meu número 111.111.111-11", SALT) == "meu número 111.111.111-11"


def test_same_value_same_token_regardless_of_format():
    a = pseudonymize("cpf 529.982.247-25", SALT)
    b = pseudonymize("cpf 52998224725", SALT)
    assert a == b
    assert TOKEN_RE.search(a)


def test_token_depends_on_salt_and_hides_value():
    a = pseudonymize("529.982.247-25", "salt-1")
    b = pseudonymize("529.982.247-25", "salt-2")
    assert a != b
    assert "529" not in a


def test_idempotent():
    once = pseudonymize("fale com (11) 98765-4321 ou a@b.com", SALT)
    assert pseudonymize(once, SALT) == once


def test_phone_with_ddi_matches_phone_without():
    assert pseudonymize("+55 11 98765-4321", SALT) == pseudonymize("(11) 98765-4321", SALT)


def test_prices_and_order_numbers_are_not_pii():
    text = "O pedido 12345 custa R$ 1.299,90 em 10x de R$ 129,99"
    assert pseudonymize(text, SALT) == text
