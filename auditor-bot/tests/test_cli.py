from __future__ import annotations

import json

from typer.testing import CliRunner

from conftest import KB_PATH, ROOT
from fiscal.cli import app

runner = CliRunner()
CONVS = str(ROOT / "data" / "synthetic" / "conversations.jsonl")
GOLDEN = str(ROOT / "data" / "synthetic" / "golden.jsonl")
KB = str(KB_PATH)


def test_rubrics_command():
    r = runner.invoke(app, ["rubrics"])
    assert r.exit_code == 0
    for rid in ["alucinacao_preco", "alucinacao_politica", "promessa_indevida", "vazamento_dados", "transbordo_falho"]:
        assert rid in r.output


def test_audit_command_writes_reports(tmp_path):
    r = runner.invoke(app, ["audit", CONVS, "--kb", KB, "--out", str(tmp_path), "--sample", "50"])
    assert r.exit_code == 0, r.output
    assert {p.name for p in tmp_path.iterdir()} == {"auditoria.html", "auditoria.md", "auditoria.json", "veredictos.jsonl"}
    data = json.loads((tmp_path / "auditoria.json").read_text(encoding="utf-8"))
    assert data["n_audited"] == 50 and data["population"] == 200
    html = (tmp_path / "auditoria.html").read_text(encoding="utf-8")
    assert "Taxa de falha por rubrica" in html and "Intervalo de confiança" in html


def test_audit_margin_computes_sample_size(tmp_path):
    r = runner.invoke(app, ["audit", CONVS, "--kb", KB, "--out", str(tmp_path), "--margin", "0.1", "--format", "json"])
    assert r.exit_code == 0, r.output
    n = json.loads((tmp_path / "auditoria.json").read_text(encoding="utf-8"))["n_audited"]
    assert 50 < n < 100  # 96 com correção de população finita (N=200)


def test_redteam_command_and_fail_on_critical(tmp_path):
    r = runner.invoke(app, ["redteam", "--target", "demo", "--kb", KB, "--out", str(tmp_path), "--fail-on-critical"])
    assert r.exit_code == 1  # o bot vulnerável tem falhas críticas
    assert "Ataques bem-sucedidos" in r.output
    assert (tmp_path / "redteam.html").exists()

    ok = runner.invoke(app, ["redteam", "--target", "demo-hardened", "--kb", KB, "--out", str(tmp_path),
                             "--category", "prompt_leak", "--fail-on-critical"])
    assert ok.exit_code == 0, ok.output


def test_synth_command(tmp_path):
    r = runner.invoke(app, ["synth", "--out", str(tmp_path), "-n", "30", "--kb", KB])
    assert r.exit_code == 0
    assert len((tmp_path / "conversations.jsonl").read_text(encoding="utf-8").splitlines()) == 30


def test_calibrate_command_gate():
    ok = runner.invoke(app, ["calibrate", CONVS, GOLDEN, "--kb", KB, "--min-f1", "0.85"])
    assert ok.exit_code == 0, ok.output
    assert "F1 macro" in ok.output
    fail = runner.invoke(app, ["calibrate", CONVS, GOLDEN, "--kb", KB, "--min-f1", "0.99"])
    assert fail.exit_code == 1


def test_missing_kb_gives_clear_error(tmp_path):
    r = runner.invoke(app, ["audit", CONVS, "--kb", str(tmp_path / "nao-existe.yaml")])
    assert r.exit_code != 0
