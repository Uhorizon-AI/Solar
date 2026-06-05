#!/usr/bin/env python3
"""Solar App voice CLI (part of solar-app skill). Local-first when whisper available."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import voice_core as vc  # noqa: E402


def _utterance_from_args(rest: list[str], prompt: str) -> str:
    text = " ".join(rest).strip()
    if text:
        return text
    env = os.environ.get("SOLAR_VOICE_TEXT", "").strip()
    if env:
        return env
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return input(prompt)


def cmd_once(paste: bool) -> int:
    if os.environ.get("SOLAR_VOICE_TEXT", "").strip():
        text = vc.capture_utterance()
    else:
        ok, msg = vc.check_voice_deps()
        if not ok:
            print(f"ERROR: {msg}", file=sys.stderr)
            print(vc.voice_deps_hint(), file=sys.stderr)
            return 1
        text = vc.capture_utterance()
    if not text.strip():
        print("Sin texto (grabación vacía o cancelada).", file=sys.stderr)
        return 1
    vc.copy_to_clipboard(text)
    print(text)
    if paste:
        vc.paste_via_osascript()
    return 0


def cmd_command(utterance: str) -> int:
    code, out = vc.run_intent(utterance)
    print(out)
    return code


def cmd_ask(utterance: str) -> int:
    on_chunk = None
    if os.environ.get("SOLAR_VOICE_TTS", "").strip().lower() == "stream":
        try:
            from host_platform.macos.voice_tts import streaming_speaker  # noqa: PLC0415

            on_chunk = streaming_speaker().feed
        except Exception:  # noqa: BLE001
            pass
    code, out = vc.run_intent(utterance, on_chunk=on_chunk, speak=True)
    print(out)
    return code


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
    parser = argparse.ArgumentParser(
        prog="solar app voice",
        description="Dictado y comandos de voz contra Solar Host.",
        epilog=(
            "Producto Wispr: Solar.app (barra de menú). doctor: deps + voice.json. "
            "CLI once/paste: solo debug. Atajo global: bug conocido — usa menú Voice en Solar.app."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    sub.add_parser("paste")
    sub.add_parser("command")
    sub.add_parser("ask")
    sub.add_parser("doctor", help="check voice deps and install missing (like solar client doctor)")
    sub.add_parser("check", help=argparse.SUPPRESS)  # deprecated alias
    p_read = sub.add_parser("read")
    p_read.add_argument("--mode", default="brief")
    args, rest = parser.parse_known_args()
    if args.cmd in ("doctor", "check"):
        import subprocess

        if args.cmd == "check":
            print("NOTE: solar app voice check → use: solar app voice doctor", file=sys.stderr)
        script = _SCRIPT_DIR / "voice_doctor.sh"
        return subprocess.call(["bash", str(script), *rest])

    if args.cmd == "once":
        print(
            "Tip: en Solar.app solo Voice → Push to talk (paste) → Detener grabación.",
            file=sys.stderr,
        )
        return cmd_once(paste=False)
    if args.cmd == "paste":
        print(
            "Tip: en Solar.app solo Voice → Push to talk (paste) → Detener grabación.",
            file=sys.stderr,
        )
        return cmd_once(paste=True)
    if args.cmd == "command":
        return cmd_command(_utterance_from_args(rest, "Command: "))
    if args.cmd == "ask":
        return cmd_ask(_utterance_from_args(rest, "Ask: "))
    if args.cmd == "read":
        return cmd_read(args.mode)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
