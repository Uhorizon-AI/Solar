#!/usr/bin/env python3
"""Explicit, bounded agent continuity and portable execution facts."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

_CORE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_CORE / "skills/solar-state/scripts"))
import solar_state
from _memory_common import directory_lock, file_hash, locked_parent, name, planet_root, within

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PARTS = {"checkpoint": {"state", "artifact_ref", "expected_sha256", "retry"},
          "last_verified_result": {"path", "sha256", "verified_at"},
          "next_check": {"at", "action", "source"},
          "decision": {"status", "owner", "source", "valid_from", "valid_until"}}




def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()








def checkpoint(value, planet, portable=False):
    extras = {"version", "task_ref", "sources"}
    if not isinstance(value, dict) or set(value) - (set(_PARTS) | {"wait"} | extras):
        raise ValueError("unsupported checkpoint fields")
    if "version" in value and (type(value["version"]) is not int or value["version"] != 1):
        raise ValueError("unsupported recorded checkpoint version")
    result = {}
    for section, row in value.items():
        if section in {"version", "task_ref"}:
            continue
        if section == "sources":
            if not isinstance(row, list) or len(row) > 20:
                raise ValueError("invalid checkpoint sources")
            result[section] = []
            for item in row:
                if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
                    raise ValueError("invalid source fingerprint")
                parsed = checkpoint({"last_verified_result": item}, planet, portable)
                result[section].append(parsed["last_verified_result"])
            continue
        if section == "wait":
            if not isinstance(row, str) or len(row) > 2048:
                raise ValueError("invalid wait text")
            result[section] = row
            continue
        omitted = ({"effect", "effect_writes_during_recovery", "verified_at"}
                   if section == "checkpoint" else
                   {"subject", "expiry_effect"} if section == "decision" else set())
        if not isinstance(row, dict) or set(row) - (_PARTS[section] | omitted):
            raise ValueError("unsupported checkpoint section")
        result[section] = {}
        for key, text in row.items():
            if key in omitted:
                continue
            if not isinstance(text, str) or len(text) > 2048:
                raise ValueError("checkpoint fields must be bounded strings")
            if key in {"path", "source", "artifact_ref"}:
                prefix = f"planets/{planet}/"
                if not portable and text.startswith(prefix):
                    text = text[len(prefix):]
                if text.startswith("planets/") or Path(text.split("#", 1)[0]).is_absolute():
                    raise ValueError("cross-planet reference refused")
            if key in {"sha256", "expected_sha256"} and not _HASH.fullmatch(text):
                raise ValueError("invalid artifact hash")
            result[section][key] = text
    if not result or len(encoded(result).encode()) > 8192:
        raise ValueError("empty or oversized checkpoint")
    return result


def reference_rows(value):
    for row in value.values():
        if isinstance(row, dict):
            yield row
        elif isinstance(row, list):
            yield from row


def show(workspace, planet, agent, responsibility, task_id):
    workspace, root, contract = planet_root(workspace, planet, agent)
    name(responsibility)
    solar_state._check_id(task_id)
    # session validates owner against SOLAR_WORKSPACE; bind only via CLI caller.
    settings = json.loads((workspace / ".solar/settings.json").read_text())
    with solar_state.read_session() as state:
        row = state.agent_continuity(planet, agent, responsibility, task_id)
    if row["workspace_id"] != settings.get("workspace_id"):
        raise ValueError("workspace identity mismatch")
    if row["agent_contract"] != f"planets/{planet}/agents/{agent}.md":
        raise ValueError("canonical contract reference mismatch")
    return row






def export(workspace, planet, agent, responsibility, task_id):
    row = show(workspace, planet, agent, responsibility, task_id)
    _, root, contract = planet_root(workspace, planet, agent)
    payload = {"version": 1, "origin_workspace": row["workspace_id"],
               "planet": planet, "agent": agent, "responsibility": responsibility,
               "origin_task": task_id, "contract_sha256": file_hash(contract),
               "checkpoint": checkpoint(row["continuity_checkpoint"], planet)}
    for section in reference_rows(payload["checkpoint"]):
        for key in {"path", "source", "artifact_ref"} & section.keys():
            within(root, section[key])
    envelope = {"payload": payload, "sha256": digest(payload)}
    path = within(root, f"agents/continuidad/{agent}.md")
    text = "# Portable agent continuity\n\n```json\n" + encoded(envelope) + "\n```\n"
    with locked_parent(path):
        if path.exists():
            if path.read_text() == text:
                return {"path": str(path), "changed": False, "sha256": envelope["sha256"]}
            raise ValueError("continuity copy exists with different content")
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".continuity-")
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {"path": str(path), "changed": True, "sha256": envelope["sha256"]}


def restore(workspace, planet, agent, apply=False):
    workspace, root, contract = planet_root(workspace, planet, agent)
    path = within(root, f"agents/continuidad/{agent}.md")
    if path.stat().st_size > 16384:
        raise ValueError("continuity copy too large")
    text = path.read_text()
    prefix, suffix = "# Portable agent continuity\n\n```json\n", "\n```\n"
    if not text.startswith(prefix) or not text.endswith(suffix):
        raise ValueError("unsupported portable continuity format")
    envelope = json.loads(text[len(prefix):-len(suffix)])
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}:
        raise ValueError("invalid continuity envelope")
    data = envelope["payload"]
    keys = {"version", "origin_workspace", "planet", "agent", "responsibility",
            "origin_task", "contract_sha256", "checkpoint"}
    if not isinstance(data, dict) or set(data) != keys or type(data["version"]) is not int or data["version"] != 1:
        raise ValueError("unsupported continuity version or fields")
    if digest(data) != envelope["sha256"] or data["planet"] != planet or data["agent"] != agent:
        raise ValueError("continuity identity or digest mismatch")
    name(data["responsibility"])
    solar_state._check_id(data["origin_task"])
    if not isinstance(data["origin_workspace"], str) or len(data["origin_workspace"]) > 128:
        raise ValueError("invalid origin workspace")
    checked = checkpoint(data["checkpoint"], planet, portable=True)
    issues = []
    if file_hash(contract) != data["contract_sha256"]:
        issues.append("contract hash differs")
    now = datetime.now(timezone.utc)
    fingerprints = {f"agents/{agent}.md": data["contract_sha256"]}
    for row in reference_rows(checked):
        if "path" in row and "sha256" in row:
            fingerprints[row["path"].split("#", 1)[0]] = row["sha256"]
        if "artifact_ref" in row and "expected_sha256" in row:
            fingerprints[row["artifact_ref"].split("#", 1)[0]] = row["expected_sha256"]
    for row in reference_rows(checked):
        for key in {"path", "source", "artifact_ref"} & row.keys():
            target = within(root, row[key])
            if not target.is_file():
                issues.append("reference missing: " + row[key])
            else:
                expected = fingerprints.get(row[key].split("#", 1)[0])
                if not expected or file_hash(target) != expected:
                    issues.append("artifact hash missing or differs: " + row[key])
        for key in ("valid_until", "valid_from"):
            if key in row:
                moment = datetime.fromisoformat(row[key].replace("Z", "+00:00"))
                if moment.tzinfo is None:
                    raise ValueError("validity requires a timezone")
                if (key == "valid_until" and moment <= now) or (key == "valid_from" and moment > now):
                    issues.append("decision outside validity interval")
    next_at = checked.get("next_check", {}).get("at")
    if next_at:
        due = datetime.fromisoformat(next_at.replace("Z", "+00:00"))
        if due.tzinfo is None:
            if len(next_at) != 10:
                raise ValueError("next review instant requires a timezone")
            due = due.replace(tzinfo=timezone.utc)
        if due <= now:
            issues.append("next review is due; owner decision required")
    result = {"payload": data, "issues": issues, "ready": not issues,
              "applied": False, "retry_authorized": False}
    if apply:
        if issues:
            raise ValueError("continuity requires a decision before incorporation")
        settings = json.loads((workspace / ".solar/settings.json").read_text())
        key = ":".join((planet, agent, data["responsibility"]))
        record = {"origin": data, "destination_workspace": settings["workspace_id"],
                  "sha256": envelope["sha256"], "authority": "none"}
        def change(current):
            current = dict(current or {})
            agents = dict(current.get("portable_agents", {}))
            if key in agents and agents[key] != record:
                raise ValueError("different continuity already incorporated")
            agents[key] = record
            current["portable_agents"] = agents
            return current
        with solar_state.session() as state:
            state.continuity_update(change)
        result["applied"] = True
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=os.environ.get("SOLAR_WORKSPACE"))
    verbs = parser.add_subparsers(dest="area", required=True)
    cont = verbs.add_parser("continuity").add_subparsers(dest="verb", required=True)
    for verb in ("show", "export", "restore"):
        sub = cont.add_parser(verb)
        sub.add_argument("--planet", required=True)
        sub.add_argument("--agent", required=True)
        if verb != "restore":
            sub.add_argument("--responsibility", required=True)
            sub.add_argument("--task-id", required=True)
        else:
            sub.add_argument("--apply", action="store_true", help="explicitly incorporate into solar-state; never activates work")
    facts = verbs.add_parser("facts").add_subparsers(dest="verb", required=True)
    for verb in ("init", "append", "read", "backup", "restore"):
        sub = facts.add_parser(verb)
        sub.add_argument("--planet", required=True)
        sub.add_argument("--agent", required=True)
        if verb == "init":
            sub.add_argument("--need", required=True, help="existing approval reference: sun/plans or sun/delegations Markdown path#heading")
        if verb in {"read", "append"}:
            sub.add_argument("--responsibility", required=True)
        if verb == "append":
            sub.add_argument("--event-id", required=True)
            sub.add_argument("--result", required=True, choices=("succeeded", "failed", "corrected"))
            sub.add_argument("--source", required=True)
            sub.add_argument("--observed-at", required=True)
        if verb == "restore":
            sub.add_argument("--source", required=True)
            sub.add_argument("--expected-current-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        if not args.workspace:
            raise ValueError("workspace is required")
        os.environ["SOLAR_WORKSPACE"] = str(Path(args.workspace).resolve())
        if args.area == "facts":
            import fact_store
            identity = (args.workspace, args.planet, args.agent)
            if args.verb == "init":
                result = fact_store.initialize(*identity, args.need)
            elif args.verb == "read":
                result = fact_store.read(*identity, args.responsibility)
            elif args.verb == "append":
                result = fact_store.append(*identity, args.responsibility, args.event_id,
                                           args.result, args.source, args.observed_at)
            elif args.verb == "backup":
                result = fact_store.backup(*identity)
            else:
                result = fact_store.restore_backup(*identity, args.source, args.expected_current_sha256)
        elif args.verb == "restore":
            result = restore(args.workspace, args.planet, args.agent, args.apply)
        else:
            operation = show if args.verb == "show" else export
            result = operation(args.workspace, args.planet, args.agent, args.responsibility, args.task_id)
        print(encoded(result))
        return 0
    except (ValueError, OSError, solar_state.StateUnavailable, sqlite3.Error) as error:
        print(encoded({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
