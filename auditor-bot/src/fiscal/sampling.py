"""Amostragem estatística e intervalos de confiança.

Auditar 100% das conversas com LLM é caro e desnecessário. Com uma amostra aleatória, a taxa de
falha tem erro conhecido e reportável (intervalo de Wilson).
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable
from statistics import NormalDist
from typing import TypeVar

T = TypeVar("T")


def z_score(confidence: float) -> float:
    if not 0 < confidence < 1:
        raise ValueError("confidence deve estar entre 0 e 1")
    return NormalDist().inv_cdf(0.5 + confidence / 2)


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Intervalo de Wilson para uma proporção. Bem comportado com n pequeno e p perto de 0/1,
    onde o intervalo normal (Wald) falha (ex.: 0 falhas em 50 conversas)."""
    if n <= 0:
        return (0.0, 1.0)
    if not 0 <= successes <= n:
        raise ValueError("successes deve estar entre 0 e n")
    z = z_score(confidence)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def required_sample_size(
    margin: float = 0.05, confidence: float = 0.95, population: int | None = None, p: float = 0.5
) -> int:
    """Tamanho de amostra para estimar uma proporção com a margem de erro desejada.

    ``p=0.5`` é o pior caso (maior variância). Com ``population`` aplica a correção de população finita.
    """
    if not 0 < margin < 1:
        raise ValueError("margin deve estar entre 0 e 1")
    z = z_score(confidence)
    n0 = (z**2) * p * (1 - p) / margin**2
    if population is not None:
        if population <= 0:
            return 0
        n0 = n0 / (1 + (n0 - 1) / population)
    n = math.ceil(n0)
    return min(n, population) if population is not None else n


def stratified_sample(
    items: list[T], n: int, key: Callable[[T], str], seed: int = 0
) -> list[T]:
    """Amostra estratificada com alocação proporcional (mínimo 1 por estrato, se couber).

    Como a alocação é proporcional ao tamanho do estrato, a amostra é autoponderada: a taxa
    global pode ser calculada sem reponderar.
    """
    if n >= len(items):
        return list(items)
    rng = random.Random(seed)
    strata: dict[str, list[T]] = defaultdict(list)
    for item in items:
        strata[key(item)].append(item)

    total = len(items)
    alloc = {k: max(1, round(n * len(v) / total)) for k, v in strata.items()}
    # ajusta para somar exatamente n, tirando/dando 1 do/ao maior estrato
    order = sorted(strata, key=lambda k: len(strata[k]), reverse=True)
    while sum(alloc.values()) > n:
        k = next((k for k in order if alloc[k] > 1), None)
        if k is None:
            break
        alloc[k] -= 1
    while sum(alloc.values()) < n:
        k = next((k for k in order if alloc[k] < len(strata[k])), None)
        if k is None:
            break
        alloc[k] += 1

    sample: list[T] = []
    for k, group in strata.items():
        sample.extend(rng.sample(group, min(alloc[k], len(group))))
    rng.shuffle(sample)
    return sample
