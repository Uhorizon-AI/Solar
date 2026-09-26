"""Console readers. The rows live in solar-state; this module only re-exports them."""
from __future__ import annotations

import sys
from pathlib import Path

_STATE_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "solar-state" / "scripts"
if str(_STATE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_STATE_SCRIPTS))

from runtime_views import (  # noqa: E402,F401
    FRESH_SECONDS,
    PAGE_SIZE,
    STALE_SECONDS,
    TASK_STATES,
    activity_page,
    artifacts,
    audit_counts,
    display_path,
    epoch,
    fields,
    iso,
    issue,
    read_router,
    read_tasks,
    result_summary,
    runtime_dir,
    snapshot,
    solar_runtime,
    solar_state,
)
