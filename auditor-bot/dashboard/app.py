"""Painel Streamlit: lê os relatórios JSON gerados por `fiscal audit` e `fiscal redteam`.

Rodar:  streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

REPORTS = Path(os.environ.get("FISCAL_REPORTS_DIR", "reports"))

st.set_page_config(page_title="Fiscal de Bot", page_icon="🔎", layout="wide")
st.title("🔎 Fiscal de Bot")
st.caption("Qualidade e segurança de agentes de IA no WhatsApp")


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def find(name: str) -> list[Path]:
    return sorted(REPORTS.rglob(name), key=lambda p: p.stat().st_mtime, reverse=True)


audit_tab, redteam_tab = st.tabs(["Auditoria de conversas", "Red teaming"])

with audit_tab:
    files = find("auditoria.json")
    if not files:
        st.info("Nenhum relatório encontrado. Rode: `fiscal audit data/synthetic/conversations.jsonl`")
    else:
        chosen = st.selectbox("Relatório", files, format_func=lambda p: str(p.relative_to(REPORTS)))
        s = json.loads(chosen.read_text(encoding="utf-8"))
        c1, c2, c3 = st.columns(3)
        c1.metric("Conversas auditadas", s["n_audited"])
        c2.metric("Com falha", pct(s["overall_rate"]), help=f"IC {pct(s['overall_ci'][0])} – {pct(s['overall_ci'][1])}")
        c3.metric("Para revisão humana", s["needs_review"])

        df = pd.DataFrame(s["rubrics"])
        df["taxa (%)"] = (df["rate"] * 100).round(1)
        df["IC baixo (%)"] = (df["ci_low"] * 100).round(1)
        df["IC alto (%)"] = (df["ci_high"] * 100).round(1)
        st.subheader("Taxa de falha por rubrica")
        st.bar_chart(df.set_index("name")["taxa (%)"])
        st.dataframe(df[["name", "failures", "n", "taxa (%)", "IC baixo (%)", "IC alto (%)"]], hide_index=True)

        if s["examples"]:
            st.subheader("Falhas mais graves")
            st.dataframe(pd.DataFrame(s["examples"])[["severity", "rubric", "conversation_id", "evidence", "explanation"]],
                         hide_index=True)

with redteam_tab:
    files = find("redteam.json")
    if not files:
        st.info("Nenhum relatório encontrado. Rode: `fiscal redteam --target demo`")
    else:
        chosen = st.selectbox("Relatório", files, key="rt", format_func=lambda p: str(p.relative_to(REPORTS)))
        s = json.loads(chosen.read_text(encoding="utf-8"))
        c1, c2, c3 = st.columns(3)
        c1.metric("Alvo", s["target"])
        c2.metric("Ataques bem-sucedidos", f"{s['successes']}/{s['total']}", help=f"IC {pct(s['ci_low'])} – {pct(s['ci_high'])}")
        c3.metric("Falhas críticas", s["critical_failures"])
        cat = pd.DataFrame(s["by_category"])
        st.bar_chart(cat.set_index("category")["rate"])
        for r in s["failed_attacks"]:
            with st.expander(f"[{r['attack']['severity']}] {r['attack']['id']} · {r['attack']['title']}"):
                st.write("**Motivo:** " + "; ".join(r["reasons"]))
                for m in r["conversation"]["messages"]:
                    st.markdown(f"**{'Cliente' if m['role'] == 'customer' else 'Bot'}:** {m['text']}")
