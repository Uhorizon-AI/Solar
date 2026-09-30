"""Verdict and loopback, without a live console."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_APP = Path(__file__).resolve().parents[3] / "skills" / "solar-app" / "scripts"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import console_data  # noqa: E402
import console_language as language_tokens  # noqa: E402
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


def test_language_aliases_live_in_one_table():
    assert language_tokens.canonical_language("es_ES") == "es"
    assert language_tokens.canonical_language("spanish") == "es"
    assert language_tokens.canonical_language("english") == "en"
    assert language_tokens.canonical_language("fr") is None
    assert language_tokens.effective_language("es-ES") == "es"
    assert language_tokens.effective_language("nope") == "en"
    assert language_tokens.effective_language(None) == "en"


def test_console_language_defaults_to_english(tmp_path):
    assert console_data.console_language(None) == "en"
    assert console_data.console_language(tmp_path) == "en"
    solar = tmp_path / ".solar"
    solar.mkdir()
    (solar / "settings.json").write_text("{}\n", encoding="utf-8")
    assert console_data.console_language(tmp_path) == "en"
    (solar / "settings.json").write_text('{"language": "en"}\n', encoding="utf-8")
    assert console_data.console_language(tmp_path) == "en"
    (solar / "settings.json").write_text('{"language": "es-ES"}\n', encoding="utf-8")
    assert console_data.console_language(tmp_path) == "es"


def test_attention_line_keeps_only_nonzero_counts_when_calm():
    calm = _state(_stamp(40))
    assert console_data.attention_line(calm, errors=7, drafts=15, quiet_days=4) == (
        "All working · 7 tasks in error · 15 drafts · no activity for 4 days"
    )
    assert console_data.attention_line(calm, errors=0, drafts=0, quiet_days=0) == "All working"
    assert console_data.attention_line(calm, errors=7, drafts=0, quiet_days=0) == (
        "All working · 7 tasks in error"
    )
    assert console_data.attention_line(calm, errors=0, drafts=15, quiet_days=0) == (
        "All working · 15 drafts"
    )
    assert console_data.attention_line(calm, errors=0, drafts=0, quiet_days=4) == (
        "All working · no activity for 4 days"
    )
    assert console_data.attention_line(calm, errors=1, drafts=1, quiet_days=1) == (
        "All working · 1 task in error · 1 draft · no activity for 1 day"
    )


def test_attention_line_uses_spanish_when_configured():
    calm = _state(_stamp(40))
    assert console_data.attention_line(
        calm, errors=1, drafts=1, quiet_days=1, language="es",
    ) == "Todo funciona · 1 tarea en error · 1 borrador · sin actividad desde hace 1 día"
    down = _state(_stamp(40, connector=False))
    assert console_data.attention_line(down, language="es") == "Avería: el gateway no está sano"


def test_attention_line_names_a_fault_and_ignores_counts():
    down = _state(_stamp(40, connector=False))
    assert console_data.attention_line(down, errors=7, drafts=15, quiet_days=4) == (
        "Fault: the gateway is not healthy"
    )
    failed = _state(_stamp(40, features={"async-tasks": "failed", "transport-gateway": "ok"}))
    assert console_data.attention_line(
        failed, errors=3, drafts=2, quiet_days=1,
        features={"async-tasks": "failed", "transport-gateway": "ok"},
    ) == "Fault: background tasks have failed"


def test_attention_line_names_what_is_missing_and_ignores_counts():
    missing = _state(None)
    assert console_data.attention_line(missing, errors=7, drafts=15, quiet_days=4) == (
        "Unverified: missing the system result, the LaunchAgent pass and the gateway state"
    )
    stamp = _stamp(40)
    stamp["gateway"] = None
    gateway = _state(stamp)
    assert console_data.attention_line(gateway, errors=4, drafts=1, quiet_days=2) == (
        "Unverified: missing the gateway state"
    )


def test_health_attention_uses_task_counts_and_skips_zeros(monkeypatch):
    monkeypatch.setattr(console_data, "read_pass_stamp", lambda: _stamp(40))
    monkeypatch.setattr(console_data, "port_taken_by_other", lambda port=9000: False)
    monkeypatch.setattr(console_data, "read_install", lambda _workspace: {"version": "v", "mode": "global"})
    monkeypatch.setattr(console_data, "read_owner", lambda: None)
    monkeypatch.setattr(console_data, "read_cutover", lambda: None)
    monkeypatch.setattr(console_data, "read_backups", lambda: [])

    class _Store:
        def counts(self):
            return {"tasks": {"error": 7, "draft": 0, "completed": 3}}

    monkeypatch.setattr(console_data, "_with_store", lambda fn: (fn(_Store()), None))
    monkeypatch.setattr(console_data.runtime_views, "console_last_activity", lambda _store: {
        "router": "2026-09-25T12:00:00Z",
        "tasks": None,
        "mandates": None,
    })
    monkeypatch.setattr(console_data.runtime_views, "console_continuity", lambda _store: None)
    report = console_data.health(Path("/tmp/unused"), now=NOW)
    assert report["language"] == "en"
    assert report["attention"] == (
        "All working · 7 tasks in error · no activity for 4 days"
    )
    assert "drafts" not in report["attention"]
    monkeypatch.setattr(console_data, "console_language", lambda workspace: "es")
    spanish = console_data.health(Path("/tmp/unused"), now=NOW)
    assert spanish["language"] == "es"
    assert spanish["attention"] == (
        "Todo funciona · 7 tareas en error · sin actividad desde hace 4 días"
    )


def test_a_revoked_mandate_is_not_active():
    defined = [
        {"mode": "active"},
        {"mode": "revoked", "revoked_at": "2026-09-01T00:00:00Z"},
        {"mode": "shadow"},
        {"mode": "paused"},
    ]
    assert console_data.active_mandate_count(defined) == 1
    assert console_data.active_mandate_count([
        {"mode": "active", "revoked_at": "2026-09-01T00:00:00Z"},
    ]) == 0


def test_mandates_reads_revoked_at_and_leaves_it_out_of_active(tmp_path, monkeypatch):
    folder = tmp_path / "delegations"
    folder.mkdir()
    (folder / "live.yaml").write_text("name: live\nmode: active\n", encoding="utf-8")
    (folder / "dated.yaml").write_text(
        "name: dated\nmode: active\nrevoked_at: 2026-09-01T00:00:00Z\n",
        encoding="utf-8",
    )
    (folder / "explicit.yaml").write_text(
        "name: explicit\nmode: revoked\nrevoked_at: 2026-08-01T00:00:00Z\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        console_data.mandate_lib, "list_mandates",
        lambda: sorted(folder.glob("*.yaml")),
    )
    monkeypatch.setattr(console_data, "_with_store", lambda fn: ({}, None))
    data = console_data.mandates(tmp_path)
    by_name = {item["name"]: item for item in data["defined"]}
    assert by_name["dated"]["revoked_at"] == "2026-09-01T00:00:00Z"
    assert by_name["dated"]["mode"] == "revoked"
    assert by_name["explicit"]["mode"] == "revoked"
    assert data["modes"]["dated"] == "revoked"
    assert data["modes"]["live"] == "active"
    assert data["active"] == 1


def test_main_refuses_a_non_loopback_host(monkeypatch, capsys):
    monkeypatch.setenv("SOLAR_APP_HOST", "0.0.0.0")

    def refuse(*_args, **_kwargs):
        raise AssertionError("the server bound")

    monkeypatch.setattr(host_server, "ThreadingHTTPServer", refuse)
    assert host_server.main() == 1
    assert "loopback" in capsys.readouterr().err
