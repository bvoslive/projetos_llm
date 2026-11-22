"""Red teaming em PT-BR: suíte de ataques, alvos e execução."""

from fiscal.redteam.demo_bot import DemoBot
from fiscal.redteam.models import Attack, AttackResult, RedTeamSummary, summarize_redteam
from fiscal.redteam.runner import load_attacks, run_attack, run_suite
from fiscal.redteam.targets import BotTarget, CallableTarget, HTTPTarget

__all__ = [
    "Attack",
    "AttackResult",
    "BotTarget",
    "CallableTarget",
    "DemoBot",
    "HTTPTarget",
    "RedTeamSummary",
    "load_attacks",
    "run_attack",
    "run_suite",
    "summarize_redteam",
]
