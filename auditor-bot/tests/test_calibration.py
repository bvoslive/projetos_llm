from __future__ import annotations

import pytest

from conftest import ROOT
from fiscal.calibration import calibrate, calibration_markdown, cohen_kappa, load_labels
from fiscal.ingest import load_conversations
from fiscal.report import summarize
from fiscal.schema import Verdict
from fiscal.synth import Label, generate, make_cpf, write_dataset


def test_cohen_kappa_reference_values():
    assert cohen_kappa(10, 0, 0, 10) == 1.0
    assert cohen_kappa(5, 5, 5, 5) == pytest.approx(0.0)
    assert cohen_kappa(0, 0, 0, 10) == 1.0  # nada a detectar e nada detectado


def test_calibrate_counts_and_metrics():
    labels = [Label(conversation_id=f"c{i}", violations=v) for i, v in enumerate(
        [["a"], ["a"], ["a"], [], [], []])]
    verdicts = [Verdict(conversation_id="c0", findings=[]), Verdict(conversation_id="c1"), Verdict(conversation_id="c2"),
                Verdict(conversation_id="c3"), Verdict(conversation_id="c4"), Verdict(conversation_id="c5")]
    from fiscal.schema import Finding, Severity

    def f():
        return Finding(rubric="a", severity=Severity.LOW, evidence="e", explanation="x")

    verdicts[1].findings = [f()]
    verdicts[2].findings = [f()]
    verdicts[3].findings = [f()]  # falso positivo
    r = calibrate(verdicts, labels, ["a"])
    m = r.metrics[0]
    assert (m.tp, m.fp, m.fn, m.tn) == (2, 1, 1, 2)
    assert m.precision == pytest.approx(2 / 3) and m.recall == pytest.approx(2 / 3)
    assert r.missed["a"] == ["c0"] and r.spurious["a"] == ["c3"]


def test_calibrate_requires_overlap():
    with pytest.raises(ValueError):
        calibrate([Verdict(conversation_id="x")], [Label(conversation_id="y")], ["a"])


def test_synth_is_reproducible_and_labelled(kb):
    c1, l1 = generate(60, seed=7, kb=kb)
    c2, l2 = generate(60, seed=7, kb=kb)
    assert c1 == c2 and l1 == l2
    assert generate(60, seed=8, kb=kb)[0] != c1
    assert any(lab.violations for lab in l1) and any(not lab.violations for lab in l1)
    assert any(lab.hard for lab in generate(200, seed=42, kb=kb)[1])


def test_generated_cpfs_are_valid():
    import random

    from fiscal.privacy import valid_cpf

    rng = random.Random(1)
    assert all(valid_cpf(make_cpf(rng)) for _ in range(50))


def test_committed_dataset_matches_generator(kb, tmp_path):
    """O dataset versionado em data/synthetic deve ser exatamente o que `fiscal synth` gera."""
    conv_path, label_path = write_dataset(tmp_path, kb, n=200, seed=42)
    committed = ROOT / "data" / "synthetic"
    assert (committed / "conversations.jsonl").read_text(encoding="utf-8") == conv_path.read_text(encoding="utf-8")
    assert (committed / "golden.jsonl").read_text(encoding="utf-8") == label_path.read_text(encoding="utf-8")


def test_heuristic_baseline_quality_on_golden_set(auditor):
    """Regressão: o baseline heurístico não pode piorar (é o gate usado no CI)."""
    convs = load_conversations(ROOT / "data" / "synthetic" / "conversations.jsonl")
    labels = load_labels(ROOT / "data" / "synthetic" / "golden.jsonl")
    report = calibrate(auditor.audit_many(convs), labels, [r.id for r in auditor.rubrics])
    by = {m.rubric: m for m in report.metrics}
    assert report.macro_f1 >= 0.85
    # regras determinísticas de preço, PII: sem erro no dataset
    assert by["alucinacao_preco"].f1 == 1.0 and by["vazamento_dados"].f1 == 1.0
    # limitações conhecidas aparecem como falsos negativos, não como bug silencioso
    assert by["alucinacao_politica"].fn > 0  # números por extenso
    assert by["promessa_indevida"].fp > 0  # "garanto!" de cortesia
    assert "| Rubrica |" in calibration_markdown(report)


def test_summary_confidence_intervals(auditor):
    convs = load_conversations(ROOT / "data" / "synthetic" / "conversations.jsonl")
    verdicts = auditor.audit_many(convs)
    s = summarize(verdicts, auditor.rubrics, population=len(convs))
    assert s.n_audited == 200
    for r in s.rubrics:
        assert r.ci_low <= r.rate <= r.ci_high
    assert s.overall_ci[0] <= s.overall_rate <= s.overall_ci[1]
    assert sum(1 for v in verdicts if v.needs_review) == s.needs_review
