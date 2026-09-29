"""Console queries over the tables that already exist."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import runtime_views
import solar_state as st

_APP = Path(st.__file__).resolve().parents[2] / "solar-app" / "scripts"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import console_data  # noqa: E402


def _task(tid: str, status: str, title: str) -> str:
    return f'---\nid: "{tid}"\ntitle: "{title}"\nstatus: {status}\npriority: normal\n---\n\n# {title}\n'


def _end(ts, status, provider="", channel="telegram", duration=None, user_id=None):
    row = {"ts": ts, "event": "end", "status": status, "channel": channel}
    if provider:
        row["provider"] = provider
    if duration is not None:
        row["duration_ms"] = duration
    if user_id is not None:
        row["user_id"] = user_id
    return row


def test_queries_cover_every_status_and_keep_reconciled_out_of_averages(ready, monkeypatch):
    monkeypatch.setattr(console_data, "port_taken_by_other", lambda port=9000: False)
    workspace = Path(os.environ["SOLAR_WORKSPACE"])
    folder = workspace / "sun" / "delegations"
    folder.mkdir(parents=True)
    (folder / "calendar-busy-sync.yaml").write_text(
        "name: calendar-busy-sync\nmode: active\n", encoding="utf-8")
    (folder / "job-triage-passive.yaml").write_text(
        "name: job-triage-passive\nmode: shadow\n", encoding="utf-8")
    with st.session(ready, auto_backup=False) as store:
        store.task_import(_task("arch", "archived", "Old"), status="archived")
        store.task_import(_task("plan", "planned", "Later"), status="planned")
        store.audit_append(_end("2026-09-01T00:00:00Z", "success", "claude", duration=100, user_id="a"))
        store.audit_append(_end("2026-09-01T00:01:00Z", "success", "claude", duration=300, user_id="b"))
        store.audit_append(_end("2026-09-02T00:00:00Z", "failed", duration=50, user_id="a"))
        store.audit_append(_end("2026-09-02T00:01:00Z", "reconciled", "claude", duration=99999))
        store.audit_append(_end("2026-09-02T00:02:00Z", "failed", "codex", duration=10))
        store.delegation_event_append(
            "calendar-busy-sync", "shadow", {"ts": "2026-07-25T00:00:00Z"})
        store.continuity_import_text(json.dumps({
            "updated_at": "2026-09-01T00:00:00Z",
            "active_task": "quiet",
        }))
    with st.read_session(ready) as store:
        tasks = runtime_views.console_tasks(store)
        runs = runtime_views.console_executions(store)
        events = runtime_views.console_mandate_events(store)
    by_id = {row["id"]: row["status"] for row in tasks["tasks"]}
    assert by_id["arch"] == "archived"
    assert by_id["plan"] == "planned"
    assert tasks["by_status"]["archived"]["n"] == 1
    assert tasks["by_status"]["planned"]["n"] == 1
    assert any(row["task_id"] == "arch" for row in tasks["history"])
    claude = next(row for row in runs["providers"] if row["provider"] == "claude")
    assert claude == {"provider": "claude", "n": 2, "avg_duration_ms": 200}
    codex = next(row for row in runs["providers"] if row["provider"] == "codex")
    assert codex["n"] == 1
    assert codex["avg_duration_ms"] == 10
    assert runs["no_provider"] == {
        "failed": 1, "failed_avg_duration_ms": 50, "reconciled": 1,
    }
    assert runs["by_status"]["reconciled"] == 1
    assert runs["total"] == 5
    assert sum(row["n"] for row in runs["channels"]) == 5
    assert events["calendar-busy-sync"]["shadow"] == 1
    data = console_data.mandates(workspace)
    assert data["modes"]["calendar-busy-sync"] == "active"
    assert data["modes"]["job-triage-passive"] == "shadow"
    assert "job-triage-passive" not in data["events"]
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    fresh = {
        "at": (now - timedelta(seconds=40)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "features": {"async-tasks": "ok", "transport-gateway": "ok"},
        "gateway": {
            "processes": {"ws": True, "http": True, "tunnel": True},
            "local_health": True,
            "connector_ready": True,
        },
    }
    system = ready / "system"
    system.mkdir()
    (system / "pass-stamp.json").write_text(json.dumps(fresh) + "\n", encoding="utf-8")
    report = console_data.health(workspace, now=now)
    assert report["verdict"]["verdict"] == "calm"
    assert report["continuity_age_seconds"] > 300
    assert report["last_activity"]["router"]["age_seconds"] is not None
    fresh["gateway"]["connector_ready"] = False
    (system / "pass-stamp.json").write_text(json.dumps(fresh) + "\n", encoding="utf-8")
    fault = console_data.health(workspace, now=now)
    assert fault["verdict"]["verdict"] == "fault"
    assert "gateway" in fault["verdict"]["reasons"]
    assert fault["continuity_age_seconds"] > 300
    asked = console_data.requester(workspace)
    assert asked["tasks"]["recorded"] is False
    assert asked["executions"]["recorded"] is False
    assert asked["approvals"]["recorded"] is False
    runs_out = console_data.executions(workspace)
    assert runs_out["requester"]["recorded"] is False
    assert runs_out["user_id_values"] == 2


def test_ides_ingress_and_channel_summaries(ready):
    workspace = Path(os.environ["SOLAR_WORKSPACE"])
    claude = workspace / ".claude" / "skills"
    claude.mkdir(parents=True)
    (claude / "gone").symlink_to(workspace / "missing-skill")
    agents = workspace / ".agents" / "skills"
    agents.mkdir(parents=True)
    (agents / ".solar-managed").write_text("solar-state\n", encoding="utf-8")
    (agents / "solar-state").mkdir()
    (workspace / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=secret-token\n"
        "SOLAR_GATEWAY_CLAIM_TELEGRAM=false\n"
        "SOLAR_CLOUDFLARED_HOSTNAME=example.invalid\n",
        encoding="utf-8",
    )
    gateway = ready / "gateway"
    gateway.mkdir()
    (gateway / "env.stamp").write_text(
        "http_host=127.0.0.1\nhttp_port=8787\ntunnel_mode=named\n"
        "keys_present=SOLAR_GATEWAY_CLAIM_TELEGRAM\n",
        encoding="utf-8",
    )
    (gateway / "env.fail").write_text(
        "reason=tunnel_recovery_failed\nattempts=2\nexhausted=0\n",
        encoding="utf-8",
    )
    conversations = ready / "router" / "conversations"
    conversations.mkdir(parents=True)
    (conversations / "telegram-summary.txt").write_text(
        "first line only\nsecond line is the rest of the thread\n", encoding="utf-8")
    (conversations / "thread.jsonl").write_text("full thread\n", encoding="utf-8")

    ides = console_data.ides(workspace)
    broken = next(row for row in ides if row["destination"] == ".claude/skills")
    assert broken["broken"] == ["gone"]
    shared = next(row for row in ides if row["destination"] == ".agents/skills")
    assert shared["kind"] == "copy"
    assert shared["skills"] == 1
    assert shared["solar_managed"] == 1
    assert shared["shared_with"] == ["codex", "antigravity"]
    door = console_data.ingress(workspace)
    assert door["claim_label"] == "not configured to claim"
    assert door["telegram_status"] == "live status not verified"
    assert door["hostname"] == "example.invalid"
    assert door["fail"]["reason"] == "tunnel_recovery_failed"
    assert "secret-token" not in json.dumps(door)
    summaries = console_data.continuity(workspace)["summaries"]
    assert summaries == [{
        "file": "telegram-summary.txt",
        "date": summaries[0]["date"],
        "first_line": "first line only",
    }]
    assert len(summaries) == 1


def test_execution_channel_and_user_id_come_from_the_start(ready):
    with st.session(ready, auto_backup=False) as store:
        store.audit_append({
            "ts": "2026-09-01T00:00:00Z", "event": "start", "router_id": "r1",
            "channel": "telegram", "user_id": "one",
        })
        store.audit_append({
            "ts": "2026-09-01T00:01:00Z", "event": "end", "router_id": "r1",
            "status": "success", "provider": "claude", "duration_ms": 10,
            "channel": "voice", "user_id": "ignored",
        })
        store.audit_append({
            "ts": "2026-09-01T00:02:00Z", "event": "start", "router_id": "r2",
            "channel": "n8n", "user_id": "two",
        })
        store.audit_append({
            "ts": "2026-09-01T00:03:00Z", "event": "end", "router_id": "r2",
            "status": "success",
        })
        store.audit_append({
            "ts": "2026-09-01T00:04:00Z", "event": "end", "router_id": "orphan",
            "status": "failed", "channel": "telegram", "user_id": "three",
        })
    with st.read_session(ready) as store:
        runs = runtime_views.console_executions(store)
    channels = {row["channel"]: row["n"] for row in runs["channels"]}
    assert channels == {"telegram": 1, "n8n": 1, "other": 1}
    assert runs["user_id_values"] == 3
    recent = {row["ts"]: row["channel"] for row in runs["recent"]}
    assert recent["2026-09-01T00:01:00Z"] == "telegram"
    assert recent["2026-09-01T00:04:00Z"] == "other"
