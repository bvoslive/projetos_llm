"""Rubricas versionadas em YAML: a "metodologia" de auditoria fica fora do código."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from fiscal.schema import Severity


class Signal(BaseModel):
    """Padrão lexical usado pelo backend heurístico (offline)."""

    pattern: str  # aplicado a texto minúsculo e sem acentos
    confidence: float = 0.8
    negate_if: list[str] = Field(default_factory=list)


class Rubric(BaseModel):
    id: str
    name: str
    severity: Severity
    description: str
    criteria: list[str]
    examples_fail: list[str] = Field(default_factory=list)
    examples_pass: list[str] = Field(default_factory=list)
    heuristic_signals: list[Signal] = Field(default_factory=list)

    def prompt_block(self) -> str:
        lines = [f"RUBRICA: {self.name} ({self.id})", self.description.strip(), "Critérios:"]
        lines += [f"- {c}" for c in self.criteria]
        if self.examples_fail:
            lines += ["Exemplos de VIOLAÇÃO:"] + [f"- {e}" for e in self.examples_fail]
        if self.examples_pass:
            lines += ["Exemplos que NÃO são violação:"] + [f"- {e}" for e in self.examples_pass]
        return "\n".join(lines)


def load_rubrics(directory: str | Path | None = None, only: list[str] | None = None) -> list[Rubric]:
    """Carrega as rubricas do pacote (padrão) ou de uma pasta do cliente."""
    paths = (
        sorted(Path(directory).glob("*.yaml"))
        if directory
        else sorted(p for p in resources.files("fiscal").joinpath("rubrics").iterdir() if p.name.endswith(".yaml"))
    )
    rubrics = []
    for p in paths:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        rubric = Rubric.model_validate(data)
        if only is None or rubric.id in only:
            rubrics.append(rubric)
    return rubrics
