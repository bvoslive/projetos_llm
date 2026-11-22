# Integrações

## 1. Export CSV (Blip e planilhas)

O jeito mais rápido de começar. O CSV pode usar `,` ou `;` e UTF-8 (com ou sem BOM). Nomes de coluna aceitos (sem diferenciar maiúsculas):

| Campo | Aceita |
|---|---|
| id da conversa | `conversation_id`, `ticket`, `session`, `id_conversa`, `conversa` |
| horário (opcional, ISO 8601) | `timestamp`, `data`, `created_at`, `datahora` |
| remetente | `sender`, `remetente`, `role`, `autor`, `from` |
| texto | `text`, `texto`, `mensagem`, `content`, `message` |
| bot (opcional) | `bot_id`, `bot` |

Remetentes: **cliente** (`customer`, `cliente`, `user`, `usuario`), **bot** (`bot`, `assistant`, `ia`, `agente_ia`, `robo`) e **humano** (`human`, `atendente`, `agent`, `humano`). Valor desconhecido gera erro explícito (não adivinhamos). As mensagens são ordenadas por horário dentro da conversa.

```bash
fiscal audit export.csv --kb kb.yaml --margin 0.05 --backend llm
```

## 2. API HTTP

```bash
pip install -e ".[api]"
fiscal serve --port 8000        # docs interativas em /docs
```

Variáveis (prefixo `FISCAL_`, ver [.env.example](../.env.example)): `KB_PATH`, `DB_PATH`, `PII_SALT`, `JUDGE_BACKEND`, `JUDGE_MODEL`, `ESCALATION_MODEL`, `API_KEY`, `WEBHOOK_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `BUSINESS_NUMBERS`.

| Método e rota | Função |
|---|---|
| `GET /health` | status (público) |
| `POST /v1/audit` | audita conversas enviadas no corpo: `{"conversations": [Conversation]}` |
| `POST /v1/messages` | registra uma mensagem (`customer_id`, `bot_id`, `role`, `text`, `timestamp?`) |
| `POST /v1/webhooks/evolution?bot_id=` | webhook da Evolution API (evento `messages.upsert`) |
| `GET/POST /v1/webhooks/whatsapp?bot_id=` | handshake e eventos da WhatsApp Cloud API |
| `POST /v1/audit/run` | audita as conversas acumuladas e devolve o resumo com IC. Corpo: `{"bot_id", "idle_minutes", "sample"}` |
| `GET /v1/verdicts`, `GET /v1/summary` | resultados guardados |

Segurança:
- Com `FISCAL_API_KEY` definido, as rotas `/v1/*` exigem o header `X-API-Key` (comparação em tempo constante). **Os webhooks da Meta usam assinatura, não essa chave**: veja abaixo.
- Em produção, ponha a API atrás de HTTPS (proxy reverso).

### WhatsApp Cloud API (Meta)

1. Configure o webhook para `https://seu-host/v1/webhooks/whatsapp?bot_id=minha-loja`.
2. A Meta faz um `GET` com `hub.verify_token`; defina o mesmo valor em `FISCAL_WEBHOOK_VERIFY_TOKEN`.
3. Defina `FISCAL_WHATSAPP_APP_SECRET`: quando presente, todo `POST` precisa de `X-Hub-Signature-256` válido (HMAC-SHA256 do corpo), senão responde 401.
4. **A Cloud API só envia ao webhook as mensagens do cliente.** Registre as respostas do bot por `POST /v1/messages` (`role: "bot"`), ou inclua o número do negócio em `FISCAL_BUSINESS_NUMBERS` caso seu fluxo reenvie as mensagens de saída ao mesmo webhook.
5. Mídia não textual entra como `[áudio]`, `[imagem]` etc. (transcrição é roadmap).

### Evolution API

Aponte o webhook de instância (evento `MESSAGES_UPSERT`) para `https://seu-host/v1/webhooks/evolution?bot_id=minha-loja`, com o header `X-API-Key` se configurado. Mensagens `fromMe=true` entram como **bot**; grupos (`@g.us`) são ignorados. Se atendentes humanos usam o mesmo número, marque-os por `POST /v1/messages` com `role: "human"` (senão contam como bot).

### Sessões

Mensagens do mesmo cliente são agrupadas em **uma conversa** até 6 h de inatividade (`idle_minutes`); depois, abre-se outra. O id público da conversa é `c-<hmac>-<n>` (o telefone nunca aparece).

## 3. Python

```python
from fiscal.factory import build_auditor, load_kb
from fiscal.ingest import load_conversations

auditor = build_auditor(load_kb("kb.yaml"), backend="llm")
verdicts = auditor.audit_many(load_conversations("export.csv"))
```

Qualquer `Conversation` (pydantic) serve; veja `fiscal/schema.py`.

## 4. CI/CD

```yaml
- run: fiscal redteam --target https://staging.exemplo.com/chat --fail-on-critical
- run: fiscal calibrate conversas.jsonl golden.jsonl --backend llm --min-f1 0.85
```

O primeiro barra o deploy se um ataque crítico funcionar; o segundo, se o juiz regredir (por exemplo ao trocar de modelo). Veja [.github/workflows/ci.yml](../.github/workflows/ci.yml).
