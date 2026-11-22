# Contribuindo

Obrigado pelo interesse! Este projeto aceita rubricas, ataques, adapters de entrada e correções.

## Ambiente

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,api]"
pytest
ruff check src tests
```

Tudo roda **offline** (o backend `heuristic` não precisa de chave). Testes com LLM usam um chat falso (`tests/test_llm_judge.py`); não adicione testes que chamem APIs reais.

## O que é fácil de contribuir

| Contribuição | Onde | O que checar |
|---|---|---|
| **Ataque novo de red teaming** | `src/fiscal/redteam/attacks/*.yaml` | `id` único; `fail_patterns` e/ou `target_rubrics`; texto em PT-BR natural. `tests/test_redteam.py` valida a estrutura |
| **Rubrica nova** | `src/fiscal/rubrics/*.yaml` | critérios do que **não** é violação; exemplos dos dois lados; caso no golden set |
| **Adapter de entrada** (Blip JSON, Zenvia, Twilio...) | `src/fiscal/ingest/` | devolva `Conversation` ou pares `(cliente, Message)`; teste com payload de exemplo anonimizado |
| **Regra determinística** | `src/fiscal/rules/` | funcione sobre texto **já pseudonimizado**; devolva `Finding` com evidência mascarada |
| **Backend de juiz** | `src/fiscal/judge/backends.py` | implemente `JudgeBackend`; traduza erros do provedor para `JudgeError` |

## Regras do jogo

- **Nunca** inclua conversas reais, CPFs reais, telefones ou chaves em código, testes, issues ou PRs. Use `fiscal synth`.
- Se mudar o gerador (`synth.py`) ou as rubricas, **regenere** os dados versionados e confirme que o teste de consistência passa:
  ```bash
  fiscal synth --out data/synthetic --kb data/loja_pitanga/kb.yaml
  pytest tests/test_calibration.py
  ```
  O README cita as métricas do baseline: atualize-as com `fiscal calibrate data/synthetic/conversations.jsonl data/synthetic/golden.jsonl`.
- Mudanças de comportamento precisam de teste. Mudanças de regra precisam de caso positivo **e** negativo (o que não deve disparar).
- Mantenha a promessa de privacidade: evidências nos achados nunca podem conter dado pessoal bruto.
- Texto de usuário (README, docs, mensagens de CLI) em **português do Brasil**; identificadores de código em inglês ou português já presentes, mas consistentes com o arquivo.

## Pull requests

1. Abra uma issue descrevendo o problema ou a ideia.
2. Branch a partir de `main`, commits pequenos e descritivos.
3. `pytest` e `ruff check` passando; o CI também roda o gate de calibração (`--min-f1 0.85`).
4. Descreva no PR o que mudou **e como você verificou**.

## Reportando vulnerabilidades

Se achar um problema de segurança (por exemplo, forma de vazar PII bruta pelo pipeline), **não abra issue pública**: contate o mantenedor por mensagem privada no GitHub.
