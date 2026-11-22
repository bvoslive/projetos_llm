# Metodologia estatística

O produto vende uma coisa: **uma taxa de falha com incerteza conhecida**. Esta página explica de onde vêm os números e como não se enganar com eles.

## 1. Por que amostrar

Julgar 100% das conversas com LLM custa caro e adiciona pouco. Uma amostra aleatória de tamanho `n` estima a taxa verdadeira com margem de erro calculável.

### Tamanho de amostra

Para estimar uma proporção com margem `e` e confiança `1-α`:

```
n₀ = z² · p(1-p) / e²          (p = 0,5 é o pior caso)
n  = n₀ / (1 + (n₀-1)/N)       (correção de população finita)
```

| Margem | Confiança | n (população grande) | n (N = 500) |
|---|---|---:|---:|
| ±5 p.p. | 95% | 385 | 218 |
| ±3 p.p. | 95% | 1068 | 341 |
| ±10 p.p. | 95% | 97 | 81 |

`fiscal audit --margin 0.05` faz esse cálculo (`sampling.required_sample_size`). Se a falha for rara (p pequeno), o `n` real necessário é menor que o do pior caso; o relatório mostra o intervalo efetivamente obtido.

## 2. Intervalo de Wilson, não o intervalo normal

Com poucas falhas, o intervalo normal (Wald) fica em `0%` quando se observa zero falhas e pode ficar negativo. O de Wilson é bem comportado nesses extremos:

- 0 falhas em 50 conversas → Wilson dá **[0%, ≈7%]**, não "0% de erro";
- 8 em 10 → **[49%, 94%]**.

Implementado em `sampling.wilson_interval` com `statistics.NormalDist` (sem SciPy), validado por testes contra valores de referência.

**Unidade de análise:** a taxa por rubrica conta **conversas** com pelo menos uma falha daquela rubrica, não mensagens. Uma conversa com duas falhas de preço conta uma vez.

## 3. Amostragem estratificada

`stratified_sample` divide por `bot_id` com **alocação proporcional** e pelo menos uma conversa por estrato. Como é proporcional, a taxa global não precisa de reponderação. Reprodutível por `--seed`.

Limite: o intervalo de Wilson do relatório trata a amostra como aleatória simples. É uma aproximação razoável com alocação proporcional; para inferência por bot individual, use amostras maiores por estrato.

## 4. Calibração do juiz

Um juiz LLM sem calibração é só uma opinião. Para cada rubrica, `fiscal calibrate` compara o juiz com rótulos humanos (golden set) e reporta:

| Métrica | Pergunta que responde |
|---|---|
| **Precisão** | Quando o juiz acusa falha, quantas vezes está certo? (custo: alarme falso, agência brigando por nada) |
| **Recall** | De todas as falhas reais, quantas o juiz pega? (custo: erro que vai para o cliente) |
| **F1** | Média harmônica das duas |
| **Kappa de Cohen** | Concordância com o humano **descontado o acaso**; importante quando a falha é rara e acertar "tudo ok" já dá 95% de acerto |

Interpretação usual do kappa: >0,8 muito boa, 0,6–0,8 boa, <0,4 fraca.

### Como montar o *seu* golden set

1. Amostre 100–200 conversas reais do cliente, incluindo as que parecem boas.
2. Rotule por rubrica (sim/não). **Dois rotuladores** nas ~30 primeiras, para medir o kappa entre humanos: se humanos discordam, a rubrica está mal definida, não o juiz.
3. Salve como `golden.jsonl` (`{"conversation_id": "...", "violations": ["promessa_indevida"]}`).
4. `fiscal calibrate conversas.jsonl golden.jsonl --backend llm` e itere nas rubricas (arquivos YAML) até F1 e kappa aceitáveis.
5. Congele o golden set e use `--min-f1` no CI para impedir regressão quando trocar de modelo ou editar um prompt.

### O golden set incluído é sintético

Foi gerado junto com as regras, então rubricas "fáceis" dão 1,00. Ele serve para: (a) testar o pipeline, (b) demonstrar o método e (c) travar regressão do baseline. **Não** é evidência de qualidade em produção. Contém casos difíceis plantados (paráfrases, números por extenso, "garanto" de cortesia) para que os erros aparecam.

## 5. O que o relatório **não** diz

- Não prova ausência de falha; mede uma taxa com incerteza.
- Falhas que o juiz não vê (falso negativo) não aparecem; o recall da calibração diz o quanto subestimamos. Se o recall de uma rubrica é 0,6, a taxa verdadeira é maior que a reportada.
- Amostras de um período não valem para outro (mudança de prompt, de modelo, sazonalidade). Reamostre.
