"""Verdict and loopback, without a live console."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_APP = Path(__file__).resolve().parents[3] / "skills" / "solar-app" / "scripts"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import console_data  # noqa: E402
import host_server  # noqa: E402

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


def _stamp(age, connector=True, processes=None, features=None, local_health=True):
    if processes is None:
        processes = {"ws": True, "http": True, "tunnel": True}
    return {
        "at": (NOW - timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "features": features or {"async-tasks": "ok", "transport-gateway": "ok"},
        "gateway": {
            "processes": processes,
            "local_health": local_health,
            "connector_ready": connector,
        },
    }


def _state(stamp, db=True, port=False):
    return console_data.verdict(stamp=stamp, db_readable=db, port_foreign=port, now=NOW)


def test_verdict_cases():
    assert _state(None)["verdict"] == "unverified"
    assert "launchagent" in _state(None)["unverified"]
    healthy = _state(_stamp(40))
    assert healthy["verdict"] == "calm"
    assert healthy["label"] == "calm"
    assert [item["id"] for item in healthy["checks"]] == [
        "database", "port", "system", "router", "launchagent", "gateway",
    ]
    assert {item["id"]: item["state"] for item in healthy["checks"]} == {
        "database": "ok", "port": "ok", "system": "ok", "router": "ok",
        "launchagent": "ok", "gateway": "ok",
    }
    assert healthy["gateway"]["local_health"] is True
    assert healthy["gateway"]["processes_alive"] is True
    local_down = _state(_stamp(40, local_health=False))
    assert local_down["verdict"] == "fault"
    assert local_down["gateway"]["connector_ready"] is True
    assert local_down["gateway"]["local_health"] is False
    http_down = _state(_stamp(40, processes={"ws": True, "http": False, "tunnel": True}))
    assert http_down["verdict"] == "fault"
    assert http_down["gateway"]["connector_ready"] is True
    assert http_down["gateway"]["local_health"] is True
    assert http_down["gateway"]["processes_alive"] is False
    assert http_down["gateway"]["processes"]["http"] is False
    stale = _state(_stamp(420))
    assert stale["verdict"] == "fault"
    assert "launchagent" in stale["reasons"]
    down = _state(_stamp(40, connector=False))
    assert down["verdict"] == "fault"
    assert down["gateway"]["processes_alive"] is True
    quiet_processes = _state(_stamp(40, connector=False, processes={"ws": False, "http": False, "tunnel": False}))
    assert quiet_processes["verdict"] == "fault"
    assert "gateway" in quiet_processes["reasons"]
    refused = _state(_stamp(40), db=False)
    assert refused["verdict"] == "fault"
    assert "database" in refused["reasons"]
    assert {item["id"]: item["state"] for item in refused["checks"]}["database"] == "fault"
    assert {item["id"]: item["state"] for item in refused["checks"]}["router"] == "fault"
    assert "port" in _state(_stamp(40), port=True)["reasons"]
    assert {item["id"]: item["state"] for item in _state(_stamp(40), port=True)["checks"]}["port"] == "fault"
    failed = _state(_stamp(40, features={"async-tasks": "failed", "transport-gateway": "ok"}))
    assert failed["verdict"] == "fault"
    assert "system" in failed["reasons"]
    assert {item["id"]: item["state"] for item in failed["checks"]}["system"] == "fault"
    missing_gateway = _stamp(40)
    missing_gateway["gateway"] = None
    missing = _state(missing_gateway)
    assert missing["verdict"] == "unverified"
    assert {item["id"]: item["state"] for item in missing["checks"]}["gateway"] == "unverified"
    blank = _state(None)
    blank_checks = {item["id"]: item["state"] for item in blank["checks"]}
    assert blank_checks["launchagent"] == "unverified"
    assert blank_checks["gateway"] == "unverified"
    assert blank_checks["system"] == "unverified"
    assert blank_checks["router"] == "ok"
    stale_checks = {item["id"]: item["state"] for item in stale["checks"]}
    assert stale_checks["launchagent"] == "fault"
    assert stale_checks["gateway"] == "unverified"
    assert stale_checks["system"] == "unverified"
    stale_failed = _state(_stamp(420, features={"async-tasks": "failed", "transport-gateway": "ok"}))
    assert {item["id"]: item["state"] for item in stale_failed["checks"]}["system"] == "fault"
    assert {item["id"]: item["state"] for item in stale_failed["checks"]}["launchagent"] == "fault"


def test_loopback_host():
    for host in ("127.0.0.1", "127.0.0.8", "::1", "localhost"):
        assert host_server.loopback_host(host)
    for host in ("0.0.0.0", "::", "192.168.1.10", "example.com"):
        assert not host_server.loopback_host(host)


def test_main_refuses_a_non_loopback_host(monkeypatch, capsys):
    monkeypatch.setenv("SOLAR_APP_HOST", "0.0.0.0")

    def refuse(*_args, **_kwargs):
        raise AssertionError("the server bound")

    monkeypatch.setattr(host_server, "ThreadingHTTPServer", refuse)
    assert host_server.main() == 1
    assert "loopback" in capsys.readouterr().err
