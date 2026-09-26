#!/usr/bin/env python3
"""Thin CLI for A3 mandates. The files are opened by solar-state."""

from __future__ import annotations

import sys
from pathlib import Path

_STATE = Path(__file__).resolve().parents[2] / "solar-state" / "scripts"
if str(_STATE) not in sys.path:
    sys.path.insert(0, str(_STATE))

import mandates as _mandates  # noqa: E402

# Names tests and callers look up on this module.
DEFAULT_SHADOW_SAFE_ACTIONS = _mandates.DEFAULT_SHADOW_SAFE_ACTIONS


def __getattr__(name: str):
    if name == "WORKSPACE":
        return _mandates.workspace()
    raise AttributeError(name)
validate_mandate = _mandates.validate_mandate
parse_frequency_hours = _mandates.parse_frequency_hours
cmd_record_usage = _mandates.cmd_record_usage
daily_usage = _mandates.daily_usage
runtime_events = _mandates.runtime_events


def main() -> int:
    return _mandates.main()


if __name__ == "__main__":
    raise SystemExit(main())
