"""Every agent-memory test owns a temporary workspace and runtime."""
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[3]
for path in (CORE / "skills/solar-agent-creator/scripts", CORE / "skills/solar-state/scripts",
             CORE / "tests/support"):
    sys.path.insert(0, str(path))
