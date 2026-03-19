#!/usr/bin/env python3
"""
solar-router v3 entrypoint.

Reads stdin, delegates to router.route(), writes stdout JSON, exits.
All routing logic lives in router.py.
"""
import json
import sys
import pathlib

# Ensure scripts/ dir is in path for sibling imports (router, providers).
_SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from router import route, parse_ai_decision_output  # noqa: F401,E402
# parse_ai_decision_output is re-exported for backward compatibility with
# tests that import it directly from run_router (check_router.sh tests 9/10).


def main() -> None:
    raw = sys.stdin.read().strip()
    response = route(raw)
    print(json.dumps(response, ensure_ascii=False))
    sys.exit(0 if response.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
