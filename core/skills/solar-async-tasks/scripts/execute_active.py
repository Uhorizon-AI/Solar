#!/usr/bin/env python3
"""
execute_active.py — Python executor for solar-async-tasks.

Handles I/O JSON with solar-router v3. Called by execute_active.sh.
- Reads task file path and task metadata from arguments/env
- Builds router v3 request (channel=async-task, mode=direct_only)
- Passes provider from task frontmatter if set (strict mode)
- Parses router v3 JSON response
- Writes structured log and returns exit code for lifecycle management

Usage:
    python3 execute_active.py <task_id> <router_script>
"""
import hashlib
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "solar-router/scripts"))
_STATE_SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "solar-state" / "scripts"
if str(_STATE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_STATE_SCRIPTS))
from managed_process import run_managed, ProcessCancelled
import solar_state

_CANCEL_CHECK = lambda: False
_START_HOOK = lambda pid: None

# Interpreters allowed as argv[0] when local_command runs a script under workspace.
_LOCAL_INTERPRETERS = frozenset({"bash", "sh", "python3", "python", "ruby"})

# Exact relative patterns under SOLAR_WORKSPACE (posix), after resolve().
_LOCAL_SCRIPT_PATTERNS = (
    re.compile(r"^planets/[^/]+/skills/[^/]+/scripts/.+"),
    re.compile(r"^solar/core/skills/[^/]+/scripts/.+"),
    re.compile(r"^core/skills/[^/]+/scripts/.+"),
)


def _field(task_id: str, key: str) -> str:
    with solar_state.session() as store:
        value = store.task_field(task_id, key)
    return "" if value is None else str(value)


def _body(task_id: str) -> str:
    with solar_state.session() as store:
        task = store.task_get(task_id)
    if not task:
        return ""
    return task.get("body") or ""


def _status(task_id: str) -> str:
    with solar_state.session() as store:
        return store.task_status(task_id) or ""


def _set(task_id: str, key: str, value: str) -> None:
    with solar_state.session() as store:
        store.task_set(task_id, key, value)


def _unset(task_id: str, key: str) -> None:
    with solar_state.session() as store:
        if store.task_field(task_id, key) is not None:
            store.task_unset(task_id, key)


def _set_body(task_id: str, body: str) -> None:
    with solar_state.session() as store:
        store.task_set_body(task_id, body)


def _log_file(task_id: str) -> pathlib.Path:
    paths = pathlib.Path(__file__).resolve().parents[2] / "solar-paths" / "scripts"
    if str(paths) not in sys.path:
        sys.path.insert(0, str(paths))
    import solar_runtime
    directory = solar_runtime.runtime_dir("task-logs")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task_id}.log"
    with solar_state.session() as store:
        store.task_record(task_id, log_path=str(path))
    return path


def _cancel_requested(task_id: str) -> bool:
    with solar_state.session() as store:
        return store.cancellation_requested(task_id)


def _acknowledge(task_id: str) -> None:
    script = pathlib.Path(__file__).with_name("complete.sh")
    subprocess.run(
        ["bash", str(script), task_id],
        env={**os.environ, "SOLAR_TASK_CANCELLED": "1"},
        check=False,
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_local_timeout(raw: str) -> Tuple[Optional[int], Optional[str]]:
    """Return (seconds, error_code). error_code set ⇒ fail-closed."""
    value = (raw or "300").strip() or "300"
    try:
        timeout_sec = int(value)
    except ValueError:
        return None, "local_timeout_invalid"
    if timeout_sec <= 0:
        return None, "local_timeout_invalid"
    return timeout_sec, None


def authorize_local_argv(
    local_command: str, workspace: pathlib.Path
) -> Tuple[Optional[List[str]], Optional[str]]:
    """Tokenize and allowlist local_command under skill script trees only.

    Allowed relative paths (after resolve, posix):
      planets/<planet>/skills/<skill>/scripts/**
      solar/core/skills/<skill>/scripts/**
      core/skills/<skill>/scripts/**

    Returns (argv, error_code). error_code set ⇒ refuse execution.
    """
    try:
        argv = shlex.split(local_command)
    except ValueError:
        return None, "local_command_invalid"
    if not argv:
        return None, "local_command_missing"

    script_idx = 0
    first_name = pathlib.Path(argv[0]).name
    if first_name in _LOCAL_INTERPRETERS:
        if len(argv) < 2:
            return None, "local_command_unauthorized"
        script_idx = 1

    script_token = argv[script_idx]
    script_path = pathlib.Path(script_token)
    if not script_path.is_absolute():
        script_path = (workspace / script_path).resolve()
    else:
        script_path = script_path.resolve()

    try:
        rel = script_path.relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return None, "local_command_unauthorized"

    if not any(pat.match(rel) for pat in _LOCAL_SCRIPT_PATTERNS):
        return None, "local_command_unauthorized"
    if not script_path.is_file():
        return None, "local_command_missing"

    argv = list(argv)
    argv[script_idx] = str(script_path)
    return argv, None


def read_frontmatter_key(task_id: str, key: str) -> str:
    """One frontmatter value. The argument is a task id."""
    if key == "status":
        return _status(str(task_id))
    return _field(str(task_id), key)


def strip_frontmatter(task_id: str) -> str:
    """Return the task body. The argument is a task id."""
    return _body(str(task_id)).strip()


def build_prompt(task_id: str, title: str, body: str) -> str:
    return (
        "You are executing a Solar asynchronous task.\n"
        "Follow the task instructions exactly as written in the task body.\n"
        "If the task asks to act as an agent and use a skill, do so.\n\n"
        f"Task ID: {task_id}\n"
        f"Task Title: {title}\n\n"
        f"Task Body:\n{body}"
    )


def _env_int_with_comment(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    value = raw.split("#", 1)[0].strip()
    if not value:
        return default
    return int(value)


def call_router(
    router_script: pathlib.Path,
    task_id: str,
    prompt: str,
    provider: Optional[str],
) -> Dict[str, Any]:
    """
    Call solar-router v3 with channel=async-task, mode=direct_only.
    Returns parsed router v3 response dict.
    """
    router_python = os.getenv("SOLAR_AI_ROUTER_PYTHON", sys.executable)
    timeout_sec = _env_int_with_comment(
        "SOLAR_ROUTER_TIMEOUT_SEC",
        _env_int_with_comment("SOLAR_AI_ROUTER_TIMEOUT_SEC", 310),
    )

    payload: Dict[str, Any] = {
        "request_id": f"task_{task_id}",
        "session_id": f"task_{task_id}",
        "user_id": "solar-async-tasks",
        "text": prompt,
        "channel": "async-task",
        "mode": "direct_only",
    }
    if provider:
        payload["provider"] = provider

    proc = run_managed(
        [router_python, str(router_script)],
        input=json.dumps(payload),
        timeout=timeout_sec,
        cancelled=_CANCEL_CHECK, on_start=_START_HOOK,
    )

    stdout = proc.stdout.strip()

    # Always try to parse stdout as router v3 JSON first — even on non-zero exit.
    # Router emits structured JSON errors (with real error_code) and then exits 1.
    if stdout:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            pass

    # Fallback: no parseable JSON at all (crash, binary not found, etc.)
    error_msg = proc.stderr.strip() or stdout or "router crashed with no output"
    return {
        "status": "failed",
        "request_id": f"task_{task_id}",
        "provider_used": provider,
        "reply_text": "",
        "decision": {"kind": "direct_reply", "task_id": None, "priority_suggested": None},
        "error_code": "router_crashed",
        "error": error_msg,
    }


def write_log(
    log_file: pathlib.Path,
    task_id: str,
    title: str,
    outcome: str,
    provider_used: Optional[str],
    result_text: str,
    error_text: Optional[str],
    error_code: Optional[str],
) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Async Task Execution",
        "",
        f"- outcome: {outcome}",
        f"- task_id: {task_id}",
        f"- title: {title}",
        f"- executed_at: {utc_now()}",
        f"- provider_used: {provider_used or 'unknown'}",
        "",
    ]
    if outcome == "success":
        lines += ["## Result", "", result_text]
    else:
        lines += [
            "## Error",
            "",
            f"- error_code: {error_code or 'unknown'}",
            f"- error: {error_text or 'unknown'}",
        ]
    log_file.write_text("\n".join(lines), encoding="utf-8")


def record_result_path(task_id: str, log_file: pathlib.Path) -> None:
    """Point the task at the file that holds its result: the execution log.

    An explicit result_url or result_path set by the task author always wins.
    """
    if _field(task_id, "result_url") or _field(task_id, "result_path"):
        return
    _set(task_id, "result_path", json.dumps(str(log_file.resolve()), ensure_ascii=False))


RE_DELIVERY = re.compile(r"<delivery>(.*?)</delivery>", re.IGNORECASE | re.DOTALL)

# A re-run must replace its own section, never stack a second one.
RE_DELIVERY_SECTION = re.compile(r"\n## Delivery\n.*?(?=\n## |\Z)", re.DOTALL)

# One Telegram message, well under the notifier's chunking threshold.
DELIVERY_MAX_CHARS = 1200


def extract_delivery(reply_text: str) -> str:
    """Return the <delivery> block of a reply, or "" when there is none.

    The last block wins: a reply that shows the format before using it would
    otherwise send the example.
    """
    matches = RE_DELIVERY.findall(reply_text or "")
    if not matches:
        return ""
    return matches[-1].strip()


def clamp_delivery(delivery: str) -> Tuple[str, bool]:
    """Cap the delivery at DELIVERY_MAX_CHARS, keeping its last line.

    That line carries the evidence, which is what the reader needs to reach the
    detail. Returns (text, truncated).
    """
    text = delivery.strip()
    if len(text) <= DELIVERY_MAX_CHARS:
        return text, False
    lines = [line for line in text.splitlines() if line.strip()]
    tail = lines[-1].strip() if lines else ""
    room = DELIVERY_MAX_CHARS - len(tail) - 2
    if room <= 0:
        return text[:DELIVERY_MAX_CHARS].rstrip(), True
    return text[:room].rstrip() + "…\n" + tail, True


def upsert_frontmatter_key(task_id: str, key: str, value: str) -> None:
    """Set a frontmatter key, replacing it when already present."""
    _set(str(task_id), key, value)


def set_frontmatter_flag(task_id: str, key: str, value: bool) -> None:
    """Set a boolean frontmatter flag, removing it when false."""
    if value:
        _set(str(task_id), key, "true")
    else:
        _unset(str(task_id), key)


def record_delivery(task_id: str, reply_text: str) -> None:
    """Copy the reply's delivery block into the task body as `## Delivery`.

    Only the body changes. A flag left by an earlier run is cleared when this
    run does not set it.
    """
    expected = read_frontmatter_key(task_id, "delivery_expected") == "true"
    delivery = extract_delivery(reply_text)
    if delivery:
        delivery, truncated = clamp_delivery(delivery)
    else:
        truncated = False

    body = RE_DELIVERY_SECTION.sub("", _body(str(task_id))).rstrip()
    if delivery:
        body += "\n\n## Delivery\n\n" + delivery
    _set_body(str(task_id), body + "\n")
    set_frontmatter_flag(task_id, "delivery_truncated", truncated)
    set_frontmatter_flag(task_id, "delivery_missing", expected and not delivery)


# ---------------------------------------------------------------------------
# Subtasks: the provider declares them, the worker creates them.
#
# The provider runs sandboxed and cannot write into the queue, so it closes its
# reply with a <subtasks> block and stops. Everything below turns that block
# into real child tasks, remembers which children belong to which parent, and
# serves their results back to the parent for its second execution.
# ---------------------------------------------------------------------------

# Returned to execute_active.sh when this task is now waiting for children.
# The shell moves the parent with await_subtasks.sh; the executor never touches
# the queue. Kept in sync with SUBTASK_WAITING_EXIT in execute_active.sh.
SUBTASK_WAITING_EXIT = 20

SUBTASK_MAX = 5
SUBTASK_TITLE_MAX = 120
SUBTASK_BODY_MAX = 8000
SUBTASK_RESULT_MAX = 4000
SUBTASK_ALLOWED_KEYS = frozenset({"title", "body", "provider"})
SUBTASK_PROVIDERS = frozenset({"codex", "claude", "agy", "agent"})

RE_SUBTASKS = re.compile(r"<subtasks>(.*?)</subtasks>", re.IGNORECASE | re.DOTALL)

# A re-run replaces its own section, never stacks a second one. `### ` headings
# inside the section do not close it: the lookahead needs "## " exactly.
RE_SUBTASK_RESULTS_SECTION = re.compile(r"\n## Subtask results\n.*?(?=\n## |\Z)", re.DOTALL)

# The executor's own log: `## Result` on success, `## Error` on failure.
RE_LOG_OUTCOME_SECTION = re.compile(r"\n## (?:Result|Error)\n(.*)", re.DOTALL)

# The provider is asked to write its own `## Result`, and the log adds one
# around it. Without this the parent reads `### <key> — completed` followed
# by a heading that says nothing it does not already know.
RE_LEADING_OUTCOME_HEADING = re.compile(r"^##\s+(?:Result|Error)\s*$", re.IGNORECASE)
RE_TASK_ERROR_SECTION = re.compile(r"\n## Execution Error\n(.*)", re.DOTALL)


def extract_subtasks(reply_text: str) -> Optional[str]:
    """Return the last <subtasks> block of a reply, or None when there is none.

    The last block wins, like <delivery>: a reply that shows the format before
    using it would otherwise create the example.
    """
    matches = RE_SUBTASKS.findall(reply_text or "")
    if not matches:
        return None
    return matches[-1].strip()


def parse_subtasks(raw: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Validate a declaration. Returns (children, rejection reason).

    All or nothing: a block that breaks any rule creates no children at all.
    Half a batch is worse than none — the parent would synthesize over work that
    was never done.
    """
    try:
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        return [], f"subtasks block is not valid JSON: {exc}"
    if not isinstance(data, list):
        return [], "subtasks block must be a JSON list"
    if not data:
        return [], "subtasks block declares no children"
    if len(data) > SUBTASK_MAX:
        return [], f"subtasks block declares {len(data)} children, the cap is {SUBTASK_MAX}"

    children: List[Dict[str, Any]] = []
    for position, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            return [], f"child {position} is not a JSON object"
        extra = sorted(set(item) - SUBTASK_ALLOWED_KEYS)
        if extra:
            return [], f"child {position} has keys that are not allowed: {', '.join(extra)}"
        title = item.get("title")
        body = item.get("body")
        if not isinstance(title, str) or not title.strip():
            return [], f"child {position} has no title"
        if not isinstance(body, str) or not body.strip():
            return [], f"child {position} has no body"
        if len(title) > SUBTASK_TITLE_MAX:
            return [], f"child {position} title is over {SUBTASK_TITLE_MAX} characters"
        # It ends up on a frontmatter line. `create.sh` quotes it, so this is
        # the second lock rather than the only one, but a title spanning lines
        # is malformed on its own terms.
        if "\n" in title or "\r" in title:
            return [], f"child {position} title spans more than one line"
        if len(body) > SUBTASK_BODY_MAX:
            return [], f"child {position} body is over {SUBTASK_BODY_MAX} characters"
        provider = item.get("provider")
        if provider is not None:
            if not isinstance(provider, str) or provider.strip().lower() not in SUBTASK_PROVIDERS:
                return [], f"child {position} declares an unknown provider: {provider!r}"
            provider = provider.strip().lower()
        children.append({
            "title": title.strip(),
            "body": body.strip(),
            "provider": provider,
        })
    return children, None


def subtask_key(parent_id: str, position: int, title: str, body: str) -> str:
    """Stable key for a declared child: same declaration, same key, always.

    It does not depend on when the worker runs, which is what makes a retry
    after a crash idempotent.
    """
    digest = hashlib.sha256((title + "\n" + body).encode("utf-8")).hexdigest()[:8]
    return f"{parent_id[:8]}-{position}-{digest}"


def read_subtask_manifest(task_file: pathlib.Path) -> List[Tuple[str, str]]:
    """Read `subtask_ids` as (key, task_id) pairs. The id is "" until created."""
    raw = read_frontmatter_key(task_file, "subtask_ids")
    pairs: List[Tuple[str, str]] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, task_id = chunk.partition("=")
        pairs.append((key.strip(), task_id.strip()))
    return pairs


def write_subtask_manifest(task_file: pathlib.Path, pairs: List[Tuple[str, str]]) -> None:
    """Write the manifest as one scalar line, the only shape set_meta supports.

    This field is the durable record of which children were this parent's, and
    it is never cleared — unlike blocked_by_task_ids, which is the traffic light
    of the wait and is dropped on unblock and on activate.
    """
    value = ",".join(f"{key}={task_id}" for key, task_id in pairs)
    upsert_frontmatter_key(task_file, "subtask_ids", json.dumps(value))


def record_subtask_plan(
    task_root: pathlib.Path, task_id: str, children: List[Dict[str, Any]]
) -> None:
    """Persist the declaration in solar-state, not beside the queue.

    The manifest holds keys, not payloads. The plan stays out of the task body:
    that body is the prompt the provider gets in execution 2.
    """
    del task_root
    with solar_state.session() as store:
        store.subtask_plan_import_text(task_id, json.dumps(children, ensure_ascii=False))


def read_subtask_plan(task_root: pathlib.Path, task_id: str) -> List[Dict[str, Any]]:
    del task_root
    with solar_state.session() as store:
        text = store.subtask_plan_text(task_id)
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


TERMINAL_STATUSES = frozenset({"completed", "archived", "error", "cancelled"})


def find_task_file(task_root: pathlib.Path, task_id: str) -> Optional[str]:
    """Return the id when the task exists. The queue is not a directory."""
    del task_root
    with solar_state.session() as store:
        return task_id if store.task_get(task_id) else None


def find_task_by_subtask_key(task_root: pathlib.Path, key: str) -> Optional[str]:
    """Locate a child by its stable key. Returns the child id."""
    del task_root
    with solar_state.session() as store:
        return store.task_find_subtask_key(key)


# The child runs from the workspace and the framework is not inside it. The
# parent is told the same thing by the router; a child's body is written here.
FRAMEWORK_PATH_NOTE = (
    "A path that starts with `core/` belongs to the framework, which lives at "
    "`$SOLAR_ROOT` and is not inside the workspace: resolve it there.\n"
)


def child_object_section(parent_file: pathlib.Path) -> str:
    """Restate the parent's object in the child's own body.

    The child inherits object/scope/effect in its frontmatter, but frontmatter
    is stripped before the prompt is built: the provider would never see it.
    The router writes the same section into a gateway parent for exactly this
    reason — the frontmatter copy is for checking, this one is what the executor
    reads. Kept in the same shape as router._gateway_object_section.
    """
    obj = read_frontmatter_key(parent_file, "object")
    bounds = read_frontmatter_key(parent_file, "scope")
    effect = read_frontmatter_key(parent_file, "effect")
    if not (obj or bounds or effect):
        return (
            "## Object\n"
            "- not declared for this request.\n"
            "Name the artifact you act on in your result, and ask before acting "
            "on anything the request does not name.\n"
            f"{FRAMEWORK_PATH_NOTE}\n"
        )
    return (
        "## Object\n"
        f"- object: {obj or 'not declared'}\n"
        f"- scope: {bounds or 'not declared'}\n"
        f"- effect: {effect or 'not declared'}\n"
        "Act on this object and only on this object. It is inherited from the "
        "request this subtask belongs to and a child cannot widen it. If it "
        "cannot be resolved (it does not exist, it is ambiguous, or the work "
        "points elsewhere), stop and return a concrete question instead of "
        "working on a substitute.\n"
        f"{FRAMEWORK_PATH_NOTE}\n"
    )


def create_child_task(
    task_root: pathlib.Path,
    parent_file: str,
    parent_id: str,
    child: Dict[str, Any],
    key: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Create one child in solar-state. Returns (task_id, error).

    The provider only chose title, body and provider. The object travels down
    from the parent unchanged, and the child gets no origin metadata, so it
    has no notify_when and only the parent speaks to the chat. The subtask key
    is written in the same create as the row.
    """
    del task_root
    priority = read_frontmatter_key(parent_file, "priority") or "normal"
    if priority not in ("high", "normal", "low"):
        priority = "normal"
    created = datetime.now().astimezone().isoformat(timespec="seconds")
    fields = [
        ("title", json.dumps(child["title"], ensure_ascii=False)),
        ("created", json.dumps(created, ensure_ascii=False)),
        ("priority", priority),
        ("scheduled_time", json.dumps("now")),
        ("recurring", "false"),
        ("parent_task_id", json.dumps(parent_id, ensure_ascii=False)),
        ("subtask_key", json.dumps(key, ensure_ascii=False)),
    ]
    if child.get("provider"):
        fields.append(("provider", json.dumps(child["provider"], ensure_ascii=False)))
    for name in ("object", "scope", "effect"):
        value = read_frontmatter_key(parent_file, name)
        if value:
            fields.append((name, json.dumps(value, ensure_ascii=False)))
    body = "\n# " + child["title"] + "\n\n" + child_object_section(parent_file) + child["body"] + "\n"
    try:
        with solar_state.session() as store:
            child_id = store.task_create(fields, body, status="queued")
            store.task_link(parent_id, child_id, key)
    except solar_state.StateError as exc:
        return None, f"task create failed for {child['title']!r}: {exc}"
    return child_id, None


def create_declared_children(
    task_file: pathlib.Path, task_root: pathlib.Path, task_id: str
) -> Optional[str]:
    """Create every child the manifest still lacks. Returns an error, or None.

    The manifest is written before the first child exists and updated after each
    one, so an interruption is recoverable: a pair that already has an id is
    skipped, an empty one is created.
    """
    plan = read_subtask_plan(task_root, task_id)
    pairs = read_subtask_manifest(task_file)
    if not pairs:
        return "subtask manifest is empty"
    if len(plan) != len(pairs):
        return (
            f"subtask plan has {len(plan)} children but the manifest has {len(pairs)}"
        )

    updated = list(pairs)
    for index, (key, existing_id) in enumerate(pairs):
        if existing_id:
            continue
        already = find_task_by_subtask_key(task_root, key)
        if already is not None:
            updated[index] = (key, read_frontmatter_key(already, "id"))
            write_subtask_manifest(task_file, updated)
            continue
        child_id, error = create_child_task(
            task_root, task_file, task_id, plan[index], key
        )
        if error:
            return error
        updated[index] = (key, child_id or "")
        write_subtask_manifest(task_file, updated)
        print(f"  → subtask created: {key} = {child_id}", flush=True)
    return None


def strip_outcome_heading(text: str) -> str:
    """Drop the `## Result` / `## Error` headings a child's own reply repeats."""
    lines = text.strip().splitlines()
    while lines and (not lines[0].strip() or RE_LEADING_OUTCOME_HEADING.match(lines[0].strip())):
        lines.pop(0)
    return "\n".join(lines).strip()


def read_child_outcome(task_root: pathlib.Path, child_id: str) -> Tuple[str, str]:
    """Return (status, result text) for one child, read from its own log."""
    del task_root
    if not child_id:
        return "missing", "child was never created"
    with solar_state.session() as store:
        task = store.task_get(child_id)
    if task is None:
        return "missing", f"task {child_id} is not in the queue"

    status = task["status"] or "unknown"
    text = ""
    candidates = []
    result_path = read_frontmatter_key(child_id, "result_path")
    if result_path:
        candidates.append(pathlib.Path(result_path))
    if task.get("log_path"):
        candidates.append(pathlib.Path(task["log_path"]))
    for log_path in candidates:
        if not log_path.is_file():
            continue
        try:
            match = RE_LOG_OUTCOME_SECTION.search(log_path.read_text(encoding="utf-8"))
        except OSError:
            match = None
        if match:
            text = strip_outcome_heading(match.group(1))
            break
    if not text:
        match = RE_TASK_ERROR_SECTION.search(task.get("body") or "")
        if match:
            text = strip_outcome_heading(match.group(1))
    if not text:
        text = "no result recorded"
    if len(text) > SUBTASK_RESULT_MAX:
        text = text[:SUBTASK_RESULT_MAX].rstrip() + f"\n\n[truncated at {SUBTASK_RESULT_MAX} characters]"
    return status, text


def record_subtask_results(task_file: pathlib.Path, task_root: pathlib.Path) -> None:
    """Write the children's results into the parent as `## Subtask results`.

    This is what replaces the child writing into the parent's file: a sandboxed
    child cannot reach the queue, so the worker serves the results instead. A
    child that failed appears with its status and its reason; it is never
    dropped, because the parent has to say which part was not covered.
    """
    pairs = read_subtask_manifest(task_file)
    if not pairs:
        return
    blocks = []
    for key, child_id in pairs:
        status, text = read_child_outcome(task_root, child_id)
        blocks.append(f"### {key} — {status}\n\n{text}")
    body = RE_SUBTASK_RESULTS_SECTION.sub("", _body(str(task_file))).rstrip()
    body += "\n\n## Subtask results\n\n" + "\n\n".join(blocks)
    _set_body(str(task_file), body + "\n")


def subtask_pre_phase(
    task_file: pathlib.Path,
    task_root: pathlib.Path,
    task_id: str,
    title: str,
    log_file: pathlib.Path,
) -> str:
    """Decide what this task needs before the provider is called.

    Three states, read from the manifest:
      - no manifest        → nothing to do; the provider may declare children
      - manifest half done → finish creating them and wait. The provider is NOT
                             called: it would re-declare, be ignored as a second
                             batch, and synthesize over children that never were
      - children still running → wait again, without calling the provider
      - manifest complete      → serve the children's results and let it synthesize

    Returns "none", "waiting", "ready" or "error".
    """
    pairs = read_subtask_manifest(task_file)
    if not pairs:
        return "none"
    if any(not child_id for _, child_id in pairs):
        print("  Resuming an interrupted subtask creation ...", flush=True)
        error = create_declared_children(task_file, task_root, task_id)
        if error:
            mark_task_error(
                task_file, task_id, title, None,
                "subtask_create_failed", error, log_file,
            )
            return "error"
        return "waiting"

    # A complete manifest is not a finished batch. Normally `start_next.sh`
    # only reactivates a parent once every child is terminal, but a parent that
    # never got parked — the worker died between the reserved exit code and
    # `await_subtasks.sh` — arrives here still active, with children queued.
    # Synthesizing then would be done over results that do not exist yet.
    pending = []
    for _, child_id in pairs:
        child_file = find_task_file(task_root, child_id)
        # A child whose file is gone can never become terminal; it is reported
        # as missing in the results rather than waited for forever.
        if child_file is None:
            continue
        if read_frontmatter_key(child_file, "status") not in TERMINAL_STATUSES:
            pending.append(child_id)
    if pending:
        print(f"  {len(pending)} subtask(s) still running; waiting.", flush=True)
        return "waiting"

    record_subtask_results(task_file, task_root)
    return "ready"


def handle_declared_subtasks(
    task_file: pathlib.Path,
    task_root: pathlib.Path,
    task_id: str,
    title: str,
    reply_text: str,
    log_file: pathlib.Path,
) -> Optional[int]:
    """Act on a <subtasks> block in a reply. Returns an exit code, or None.

    None means "there was nothing to act on, carry on with the normal ending".
    """
    declared = extract_subtasks(reply_text)
    if declared is None:
        return None

    if read_frontmatter_key(task_file, "parent_task_id"):
        # Depth is one. A child that asks for children is ignored, not failed:
        # its own work is done and its parent is waiting for it.
        print("  Ignoring <subtasks> from a child task: depth is one.", flush=True)
        return None

    if read_subtask_manifest(task_file):
        # Execution 2 carries the same body, so the parent can declare again.
        # Ignoring it is the one exception to visible rejection: sending a
        # synthesizing parent to error/ would throw away its children's work.
        print("  Ignoring a second <subtasks> block: this task already has children.", flush=True)
        return None

    children, error = parse_subtasks(declared)
    if error:
        mark_task_error(
            task_file, task_id, title, None, "subtasks_rejected", error, log_file
        )
        return 1

    record_subtask_plan(task_root, task_id, children)
    write_subtask_manifest(
        task_file,
        [
            (subtask_key(task_id, position, child["title"], child["body"]), "")
            for position, child in enumerate(children, start=1)
        ],
    )
    error = create_declared_children(task_file, task_root, task_id)
    if error:
        mark_task_error(
            task_file, task_id, title, None, "subtask_create_failed", error, log_file
        )
        return 1
    print(f"  Declared {len(children)} subtask(s); waiting for them.", flush=True)
    return SUBTASK_WAITING_EXIT


def mark_task_error(
    task_file: str,
    task_id: str,
    title: str,
    provider_used: Optional[str],
    error_code: Optional[str],
    error_text: str,
    log_file: pathlib.Path,
) -> None:
    """Move the task to error and append the failure to its body, together."""
    del task_file
    err_ts = utc_now()
    suffix = (
        "## Execution Error\n"
        f"- time: {err_ts}\n"
        f"- provider_attempted: {provider_used or 'unknown'}\n"
        f"- error_code: {error_code or 'unknown'}\n"
        f"- error: {error_text}\n"
    )
    with solar_state.session() as store:
        store.task_fail(task_id, suffix)
    write_log(log_file, task_id, title, "error", provider_used, "", error_text, error_code)
    print(f"❌ Task execution failed: {task_id}", flush=True)
    print(f"   Log: {log_file}", flush=True)


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "Usage: execute_active.py <task_id> <router_script>",
            file=sys.stderr,
        )
        return 1

    task_id = sys.argv[1]
    router_script = pathlib.Path(sys.argv[2])
    task_file = task_id
    task_root = pathlib.Path(".")

    if not _status(task_id):
        print(f"Error: task not found: {task_id}", file=sys.stderr)
        return 1
    title = _field(task_id, "title") or task_id
    log_file = _log_file(task_id)

    global _CANCEL_CHECK, _START_HOOK
    _CANCEL_CHECK = lambda: _cancel_requested(task_id)

    def record_pid(pid):
        with solar_state.session() as store:
            store.task_record(task_id, pid=pid)

    _START_HOOK = record_pid
    if _CANCEL_CHECK():
        _acknowledge(task_id)
        return 130

    task_provider = read_frontmatter_key(task_file, "provider").strip().lower() or None
    executor = read_frontmatter_key(task_file, "executor").strip().lower()
    if read_frontmatter_key(task_file, "origin_channel") in ("app", "voice"):
        # Phase 1 preparation worker: read context, return text. No write/shell/MCP tools.
        task_provider = "claude"
        os.environ["SOLAR_ROUTER_CLAUDE_CMD"] = shlex.join([
            'claude', '-p', '--no-session-persistence', '--permission-mode', 'plan',
            '--tools', 'Read,Glob,Grep', '--allowedTools', 'Read,Glob,Grep',
            '--strict-mcp-config', '--mcp-config', json.dumps({'mcpServers': {}}),
            '--settings', json.dumps({'disableAllHooks': True}),
        ])
        if executor == "local":
            raise ValueError("Voice preparation cannot use local executors")

    if executor == "local":
        local_command = read_frontmatter_key(task_file, "local_command").strip()
        if not local_command:
            mark_task_error(
                task_file, task_id, title, "local",
                "local_command_missing", "executor=local requires local_command", log_file
            )
            return 1
        workspace = pathlib.Path(
            os.getenv("SOLAR_WORKSPACE") or task_root.parent.parent.parent
        ).resolve()
        timeout_sec, timeout_err = parse_local_timeout(
            read_frontmatter_key(task_file, "local_timeout")
        )
        if timeout_err:
            mark_task_error(
                task_file, task_id, title, "local",
                timeout_err, f"invalid local_timeout: {read_frontmatter_key(task_file, 'local_timeout')!r}",
                log_file,
            )
            return 1
        argv, auth_err = authorize_local_argv(local_command, workspace)
        if auth_err or not argv:
            mark_task_error(
                task_file, task_id, title, "local",
                auth_err or "local_command_unauthorized",
                f"local_command not authorized under workspace scripts/: {local_command}",
                log_file,
            )
            return 1
        print(f"  Running approved local executor: {local_command}", flush=True)
        try:
            proc = run_managed(
                argv,
                cwd=workspace,
                timeout=timeout_sec,
                cancelled=_CANCEL_CHECK, on_start=_START_HOOK,
            )
        except ProcessCancelled:
            _acknowledge(task_id)
            return 130
        except subprocess.TimeoutExpired:
            mark_task_error(
                task_file, task_id, title, "local",
                "local_timeout", f"local command timed out after {timeout_sec}s", log_file
            )
            return 1
        except Exception as exc:
            mark_task_error(
                task_file, task_id, title, "local",
                "local_exception", str(exc), log_file
            )
            return 1

        output = "\n".join(
            part.strip() for part in (proc.stdout, proc.stderr) if part.strip()
        )
        # 0 = success with work; 10 = success with no changes (caller convention).
        if proc.returncode not in (0, 10):
            mark_task_error(
                task_file, task_id, title, "local",
                f"local_exit_{proc.returncode}",
                output or f"local command exited {proc.returncode}",
                log_file,
            )
            return 1
        result_text = output or "Local command completed with no changes."
        write_log(log_file, task_id, title, "success", "local", result_text, None, None)
        record_result_path(task_file, log_file)
        record_delivery(task_file, result_text)
        print(result_text, flush=True)
        return 0

    if not router_script.exists():
        print(f"Error: router script not found: {router_script}", file=sys.stderr)
        return 1

    # Children first: finish creating them, or serve their results, before this
    # task reaches a provider. start_next.sh is what reactivates a parent and it
    # stays untouched — by the time the executor has the task it is already
    # active, so the wait and the unblock never notice this step.
    phase = subtask_pre_phase(task_file, task_root, task_id, title, log_file)
    if phase == "error":
        return 1
    if phase == "waiting":
        return SUBTASK_WAITING_EXIT

    # Build prompt
    body = strip_frontmatter(task_file)
    prompt = build_prompt(task_id, title, body)

    # Call router
    print(f"  Calling router (channel=async-task, mode=direct_only, provider={task_provider or 'priority'}) ...", flush=True)
    try:
        response = call_router(router_script, task_id, prompt, task_provider)
    except ProcessCancelled:
        _acknowledge(task_id)
        return 130
    except subprocess.TimeoutExpired:
        mark_task_error(
            task_file, task_id, title, task_provider,
            "router_timeout", "router call timed out", log_file
        )
        return 1
    except Exception as exc:
        mark_task_error(
            task_file, task_id, title, task_provider,
            "router_exception", str(exc), log_file
        )
        return 1

    provider_used = response.get("provider_used") or task_provider
    status = response.get("status", "failed")
    reply_text = response.get("reply_text", "")
    error_code = response.get("error_code")
    error_text = response.get("error")

    if status != "success" or not reply_text:
        error_msg = error_text or f"router returned status={status}"
        mark_task_error(
            task_file, task_id, title, provider_used,
            error_code or "router_failed", error_msg, log_file
        )
        return 1

    # Success: write log
    write_log(log_file, task_id, title, "success", provider_used, reply_text, None, None)
    record_result_path(task_file, log_file)

    # A declared batch ends execution 1 here. No delivery is expected yet, and
    # record_delivery would mark this task as missing one.
    subtask_exit = handle_declared_subtasks(
        task_file, task_root, task_id, title, reply_text, log_file
    )
    if subtask_exit is not None:
        print(f"  → provider_used: {provider_used}", flush=True)
        return subtask_exit

    record_delivery(task_file, reply_text)
    print(f"  → provider_used: {provider_used}", flush=True)
    # Output reply_text to stdout for execute_active.sh to capture if needed
    print(reply_text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
