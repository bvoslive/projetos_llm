"""Interface de linha de comando: ``fiscal audit | redteam | synth | calibrate | rubrics | serve``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from fiscal import __version__
from fiscal.calibration import calibrate, calibration_markdown, load_labels
from fiscal.factory import build_auditor, load_kb
from fiscal.ingest import load_conversations
from fiscal.judge import load_rubrics
from fiscal.redteam import DemoBot, HTTPTarget, load_attacks, run_suite, summarize_redteam
from fiscal.report import summarize, write_audit_report, write_redteam_report
from fiscal.report.render import pct
from fiscal.sampling import required_sample_size, stratified_sample
from fiscal.synth import write_dataset

app = typer.Typer(
    help="Fiscal de Bot: audita agentes de IA no WhatsApp e testa vulnerabilidades (red teaming).",
    no_args_is_help=True,
    add_completion=False,
)

KbOpt = Annotated[Path | None, typer.Option("--kb", help="YAML com preços e políticas do cliente.")]
BackendOpt = Annotated[str | None, typer.Option("--backend", help="'heuristic' (offline) ou 'llm'.")]
ModelOpt = Annotated[str | None, typer.Option("--model", help="Modelo do juiz, ex.: anthropic:claude-haiku-5-5")]
OutOpt = Annotated[Path, typer.Option("--out", help="Pasta de saída dos relatórios.")]
FormatOpt = Annotated[str, typer.Option("--format", help="Lista separada por vírgula: html,md,json,pdf")]


def _formats(raw: str) -> list[str]:
    return [f.strip() for f in raw.split(",") if f.strip()]


def _progress(label: str):
    def cb(done: int, total: int) -> None:
        if done == total or done % 10 == 0:
            typer.echo(f"  {label}: {done}/{total}", err=True)

    return cb


def _interactive_resolver(payload: dict[str, Any]) -> dict[str, Any]:
    """Revisão humana no terminal: confirma ou descarta cada rubrica incerta."""
    typer.echo("\n" + "=" * 70)
    typer.echo(f"Revisão humana · conversa {payload['conversation_id']}")
    typer.echo(payload["transcript"])
    confirm, dismiss = [], []
    for rubric in sorted({f["rubric"] for f in payload["findings"]}):
        for f in [f for f in payload["findings"] if f["rubric"] == rubric]:
            typer.echo(f"\n→ {rubric} (conf. {f['confidence']:.2f}): {f['explanation']}\n  evidência: {f['evidence']}")
        ok = typer.confirm(f"Confirmar a violação de '{rubric}'?", default=True)
        (confirm if ok else dismiss).append(rubric)
    return {"confirm": confirm, "dismiss": dismiss}


@app.command()
def audit(
    conversations: Annotated[Path, typer.Argument(help="Arquivo .csv ou .jsonl com as conversas.")],
    kb: KbOpt = None,
    backend: BackendOpt = None,
    model: ModelOpt = None,
    escalation_model: Annotated[str | None, typer.Option(help="Modelo forte para casos incertos.")] = None,
    sample: Annotated[int | None, typer.Option(help="Audita só N conversas (amostra estratificada por bot).")] = None,
    margin: Annotated[float | None, typer.Option(help="Margem de erro desejada (ex.: 0.05) para calcular N.")] = None,
    confidence: Annotated[float, typer.Option(help="Nível de confiança dos intervalos.")] = 0.95,
    seed: Annotated[int, typer.Option(help="Seed da amostragem (reprodutível).")] = 0,
    interactive: Annotated[bool, typer.Option(help="Revisão humana no terminal dos casos incertos.")] = False,
    rubrics_dir: Annotated[Path | None, typer.Option(help="Pasta com rubricas próprias (YAML).")] = None,
    out: OutOpt = Path("reports"),
    fmt: FormatOpt = "html,md,json",
    title: Annotated[str, typer.Option(help="Título do relatório.")] = "Auditoria de atendimento",
) -> None:
    """Audita conversas reais (export CSV/JSONL) e gera o relatório com intervalos de confiança."""
    knowledge = load_kb(kb)
    auditor = build_auditor(
        knowledge, backend=backend, model=model, escalation_model=escalation_model, rubrics_dir=rubrics_dir,
        review_resolver=_interactive_resolver if interactive else None,
    )
    convs = load_conversations(conversations)
    population = len(convs)
    if sample is None and margin is not None:
        sample = required_sample_size(margin, confidence, population)
        typer.echo(f"Margem {margin:.0%} a {confidence:.0%} de confiança → amostra de {sample} de {population}.", err=True)
    if sample is not None:
        convs = stratified_sample(convs, sample, key=lambda c: c.bot_id, seed=seed)

    typer.echo(f"Auditando {len(convs)} conversas com juiz '{auditor.backend.name}'...", err=True)
    verdicts = auditor.audit_many(convs, _progress("conversas"))
    summary = summarize(verdicts, auditor.rubrics, population=population, confidence=confidence, title=title)

    out.mkdir(parents=True, exist_ok=True)
    (out / "veredictos.jsonl").write_text("\n".join(v.model_dump_json() for v in verdicts) + "\n", encoding="utf-8")
    paths = write_audit_report(summary, out, _formats(fmt))

    typer.echo(f"\nConversas com falha: {pct(summary.overall_rate)} (IC {pct(summary.overall_ci[0])} – {pct(summary.overall_ci[1])})")
    for r in summary.rubrics:
        typer.echo(f"  {r.name:<28} {r.failures:>4}/{r.n:<4} {pct(r.rate):>7}  IC {pct(r.ci_low)} – {pct(r.ci_high)}")
    if summary.needs_review:
        typer.echo(f"\n{summary.needs_review} conversa(s) com achados incertos aguardam revisão (use --interactive).")
    typer.echo("\nRelatórios: " + ", ".join(str(p) for p in paths))


@app.command()
def redteam(
    target: Annotated[str, typer.Option(help="'demo', 'demo-hardened' ou a URL HTTP do seu bot.")] = "demo",
    kb: KbOpt = None,
    backend: BackendOpt = None,
    model: ModelOpt = None,
    category: Annotated[list[str] | None, typer.Option(help="Filtra por categoria (repetível).")] = None,
    attacks_dir: Annotated[Path | None, typer.Option(help="Pasta com ataques próprios (YAML).")] = None,
    header: Annotated[list[str] | None, typer.Option(help="Header HTTP 'Chave: valor' (repetível).")] = None,
    request_field: Annotated[str, typer.Option(help="Campo JSON da mensagem enviada.")] = "message",
    session_field: Annotated[str, typer.Option(help="Campo JSON do id da sessão.")] = "session_id",
    response_field: Annotated[str, typer.Option(help="Campo (com pontos) da resposta.")] = "reply",
    fail_on_critical: Annotated[bool, typer.Option(help="Sai com código 1 se algum ataque crítico funcionar (CI).")] = False,
    out: OutOpt = Path("reports"),
    fmt: FormatOpt = "html,md,json",
) -> None:
    """Roda a bateria de ataques em PT-BR contra um bot antes de ir ao ar."""
    knowledge = load_kb(kb)
    auditor = build_auditor(knowledge, backend=backend, model=model)
    if target in ("demo", "demo-hardened"):
        bot = DemoBot(knowledge, vulnerable=target == "demo")
    else:
        headers = dict(h.split(":", 1) for h in (header or []))
        headers = {k.strip(): v.strip() for k, v in headers.items()}
        bot = HTTPTarget(target, headers=headers, request_field=request_field,
                         session_field=session_field, response_field=response_field)
    attacks = load_attacks(attacks_dir, categories=category)
    typer.echo(f"Executando {len(attacks)} ataques contra {bot.name}...", err=True)
    results = run_suite(bot, auditor, attacks, _progress("ataques"))
    summary = summarize_redteam(results, bot.name)
    paths = write_redteam_report(summary, out, _formats(fmt))

    typer.echo(f"\nAtaques bem-sucedidos: {summary.successes}/{summary.total} ({pct(summary.rate)}) · críticos: {summary.critical_failures}")
    for c in summary.by_category:
        typer.echo(f"  {c.category:<22} {c.successes}/{c.attacks}")
    if summary.errors:
        typer.echo(f"\n{summary.errors} ataque(s) com erro de conexão com o alvo.", err=True)
    typer.echo("\nRelatórios: " + ", ".join(str(p) for p in paths))
    if fail_on_critical and summary.critical_failures:
        raise typer.Exit(code=1)


@app.command()
def synth(
    out: Annotated[Path, typer.Option(help="Pasta de saída.")] = Path("data/synthetic"),
    n: Annotated[int, typer.Option("-n", help="Número de conversas.")] = 200,
    seed: Annotated[int, typer.Option(help="Seed (reprodutível).")] = 42,
    kb: KbOpt = None,
) -> None:
    """Gera conversas sintéticas com falhas plantadas e o golden set correspondente."""
    conv_path, label_path = write_dataset(out, load_kb(kb), n=n, seed=seed)
    typer.echo(f"Conversas: {conv_path}\nRótulos:   {label_path}")


@app.command("calibrate")
def calibrate_cmd(
    conversations: Annotated[Path, typer.Argument(help="Conversas (.jsonl/.csv).")],
    golden: Annotated[Path, typer.Argument(help="Rótulos humanos (golden.jsonl).")],
    kb: KbOpt = None,
    backend: BackendOpt = None,
    model: ModelOpt = None,
    min_f1: Annotated[float | None, typer.Option(help="Sai com código 1 se o F1 macro ficar abaixo (CI).")] = None,
    out: Annotated[Path | None, typer.Option(help="Salva o relatório em Markdown.")] = None,
) -> None:
    """Mede precisão, recall, F1 e kappa do juiz contra o golden set."""
    auditor = build_auditor(load_kb(kb), backend=backend, model=model)
    verdicts = auditor.audit_many(load_conversations(conversations), _progress("conversas"))
    report = calibrate(verdicts, load_labels(golden), [r.id for r in auditor.rubrics])
    md = calibration_markdown(report)
    typer.echo(md)
    if out:
        out.write_text(md, encoding="utf-8")
    if min_f1 is not None and report.macro_f1 < min_f1:
        typer.echo(f"F1 macro {report.macro_f1:.2f} abaixo do mínimo {min_f1:.2f}", err=True)
        raise typer.Exit(code=1)


@app.command()
def rubrics(rubrics_dir: Annotated[Path | None, typer.Option(help="Pasta com rubricas próprias.")] = None) -> None:
    """Lista as rubricas de auditoria disponíveis."""
    for r in load_rubrics(rubrics_dir):
        typer.echo(f"{r.id:<22} [{r.severity.value:<8}] {r.name}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Sobe a API HTTP (requer o extra 'api')."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise typer.BadParameter("Instale o extra da API: pip install 'fiscal-de-bot[api]'") from exc
    uvicorn.run("fiscal.api.app:app", host=host, port=port, reload=reload)


@app.command()
def version() -> None:
    """Mostra a versão."""
    typer.echo(__version__)


if __name__ == "__main__":  # pragma: no cover
    app()
