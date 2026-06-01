---
name: solar-host
description: >
  Solar App (skill solar-host) — local app on :9000: fleet UI, API, voice, approvals.
  Product name Solar App; folder rename to solar-app planned. Primary human entry.
---

# Solar App (`solar-host`)

## Purpose

Machine-local **localhost** control plane:

- **Fleet:** registry of workspaces (`{app_data}/Solar/workspaces.json` via `host_platform/paths`; override tests with `SOLAR_APP_DATA`)
- **Workspace switch:** `solar host workspace use` calls Host `:9000` when running; set `SOLAR_HOST_OFFLINE=1` to force local-only (tests)
- **Health:** semaphores per workspace + `solar status`
- **HitL:** approvals inbox (in-process `InterfaceStore`; legacy `:7741` proxy optional)
- **Async:** job timeline under `sun/runtime/async-tasks/`
- **Runtime:** start interface/gateway, kill switch
- **Scoped chat** and **markdown editor** for `sun/` / `planets/`

**Not:** generalist chat, code IDE, M2M webhooks (`solar-gateway`).

## Required MCP

None

## Ports

| Service | Default | Role |
|---------|---------|------|
| **Solar Host** | `127.0.0.1:9000` | Human UI + in-process workspace API |
| **solar-gateway** | `:8787` + hash per workspace | Webhooks M2M |

## CLI

```bash
solar host start|stop|status|open
solar host workspace list|add|remove|use <path>
solar voice once|paste|command|ask|read
bash core/skills/solar-host/scripts/onboard_host_env.sh
```

## macOS tray + notifications (Host-1)

**Dependencies (once):**

| Tool | Command | Why |
|------|---------|-----|
| uv | `brew install uv` | run tray |
| terminal-notifier | `brew install terminal-notifier` | **required** for alerts (dev + Solar.app); never osascript/rumps.notification |
| Solar.app | `bash …/build_solar_tray_app.sh` | menu bar UI (rumps); alerts via terminal-notifier `-sender ai.uhorizon.solar.host` |

**Run tray** (workspace paths use `solar/` prefix when framework is nested):

```bash
# Dev — menu bar via rumps (no uv required)
bash solar/core/skills/solar-host/scripts/run_host_tray.sh

# Product — same notification path; Solar.app for menu bar identity
open solar/core/skills/solar-host/scripts/host_platform/macos/dist/Solar.app
```

- `SOLAR_HOST_TRAY=1` — `start_host.sh` launches built `Solar.app` if present, else `run_host_tray.sh`.
- Inbox web on `:9000` works without tray.

**Remove stale "Python" from System Settings → Notifications** (after old dev tray runs):

```bash
bash core/skills/solar-host/scripts/host_platform/macos/clean_python_notifications.sh --list
bash core/skills/solar-host/scripts/host_platform/macos/clean_python_notifications.sh --apply
```

Requires **Full Disk Access** for the terminal (Cursor/Terminal). If Python still appears, log out/in once.

## LaunchAgent

Add `host` to `SOLAR_SYSTEM_FEATURES`. Orchestrator runs `ensure_host.sh` (workspace API in-process on `:9000`; no separate `:7741` daemon).

## Voice (part of this skill)

Voice in Solar.app: **tray → Voice → Push to talk (paste)** then **■ Detener grabación** (transcribe + ⌘V in active app). CLI intents and TTS exist but are not the validated path.

### Known bugs

| Issue | Workaround |
|-------|------------|
| **Only paste PTT works** in Solar.app (v0.17.0) | **Voice → Push to talk (paste)** → speak → **■ Detener grabación**. Needs Mic + Accessibility. |
| **Push to talk (copy)** | Not validated in tray — use paste or CLI `solar voice paste`. |
| **Ask Solar** | Not validated — transcription only; no reliable Host/router reply. Use dashboard chat `:9000`. |
| **Global hotkey** | Disabled (`SOLAR_VOICE_HOTKEY_ENABLE=1` experimental). |

Scripts: `scripts/voice_core.py` (shared), `scripts/voice_cli.py` — not a separate bundle skill (`solar-voice` is a deprecation stub only).

| Env | Purpose |
|-----|---------|
| `SOLAR_HOST_BASE_URL` | Override Host URL (voice + tests) |
| `SOLAR_HOST_HOST` / `SOLAR_HOST_PORT` | Host address (default `127.0.0.1:9000`) |
| `SOLAR_VOICE_TEXT` | Skip mic — inject utterance (tests) |
| `SOLAR_VOICE_MOCK_STREAM=1` | SSE mock fixture (CI; no LLM) |
| `SOLAR_VOICE_TTS` | `stream` \| `batch` \| `off` |
| `SOLAR_VOICE_HOTKEY` | Key spec when hotkey enabled (`right_option`, `f8`, …) — **disabled by default** (known bug) |
| `SOLAR_VOICE_HOTKEY_ENABLE` | Set `1` to attempt global hotkey (experimental; usually broken) |
| `~/Library/.../Solar/voice.json` | Tool paths for Solar.app (`solar voice doctor` writes this) |

**Deps (install once):**

```bash
solar voice doctor          # check + auto-install (brew + uv → voice-uv venv)
solar voice doctor --no-fix # report only
```

| Tool | Install | Required |
|------|---------|----------|
| SoX `rec` | `brew install sox` | **yes** for mic dictation |
| whisper | optional | local STT |
| terminal-notifier | `brew install terminal-notifier` | tray alerts |
| uv | `brew install uv` | **required** for Python voice deps |
| PyObjC Quartz | `solar voice doctor` (uv venv) | hotkey module only; global shortcut **known broken** |
| rumps | `solar voice doctor` | dev tray (`run_host_tray.sh`) |

**macOS permissions:** **Microphone** (record) and **Accessibility** (paste via ⌘V). System Settings → Privacy.

**Tray menu (v0.17.0):** Voice → **Push to talk (paste)** → **■ Detener grabación**. No copy / ask / hotkey in menu until fixed.

## Validation

```bash
bash -n core/skills/solar-host/scripts/host_lib.sh
python3 -m py_compile core/skills/solar-host/scripts/host_platform/paths.py
python3 -m py_compile core/skills/solar-host/scripts/host_workspace_context.py
python3 -m py_compile core/skills/solar-host/scripts/host_interface.py
python3 -m py_compile core/skills/solar-interface/scripts/interface_store.py
python3 -m py_compile core/skills/solar-interface/scripts/interface_http.py
python3 -m py_compile core/skills/solar-interface/scripts/interface_server.py
python3 -m py_compile core/skills/solar-host/scripts/host_events.py
python3 -m py_compile core/skills/solar-host/scripts/host_server.py
python3 -m py_compile core/skills/solar-host/scripts/host_registry.py
python3 -m py_compile core/skills/solar-host/scripts/voice_core.py
python3 -m py_compile core/skills/solar-host/scripts/voice_config.py
python3 -m py_compile core/skills/solar-host/scripts/voice_cli.py
python3 -m py_compile core/skills/solar-host/scripts/host_platform/macos/voice_tts.py
python3 -m py_compile core/skills/solar-host/scripts/host_platform/macos/hotkey.py
bash core/tests/skills/solar-host/test_voice_core_unit.sh
bash core/tests/skills/solar-host/test_voice_cli_host_api.sh
bash core/tests/skills/solar-host/test_voice_stream_contract.sh
bash core/tests/skills/solar-host/test_voice_macos_imports.sh
bash -n core/skills/solar-host/scripts/voice_doctor.sh
bash -n core/skills/solar-host/scripts/voice_uv_lib.sh
bash core/tests/skills/solar-host/test_fleet_registry.sh
bash core/tests/skills/solar-host/test_fleet_api_contract.sh
bash core/tests/skills/solar-host/test_host_platform_import.sh
bash core/tests/skills/solar-host/test_workspace_mount.sh
bash core/tests/skills/solar-host/test_host_api_smoke.sh
bash core/tests/skills/solar-host/test_host_events_contract.sh
bash core/tests/skills/solar-host/test_host_approvals_two_workspaces.sh
bash core/tests/skills/solar-host/test_host_macos_notifications_unit.sh
bash core/tests/skills/solar-host/test_host_interface_routes.sh
bash core/tests/skills/solar-host/test_host_stream_smoke.sh
bash core/tests/skills/solar-host/test_no_legacy_listener_after_switch.sh
```

## Frontera

| Layer | Rol |
|-------|-----|
| **IDE** | Code, refactors |
| **Solar Host** | Operations, fleet, approvals, governance |
| **solar-interface** | CLI `solar ask` + optional dev daemon; Host uses `InterfaceStore` in-process |
| **voice** (`voice_cli.py`) | Speech → Host API — same skill, not `solar-voice` bundle |
| **solar-client** | init, sync, bundle |

## Rename note

See `references/rename-interface-eval.md` — keep `solar-interface` as API skill until Host-4 review.
