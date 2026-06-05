#!/usr/bin/env bash
# solar app voice doctor — dependency health + auto-fix (like solar client doctor).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=voice_uv_lib.sh
source "$SCRIPT_DIR/voice_uv_lib.sh"

FIX=true
STRICT=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-fix|--check-only)
      FIX=false
      shift
      ;;
    --strict)
      STRICT=true
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Usage: solar app voice doctor [--no-fix] [--strict]

Checks voice dependencies. Python packages install via uv into
~/Library/Application Support/Solar/voice-uv/.venv (never system pip).

  --no-fix     Report only; do not run install commands
  --strict     Exit non-zero if warnings remain after fix pass

Required: uv, SoX (rec). Recommended: terminal-notifier, whisper, PyObjC Quartz, rumps.
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

warn_count=0
err_count=0
fix_count=0

warn() { echo "WARN: $1"; warn_count=$((warn_count + 1)); }
err() { echo "ERROR: $1"; err_count=$((err_count + 1)); }
ok() { echo "OK: $1"; }
fix() { echo "FIX: $1"; fix_count=$((fix_count + 1)); }

have_brew() { command -v brew >/dev/null 2>&1; }
have_uv() { command -v uv >/dev/null 2>&1; }

run_fix() {
  if [[ "$FIX" != true ]]; then
    return 1
  fi
  fix "$*"
  "$@"
}

brew_install() {
  local pkg="$1"
  if ! have_brew; then
    warn "Homebrew not found — install manually: brew install $pkg"
    return 1
  fi
  run_fix brew install "$pkg"
}

uv_install_into_voice_venv() {
  local pkg="$1"
  if ! have_uv; then
    err "uv missing — brew install uv (required for Python voice deps)"
    return 1
  fi
  local py
  py="$(voice_uv_ensure)" || return 1
  run_fix uv pip install --python "$py" "$pkg"
}

venv_python_import() {
  local mod="$1"
  local py
  py="$(voice_uv_python)" || return 1
  "$py" -c "import ${mod}" 2>/dev/null
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  warn "voice dictation is primarily tested on macOS"
fi

# --- Required: uv ---
if have_uv; then
  ok "uv — $(command -v uv) ($(uv --version 2>/dev/null | head -1))"
else
  err "uv missing — install: brew install uv"
  if have_brew && [[ "$FIX" == true ]]; then
    fix "brew install uv"
    brew install uv || true
    have_uv && ok "uv — installed" && err_count=$((err_count - 1))
  fi
fi

# --- Required: SoX / rec ---
if command -v rec >/dev/null 2>&1; then
  ok "rec (SoX) — $(command -v rec)"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    MIC_PROBE="$(
      python3 - <<'PY' "$SCRIPT_DIR" 2>/dev/null || true
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import voice_config as v
import subprocess
import signal

wav = Path(tempfile.gettempdir()) / "solar_voice_mic_probe.wav"
v.prepare_capture(wav)
cmd = v.rec_argv(wav)
if not cmd:
    print("skip")
    raise SystemExit(0)
p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=v.subprocess_env())
import time
time.sleep(2)
p.send_signal(signal.SIGINT)
p.wait(timeout=5)
amp = v.wav_max_amplitude(wav)
print(f"amp={amp}" if amp is not None else "amp=unknown")
PY
    )"
    if [[ "$MIC_PROBE" == amp=* ]]; then
      amp_val="${MIC_PROBE#amp=}"
      if python3 -c "import sys; sys.exit(0 if float('${amp_val}') >= 0.05 else 1)" 2>/dev/null; then
        ok "mic probe — señal OK ($MIC_PROBE en 2s; habla durante doctor si falla)"
      else
        warn "mic probe — señal baja ($MIC_PROBE). Ajustes → Sonido → Entrada: micrófono correcto"
      fi
    fi
  fi
else
  err "rec missing — dictation requires SoX"
  if brew_install sox && command -v rec >/dev/null 2>&1; then
    ok "rec (SoX) — installed"
    err_count=$((err_count - 1))
  fi
fi

# --- Recommended: terminal-notifier ---
tn_ok=false
for p in /opt/homebrew/bin/terminal-notifier /usr/local/bin/terminal-notifier; do
  if [[ -x "$p" ]]; then
    tn_ok=true
    break
  fi
done
if command -v terminal-notifier >/dev/null 2>&1 || [[ "$tn_ok" == true ]]; then
  ok "terminal-notifier — tray / Solar.app alerts"
else
  warn "terminal-notifier missing"
  if brew_install terminal-notifier && command -v terminal-notifier >/dev/null 2>&1; then
    ok "terminal-notifier — installed"
    warn_count=$((warn_count - 1))
  fi
fi

# --- STT: voice.json paths + openai-whisper in voice-uv (Solar.app-safe) ---
WHISPER_OK=false
if python3 - <<PY "$SCRIPT_DIR" "$FIX" 2>/dev/null
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import voice_config as v
fix = sys.argv[2] == "true"
v.discover_tool_paths(refresh=True, save=fix)
dummy = Path("/tmp/solar_voice_doctor.wav")
if v.whisper_argv(dummy):
    print("argv-ok")
    raise SystemExit(0)
if not fix:
    raise SystemExit(1)
v.ensure_whisper_in_voice_uv()
if v.whisper_argv(dummy):
    print("venv-ok")
    raise SystemExit(0)
else:
    raise SystemExit(1)
PY
then
  WHISPER_OK=true
  ok "whisper — configured in $(python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); import voice_config as v; print(v.voice_config_path())")"
elif command -v whisper >/dev/null 2>&1; then
  warn "whisper CLI (Homebrew) no sirve dentro de Solar.app — instalando en voice-uv…"
  if [[ "$FIX" == true ]] && have_uv; then
    py="$(voice_uv_ensure 2>/dev/null || true)"
    if [[ -n "$py" ]]; then
      run_fix uv pip install --python "$py" openai-whisper || true
      python3 - <<PY "$SCRIPT_DIR" || true
import sys
sys.path.insert(0, sys.argv[1])
import voice_config as v
v.ensure_whisper_in_voice_uv()
v.discover_tool_paths(refresh=True)
PY
      if python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); import voice_config as v; from pathlib import Path; assert v.whisper_argv(Path('/tmp/x.wav'))" 2>/dev/null; then
        ok "whisper — voice-uv (python -m whisper) para Solar.app"
        WHISPER_OK=true
      fi
    fi
  fi
  if [[ "$WHISPER_OK" != true ]]; then
    warn "solo whisper Homebrew — ejecuta: solar app voice doctor (con --fix)"
  fi
else
  warn "whisper not configured for Solar.app"
  if [[ "$FIX" == true ]] && have_uv; then
    py="$(voice_uv_ensure 2>/dev/null || true)"
    if [[ -n "$py" ]]; then
      run_fix uv pip install --python "$py" openai-whisper || true
      python3 - <<PY "$SCRIPT_DIR" || true
import sys
sys.path.insert(0, sys.argv[1])
import voice_config as v
v.ensure_whisper_in_voice_uv()
v.discover_tool_paths(refresh=True)
PY
      if python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); import voice_config as v; from pathlib import Path; assert v.whisper_argv(Path('/tmp/x.wav'))" 2>/dev/null; then
        ok "whisper — voice-uv (python -m whisper)"
        WHISPER_OK=true
        warn_count=$((warn_count - 1))
      fi
    fi
  fi
fi

# --- Python voice venv (uv): rumps + PyObjC Quartz ---
if [[ "$(uname -s)" == "Darwin" ]] && have_uv; then
  root="$(voice_uv_root)"
  if [[ "$FIX" == true ]]; then
    voice_uv_ensure >/dev/null
  fi
  py="$(voice_uv_python 2>/dev/null || true)"

  if [[ -n "$py" ]] && venv_python_import rumps; then
    ok "rumps — voice-uv venv ($root)"
  else
    warn "rumps missing in voice-uv venv (dev tray)"
    if uv_install_into_voice_venv rumps && venv_python_import rumps; then
      ok "rumps — installed in voice-uv venv"
      warn_count=$((warn_count - 1))
    fi
  fi

  if [[ -n "$py" ]] && venv_python_import Quartz; then
    ok "PyObjC Quartz — voice-uv venv (hotkey module; global shortcut known broken)"
  else
    warn "PyObjC Quartz missing in voice-uv venv — optional; global hotkey is a known bug anyway"
    if uv_install_into_voice_venv pyobjc-framework-Quartz && venv_python_import Quartz; then
      ok "PyObjC Quartz — installed in voice-uv venv"
      warn_count=$((warn_count - 1))
    fi
  fi

  if [[ -d "$SCRIPT_DIR/host_platform/macos/dist/Solar.app" ]] && venv_python_import Quartz; then
    ok "Rebuild Solar.app after doctor: bash $SCRIPT_DIR/build_solar_tray_app.sh"
  fi
elif [[ "$(uname -s)" == "Darwin" ]]; then
  warn "uv required for rumps/Quartz — brew install uv"
fi

echo ""
echo "Summary: $err_count error(s), $warn_count warning(s), $fix_count fix command(s) run"
if have_uv; then
  echo "Python deps venv: $(voice_uv_root)/.venv"
fi
echo ""
echo "Usage:"
echo "  solar app voice paste              # Enter = stop recording"
echo "  bash …/run_host_tray.sh        # dev tray (voice-uv venv)"
echo "  Solar.app → Voice → Push to talk (paste) → Detener grabación  # only validated path"
echo "  copy / Ask Solar / hotkey        # known bugs"

if [[ "$err_count" -gt 0 ]]; then
  exit 1
fi
if [[ "$STRICT" == true && "$warn_count" -gt 0 ]]; then
  exit 1
fi
exit 0
