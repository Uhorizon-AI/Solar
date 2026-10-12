"""Read side of tasks, and schedule planning.

Everything here is read-only: it opens `state.sqlite` through a read session and
never writes. Writes live in `operations.py`.
"""
from __future__ import annotations

import datetime
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capability_registry  # noqa: E402
from mcp_context import OperationError  # noqa: E402
import runtime_views  # noqa: E402  (solar-state/scripts is on sys.path via mcp_context)

_UTC = datetime.timezone.utc
_VIEWS = ("detail", "instructions", "config", "status", "result", "error", "history")
_LEGACY_STATE = {"drafts": "draft"}
_RUNTIME_SECTIONS = ("Execution Error", "Subtask results", "Delivery")
_RESULT_SECTIONS = ("Result", "Resultado", "Delivery", "Subtask results")
_ERROR_SECTIONS = ("Execution Error", "Error")
_IDENTITY = ("workspace_id", "agent", "planet", "responsibility", "agent_contract")
_LIMIT_BYTES = 60000
# A recurrence must be able to fire again even when the week is one hour shorter
# (daylight-saving change) and the previous run finished late.
_INTERVAL_MARGIN = 7200


ViewError = OperationError


# ---------------------------------------------------------------------------
# schedule planning
# ---------------------------------------------------------------------------

def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ViewError("schedule_invalid", f"unknown time zone {name!r}") from None


def next_occurrences(time: str, weekdays, zone: str, after=None, count: int = 4) -> list[dict]:
    """The next local wall-clock occurrences, with their offsets.

    Local times that do not exist (the skipped hour of a spring-forward day) are
    left out, exactly as the queue would never match them.
    """
    info = _zone(zone)
    hour, minute = (int(part) for part in time.split(":"))
    after = (after or datetime.datetime.now(_UTC)).astimezone(_UTC)
    allowed = set(weekdays or range(1, 8))
    day = after.astimezone(info).date()
    found = []
    for _ in range(800):
        if day.isoweekday() in allowed:
            local = datetime.datetime(day.year, day.month, day.day, hour, minute, tzinfo=info)
            instant = local.astimezone(_UTC)
            exists = instant.astimezone(info).replace(tzinfo=None) == local.replace(tzinfo=None)
            if exists and instant > after:
                found.append(dict(local=local.isoformat(), utc=instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                  weekday=day.isoweekday(), utc_offset=local.strftime("%z")))
                if len(found) == count:
                    break
        day += datetime.timedelta(days=1)
    return found


def shortest_gap_days(weekdays) -> int:
    days = sorted(set(weekdays or range(1, 8)))
    if len(days) == 1:
        return 7
    return min((days[(i + 1) % len(days)] - days[i]) % 7 or 7 for i in range(len(days)))


def plan_schedule(*, time, weekdays, zone, recurring, min_interval, after=None) -> dict:
    """Validate a schedule and derive what depends on it.

    A wall-clock schedule needs an explicit IANA zone: without one the hour
    would follow whichever host runs the queue. A recurrence interval longer
    than the shortest gap between occurrences (less a safety margin) would skip
    runs after a daylight-saving change, so it is refused instead of stored.
    """
    # `scheduled_time: now` (create.sh --queued) means "no clock restriction".
    # Weekdays are kept: without a real HH:MM they are refused below, so a task that
    # inherited "now" cannot be stored as "Fridays" while still running on any day.
    if time == "now":
        time = None
    scheduled = bool(time or weekdays)
    notes = []
    plan = dict(scheduled_time=time, scheduled_weekdays=list(weekdays or []),
                scheduled_timezone=zone, recurring=bool(recurring),
                recurring_min_interval=min_interval, next_occurrences=[], notes=notes)
    if scheduled:
        if not zone:
            raise ViewError("schedule_invalid",
                            "scheduled_timezone is required with a schedule (e.g. Europe/Madrid)")
        _zone(zone)
        if weekdays and not time:
            raise ViewError("schedule_invalid", "scheduled_weekdays needs scheduled_time")
        if time and time.split(":")[0] == "02":
            notes.append("02:00-02:59 does not exist on the spring-forward day; that day is skipped.")
        plan["next_occurrences"] = next_occurrences(time, weekdays, zone, after)
    if recurring and scheduled:
        longest = shortest_gap_days(weekdays) * 86400 - _INTERVAL_MARGIN
        if min_interval is None:
            plan["recurring_min_interval"] = longest
        elif min_interval > longest:
            raise ViewError(
                "schedule_invalid",
                f"recurring_min_interval {min_interval}s would skip occurrences after a clock "
                f"change; use at most {longest}s for this schedule")
    return plan


# ---------------------------------------------------------------------------
# task reading
# ---------------------------------------------------------------------------

def _values(task: dict) -> dict:
    import solar_state

    return {key: solar_state.value_of(rest) for key, rest in task["frontmatter"]}


def _weekdays(text) -> list[int]:
    return [int(part) for part in str(text or "").split(",") if part.strip().isdigit()]


def _schedule(values: dict) -> dict:
    block = dict(time=values.get("scheduled_time"), weekdays=_weekdays(values.get("scheduled_weekdays")),
                 timezone=values.get("scheduled_timezone"),
                 recurring=str(values.get("recurring") or "").lower() == "true",
                 recurring_min_interval=values.get("recurring_min_interval"),
                 recurring_max_runs=values.get("recurring_max_runs"),
                 recurring_run_count=values.get("recurring_run_count"),
                 recurring_last_run=values.get("recurring_last_run"))
    try:
        if block["time"] and block["time"] != "now" and block["timezone"]:
            block["next_occurrences"] = next_occurrences(block["time"], block["weekdays"], block["timezone"])
    except (ViewError, ValueError):
        block["next_occurrences"] = []
    if block["time"] and block["time"] != "now" and not block["timezone"]:
        block["note"] = "No time zone stored: the hour follows the host that runs the queue."
    return block


def _row(task: dict) -> dict:
    values = _values(task)
    return dict(id=task["id"], title=task["title"], status=task["status"], priority=task["priority"],
                recurring=bool(task["recurring"]), row_version=task["row_version"],
                updated=task["updated"] or task["created"], schedule=_schedule(values),
                revises_task_id=values.get("revises_task_id"))


def find_tasks(query: str = "", state: str = "", limit: int = 10) -> dict:
    import solar_state

    state = _LEGACY_STATE.get(state, state)
    if state and state not in solar_state.STATUSES:
        raise ViewError("invalid_arguments", f"state must be one of {', '.join(solar_state.STATUSES)}")
    terms = set(re.findall(r"\w+", query.casefold()))
    limit = max(1, min(limit, 50))
    with solar_state.read_session() as store:
        tasks = store.task_list(state or None)
    ranked = []
    for task in tasks:
        haystack = f"{task['id']} {task['title'] or ''}".casefold()
        matched = sum(1 for term in terms if term in haystack)
        if terms and not matched:
            continue
        ranked.append((-matched, task["updated"] or task["created"] or "", task))
    ranked.sort(key=lambda item: item[1], reverse=True)   # newest first ...
    ranked.sort(key=lambda item: item[0])                  # ... then best match first
    shown = ranked[:limit]
    return dict(count=len(ranked), tasks=[_row(task) for _, _, task in shown],
                truncated=len(ranked) > len(shown))


def _resolve(store, task_id: str) -> dict:
    task = store.task_get(task_id)
    if task is None:
        stems = [row for row in store.task_list()
                 if Path(row.get("source_name") or "").stem == task_id]
        if len(stems) == 1:
            task = stems[0]
    if task is None:
        raise ViewError("task_not_found", f"no task {task_id}")
    return task


def _sections_named(body: str, titles) -> list[dict]:
    return [item for item in capability_registry.sections(body)
            if item["level"] == 2 and item["title"] in titles]


def _without_sections(body: str, titles) -> str:
    for item in sorted(_sections_named(body, titles), key=lambda s: s["start"], reverse=True):
        body = body[:item["start"]] + body[item["start"] + len(item["text"]):]
    return body.rstrip() + "\n"


def _checkpoint(values: dict) -> dict | None:
    if "continuity_checkpoint" not in values:
        return None
    try:
        return runtime_views.task_checkpoint(values["continuity_checkpoint"])
    except ValueError:
        raise ViewError("checkpoint_invalid", "continuity_checkpoint must be a JSON object") from None


def _execution_result(task: dict, values: dict) -> dict | None:
    """The `## Result` the executor wrote to the task's execution log, if any.

    Only a regular file inside the runtime `task-logs` folder is read, and at most
    60 KB of it: the paths come from stored task fields, so they are not trusted.
    """
    import solar_runtime

    root = solar_runtime.runtime_dir("task-logs").resolve()
    for raw in (values.get("result_path"), task.get("log_path")):
        if not raw:
            continue
        try:
            path = Path(str(raw)).resolve(strict=True)
            if not path.is_file() or not path.is_relative_to(root):
                continue
            with path.open("rb") as stream:
                text = stream.read(_LIMIT_BYTES + 1).decode("utf-8", "replace")
        except (OSError, ValueError):
            continue
        found = [item for item in capability_registry.sections(text) if item["title"] in ("Result", "Error")]
        if not found:
            continue
        return dict(file=path.name, truncated=len(text.encode()) > _LIMIT_BYTES,
                    outcome=found[0]["title"].lower(), text=found[0]["text"][:_LIMIT_BYTES])
    return None


def view_task(task_id: str, view: str = "detail", section: str = "") -> dict:
    import solar_state

    if view not in _VIEWS:
        raise ViewError("invalid_arguments", f"view must be one of {', '.join(_VIEWS)}")
    if section and view != "instructions":
        raise ViewError("invalid_arguments", "section applies only to view=instructions")
    with solar_state.read_session() as store:
        task = _resolve(store, task_id)
        events = [dict(ts=r["ts"], from_status=r["from_status"], to_status=r["to_status"],
                       actor=r["actor"])
                  for r in store.conn.execute(
                      "SELECT ts, from_status, to_status, actor FROM task_events "
                      "WHERE task_id = ? ORDER BY seq", (task["id"],))]
        cancel_requested = store.cancellation_requested(task["id"])
    values = _values(task)
    base = dict(id=task["id"], title=task["title"], status=task["status"],
                row_version=task["row_version"], view=view)
    body = task["body"] or ""
    if view == "detail":
        digest = solar_state.material_digest(task["frontmatter"], body)
        detail = dict(base, priority=task["priority"], created=task["created"], updated=task["updated"],
                      object=task["object"], scope=task["scope"], effect=task["effect"],
                      schedule=_schedule(values), digest=digest,
                      approved_digest=values.get("approved_digest"),
                      revises_task_id=values.get("revises_task_id"),
                      archived_reason=values.get("archived_reason"),
                      views=list(_VIEWS))
        for key in _IDENTITY:
            if key in values:
                detail[key] = values[key]
        checkpoint = _checkpoint(values)
        if checkpoint is not None:
            # Recorded evidence, not a new verification or retry authority.
            detail["continuity_checkpoint"] = checkpoint
        return detail
    if view == "instructions":
        text = _without_sections(body, _RUNTIME_SECTIONS)
        parsed = capability_registry.sections(text)
        if section:
            chosen = next((item for item in parsed if item["title"] == section), None)
            if chosen is None:
                titles = ", ".join(item["title"] for item in parsed) or "(none)"
                raise ViewError("unknown_section", f"Unknown section. Titles: {titles}")
            return dict(base, section=section, instructions=chosen["text"])
        if len(text.encode("utf-8")) > _LIMIT_BYTES:
            titles = [item["title"] for item in parsed]
            raise ViewError("too_large", "Instructions exceed 60 KB; read one section. Titles: "
                            + ", ".join(titles))
        return dict(base, instructions=text, sections=[item["title"] for item in parsed])
    if view == "config":
        hidden = {"id", "status", "continuity_checkpoint"}
        return dict(base, config={k: v for k, v in values.items() if k not in hidden},
                    schedule=_schedule(values))
    if view == "status":
        return dict(base, claimed_by=values.get("claimed_by"), claimed_at=values.get("claimed_at"),
                    cancellation_requested=cancel_requested,
                    blocked_by_task_ids=values.get("blocked_by_task_ids"),
                    subtask_ids=values.get("subtask_ids"),
                    recurring=_schedule(values), recent_events=events[-10:])
    if view == "result":
        found = _sections_named(body, _RESULT_SECTIONS)
        logged = _execution_result(task, values)
        return dict(base, results=[dict(title=i["title"], text=i["text"]) for i in found],
                    execution_log=logged, recorded=bool(found) or logged is not None)
    if view == "error":
        found = _sections_named(body, _ERROR_SECTIONS)
        return dict(base, errors=[dict(title=i["title"], text=i["text"]) for i in found],
                    recorded=bool(found), error_status=task["status"] == "error")
    return dict(base, events=events[-100:], count=len(events))
