#!/usr/bin/env python3
"""Shared voice logic for Solar App CLI and macOS tray (Wispr-like flows)."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import host_registry as reg
except ImportError:
    reg = None  # type: ignore

IntentName = str
OnChunkFn = Callable[[str], None]


def host_base_url() -> str:
    base = os.environ.get("SOLAR_HOST_BASE_URL", "").strip().rstrip("/")
    if base:
        return base
    host = os.environ.get("SOLAR_HOST_HOST", "127.0.0.1")
    port = os.environ.get("SOLAR_HOST_PORT", "9000")
    return f"http://{host}:{port}"


def active_workspace() -> str:
    if reg:
        active = reg.get_active_path()
        if active:
            return active
    return os.environ.get("SOLAR_WORKSPACE", os.getcwd())


def voice_runtime_dir(workspace: Optional[str] = None) -> Path:
    ws = workspace or active_workspace()
    d = Path(ws) / "sun/runtime/host/voice"
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_path(workspace: Optional[str] = None) -> Path:
    return voice_runtime_dir(workspace) / "session.json"


def load_session(workspace: Optional[str] = None) -> Dict[str, Any]:
    path = session_path(workspace)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_session(data: Dict[str, Any], workspace: Optional[str] = None) -> None:
    path = session_path(workspace)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def cleanup_text(text: str) -> str:
    return " ".join(text.split())


def check_voice_deps(*, require_whisper: bool = False) -> Tuple[bool, str]:
    missing: List[str] = []
    if not _resolve_rec():
        missing.append("SoX (brew install sox) — provides the rec command")
    if require_whisper:
        try:
            import voice_config as vcfg  # noqa: PLC0415

            if not vcfg.whisper_argv(Path("/dev/null")):
                missing.append("whisper (solar voice doctor)")
        except ImportError:
            if not shutil.which("whisper"):
                missing.append("whisper CLI (solar voice doctor)")
    if missing:
        return False, "; ".join(missing)
    return True, ""


def voice_deps_hint() -> str:
    lines = [
        "Voice dictation needs SoX:",
        "  brew install sox",
        "Optional local transcription:",
        "  pip install openai-whisper  # or your whisper CLI",
        "Run: solar voice doctor",
    ]
    return "\n".join(lines)


def _stop_rec(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=8)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


def _resolve_rec() -> Optional[str]:
    try:
        import voice_config as vcfg  # noqa: PLC0415

        return vcfg.resolve_rec()
    except ImportError:
        return shutil.which("rec")


def record_audio_to(path: Path) -> bool:
    """Record from default mic until interactive stop (Enter) or max seconds."""
    rec = _resolve_rec()
    if not rec:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import voice_config as vcfg  # noqa: PLC0415

        vcfg.prepare_capture(path)
        cmd = vcfg.rec_argv(path)
        env = vcfg.subprocess_env()
    except ImportError:
        cmd = [rec, "-q", "-c", "1", str(path)]
        env = None
    if not cmd:
        return False
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        if sys.stdin.isatty():
            print(
                "Grabando… habla ahora. Pulsa Enter para terminar (Ctrl+C cancela).",
                file=sys.stderr,
            )
            try:
                input()
            except KeyboardInterrupt:
                print("\nCancelado.", file=sys.stderr)
                _stop_rec(proc)
                return False
        else:
            max_sec = int(os.environ.get("SOLAR_VOICE_MAX_SECONDS", "30"))
            print(f"Grabando hasta {max_sec}s…", file=sys.stderr)
            try:
                proc.wait(timeout=max_sec)
            except subprocess.TimeoutExpired:
                pass
        _stop_rec(proc)
        return path.is_file() and path.stat().st_size > 0
    except Exception:
        _stop_rec(proc)
        raise


def transcribe(audio: Path, *, language: str = "es", _retry: bool = False) -> str:
    """Transcribe WAV; uses voice.json paths (Solar.app-safe)."""
    try:
        import voice_config as vcfg  # noqa: PLC0415
    except ImportError:
        vcfg = None  # type: ignore

    if not audio.is_file() or audio.stat().st_size == 0:
        return ""

    source_audio = audio
    source_amp: Optional[float] = None
    if vcfg is not None:
        source_amp = vcfg.wav_max_amplitude(source_audio)
        vcfg.voice_log(f"pre-transcribe amp={source_amp} file={source_audio.name}")
        if source_amp is not None and source_amp < 0.02:
            try:
                import voice_mic as vm  # noqa: PLC0415

                _, mic_ok = vm.microphone_status()
                mic_hint = (
                    vm.microphone_hint_for_denied()
                    if not mic_ok
                    else "Ajustes → Sonido → Entrada: elige el micrófono correcto."
                )
            except ImportError:
                mic_hint = (
                    "Privacidad → Micrófono: activa Solar; "
                    "Ajustes → Sonido → Entrada: micrófono correcto."
                )
            return (
                "[voice] Micrófono sin señal (audio casi silencio). "
                f"{mic_hint} max_amp={source_amp:.4f}"
            )
        audio = vcfg.normalize_wav_for_stt(source_audio)

    argv: Optional[List[str]] = None
    if vcfg is not None:
        argv = vcfg.whisper_argv(audio, language=language)
    elif shutil.which("whisper"):
        argv = ["whisper", str(audio), "--language", language, "--output_format", "txt"]

    if not argv and vcfg is not None and not _retry:
        if vcfg.ensure_whisper_in_voice_uv():
            return transcribe(audio, language=language, _retry=True)

    if argv:
        env = vcfg.subprocess_env() if vcfg else None
        if vcfg:
            vcfg.voice_log(f"transcribe start {audio} argv0={argv[0]}")
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
            cwd=str(audio.parent.resolve()),
            timeout=int(os.environ.get("SOLAR_VOICE_WHISPER_TIMEOUT", "300")),
        )
        if vcfg:
            err_snip = (proc.stderr or proc.stdout or "").strip()
            vcfg.voice_log(
                f"transcribe done code={proc.returncode} stderr={err_snip[:400]!r}"
            )
        if proc.returncode != 0:
            if vcfg:
                vcfg.cleanup_transcript_artifacts(audio)
            if vcfg and not _retry and vcfg.ensure_whisper_in_voice_uv():
                vcfg.voice_log("transcribe retry via voice-uv after brew/cli failure")
                return transcribe(source_audio, language=language, _retry=True)
            err = (proc.stderr or proc.stdout or "").strip()
            if err:
                return (
                    "[voice] Transcripción falló. Ejecuta: solar voice doctor. "
                    f"Detalle: {err[:220]}"
                )
            return f"[voice] Transcription failed (exit {proc.returncode})"
        if vcfg:
            text = vcfg.read_transcript_for_audio(audio)
            if text:
                if vcfg.is_likely_hallucination(text) and (
                    source_amp is None or source_amp < 0.08
                ):
                    if vcfg:
                        vcfg.cleanup_transcript_artifacts(audio)
                    return (
                        "[voice] Whisper no oyó tu voz (frase genérica de YouTube). "
                        "Prueba otro micrófono en Ajustes → Sonido → Entrada, o "
                        "SOLAR_VOICE_MIC_DEVICE=\"nombre del mic\"."
                    )
                return text
        txt_files = sorted(audio.parent.glob(f"{audio.stem}*.txt"))
        if txt_files:
            return txt_files[-1].read_text(encoding="utf-8").strip()
    return f"[voice] No whisper — run: solar voice doctor. Audio: {audio}"


def capture_utterance(
    *,
    audio_path: Optional[Path] = None,
    use_rec: bool = True,
) -> str:
    env_text = os.environ.get("SOLAR_VOICE_TEXT", "").strip()
    if env_text:
        return cleanup_text(env_text)
    if not sys.stdin.isatty():
        return cleanup_text(sys.stdin.read())
    if use_rec and _resolve_rec():
        tmp = audio_path or (voice_runtime_dir() / "capture.wav")
        if not record_audio_to(tmp):
            return ""
        text = transcribe(tmp)
        if audio_path is None:
            tmp.unlink(missing_ok=True)
        return cleanup_text(text)
    if sys.stdin.isatty():
        print(voice_deps_hint(), file=sys.stderr)
    return cleanup_text(input("Sin mic (SoX): escribe el texto: "))


class VoiceHostClient:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base = (base_url or host_base_url()).rstrip("/")

    def _url(self, path: str) -> str:
        return self.base + path

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: Optional[Dict[str, Any]] = None,
        timeout: float = 15,
    ) -> Tuple[int, str]:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self._url(path), data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return 0, str(exc)

    def ensure_host(self) -> Tuple[bool, str]:
        code, _ = self._request("/health", timeout=4)
        if code == 200:
            return True, ""
        if self.start_host():
            code, _ = self._request("/health", timeout=4)
            if code == 200:
                return True, ""
        return (
            False,
            f"Solar App not reachable at {self.base}. Start with: solar app start (or solar app start)",
        )

    def _start_host_script(self) -> Optional[Path]:
        candidates = [
            _SCRIPT_DIR / "start_host.sh",
            Path(active_workspace()) / "solar/core/skills/solar-app/scripts/start_host.sh",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def start_host(self) -> bool:
        script = self._start_host_script()
        if not script:
            return False
        env = os.environ.copy()
        env.setdefault("SOLAR_WORKSPACE", active_workspace())
        try:
            proc = subprocess.run(
                ["bash", str(script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                env=env,
                timeout=12,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        try:
            import voice_config as vcfg  # noqa: PLC0415

            out = ((proc.stdout or "") + (proc.stderr or "")).strip()
            vcfg.voice_log(
                f"ask start_host code={proc.returncode} script={script} out={out[:300]!r}"
            )
        except Exception:  # noqa: BLE001
            pass
        if proc.returncode != 0:
            return False
        for _ in range(20):
            code, _ = self._request("/health", timeout=1)
            if code == 200:
                return True
            time.sleep(0.2)
        return False

    def chat(self, text: str) -> Tuple[int, str]:
        code, raw = self._request(
            "/api/chat",
            method="POST",
            body={"message": text},
            timeout=120,
        )
        if code != 200:
            return code or 1, raw or f"Host chat failed ({code})"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return 1, raw
        reply = data.get("reply_text") if isinstance(data, dict) else ""
        return 0, str(reply or "(empty response)")

    def create_thread(self, title: str = "voice") -> Optional[str]:
        code, raw = self._request(
            "/threads",
            method="POST",
            body={"title": title, "scope_layer": "sun"},
        )
        if code not in (200, 201):
            return None
        try:
            data = json.loads(raw)
            thread = data.get("thread") if isinstance(data, dict) else None
            if isinstance(thread, dict):
                tid = thread.get("thread_id")
                return str(tid) if tid else None
        except json.JSONDecodeError:
            return None
        return None

    def get_or_create_thread_id(self, workspace: Optional[str] = None) -> Optional[str]:
        ws = workspace or active_workspace()
        sess = load_session(ws)
        tid = sess.get("thread_id")
        if isinstance(tid, str) and tid.strip():
            return tid.strip()
        new_id = self.create_thread("voice session")
        if not new_id:
            return None
        save_session({"thread_id": new_id}, ws)
        return new_id

    def status_json(self) -> str:
        _, raw = self._request("/api/status")
        return raw

    def list_pending_approvals(self) -> List[Dict[str, Any]]:
        _, raw = self._request("/api/approvals")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        approvals = data.get("approvals", []) if isinstance(data, dict) else []
        return [
            a
            for a in approvals
            if isinstance(a, dict) and a.get("status") == "pending"
        ]

    def approve_first(self) -> str:
        pending = self.list_pending_approvals()
        if not pending:
            return "No pending approvals."
        aid = pending[0].get("approval_id")
        code, raw = self._request(f"/api/approvals/{aid}/approve", method="POST", body={})
        return raw if code == 200 else f"approve failed ({code}): {raw}"

    def reject_first(self) -> str:
        pending = self.list_pending_approvals()
        if not pending:
            return "No pending approvals."
        aid = pending[0].get("approval_id")
        code, raw = self._request(f"/api/approvals/{aid}/reject", method="POST", body={})
        return raw if code == 200 else f"reject failed ({code}): {raw}"

    def switch_workspace_by_label(self, utterance: str) -> str:
        if not reg:
            return "Registry unavailable."
        low = utterance.lower()
        for ws in reg.list_workspaces():
            label = (ws.get("label") or "").lower()
            path = ws.get("path", "")
            if label and label in low and path:
                reg.switch_active_workspace(str(path))
                return f"OK: active {path}"
        return "Say workspace name after 'switch'."


def parse_intent(text: str) -> IntentName:
    low = text.lower().strip()
    if not low:
        return "ask"
    if "status" in low or "estado" in low:
        return "status"
    if "aprobar" in low or "approve" in low:
        return "approve"
    if "rechazar" in low or "reject" in low:
        return "reject"
    if "cambiar" in low or "switch" in low or "workspace" in low:
        return "switch_ws"
    if "abrir dashboard" in low or "open dashboard" in low or "open host" in low:
        return "open_dashboard"
    return "ask"


def parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse one SSE line (`data: {...}`). Pure — no network."""
    stripped = line.strip()
    if not stripped.startswith("data:"):
        return None
    payload = stripped[5:].strip()
    if not payload:
        return None
    try:
        data = json.loads(payload)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _mock_stream_fixture_path() -> Optional[Path]:
    raw = os.environ.get("SOLAR_VOICE_MOCK_STREAM_FIXTURE", "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_file() else None
    default = (
        _SCRIPT_DIR.parent.parent.parent
        / "tests"
        / "skills"
        / "solar-app"
        / "fixtures"
        / "voice_mock_stream.sse"
    )
    return default if default.is_file() else None


def _iter_mock_sse(fixture: Path) -> Generator[Dict[str, Any], None, None]:
    for line in fixture.read_text(encoding="utf-8").splitlines():
        evt = parse_sse_line(line)
        if evt:
            yield evt


def stream_ask(
    text: str,
    thread_id: str,
    *,
    client: Optional[VoiceHostClient] = None,
    on_chunk: Optional[OnChunkFn] = None,
    provider: str = "auto",
) -> Generator[Dict[str, Any], None, None]:
    """Consume SSE from Host POST /threads/{id}/stream; yield parsed events."""
    mock = os.environ.get("SOLAR_VOICE_MOCK_STREAM", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if mock:
        fixture = _mock_stream_fixture_path()
        if fixture:
            for evt in _iter_mock_sse(fixture):
                if evt.get("type") == "chunk":
                    chunk = evt.get("text", "")
                    if chunk and on_chunk:
                        on_chunk(str(chunk))
                yield evt
            return
        yield {"type": "error", "error": "mock stream fixture missing"}
        return

    host = client or VoiceHostClient()
    url = host._url(f"/threads/{thread_id}/stream")
    body = json.dumps(
        {"text": text, "mode": "ask", "provider": provider}, ensure_ascii=False
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        yield {"type": "error", "error": str(exc)}
        return

    try:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace")
            evt = parse_sse_line(line)
            if not evt:
                continue
            if evt.get("type") == "chunk":
                chunk = evt.get("text", "")
                if chunk and on_chunk:
                    on_chunk(str(chunk))
            yield evt
            if evt.get("type") in ("done", "run.completed", "run.failed"):
                break
    finally:
        resp.close()


def speak_brief(text: str, *, max_chars: int = 400) -> None:
    if os.environ.get("SOLAR_VOICE_TTS", "").strip().lower() in ("0", "off", "no"):
        return
    snippet = cleanup_text(text)[:max_chars]
    if not snippet:
        return
    mode = os.environ.get("SOLAR_VOICE_TTS", "batch").strip().lower()
    if mode == "stream" and sys.platform == "darwin":
        try:
            from host_platform.macos.voice_tts import speak_batch_fallback  # noqa: PLC0415

            speak_batch_fallback(snippet)
            return
        except Exception:  # noqa: BLE001
            pass
    if shutil.which("say"):
        subprocess.run(["say", snippet], check=False)


def run_intent(
    utterance: str,
    *,
    client: Optional[VoiceHostClient] = None,
    on_chunk: Optional[OnChunkFn] = None,
    speak: bool = True,
) -> Tuple[int, str]:
    host = client or VoiceHostClient()
    ok, hint = host.ensure_host()
    if not ok:
        return 1, hint

    intent = parse_intent(utterance)
    if intent == "status":
        return 0, host.status_json()
    if intent == "approve":
        return 0, host.approve_first()
    if intent == "reject":
        return 0, host.reject_first()
    if intent == "switch_ws":
        msg = host.switch_workspace_by_label(utterance)
        return (0 if msg.startswith("OK:") else 1, msg)
    if intent == "open_dashboard":
        base = host.base
        if shutil.which("open"):
            subprocess.run(["open", f"{base}/dashboard"], check=False)
        return 0, f"Opened {base}/dashboard"

    thread_id = host.get_or_create_thread_id()
    stream_err = ""
    if not thread_id:
        stream_err = "could not create voice thread on Host"
    else:
        parts: List[str] = []
        for evt in stream_ask(utterance, thread_id, client=host, on_chunk=on_chunk):
            if evt.get("type") == "chunk":
                parts.append(str(evt.get("text", "")))
            if evt.get("type") == "error":
                stream_err = str(evt.get("error", "stream error"))
                break
            if evt.get("type") in ("done", "run.failed"):
                if evt.get("status") == "failed" or evt.get("type") == "run.failed":
                    stream_err = str(evt.get("error", "run failed"))
                    break
        reply = "".join(parts).strip()
        if reply:
            if speak:
                speak_brief(reply)
            return 0, reply

    code, reply = host.chat(utterance)
    if code != 0:
        if stream_err:
            return (
                1,
                f"Ask failed — stream: {stream_err}; chat fallback: {reply}. "
                "Use dashboard chat at :9000 (Ask Solar not validated E2E).",
            )
        return 1, reply
    if speak and reply:
        speak_brief(reply)
    return 0, reply or "(empty response)"


def copy_to_clipboard(text: str) -> None:
    if shutil.which("pbcopy"):
        subprocess.run(["pbcopy"], input=text.encode(), check=False)


def paste_via_osascript() -> None:
    if shutil.which("osascript"):
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "v" using command down',
            ],
            check=False,
        )
