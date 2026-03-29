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

from router import parse_ai_decision_output, route, route_stream  # noqa: E402


def main() -> None:
    raw = sys.stdin.read().strip()

    # Streaming mode: request payload contains "stream": true
    # Outputs JSONL lines incrementally; caller reads them in real-time.
    try:
        stream_mode = json.loads(raw).get("stream") if raw else False
    except (json.JSONDecodeError, AttributeError):
        stream_mode = False

    if stream_mode:
        for line in route_stream(raw):
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        sys.exit(0)

    response = route(raw)
    print(json.dumps(response, ensure_ascii=False))
    sys.exit(0 if response.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
