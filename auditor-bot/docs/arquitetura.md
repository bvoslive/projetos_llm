# Arquitetura

## Visão geral

```
                ┌──────────── ingest/ ────────────┐
 CSV / JSONL ──▶│ csv_export · jsonl              │
 Webhook Meta ─▶│ whatsapp_cloud · evolution      │──▶ Conversation
 POST /v1/…  ──▶│ buffer (sessões por inatividade)│
                └─────────────────────────────────┘
                                │
                  sampling.stratified_sample (opcional)
                                ▼
                       judge/graph.py (LangGraph)
                                ▼
                            Verdict ──▶ report/aggregate ──▶ HTML · MD · JSON · PDF
```

O red teaming reaproveita o **mesmo grafo**: o runner conversa com o alvo, monta uma `Conversation` e a manda para o `Auditor`. Um ataque "funciona" quando a resposta casa com um padrão de falha ou quando o juiz acusa a rubrica-alvo.

## O grafo de julgamento (`src/fiscal/judge/graph.py`)

Estado (`AuditState`, um `TypedDict`):

| Campo | Tipo | Quem escreve | Observação |
|---|---|---|---|
| `conversation` | `Conversation` | entrada | texto **bruto** |
| `masked` | `Conversation` | `anonymize` | só ele segue adiante |
| `rule_findings` | `list[Finding]` | `run_rules` | confiança 1.0 |
| `judge_findings` | `list[Finding]` + reducer `add` | `judge_rubric` (paralelo) | fan-in dos juízes |
| `errors` | `list[str]` + reducer `add` | juízes/escalonamento | falha vira revisão, não exceção |
| `escalation_findings`, `escalated_rubrics` | | `escalate` | substituem os achados do juiz barato naquelas rubricas |
| `findings`, `uncertain` | | `consolidate` | recalculados a cada passagem |
| `verdict` | `Verdict` | `finalize` | saída |

Nós e arestas:

1. **`anonymize`**: `privacy.pseudonymize_conversation`. Daqui em diante ninguém vê PII bruta.
2. **`run_rules`**: preço, política, vazamento de PII, transbordo (`src/fiscal/rules/`).
3. **fan-out**: uma aresta condicional devolve um `Send("judge_rubric", {...})` **por rubrica**; LangGraph executa em paralelo e junta os resultados pelo reducer.
4. **`consolidate`**: agrupa por `(rubrica, índice da mensagem)`. Fontes diferentes concordando → `corroborated=True` e confiança `+0.15` (teto 1.0). Rubricas com algum achado abaixo do limiar (padrão 0,75) ficam em `uncertain`.
5. **Roteamento** após `consolidate`:
   - nada incerto → `finalize`;
   - incerto e há modelo forte configurado e ainda não escalou → `escalate` → volta a `consolidate`;
   - incerto sem escalonamento (ou depois dele) → `review_gate`.
6. **`review_gate`**:
   - modo **não interativo** (padrão): não altera nada; o `Verdict` sai com `needs_review=True` e o motivo;
   - modo **interativo** (`review_resolver` no `Auditor`, ou `fiscal audit --interactive`): chama `interrupt(...)` do LangGraph com a transcrição e os achados incertos; o humano devolve `{"confirm": [...], "dismiss": [...]}`. Confirmar fixa a confiança em 1.0; descartar remove o achado. O grafo é compilado com `InMemorySaver`, necessário para `interrupt`.
7. **`finalize`**: monta o `Verdict`. `needs_review` fica verdadeiro se sobrou incerteza **ou** se algum juiz falhou.

## Decisões de projeto

**Regras antes do LLM.** Preço, prazo, PII e transbordo são verificáveis. Regra é grátis, exata e auditável; LLM serve onde a regra não alcança (paráfrase, contexto). As duas fontes são fundidas e uma confirma a outra.

**Rubricas em YAML.** Critérios, exemplos positivos/negativos e severidade ficam em `src/fiscal/rubrics/*.yaml`, versionados e editáveis sem mexer no código. É a "metodologia" que você pode mostrar ao cliente e ajustar por vertical.

**Duas fases de custo.** Modelo barato em tudo; modelo forte só nos achados incertos (`--escalation-model`). O número de chamadas caras é proporcional à incerteza, não ao volume.

**Falha segura.** Se o juiz cai (rede, limite, saída inválida), a exceção é capturada **por rubrica**: a conversa sai com `needs_review=True` e o erro registrado. Se o modelo forte falha, mantemos o achado original em vez de zerar a rubrica.

**Índices alucinados são descartados.** O juiz LLM devolve `message_index`; índices fora da conversa são ignorados.

**Prompt injection no juiz.** O prompt do sistema declara a conversa como *dado* e manda ignorar pedidos para mudar de papel. Isso mitiga, não elimina; por isso o juiz só *classifica* e nunca executa ferramenta.

**Pseudonimização, não anonimização.** O mesmo dado gera o mesmo token (HMAC-SHA256 com sal secreto). Sem isso não seria possível detectar vazamento sem ver o dado. Ver [privacidade-lgpd.md](privacidade-lgpd.md).

## Backends de julgamento (`judge/backends.py`)

| Backend | Quando usar | Como funciona |
|---|---|---|
| `heuristic` | demo, CI, baseline, custo zero | regex nos `heuristic_signals` das rubricas, com negações e confiança por padrão. Só avalia rubricas que declaram sinais |
| `llm` | produção | `init_chat_model("provedor:modelo")` + `with_structured_output(LLMJudgeOutput)`; um prompt por rubrica com KB, critérios, exemplos e transcrição numerada |

Para outro backend, implemente o protocolo `JudgeBackend`: um atributo `name` e `evaluate(rubric, conv, kb) -> list[Finding]`.

## Base de verdade (`knowledge.py`)

`KnowledgeBase` é um YAML com produtos e preços, políticas com número verificável (`pattern` com um grupo de captura + `value`), valores fixos permitidos (frete), parcelas máximas e as frases que indicam pedido de humano e transbordo. Sem verdade de referência não existe "alucinação": é por isso que o relatório é sempre *contra a KB do cliente*.

## Armazenamento (`api/store.py`)

SQLite (stdlib). Grava **apenas texto já pseudonimizado** e ids anônimos (`c-<hmac>`), nunca o telefone. Veredictos são serializados em JSON.
