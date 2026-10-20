"""Real `codex exec --help` output (fixture), for test doubles whose help must declare option blocks."""
from pathlib import Path

HELP = Path(__file__).resolve().parents[1] / "skills" / "solar-router" / "fixtures" / "codex_0.162.1_exec_help.txt"


def codex_help() -> str:
    return HELP.read_text()
