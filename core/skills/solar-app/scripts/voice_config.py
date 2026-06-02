#!/usr/bin/env python3
"""Machine-local voice tool paths (Solar.app has no shell PATH)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Whisper on silence/noise often emits these — not real dictation.
_HALLUCINATION_PHRASES = (
    "gracias por ver el video",
    "gracias por ver el vídeo",
    "thanks for watching",
    "thank you for watching",
    "suscríbete",
    "subscribe",
    "subtítulos",
    "subtitulos",
    "amara.org",
)

_WHISPER_EXTRA = (
    "--condition_on_previous_text",
    "False",
    "--temperature",
    "0",
    "--beam_size",
    "5",
)

_SCRIPT_DIR = Path(__file__).resolve().parent

_BREW_PATHS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/opt/homebrew/sbin",
    "/usr/local/sbin",
)

_EXTERNAL_ENV_DROP = (
    "PYTHONEXECUTABLE",
    "PYTHONHOME",
    "PYTHONPATH",
    "__PYVENV_LAUNCHER__",
    "DYLD_FRAMEWORK_PATH",
    "DYLD_FALLBACK_FRAMEWORK_PATH",
    "DYLD_LIBRARY_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
)


def _host_global_dir() -> Path:
    try:
        from host_platform.paths import host_global_dir  # noqa: PLC0415

        return host_global_dir()
    except ImportError:
        base = os.environ.get("SOLAR_APP_DATA", "").strip()
        if base:
            return Path(base).expanduser() / "Solar"
        return Path.home() / "Library" / "Application Support" / "Solar"


def voice_config_path() -> Path:
    return _host_global_dir() / "voice.json"


def voice_uv_python_path() -> Path:
    return _host_global_dir() / "voice-uv" / ".venv" / "bin" / "python"


def augmented_path() -> str:
    parts = list(_BREW_PATHS)
    current = os.environ.get("PATH", "")
    if current:
        parts.append(current)
    seen: set[str] = set()
    out: List[str] = []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return os.pathsep.join(out)


def subprocess_env() -> Dict[str, str]:
    env = os.environ.copy()
    for key in _EXTERNAL_ENV_DROP:
        env.pop(key, None)
    env["PATH"] = augmented_path()
    return env


def load_voice_config() -> Dict[str, Any]:
    path = voice_config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_voice_config(data: Dict[str, Any]) -> Path:
    path = voice_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, **data}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _brew_binary(name: str) -> Optional[str]:
    for base in _BREW_PATHS:
        candidate = Path(base) / name
        if candidate.is_file():
            return str(candidate)
    return None


def _which(name: str) -> Optional[str]:
    found = _brew_binary(name) or shutil.which(name, path=augmented_path())
    if found:
        return found
    override = os.environ.get(f"SOLAR_VOICE_{name.upper()}", "").strip()
    if override and Path(override).is_file():
        return override
    return None


def _voice_uv_imports_whisper(py: Path) -> bool:
    if not py.is_file():
        return False
    proc = subprocess.run(
        [str(py), "-c", "import whisper"],
        capture_output=True,
        check=False,
        env=subprocess_env(),
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace")
        voice_log(f"voice-uv import whisper failed py={py} err={err.strip()[:300]!r}")
    return proc.returncode == 0


def _running_in_solar_app() -> bool:
    try:
        from host_platform.macos.notifications import running_in_solar_app  # noqa: PLC0415

        return running_in_solar_app()
    except Exception:  # noqa: BLE001
        import sys

        return "Solar.app" in sys.executable


def discover_tool_paths(*, refresh: bool = False, save: bool = True) -> Dict[str, Any]:
    cfg = {} if refresh else load_voice_config()
    rec = _which("rec")
    if rec:
        cfg["rec"] = rec
    py = voice_uv_python_path()
    if py.is_file():
        cfg["voice_uv_python"] = str(py)
    # Prefer voice-uv (python -m whisper): brew CLI breaks inside Solar.app (torch/DYLD).
    if py.is_file() and _voice_uv_imports_whisper(py):
        cfg["whisper_via_python"] = True
        cfg.pop("whisper", None)
    elif _running_in_solar_app() or cfg.get("whisper_via_python"):
        cfg.pop("whisper", None)
        if py.is_file():
            cfg["whisper_via_python"] = True
    else:
        whisper = _which("whisper")
        if whisper:
            cfg["whisper"] = whisper
            cfg.pop("whisper_via_python", None)
        elif py.is_file():
            cfg["whisper_via_python"] = True
    cfg["hotkey"] = (
        os.environ.get("SOLAR_VOICE_HOTKEY", "").strip().lower()
        or str(cfg.get("hotkey", "")).strip().lower()
        or "right_option"
    )
    if save:
        save_voice_config(cfg)
    return cfg


def resolve_rec() -> Optional[str]:
    cfg = load_voice_config()
    rec = cfg.get("rec")
    if isinstance(rec, str) and Path(rec).is_file():
        return rec
    return _which("rec")


def resolve_mic_device() -> Optional[str]:
    cfg = load_voice_config()
    mic = cfg.get("mic_device") or os.environ.get("SOLAR_VOICE_MIC_DEVICE", "").strip()
    return mic or None


def new_capture_path(workspace: Optional[Path] = None) -> Path:
    root = workspace
    if root is None:
        try:
            import voice_core as vc  # noqa: PLC0415

            root = vc.voice_runtime_dir()
        except ImportError:
            root = Path.cwd() / "sun/runtime/host/voice"
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return root / f"capture_{stamp}.wav"


def prepare_capture(path: Path) -> None:
    """Remove stale WAV/TXT so we never transcribe an old take."""
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in (".wav", ".txt"):
        p = path.parent / f"{path.stem}{suffix}"
        if p.is_file():
            p.unlink()
    for old_txt in path.parent.glob(f"{path.stem}*.txt"):
        old_txt.unlink(missing_ok=True)
    if path.is_file():
        path.unlink()


def rec_argv(output: Path) -> Optional[List[str]]:
    rec = resolve_rec()
    if not rec:
        return None
    cmd = [rec, "-q"]
    mic = resolve_mic_device()
    if mic:
        cmd.extend(["-d", mic])
    # 16-bit PCM; macOS CoreAudio often ignores -r 16000 (uses 48k) — do not force 16k here.
    cmd.extend(["-b", "16", "-c", "1", str(output.resolve())])
    return cmd


def _wav_peak_from_pcm(path: Path) -> Optional[float]:
    """Peak 0..1 from 8/16-bit WAV (stdlib); reliable when sox stat lies on 32-bit."""
    import struct
    import wave

    try:
        with wave.open(str(path.resolve()), "rb") as w:
            sampwidth = w.getsampwidth()
            if sampwidth not in (1, 2):
                return None
            nframes = w.getnframes()
            if nframes <= 0:
                return 0.0
            chunk = min(nframes, 16000 * 120)
            raw = w.readframes(chunk)
    except (OSError, wave.Error):
        return None

    if sampwidth == 2:
        count = len(raw) // 2
        if count == 0:
            return 0.0
        samples = struct.unpack(f"<{count}h", raw[: count * 2])
        peak = max(abs(s) for s in samples)
        return peak / 32768.0
    if sampwidth == 1:
        if not raw:
            return 0.0
        peak = max(abs(b - 128) for b in raw)
        return peak / 128.0
    return None


def wav_max_amplitude(path: Path) -> Optional[float]:
    pcm_peak = _wav_peak_from_pcm(path)
    sox = _brew_binary("sox") or shutil.which("sox", path=augmented_path())
    sox_peak: Optional[float] = None
    if sox and path.is_file():
        proc = subprocess.run(
            [sox, str(path.resolve()), "-n", "stat"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=subprocess_env(),
        )
        text = (proc.stderr or "") + (proc.stdout or "")
        match = re.search(r"Maximum amplitude:\s*([\d.]+)", text)
        if match:
            try:
                sox_peak = float(match.group(1))
            except ValueError:
                sox_peak = None
    peaks = [p for p in (pcm_peak, sox_peak) if p is not None]
    if not peaks:
        return None
    return max(peaks)


def is_likely_hallucination(text: str) -> bool:
    low = text.lower().strip()
    return any(phrase in low for phrase in _HALLUCINATION_PHRASES)


def normalize_wav_for_stt(source: Path) -> Path:
    """Normalize level so quiet mics are usable by whisper."""
    sox = _brew_binary("sox") or shutil.which("sox", path=augmented_path())
    if not sox:
        return source
    out = source.parent / f"{source.stem}_norm.wav"
    proc = subprocess.run(
        [sox, str(source.resolve()), str(out.resolve()), "gain", "-n"],
        capture_output=True,
        check=False,
        env=subprocess_env(),
    )
    if proc.returncode == 0 and out.is_file():
        return out
    return source


def _whisper_base_argv(audio: Path, *, language: str, executable: str) -> List[str]:
    """Whisper must write next to the WAV — Solar.app cwd is not the workspace."""
    out_dir = str(audio.parent.resolve())
    audio_path = str(audio.resolve())
    if executable == "python-module":
        py = str(voice_uv_python_path())
        cfg = load_voice_config()
        if cfg.get("voice_uv_python"):
            py = str(cfg["voice_uv_python"])
        return [
            py,
            "-m",
            "whisper",
            audio_path,
            "--language",
            language,
            "--output_format",
            "txt",
            *_WHISPER_EXTRA,
            "--output_dir",
            out_dir,
        ]
    return [
        executable,
        audio_path,
        "--language",
        language,
        "--output_format",
        "txt",
        *_WHISPER_EXTRA,
        "--output_dir",
        out_dir,
    ]


def whisper_argv(audio: Path, *, language: str = "es") -> Optional[List[str]]:
    cfg = load_voice_config()
    py = cfg.get("voice_uv_python")
    use_python = bool(cfg.get("whisper_via_python")) or _running_in_solar_app()
    if use_python:
        py_path = Path(str(py)) if isinstance(py, str) else voice_uv_python_path()
        if py_path.is_file():
            if (
                bool(cfg.get("whisper_via_python"))
                or _running_in_solar_app()
                or _voice_uv_imports_whisper(py_path)
            ):
                return _whisper_base_argv(audio, language=language, executable="python-module")
    whisper = cfg.get("whisper")
    if (
        isinstance(whisper, str)
        and Path(whisper).is_file()
        and not _running_in_solar_app()
    ):
        return _whisper_base_argv(audio, language=language, executable=whisper)
    if voice_uv_python_path().is_file() and _voice_uv_imports_whisper(voice_uv_python_path()):
        return _whisper_base_argv(audio, language=language, executable="python-module")
    w = _which("whisper")
    if w and not _running_in_solar_app():
        return _whisper_base_argv(audio, language=language, executable=w)
    return None


def cleanup_transcript_artifacts(audio: Path) -> None:
    """Remove whisper txt outputs for this take (avoid stale reads after failure)."""
    for pattern in (f"{audio.stem}.txt", f"{audio.stem}*.txt"):
        for p in audio.parent.glob(pattern):
            try:
                p.unlink()
            except OSError:
                pass


def notification_parts_for_voice_error(text: str) -> tuple[str, str]:
    """(subtitle, message) for macOS alerts — subtitle is the headline users read."""
    body = (text or "Sin transcripción").strip()
    if body.startswith("[voice]"):
        body = body[7:].strip()
    low = body.lower()
    if "micrófono sin señal" in low or "audio casi silencio" in low:
        return ("Micrófono sin señal", body[:400])
    if "transcription failed" in low or "transcripción" in low:
        return ("Transcripción falló", body[:400])
    if "whisper no oyó" in low or "youtube" in low:
        return ("No se oyó tu voz", body[:400])
    if "no whisper" in low:
        return ("Whisper no instalado", body[:400])
    return ("Voz falló", body[:400])


def read_transcript_for_audio(audio: Path) -> Optional[str]:
    """Read whisper txt output for a given WAV path."""
    direct = audio.parent / f"{audio.stem}.txt"
    if direct.is_file():
        return direct.read_text(encoding="utf-8").strip()
    matches = sorted(audio.parent.glob(f"{audio.stem}*.txt"))
    if matches:
        return matches[-1].read_text(encoding="utf-8").strip()
    return None


def voice_log(message: str) -> None:
    try:
        from datetime import datetime, timezone

        path = _host_global_dir() / "voice.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{ts} {message}\n")
    except OSError:
        pass


def ensure_whisper_in_voice_uv() -> bool:
    """Install openai-whisper into voice-uv venv via uv; return True if import works."""
    if not shutil.which("uv", path=augmented_path()):
        return False
    py = voice_uv_python_path()
    if not py.parent.is_dir():
        subprocess.run(
            ["uv", "venv", str(py.parent.parent)],
            check=False,
            env=subprocess_env(),
        )
    if not py.is_file():
        return False
    subprocess.run(
        ["uv", "pip", "install", "--python", str(py), "openai-whisper"],
        check=False,
        env=subprocess_env(),
    )
    proc = subprocess.run(
        [str(py), "-c", "import whisper"],
        capture_output=True,
        env=subprocess_env(),
    )
    if proc.returncode == 0:
        cfg = load_voice_config()
        cfg["voice_uv_python"] = str(py)
        cfg["whisper_via_python"] = True
        cfg.pop("whisper", None)
        save_voice_config(cfg)
        return True
    return False
