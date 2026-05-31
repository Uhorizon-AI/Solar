#!/usr/bin/env python3
"""Solar App voice CLI (part of solar-host skill). Local-first when whisper available."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import host_registry as reg
except ImportError:
    reg = None  # type: ignore


def _workspace() -> str:
    if reg:
        active = reg.get_active_path()
        if active:
            return active
    return os.environ.get("SOLAR_WORKSPACE", os.getcwd())


def _voice_runtime() -> Path:
    d = Path(_workspace()) / "sun/runtime/host/voice"
    d.mkdir(parents=True, exist_ok=True)
    return d


def transcribe(audio: Path) -> str:
    if shutil.which("whisper"):
        proc = subprocess.run(
            ["whisper", str(audio), "--language", "es", "--output_format", "txt"],
            capture_output=True,
            text=True,
            check=False,
        )
        txt_files = list(audio.parent.glob(f"{audio.stem}*.txt"))
        if txt_files:
            return txt_files[0].read_text(encoding="utf-8").strip()
        if proc.stdout:
            return proc.stdout.strip()
    return "[voice] Install whisper CLI for transcription. Audio saved at: " + str(audio)


def cleanup_text(text: str) -> str:
    return " ".join(text.split())


def _host_base() -> str:
    return os.environ.get("SOLAR_HOST_BASE_URL", "http://127.0.0.1:9000")


def _host_post(path: str, body: dict) -> str:
    url = _host_base().rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


def run_command(utterance: str) -> int:
    low = utterance.lower().strip()
    if "status" in low or "estado" in low:
        with urllib.request.urlopen(_host_base() + "/api/status", timeout=15) as resp:
            print(resp.read().decode())
        return 0
    if "aprobar" in low or "approve" in low:
        with urllib.request.urlopen(_host_base() + "/api/approvals", timeout=15) as resp:
            data = json.loads(resp.read().decode())
        pending = [
            a for a in data.get("approvals", [])
            if isinstance(a, dict) and a.get("status") == "pending"
        ]
        if not pending:
            print("No pending approvals.")
            return 0
        aid = pending[0].get("approval_id")
        print(_host_post(f"/api/approvals/{aid}/approve", {}))
        return 0
    if "cambiar" in low or "switch" in low or "workspace" in low:
        if reg:
            for ws in reg.list_workspaces():
                name = (ws.get("label") or "").lower()
                if name and name in low:
                    reg.set_active(ws["path"])
                    print(f"OK: active {ws['path']}")
                    return 0
        print("Say workspace name after 'switch'.")
        return 1
    print(f"Unknown command intent: {utterance}")
    return 1


def cmd_once(paste: bool) -> int:
    text = ""
    if not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        tmp = _voice_runtime() / "capture.wav"
        if shutil.which("rec"):
            subprocess.run(["rec", "-r", "16000", "-c", "1", str(tmp)], check=False)
            text = transcribe(tmp)
            tmp.unlink(missing_ok=True)
        else:
            text = input("Speak/type text: ")
    text = cleanup_text(text)
    subprocess.run(["pbcopy"], input=text.encode(), check=False)
    print(text)
    if paste and shutil.which("osascript"):
        subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'],
            check=False,
        )
    return 0


def cmd_read(mode: str) -> int:
    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    if not raw and len(sys.argv) > 2:
        raw = Path(sys.argv[2]).read_text(encoding="utf-8")
    if mode == "brief":
        lines = raw.strip().splitlines()[:12]
        summary = "\n".join(lines)
        print(f"Brief read ({len(lines)} lines):\n{summary}")
    else:
        print(raw[:4000])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="solar voice")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    sub.add_parser("paste")
    sub.add_parser("command")
    p_read = sub.add_parser("read")
    p_read.add_argument("--mode", default="brief")
    args, rest = parser.parse_known_args()
    if args.cmd == "once":
        return cmd_once(paste=False)
    if args.cmd == "paste":
        return cmd_once(paste=True)
    if args.cmd == "command":
        utterance = " ".join(rest) or input("Command: ")
        return run_command(utterance)
    if args.cmd == "read":
        return cmd_read(args.mode)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
