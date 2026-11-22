"""Renderização dos relatórios: HTML (Jinja2), Markdown, JSON e PDF opcional (WeasyPrint)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from fiscal import __version__
from fiscal.redteam.models import RedTeamSummary
from fiscal.report.aggregate import AuditSummary

_env = Environment(
    loader=PackageLoader("fiscal.report", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def pct(x: float) -> str:
    return f"{x * 100:.1f}%".replace(".", ",")


def _ctx() -> dict:
    return {"pct": pct, "version": __version__, "generated": datetime.now().strftime("%d/%m/%Y %H:%M")}


def audit_html(s: AuditSummary) -> str:
    return _env.get_template("audit.html.j2").render(s=s, title=s.title, **_ctx())


def redteam_html(s: RedTeamSummary, title: str = "Relatório de red teaming") -> str:
    return _env.get_template("redteam.html.j2").render(s=s, title=title, **_ctx())


def audit_markdown(s: AuditSummary) -> str:
    out = [
        f"# {s.title}",
        "",
        f"- Conversas auditadas: **{s.n_audited}**" + (f" de {s.population}" if s.population else ""),
        f"- Juiz: `{s.judge_backend}` · confiança {s.confidence * 100:.0f}%",
        f"- Conversas com falha: **{pct(s.overall_rate)}** (IC {pct(s.overall_ci[0])} – {pct(s.overall_ci[1])})",
        f"- Para revisão humana: {s.needs_review}",
        "",
        "## Taxa de falha por rubrica",
        "",
        "| Rubrica | Falhas | Taxa | IC |",
        "|---|---:|---:|---|",
    ]
    for r in s.rubrics:
        out.append(f"| {r.name} | {r.failures}/{r.n} | {pct(r.rate)} | {pct(r.ci_low)} – {pct(r.ci_high)} |")
    if s.examples:
        out += ["", "## Falhas mais graves", "", "| Gravidade | Rubrica | Conversa | Evidência |", "|---|---|---|---|"]
        for e in s.examples:
            ev = e.evidence.replace("|", "\\|")
            out.append(f"| {e.severity.value} | {e.rubric} | `{e.conversation_id}` | {ev} |")
    return "\n".join(out) + "\n"


def redteam_markdown(s: RedTeamSummary) -> str:
    out = [
        "# Relatório de red teaming",
        "",
        f"- Alvo: `{s.target}`",
        f"- Ataques bem-sucedidos: **{s.successes}/{s.total}** ({pct(s.rate)}, IC {pct(s.ci_low)} – {pct(s.ci_high)})",
        f"- Falhas críticas: **{s.critical_failures}**",
        "",
        "## Por categoria",
        "",
        "| Categoria | Ataques | Falhas do bot | Taxa |",
        "|---|---:|---:|---:|",
    ]
    for c in s.by_category:
        out.append(f"| {c.category} | {c.attacks} | {c.successes} | {pct(c.rate)} |")
    if s.failed_attacks:
        out += ["", "## Ataques que funcionaram", ""]
        for r in s.failed_attacks:
            out.append(f"- **{r.attack.id}** ({r.attack.severity.value}) {r.attack.title}: {'; '.join(r.reasons)}")
    return "\n".join(out) + "\n"


def html_to_pdf(html: str, path: Path) -> None:
    try:
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover - dependência opcional
        raise RuntimeError("PDF requer WeasyPrint: pip install 'fiscal-de-bot[pdf]'") from exc
    HTML(string=html).write_pdf(str(path))


def write_audit_report(s: AuditSummary, out_dir: Path, formats: list[str], stem: str = "auditoria") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    html = audit_html(s) if ({"html", "pdf"} & set(formats)) else ""
    for fmt in formats:
        path = out_dir / f"{stem}.{fmt}"
        if fmt == "html":
            path.write_text(html, encoding="utf-8")
        elif fmt == "md":
            path.write_text(audit_markdown(s), encoding="utf-8")
        elif fmt == "json":
            path.write_text(s.model_dump_json(indent=2), encoding="utf-8")
        elif fmt == "pdf":
            html_to_pdf(html, path)
        else:
            raise ValueError(f"Formato desconhecido: {fmt}")
        written.append(path)
    return written


def write_redteam_report(s: RedTeamSummary, out_dir: Path, formats: list[str], stem: str = "redteam") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    html = redteam_html(s) if ({"html", "pdf"} & set(formats)) else ""
    for fmt in formats:
        path = out_dir / f"{stem}.{fmt}"
        if fmt == "html":
            path.write_text(html, encoding="utf-8")
        elif fmt == "md":
            path.write_text(redteam_markdown(s), encoding="utf-8")
        elif fmt == "json":
            path.write_text(s.model_dump_json(indent=2), encoding="utf-8")
        elif fmt == "pdf":
            html_to_pdf(html, path)
        else:
            raise ValueError(f"Formato desconhecido: {fmt}")
        written.append(path)
    return written
