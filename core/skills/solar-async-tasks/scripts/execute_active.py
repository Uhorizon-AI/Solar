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
    python3 execute_active.py <task_file> <router_script> <task_id> <title>
"""
import hashlib
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "solar-router/scripts"))
from managed_process import run_managed, ProcessCancelled
from task_cancel import requested, acknowledge

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


def read_frontmatter_key(task_file: pathlib.Path, key: str) -> str:
    """Extract a single frontmatter key value from a markdown file."""
    in_fm = False
    for line in task_file.read_text(encoding="utf-8").splitlines():
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            else:
                break
        if in_fm and line.startswith(f"{key}:"):
            value = line[len(f"{key}:"):].strip().strip('"')
            return value
    return ""


def strip_frontmatter(task_file: pathlib.Path) -> str:
    """Return task body with frontmatter removed."""
    lines = task_file.read_text(encoding="utf-8").splitlines()
    in_fm = False
    fm_done = False
    body_lines = []
    for line in lines:
        if not fm_done:
            if line.strip() == "---":
                if not in_fm:
                    in_fm = True
                    continue
                else:
                    fm_done = True
                    continue
            elif not in_fm:
                fm_done = True
                body_lines.append(line)
        else:
            body_lines.append(line)
    return "\n".join(body_lines).strip()


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


def record_result_path(task_file: pathlib.Path, log_file: pathlib.Path) -> None:
    """Point the task at the file that holds its result: the execution log.

    The result is written to the log, not to the task (a provider sandbox may
    not be able to write into the task queue). Without this, the completion
    notify falls back to the task file itself, which has no result. An explicit
    result_url/result_path set by the task author always wins.
    """
    try:
        content = task_file.read_text(encoding="utf-8")
    except OSError:
        return
    if not content.startswith("---\n"):
        return
    end = content.find("\n---", 4)
    if end == -1:
        return
    frontmatter = content[4:end]
    if re.search(r"^result_(path|url):", frontmatter, flags=re.MULTILINE):
        return
    # Absolute and resolved: this string is what the notification sends out.
    line = f'result_path: "{log_file.resolve()}"'
    frontmatter = frontmatter.rstrip("\n") + "\n" + line
    try:
        task_file.write_text("---\n" + frontmatter + content[end:], encoding="utf-8")
    except OSError:
        return


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


def upsert_frontmatter_key(task_file: pathlib.Path, key: str, value: str) -> None:
    """Set a frontmatter key, replacing it when already present."""
    try:
        content = task_file.read_text(encoding="utf-8")
    except OSError:
        return
    if not content.startswith("---\n"):
        return
    end = content.find("\n---", 4)
    if end == -1:
        return
    frontmatter = content[4:end]
    line = f"{key}: {value}"
    pattern = re.compile(rf"^{re.escape(key)}:.*$", flags=re.MULTILINE)
    if pattern.search(frontmatter):
        frontmatter = pattern.sub(line, frontmatter, count=1)
    else:
        frontmatter = frontmatter.rstrip("\n") + "\n" + line
    try:
        task_file.write_text("---\n" + frontmatter + content[end:], encoding="utf-8")
    except OSError:
        return


def set_frontmatter_flag(task_file: pathlib.Path, key: str, value: bool) -> None:
    """Set a boolean frontmatter flag, removing it when false.

    Removing matters as much as setting: these flags describe the run that just
    finished, and one inherited from an earlier run would be read as current.
    """
    if value:
        upsert_frontmatter_key(task_file, key, "true")
        return
    try:
        content = task_file.read_text(encoding="utf-8")
    except OSError:
        return
    if not content.startswith("---\n"):
        return
    end = content.find("\n---", 4)
    if end == -1:
        return
    frontmatter = content[4:end]
    stripped = re.sub(
        rf"^{re.escape(key)}:.*\n?", "", frontmatter, flags=re.MULTILINE
    )
    if stripped == frontmatter:
        return
    try:
        task_file.write_text("---\n" + stripped + content[end:], encoding="utf-8")
    except OSError:
        return


def record_delivery(task_file: pathlib.Path, reply_text: str) -> None:
    """Copy the reply's delivery block into the task as `## Delivery`.

    The worker does this, not the provider: the provider can write here but only
    does so when it obeys an instruction, and the notification depends on the
    section being there. `## Result` is left alone — it is the provider's own
    account, unbounded, and sending it would be transport, not compression.
    A task that was asked for a delivery and returned none is marked, so the
    notification can say so instead of announcing the work as resolved.
    """
    expected = read_frontmatter_key(task_file, "delivery_expected") == "true"
    delivery = extract_delivery(reply_text)
    if delivery:
        delivery, truncated = clamp_delivery(delivery)
    else:
        truncated = False

    # Every run starts from a clean slate: a parent executes twice by design
    # (create children, then synthesize) and can be requeued from error, so a
    # section or a flag left by the previous run would be notified as if it
    # described this one.
    try:
        content = task_file.read_text(encoding="utf-8")
    except OSError:
        return
    body = RE_DELIVERY_SECTION.sub("", content).rstrip()
    if delivery:
        body += "\n\n## Delivery\n\n" + delivery
    try:
        task_file.write_text(body + "\n", encoding="utf-8")
    except OSError:
        return

    set_frontmatter_flag(task_file, "delivery_truncated", truncated)
    set_frontmatter_flag(task_file, "delivery_missing", expected and not delivery)


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


def subtask_plan_path(task_root: pathlib.Path, task_id: str) -> pathlib.Path:
    return task_root / "subtasks" / f"{task_id}.json"


def record_subtask_plan(
    task_root: pathlib.Path, task_id: str, children: List[Dict[str, Any]]
) -> None:
    """Persist the declaration itself, beside the queue.

    The manifest holds keys, not payloads, so a crash halfway through creation
    would leave the worker knowing that a child is missing but not what it was.
    It lives outside the task file on purpose: the task body is the prompt the
    provider gets in execution 2, and five child bodies in it would drown the
    synthesis.
    """
    path = subtask_plan_path(task_root, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(children, ensure_ascii=False, indent=2), encoding="utf-8")


def read_subtask_plan(task_root: pathlib.Path, task_id: str) -> List[Dict[str, Any]]:
    path = subtask_plan_path(task_root, task_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


_TASK_DIRS = (
    "queued", "active", "completed", "error", "archive", "cancelled", "drafts", "planned",
)


def find_task_file(task_root: pathlib.Path, task_id: str) -> Optional[pathlib.Path]:
    """Locate a task by id across every state directory."""
    for name in _TASK_DIRS:
        directory = task_root / name
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.glob("*.md")):
            try:
                if read_frontmatter_key(candidate, "id") == task_id:
                    return candidate
            except OSError:
                continue
    return None


def find_task_by_subtask_key(task_root: pathlib.Path, key: str) -> Optional[pathlib.Path]:
    """Locate a child by its stable key.

    Closes the narrow window between create.sh returning and the manifest being
    updated: on retry the child exists but the parent does not know its id yet.
    find_task cannot do this — it searches by id, not by key.
    """
    for name in _TASK_DIRS:
        directory = task_root / name
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.glob("*.md")):
            try:
                if read_frontmatter_key(candidate, "subtask_key") == key:
                    return candidate
            except OSError:
                continue
    return None


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
    parent_file: pathlib.Path,
    parent_id: str,
    child: Dict[str, Any],
    key: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Create one child with create.sh. Returns (task_id, error).

    The provider only chose title, body and provider. Everything else is the
    worker's: the object travels down from the parent unchanged, and the child
    gets no origin metadata — so create.sh writes no notify_when and only the
    parent ever speaks to the chat.
    """
    scripts_dir = pathlib.Path(__file__).resolve().parent
    create_script = scripts_dir / "create.sh"
    if not create_script.is_file():
        return None, f"create.sh not found: {create_script}"

    metadata = {}
    for field in ("object", "scope", "effect"):
        value = read_frontmatter_key(parent_file, field)
        if value:
            metadata[field] = value
    priority = read_frontmatter_key(parent_file, "priority") or "normal"

    body_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(child_object_section(parent_file) + child["body"] + "\n")
            body_file = pathlib.Path(handle.name)

        cmd = [
            "bash", str(create_script), "--queued",
            "--priority", priority,
            "--body-file", str(body_file),
            # Identity goes in with the file. create.sh publishes into queued/
            # atomically and the worker can pick the child up at once, so a key
            # written afterwards leaves a window where the child exists, runs,
            # and cannot be matched back to its parent on a retry.
            "--parent-task-id", parent_id,
            "--subtask-key", key,
        ]
        if child.get("provider"):
            cmd += ["--provider", child["provider"]]
        if metadata:
            cmd += ["--metadata", json.dumps(metadata, ensure_ascii=False)]
        cmd += [child["title"]]

        env = os.environ.copy()
        env["SOLAR_TASK_ROOT"] = str(task_root)
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, env=env, timeout=120
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return None, f"create.sh failed for {child['title']!r}: {exc}"
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            return None, f"create.sh exited {proc.returncode} for {child['title']!r}: {detail}"

        child_id = ""
        for line in (proc.stdout or "").splitlines():
            if line.startswith("ID: "):
                child_id = line[4:].strip()
        if not child_id:
            return None, f"create.sh printed no id for {child['title']!r}"
    finally:
        if body_file is not None:
            try:
                body_file.unlink()
            except OSError:
                pass

    if find_task_file(task_root, child_id) is None:
        return None, f"child {child_id} was created but cannot be found in the queue"
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


def read_child_outcome(task_root: pathlib.Path, child_id: str) -> Tuple[str, str]:
    """Return (status, result text) for one child, read from its own log."""
    if not child_id:
        return "missing", "child was never created"
    child_file = find_task_file(task_root, child_id)
    if child_file is None:
        return "missing", f"task {child_id} is not in the queue"

    status = read_frontmatter_key(child_file, "status") or "unknown"
    text = ""
    # result_path is written on success only: it is what the completion notify
    # points at, and a failed task must not advertise a result. A failed child
    # still has its log, under the name it was written with.
    candidates = []
    result_path = read_frontmatter_key(child_file, "result_path")
    if result_path:
        candidates.append(pathlib.Path(result_path))
    candidates.append(task_root / "logs" / (child_file.stem + ".log"))
    for log_path in candidates:
        if not log_path.is_file():
            continue
        try:
            match = RE_LOG_OUTCOME_SECTION.search(log_path.read_text(encoding="utf-8"))
        except OSError:
            match = None
        if match:
            text = match.group(1).strip()
            break
    if not text:
        # Nothing in the log: the task file carries its own account.
        try:
            match = RE_TASK_ERROR_SECTION.search(child_file.read_text(encoding="utf-8"))
        except OSError:
            match = None
        if match:
            text = match.group(1).strip()
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
    try:
        content = task_file.read_text(encoding="utf-8")
    except OSError:
        return
    body = RE_SUBTASK_RESULTS_SECTION.sub("", content).rstrip()
    body += "\n\n## Subtask results\n\n" + "\n\n".join(blocks)
    try:
        task_file.write_text(body + "\n", encoding="utf-8")
    except OSError:
        return


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
      - manifest complete  → serve the children's results and let it synthesize

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
    task_file: pathlib.Path,
    task_id: str,
    title: str,
    provider_used: Optional[str],
    error_code: Optional[str],
    error_text: str,
    log_file: pathlib.Path,
) -> None:
    """Update task frontmatter status to error and move to error/ dir."""
    content = task_file.read_text(encoding="utf-8")
    content = re.sub(r"^status:.*$", "status: error", content, flags=re.MULTILINE)
    err_ts = utc_now()
    content += (
        f"\n\n## Execution Error\n"
        f"- time: {err_ts}\n"
        f"- provider_attempted: {provider_used or 'unknown'}\n"
        f"- error_code: {error_code or 'unknown'}\n"
        f"- error: {error_text}\n"
    )
    task_file.write_text(content, encoding="utf-8")

    write_log(log_file, task_id, title, "error", provider_used, "", error_text, error_code)

    error_dir = task_file.parent.parent / "error"
    error_dir.mkdir(parents=True, exist_ok=True)
    dest = error_dir / task_file.name
    task_file.rename(dest)
    print(f"❌ Task execution failed and moved to error/: {task_id}", flush=True)
    print(f"   Log: {log_file}", flush=True)


def main() -> int:
    if len(sys.argv) < 5:
        print(
            "Usage: execute_active.py <task_file> <router_script> <task_id> <title>",
            file=sys.stderr,
        )
        return 1

    task_file = pathlib.Path(sys.argv[1])
    router_script = pathlib.Path(sys.argv[2])
    task_id = sys.argv[3]
    title = sys.argv[4]

    if not task_file.exists():
        print(f"Error: task file not found: {task_file}", file=sys.stderr)
        return 1

    # Derive log path
    task_root = task_file.parent.parent
    log_dir = task_root / "logs"
    log_file = log_dir / (task_file.stem + ".log")

    # Read per-task provider override from frontmatter
    global _CANCEL_CHECK, _START_HOOK
    _CANCEL_CHECK = lambda: requested(task_root, task_id)
    def record_pid(pid):
        handles = task_root / "handles"
        handles.mkdir(exist_ok=True)
        (handles / (task_id + ".json")).write_text(json.dumps({"pid": pid, "task_id": task_id}))
    _START_HOOK = record_pid
    if _CANCEL_CHECK():
        acknowledge(task_file)
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
            acknowledge(task_file)
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
        acknowledge(task_file)
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
