"""Agregação estatística e renderização de relatórios."""

from fiscal.report.aggregate import AuditSummary, summarize
from fiscal.report.render import write_audit_report, write_redteam_report

__all__ = ["AuditSummary", "summarize", "write_audit_report", "write_redteam_report"]
