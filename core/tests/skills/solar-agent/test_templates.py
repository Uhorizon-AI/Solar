"""Keep the portable memory template aligned with its canonical source."""
from pathlib import Path


CORE = Path(__file__).resolve().parents[3]


def test_packaged_memory_template_matches_canonical_bytes():
    canonical = CORE / "templates/planet-MEMORY.md"
    packaged = CORE / "skills/solar-agent/assets/memory.md"

    assert packaged.read_bytes() == canonical.read_bytes(), (
        "Refresh solar-agent/assets/memory.md from core/templates/planet-MEMORY.md "
        "before packaging; the files must be byte-identical."
    )
