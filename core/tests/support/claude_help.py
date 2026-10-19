"""Real `claude --help` output (fixtures), for test doubles whose help must declare option blocks."""
from pathlib import Path

HELP = Path(__file__).resolve().parents[1] / "skills" / "solar-router" / "fixtures" / "claude_2.1.303_help.txt"


def claude_help() -> str:
    return HELP.read_text()
