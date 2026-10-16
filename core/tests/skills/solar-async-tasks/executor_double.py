#!/usr/bin/env python3
"""A simulated executor, started by a supervisor exactly like `execute_active.sh --task --token`.

It never calls a provider. Its behaviour comes from `$DOUBLE_DIR/spec/<task>.json` so a test decides
what each task does, and everything it does is written to `$DOUBLE_DIR/events.jsonl`, one line per
event with a wall-clock time, so a test proves overlap from start/end events and not from the
`active` status of the console.

Spec keys (all optional):
  barrier {name, parties, timeout}  wait until `parties` executors of that barrier have started
  gate <name>                       wait until the test creates $DOUBLE_DIR/gates/<name>
  hold <seconds>                    sleep after the barrier/gate, before finishing
  outcome  complete (default) | crash_before_attach | hang_before_attach | crash_after_attach | hang
  straggler true                    leave a child in this process group that outlives the executor
  heartbeat true                    renew the lease every 0.3 s while running
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

CORE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CORE / "skills" / "solar-state" / "scripts"))

import solar_state  # noqa: E402
sys.path.insert(0, str(CORE / "skills" / "solar-async-tasks" / "scripts"))
import supervisor_lib as lib  # noqa: E402

BASE = Path(os.environ["DOUBLE_DIR"])


def event(task: str, name: str, **extra) -> None:
    line = json.dumps({"task": task, "event": name, "t": time.time(), "pid": os.getpid(), **extra})
    fd = os.open(BASE / "events.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (line + "\n").encode())
    finally:
        os.close(fd)


def started_in(barrier: str) -> int:
    folder = BASE / "barriers" / barrier
    return len(list(folder.glob("*"))) if folder.is_dir() else 0


def main(argv: list[str]) -> int:
    task = argv[argv.index("--task") + 1]
    token = argv[argv.index("--token") + 1]
    spec_file = BASE / "spec" / f"{task}.json"
    spec = json.loads(spec_file.read_text()) if spec_file.is_file() else {}
    outcome = spec.get("outcome", "complete")
    event(task, "launched")
    pids = BASE / "pids"
    pids.mkdir(exist_ok=True)
    (pids / task).write_text(json.dumps({"pid": os.getpid(), "started": lib.process_start(os.getpid())}))
    if outcome == "crash_before_attach":
        return 9
    if outcome == "hang_before_attach":
        event(task, "hang_before_attach")
        time.sleep(3600)
        return 0
    with solar_state.session() as store:
        store.reservation_attach(task, token)
    if spec.get("heartbeat"):
        def beat() -> None:
            while True:
                time.sleep(0.3)
                try:
                    with solar_state.session() as store:
                        store.reservation_heartbeat(task, token)
                except solar_state.StateError:
                    return
        threading.Thread(target=beat, daemon=True).start()
    if spec.get("straggler"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
        (BASE / f"straggler-{task}.pid").write_text(str(child.pid))
    event(task, "start")
    barrier = spec.get("barrier")
    if barrier:
        folder = BASE / "barriers" / barrier["name"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / task).write_text("1")
        deadline = time.time() + float(barrier.get("timeout", 30))
        while started_in(barrier["name"]) < int(barrier["parties"]):
            if time.time() > deadline:
                event(task, "barrier_timeout")
                return 3
            time.sleep(0.02)
    gate = spec.get("gate")
    if gate:
        path = BASE / "gates" / gate
        while not path.exists():
            time.sleep(0.02)
    if outcome == "crash_after_attach":
        event(task, "crash")
        return 7
    if outcome == "hang":
        event(task, "hang")
        time.sleep(3600)
        return 0
    if spec.get("hold"):
        time.sleep(float(spec["hold"]))
    event(task, "end")
    with solar_state.session() as store:
        if store.cancellation_requested(task) and spec.get("respect_cancel"):
            store.task_complete(task, cancelled=True, token=token)
        else:
            store.task_complete(task, token=token)
    event(task, "completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
