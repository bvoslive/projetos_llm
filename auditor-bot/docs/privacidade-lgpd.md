# Privacidade e LGPD

Auditar atendimento é, por natureza, processar dados pessoais. O projeto foi desenhado para **minimizar** o que é tocado, mas isto é engenharia, não parecer jurídico: valide o tratamento (base legal, contrato com o cliente da agência, papéis de controlador/operador) com o jurídico antes de usar em produção.

## Princípio: o dado bruto não passa do primeiro nó

`privacy.pseudonymize` roda **antes** de qualquer regra, juiz, relatório ou gravação:

| Detecta | Validação | Token |
|---|---|---|
| CPF | dígitos verificadores | `[CPF#a1b2c3d4]` |
| CNPJ | dígitos verificadores | `[CNPJ#…]` |
| Cartão | algoritmo de Luhn | `[CARTAO#…]` |
| E-mail | regex | `[EMAIL#…]` |
| Telefone BR (com/sem DDI e máscara) | regex | `[TEL#…]` |

Validar CPF/CNPJ/cartão evita mascarar números aleatórios (ex.: número de pedido) e reduz falso positivo.

O token é `HMAC-SHA256(sal, tipo + valor normalizado)[:8]`. Propriedades:

- **Estável:** o mesmo CPF digitado com ou sem pontuação gera o mesmo token. É o que permite à regra `vazamento_dados` perceber que o bot citou um dado que o cliente **nunca informou**, sem ver o dado.
- **Não reversível sem o sal:** o espaço de CPFs é pequeno (10⁹); sem o sal secreto não dá para pré-computar uma tabela. **Troque o sal padrão** (`FISCAL_PII_SALT`) e guarde-o como segredo. Quem tem o sal pode testar palpites de CPF contra tokens.
- **Idempotente:** pseudonimizar de novo um texto já pseudonimizado não muda nada.

## O que é gravado

| Onde | Conteúdo |
|---|---|
| Banco SQLite (API) | texto **já pseudonimizado**, id do cliente como `c-<hmac>` (o telefone nunca é gravado), papel e horário |
| Veredictos e relatórios | evidências extraídas do texto pseudonimizado |
| Relatórios de red teaming | transcrições pseudonimizadas (testado: `test_report_never_contains_raw_pii`) |
| Chamadas ao LLM | somente texto pseudonimizado |

Há testes que garantem esses pontos: `test_raw_pii_never_reaches_findings`, `test_webhook_to_audit_flow_stores_no_raw_pii` (confere os bytes do arquivo `.db`) e `test_report_never_contains_raw_pii`.

## O que **não** é coberto

- **Nomes próprios e endereços** não são detectados (exigiria NER). Um bot que fala "Pedido da Carla Souza, Rua X, 123" **não** dispara a regra de vazamento por nome/endereço, e o texto vai ao LLM com esses dados. Se isso importa no seu caso, adicione uma etapa de NER ao `pseudonymize` ou rode o juiz em modelo/região com contrato adequado.
- **Dados sensíveis em texto livre** (saúde, religião...) não são detectados; o texto segue como está.
- **Pseudonimização ≠ anonimização** na LGPD: o dado continua sendo pessoal (é reidentificável com o sal). Trate o banco e os relatórios como dados pessoais.
- **Eco do cliente:** o bot repetir um CPF que o cliente acabou de digitar **não** é marcado como vazamento (é confirmação). Se a sua política proíbe até isso, endureça a regra em `rules/pii.py`.
- Quando um token do bot coincide com um que o cliente forneceu **depois**, ainda é sinalizado (o bot revelou antes de o cliente informar).

## Retenção e minimização (recomendações)

- Audite por **amostra** (`--margin`): menos conversas tocadas = menos exposição.
- Defina retenção para a tabela `messages` (ex.: apagar após o fechamento do relatório mensal). O projeto não apaga sozinho.
- Proteja o arquivo `.db`, o `.env` (sal, chaves) e a pasta `reports/` com as permissões da sua infraestrutura. `reports/` está no `.gitignore`.
- Não publique conversas reais em issues ou no repositório. Para reproduzir um problema, use `fiscal synth`.

## Dados sintéticos

Todos os CPFs, telefones e e-mails dos exemplos são **fictícios**: os CPFs são gerados por algoritmo (têm dígitos verificadores válidos para passar na detecção, e por acaso podem coincidir com o de uma pessoa real, mas não foram tirados de nenhuma fonte), e os e-mails usam `@example.com`. Nenhum dado de pessoa real foi usado.
