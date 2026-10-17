"""The pass stamp's feature results `starting` and `blocked` reach the console as what they are:
a feature that is still starting is neither a success nor a fault; one that is blocked, like one that
failed, is a fault that names the feature. Existing results keep their meaning."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_APP = Path(__file__).resolve().parents[3] / "skills" / "solar-app" / "scripts"
_CLIENT = Path(__file__).resolve().parents[3] / "skills" / "solar-client" / "scripts"
for _path in (_APP, _CLIENT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import console_data  # noqa: E402

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def _stamp(**features):
    return {"at": (NOW - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "features": features,
            "gateway": {"processes": {"ws": True, "http": True, "tunnel": True},
                        "local_health": True, "connector_ready": True}}


def _verdict(**features):
    return console_data.verdict(stamp=_stamp(**features), db_readable=True, port_foreign=False, now=NOW)


def test_existing_results_keep_their_meaning():
    for value in ("ok", "skipped", "deprecated", "ignored"):
        assert _verdict(**{"async-tasks": value})["verdict"] == "calm", value
    failed = _verdict(**{"async-tasks": "failed"})
    assert failed["verdict"] == "fault" and failed["reasons"] == ["system"]


def test_starting_is_not_a_fault_and_not_reported_as_one():
    starting = _verdict(**{"async-tasks": "starting"})
    assert starting["verdict"] == "calm" and starting["reasons"] == []
    system = next(c for c in starting["checks"] if c["id"] == "system")
    assert system["state"] == "ok"                     # a live, identified supervisor reconciling


def test_blocked_is_a_fault_that_asks_for_attention_and_names_the_feature():
    blocked = _verdict(**{"async-tasks": "blocked"})
    assert blocked["verdict"] == "fault" and blocked["reasons"] == ["system"]
    system = next(c for c in blocked["checks"] if c["id"] == "system")
    assert system["state"] == "fault"
    en = console_data.attention_line(blocked, features={"async-tasks": "blocked"}, language="en")
    assert "background tasks need attention" in en and "failed" not in en
    es = console_data.attention_line(blocked, features={"async-tasks": "blocked"}, language="es")
    assert "necesitan atención" in es
    both = console_data.attention_line(blocked, features={"async-tasks": "blocked", "transport-gateway": "failed"},
                                       language="en")
    assert "the gateway has failed" in both and "background tasks need attention" in both


def test_a_failed_feature_text_is_unchanged():
    failed = _verdict(**{"async-tasks": "failed"})
    assert console_data.attention_line(failed, features={"async-tasks": "failed"}, language="en") == \
        "Fault: background tasks have failed"
    assert console_data.attention_line(failed, features={"async-tasks": "failed"}, language="es") == \
        "Avería: han fallado las tareas en segundo plano"
