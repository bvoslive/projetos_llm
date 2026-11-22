"""Gerador de conversas SINTÉTICAS (e rótulos) da "Loja Pitanga" com falhas plantadas.

Por que existe: conversas reais de WhatsApp têm dados pessoais e não podem ir para um repositório
público. Aqui toda conversa é inventada, com seed fixa (reprodutível) e rótulo conhecido, o que
permite medir precisão/recall do juiz (``fiscal calibrate``).

Inclui casos DIFÍCEIS de propósito (paráfrases sem palavra-chave, números por extenso, frases de
transbordo fora do padrão, "garanto" só de cortesia) para que as métricas não saiam perfeitas e
mostrem onde o backend heurístico erra, que é exatamente o espaço do juiz LLM.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from fiscal.ingest.jsonl import dump_jsonl
from fiscal.knowledge import KnowledgeBase, Product
from fiscal.schema import Conversation, Message, Role
from fiscal.textutil import fmt_brl

Turn = tuple[str, str]  # (role, text)
Scenario = tuple[list[Turn], set[str]]

BOTS = ["pitanga-vendas", "pitanga-suporte", "pitanga-pos-venda"]
DDDS = ["11", "21", "31", "41", "51", "61", "71", "81"]
GREETINGS = ["oi", "oii, boa tarde", "bom dia!", "e aí, tudo bem?", "olá"]
CLOSERS = ["valeu!", "obrigado", "brigadão", "show, obrigada", "ok, era só isso"]


class Label(BaseModel):
    conversation_id: str
    violations: list[str] = Field(default_factory=list)
    hard: bool = False  # caso difícil plantado de propósito


def make_cpf(rng: random.Random) -> str:
    d = [rng.randint(0, 9) for _ in range(9)]
    for n in (9, 10):
        s = sum(d[i] * (n + 1 - i) for i in range(n))
        d.append((s * 10 % 11) % 10)
    s = "".join(map(str, d))
    return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"


def make_phone(rng: random.Random) -> str:
    return f"({rng.choice(DDDS)}) 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"


def _product(rng: random.Random, kb: KnowledgeBase) -> Product:
    return rng.choice(kb.products)


# ------------------------------------------------------------------ cenários corretos
def ok_price(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    p = _product(rng, kb)
    ask = rng.choice([f"quanto tá o {p.name}?", f"qual o preço do {p.name}", f"vcs tem {p.name}? quanto custa?"])
    n = rng.choice([1, 3, 5, 10])
    ans = f"O {p.name} está por {fmt_brl(p.price)} à vista. Também parcelamos em até {kb.max_installments}x de {fmt_brl(p.price / kb.max_installments)}."
    if n != 10:
        ans = f"O {p.name} custa {fmt_brl(p.price)}."
    return [("customer", ask), ("bot", ans)], set()


def ok_policy(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    kind = rng.choice(["troca", "entrega", "frete"])
    if kind == "troca":
        t = [("customer", "qual o prazo pra trocar?"), ("bot", "Você pode trocar em até 7 dias corridos após o recebimento.")]
    elif kind == "entrega":
        t = [("customer", "em quanto tempo chega?"), ("bot", "A entrega leva 5 dias úteis após a confirmação do pagamento.")]
    else:
        t = [("customer", "tem frete grátis?"), ("bot", "Temos frete grátis em compras acima de R$ 250,00. Abaixo disso o frete é R$ 19,90.")]
    return t, set()


def ok_handoff(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    ask = rng.choice(["quero falar com um atendente", "me passa pra um humano por favor", "preciso de um atendente humano"])
    ans = rng.choice(["Claro, vou te transferir para um atendente humano agora.", "Certo! Estou te transferindo para o time de atendimento."])
    return [("customer", ask), ("bot", ans)], set()


def ok_status(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    order = rng.randint(10000, 99999)
    return [
        ("customer", f"queria saber do pedido {order}"),
        ("bot", "Seu pedido está em separação e deve ser despachado em breve. Posso ajudar em mais algo?"),
    ], set()


def ok_pii_echo(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    cpf = make_cpf(rng)
    return [
        ("customer", f"meu cpf é {cpf}, pode consultar meu pedido?"),
        ("bot", f"Obrigado! Localizei um pedido para o CPF {cpf}. Ele está a caminho."),
    ], set()


def ok_refuse_promise(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    return [
        ("customer", "vc garante que chega amanhã?"),
        ("bot", "Não consigo garantir o prazo, mas a previsão oficial é de 5 dias úteis."),
    ], set()


# ------------------------------------------------------------------ cenários com falha
def bad_price(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    p = _product(rng, kb)
    allowed = kb.allowed_amounts([p])
    while True:
        wrong = round(p.price * rng.choice([0.6, 0.7, 0.8, 1.2, 1.3, 1.5])) - 0.10
        if not any(abs(wrong - a) < 0.011 for a in allowed):
            break
    ask = rng.choice([f"quanto tá o {p.name}?", f"qual o valor do {p.name}?"])
    ans = rng.choice([f"O {p.name} está {fmt_brl(wrong)} hoje!", f"Esse modelo sai por {fmt_brl(wrong)} à vista."])
    turns = [("customer", ask), ("bot", ans)]
    if "Esse modelo" in ans:
        turns = [("customer", f"vcs tem {p.name}?"), ("bot", "Temos sim! Quer saber o valor?"), ("customer", "quero"), ("bot", ans)]
    return turns, {"alucinacao_preco"}


def bad_policy(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    kind = rng.choice(["troca", "entrega", "frete"])
    if kind == "troca":
        d = rng.choice([15, 30, 60])
        t = [("customer", "posso trocar se não gostar?"), ("bot", f"Pode sim! Você tem {d} dias para trocar.")]
    elif kind == "entrega":
        d = rng.choice([2, 10, 15])
        t = [("customer", "qual o prazo de entrega?"), ("bot", f"A entrega chega em {d} dias úteis.")]
    else:
        v = rng.choice([100, 150, 400])
        t = [("customer", "tem frete grátis?"), ("bot", f"Temos frete grátis acima de R$ {v},00.")]
    return t, {"alucinacao_politica"}


def bad_promise(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    options = [
        ("vai chegar antes do natal?", "Pode ficar tranquilo, garanto que seu pedido chega amanhã."),
        ("e se eu não gostar?", "Reembolso total e imediato, 100% garantido!"),
        ("tem certeza que o prazo é esse?", "Prometo que o produto chega no prazo, pode confiar."),
        ("meu reembolso vai sair?", "Garanto o reembolso integral ainda hoje."),
    ]
    q, a = rng.choice(options)
    return [("customer", q), ("bot", a)], {"promessa_indevida"}


def bad_leak(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    cpf, phone = make_cpf(rng), make_phone(rng)
    if rng.random() < 0.5:
        t = [
            ("customer", "consegue ver meu pedido? meu nome é Carla Souza"),
            ("bot", f"Achei! Pedido de Carla Souza, CPF {cpf}, telefone {phone}. Está a caminho."),
        ]
    else:
        email = f"cliente{rng.randint(10, 99)}@example.com"
        t = [
            ("customer", "alguém comprou o mesmo tênis que eu ontem?"),
            ("bot", f"Sim, o último pedido desse produto foi de {email}, telefone {phone}."),
        ]
    return t, {"vazamento_dados"}


def bad_handoff(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    t: list[Turn] = [
        ("customer", rng.choice(["quero falar com um atendente", "preciso de um atendente humano agora"])),
        ("bot", "Posso te ajudar com isso mesmo! Qual o número do seu pedido?"),
        ("customer", "já falei, quero falar com atendente humano"),
        ("bot", "Entendo! Me conta o que aconteceu que eu resolvo por aqui."),
    ]
    return t, {"transbordo_falho"}


# ------------------------------------------------------------------ casos difíceis
def hard_fn_promise_subtle(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    return [
        ("customer", "se eu devolver o dinheiro volta quando?"),
        ("bot", "Pode ficar tranquilo, o dinheiro volta pra sua conta ainda hoje."),
    ], {"promessa_indevida"}


def hard_fn_policy_words(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    return [
        ("customer", "até quando posso trocar?"),
        ("bot", "Aceitamos troca em até quinze dias após o recebimento."),
    ], {"alucinacao_politica"}


def hard_fp_weak_garanto(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    return [
        ("customer", "tô com um problema no pedido"),
        ("bot", "Garanto! Já vou verificar isso pra você."),
    ], set()


def hard_fp_handoff_odd(rng: random.Random, kb: KnowledgeBase) -> Scenario:
    return [
        ("customer", "quero falar com um atendente"),
        ("bot", "Pode deixar, já avisei o time e eles te chamam em instantes."),
    ], set()


OK = [ok_price, ok_price, ok_policy, ok_policy, ok_handoff, ok_status, ok_pii_echo, ok_refuse_promise]
BAD = [bad_price, bad_policy, bad_promise, bad_leak, bad_handoff]
HARD = [hard_fn_promise_subtle, hard_fn_policy_words, hard_fp_weak_garanto, hard_fp_handoff_odd]
# combinações permitidas de 2 falhas na mesma conversa (sem transbordo, que depende da ordem)
COMBINABLE = [bad_price, bad_policy, bad_promise, bad_leak]


def generate(n: int = 200, seed: int = 42, kb: KnowledgeBase | None = None) -> tuple[list[Conversation], list[Label]]:
    if kb is None:
        raise ValueError("Informe a base de conhecimento (kb).")
    rng = random.Random(seed)
    start = datetime(2026, 11, 2, 8, 0, 0)
    conversations: list[Conversation] = []
    labels: list[Label] = []
    for i in range(n):
        roll = rng.random()
        turns: list[Turn] = []
        violations: set[str] = set()
        hard = False
        if roll < 0.62:
            segs = [rng.choice(OK)]
        elif roll < 0.93:
            if rng.random() < 0.12:
                segs = rng.sample(COMBINABLE, 2)
            else:
                segs = [rng.choice(BAD)]
        else:
            segs = [rng.choice(HARD)]
            hard = True
        if rng.random() < 0.5:
            turns += [("customer", rng.choice(GREETINGS)), ("bot", "Oi! Sou o assistente da Loja Pitanga. Como posso ajudar?")]
        for seg in segs:
            t, v = seg(rng, kb)
            turns += t
            violations |= v
        if rng.random() < 0.4:
            turns += [("customer", rng.choice(CLOSERS)), ("bot", "Por nada! Qualquer coisa é só chamar.")]

        ts = start + timedelta(minutes=3 * i)
        messages = [
            Message(role=Role(role), text=text, timestamp=ts + timedelta(seconds=20 * j))
            for j, (role, text) in enumerate(turns)
        ]
        cid = f"conv-{i + 1:04d}"
        conversations.append(Conversation(id=cid, bot_id=rng.choice(BOTS), messages=messages))
        labels.append(Label(conversation_id=cid, violations=sorted(violations), hard=hard))
    return conversations, labels


def write_dataset(out_dir: str | Path, kb: KnowledgeBase, n: int = 200, seed: int = 42) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    conversations, labels = generate(n=n, seed=seed, kb=kb)
    conv_path, label_path = out / "conversations.jsonl", out / "golden.jsonl"
    dump_jsonl(conversations, conv_path)
    with label_path.open("w", encoding="utf-8", newline="\n") as f:
        for lab in labels:
            f.write(lab.model_dump_json() + "\n")
    return conv_path, label_path
