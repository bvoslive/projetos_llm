"""Calibração do juiz contra rótulos humanos (golden set).

É o que separa "um LLM que opina" de um auditor com precisão conhecida: para cada rubrica
medimos precisão, recall, F1 e o kappa de Cohen (concordância descontado o acaso).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from fiscal.schema import Verdict
from fiscal.synth import Label


class RubricMetrics(BaseModel):
    rubric: str
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float | None
    recall: float | None
    f1: float | None
    kappa: float | None
    support: int  # conversas realmente com essa falha


class CalibrationReport(BaseModel):
    n: int
    exact_match_rate: float  # conjunto de rubricas igual ao rótulo
    macro_f1: float
    metrics: list[RubricMetrics]
    missed: dict[str, list[str]] = {}  # rubrica -> ids de falsos negativos
    spurious: dict[str, list[str]] = {}  # rubrica -> ids de falsos positivos


def load_labels(path: str | Path) -> list[Label]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [Label.model_validate_json(line) for line in lines if line.strip()]


def _div(a: float, b: float) -> float | None:
    return a / b if b else None


def cohen_kappa(tp: int, fp: int, fn: int, tn: int) -> float | None:
    n = tp + fp + fn + tn
    if n == 0:
        return None
    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / n**2
    if pe == 1:
        return 1.0 if po == 1 else 0.0
    return (po - pe) / (1 - pe)


def calibrate(verdicts: list[Verdict], labels: list[Label], rubric_ids: list[str]) -> CalibrationReport:
    truth = {lab.conversation_id: set(lab.violations) for lab in labels}
    pred = {v.conversation_id: v.violated_rubrics for v in verdicts}
    ids = sorted(set(truth) & set(pred))
    if not ids:
        raise ValueError("Nenhuma conversa em comum entre veredictos e rótulos.")

    metrics, missed, spurious = [], {}, {}
    for rid in rubric_ids:
        tp = fp = fn = tn = 0
        miss, spur = [], []
        for cid in ids:
            t, p = rid in truth[cid], rid in pred[cid]
            if t and p:
                tp += 1
            elif p:
                fp += 1
                spur.append(cid)
            elif t:
                fn += 1
                miss.append(cid)
            else:
                tn += 1
        prec, rec = _div(tp, tp + fp), _div(tp, tp + fn)
        f1 = _div(2 * prec * rec, prec + rec) if prec is not None and rec is not None else None
        metrics.append(
            RubricMetrics(rubric=rid, tp=tp, fp=fp, fn=fn, tn=tn, precision=prec, recall=rec, f1=f1,
                          kappa=cohen_kappa(tp, fp, fn, tn), support=tp + fn)
        )
        missed[rid], spurious[rid] = miss, spur

    f1s = [m.f1 for m in metrics if m.f1 is not None]
    exact = sum(1 for cid in ids if truth[cid] == (pred[cid] & set(rubric_ids))) / len(ids)
    return CalibrationReport(
        n=len(ids), exact_match_rate=exact, macro_f1=sum(f1s) / len(f1s) if f1s else 0.0,
        metrics=metrics, missed=missed, spurious=spurious,
    )


def _fmt(x: float | None) -> str:
    return "n/d" if x is None else f"{x:.2f}"


def calibration_markdown(r: CalibrationReport) -> str:
    out = [
        f"**{r.n} conversas** · F1 macro **{r.macro_f1:.2f}** · acerto exato do conjunto de rubricas **{r.exact_match_rate:.1%}**",
        "",
        "| Rubrica | Suporte | TP | FP | FN | Precisão | Recall | F1 | Kappa |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for m in r.metrics:
        out.append(
            f"| {m.rubric} | {m.support} | {m.tp} | {m.fp} | {m.fn} | {_fmt(m.precision)} | {_fmt(m.recall)} | {_fmt(m.f1)} | {_fmt(m.kappa)} |"
        )
    return "\n".join(out) + "\n"
