#!/usr/bin/env python3
"""macOS menu bar tray for Solar Host (requires rumps)."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from host_platform.macos import client, notifications  # noqa: E402

import voice_core as vc  # noqa: E402


def _voice_log(msg: str) -> None:
    try:
        import voice_config as vcfg  # noqa: PLC0415

        vcfg.voice_log(msg)
    except ImportError:
        pass


def _bootstrap_voice_env() -> None:
    try:
        import host_registry as reg  # noqa: PLC0415
        import voice_config as vcfg  # noqa: PLC0415

        ws = reg.get_active_path()
        if ws:
            os.environ["SOLAR_WORKSPACE"] = ws
        if not vcfg.load_voice_config().get("whisper_via_python"):
            vcfg.ensure_whisper_in_voice_uv()
        vcfg.discover_tool_paths(refresh=True)
        try:
            import voice_mic as vm  # noqa: PLC0415

            label, granted = vm.microphone_status()
            _voice_log(f"mic permission status={label} granted={granted}")
        except ImportError:
            pass
        _voice_log(f"bootstrap workspace={ws or 'unset'} config={vcfg.voice_config_path()}")
    except Exception as exc:  # noqa: BLE001
        _voice_log(f"bootstrap failed: {exc}")


def _open_privacy_pane() -> None:
    subprocess.run(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
        check=False,
    )


class VoiceSession:
    """Tray push-to-talk state (toggle rec in worker threads)."""

    def __init__(self, app: object) -> None:
        self._app = app
        self._rec_proc: Optional[subprocess.Popen] = None
        self._mode: Optional[str] = None  # copy | paste | ask
        self._audio_path = vc.voice_runtime_dir() / "tray_capture.wav"
        self._recording = False
        self._capture_path: Optional[Path] = None
        self._rec_stderr_path: Optional[Path] = None
        self._menu_refresh: Optional[Callable[[], None]] = None

    @property
    def recording(self) -> bool:
        return self._recording

    def start(self, mode: str) -> bool:
        rec = vc._resolve_rec()
        if not rec:
            notifications.show_notification(
                "Solar",
                "Voice unavailable",
                "Run: solar voice doctor",
            )
            return False
        if self._recording:
            return False
        try:
            import voice_mic as vm  # noqa: PLC0415

            label, granted = vm.microphone_status()
            if not granted and label == "not_determined":
                notifications.show_notification(
                    "Solar",
                    "Permiso de micrófono",
                    "macOS pedirá acceso para dictar. Acepta y vuelve a grabar.",
                )
                vm.ensure_microphone_access()
            elif not granted:
                notifications.show_notification(
                    "Solar",
                    "Micrófono bloqueado",
                    vm.microphone_hint_for_denied(),
                )
                return False
        except ImportError:
            pass
        self._mode = mode
        rec_stderr_path: Optional[Path] = None
        try:
            import voice_config as vcfg  # noqa: PLC0415

            self._capture_path = vcfg.new_capture_path(self._audio_path.parent)
            vcfg.prepare_capture(self._capture_path)
            cmd = vcfg.rec_argv(self._capture_path)
            env = vcfg.subprocess_env()
            rec_stderr_path = self._capture_path.parent / "rec_last.stderr"
            _voice_log(f"rec start {cmd}")
        except ImportError:
            self._capture_path = self._audio_path
            cmd = [rec, "-q", "-b", "16", "-c", "1", str(self._capture_path)]
            env = None
            rec_stderr_path = None
        if not cmd:
            notifications.show_notification("Solar", "Voice", "rec no disponible")
            return False
        errfh = None
        if rec_stderr_path is not None:
            rec_stderr_path.parent.mkdir(parents=True, exist_ok=True)
            errfh = open(rec_stderr_path, "w", encoding="utf-8")  # noqa: SIM115
        self._rec_stderr_path = rec_stderr_path
        self._rec_proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=errfh if errfh else subprocess.DEVNULL,
            env=env,
        )
        self._recording = True
        self._set_recording_ui(True)
        if self._menu_refresh:
            self._menu_refresh()
        notifications.show_notification(
            "Solar",
            "Grabando…",
            "Voice → ■ Detener grabación para transcribir y pegar (⌘V).",
        )
        return True

    def stop_async(self) -> None:
        if not self._recording:
            return
        proc = self._rec_proc
        mode = self._mode
        self._rec_proc = None
        self._recording = False
        self._mode = None
        self._set_recording_ui(False)

        def _worker() -> None:
            try:
                if proc and proc.poll() is None:
                    proc.send_signal(signal.SIGINT)
                    proc.wait(timeout=8)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if proc and proc.poll() is None:
                    proc.kill()
            try:
                wav = self._capture_path or self._audio_path
                size = wav.stat().st_size if wav.is_file() else 0
                _voice_log(f"stop mode={mode} wav={wav} bytes={size}")
                stderr_path = getattr(self, "_rec_stderr_path", None)
                if stderr_path and Path(stderr_path).is_file():
                    rec_err = Path(stderr_path).read_text(encoding="utf-8", errors="replace")
                    if rec_err.strip():
                        _voice_log(f"rec stderr: {rec_err.strip()[:300]}")
                if size < 1000:
                    notifications.show_notification(
                        "Solar",
                        "Audio vacío",
                        "No se oyó micrófono. Revisa permiso Micrófono para Solar.",
                    )
                    return
                notifications.show_notification(
                    "Solar",
                    "Transcribiendo…",
                    "Puede tardar 15–30 s (whisper en CPU).",
                )
                text = vc.transcribe(wav)
                text = vc.cleanup_text(text)
                _voice_log(f"transcript len={len(text)} preview={text[:80]!r}")
                if not text or text.startswith("[voice]"):
                    try:
                        import voice_config as vcfg  # noqa: PLC0415

                        sub, msg = vcfg.notification_parts_for_voice_error(
                            text or "Sin transcripción"
                        )
                    except ImportError:
                        sub, msg = "Voz falló", (text or "Sin transcripción")[:200]
                    notifications.show_notification("Solar", sub, msg)
                    return
                if mode == "copy":
                    vc.copy_to_clipboard(text)
                    notifications.show_notification("Solar", "Copiado", text[:120])
                elif mode == "paste":
                    vc.copy_to_clipboard(text)
                    vc.paste_via_osascript()
                    notifications.show_notification("Solar", "Pegado", text[:80])
                elif mode == "ask":
                    notifications.show_notification(
                        "Solar",
                        "Ask Solar (experimental)",
                        "Enviando al Host… Si falla, usa el chat del dashboard :9000.",
                    )
                    code, out = vc.run_intent(text, speak=False)
                    summary = (out[:200] + "…") if len(out) > 200 else out
                    _voice_log(f"ask result code={code} preview={summary[:120]!r}")
                    if code != 0:
                        notifications.show_notification(
                            "Solar",
                            "Ask no validado",
                            summary[:220]
                            or "Backend/router sin validar. Usa dashboard o solar ask.",
                        )
                    else:
                        notifications.show_notification("Solar", "Ask Solar", summary)
            except Exception as exc:  # noqa: BLE001
                _voice_log(f"worker error: {exc}")
                notifications.show_notification("Solar", "Voice error", str(exc)[:200])
                print(f"voice tray error: {exc}", file=sys.stderr)
            finally:
                if self._menu_refresh:
                    self._menu_refresh()

        threading.Thread(target=_worker, daemon=True).start()

    def toggle(self, mode: str) -> None:
        if self._recording:
            self.stop_async()
        else:
            self.start(mode)

    def _set_recording_ui(self, on: bool) -> None:
        app = self._app
        if on:
            app.title = "Solar 🔴"  # type: ignore[attr-defined]
        else:
            n = client.pending_approval_count()
            app.title = f"Solar ({n})" if n else "Solar"  # type: ignore[attr-defined]


def main() -> int:
    if sys.platform != "darwin":
        print("WARN: tray is macOS-only", file=sys.stderr)
        return 0

    try:
        import rumps  # type: ignore
    except ImportError:
        print(
            "WARN: rumps not available — tray needs: uv run --with rumps python3 .../host_tray.py",
            file=sys.stderr,
        )
        print(f"Open Host in browser: {client.host_url()}", file=sys.stderr)
        return 0

    class SolarHostApp(rumps.App):
        def __init__(self) -> None:
            super().__init__("Solar", quit_button="Quit")
            self._seen_events: set[str] = set()
            self._workspace_menu = rumps.MenuItem("Switch workspace")
            self._workspace_menu.add(rumps.MenuItem("Loading…", callback=lambda *_: None))
            self._voice = VoiceSession(self)
            self._hotkey_listener = None
            self._hotkey_mode = "paste"
            self._voice_menu = rumps.MenuItem("Voice")
            self._voice_menu.add(rumps.MenuItem("Loading…", callback=lambda *_: None))
            self.menu = [
                "Open Host",
                "Open Inbox",
                self._workspace_menu,
                None,
                self._voice_menu,
                "Refresh",
            ]
            self._bootstrapped = False

        @rumps.timer(1)
        def _bootstrap(self, _: object) -> None:
            if self._bootstrapped:
                return
            self._bootstrapped = True
            _bootstrap_voice_env()
            self._refresh_workspaces()
            self.refresh_badge(_)
            self._setup_voice_menu()
            if os.environ.get("SOLAR_VOICE_HOTKEY_ENABLE", "").strip() == "1":
                self._setup_hotkey()

        def _setup_voice_menu(self) -> None:
            import rumps  # type: ignore

            def refresh_voice_menu() -> None:
                voice = self._voice_menu
                if getattr(voice, "_menu", None) is None:
                    return
                voice.clear()
                if self._voice.recording:
                    voice.add(
                        rumps.MenuItem(
                            "■ Detener grabación",
                            callback=lambda *_: self._voice.stop_async(),
                        )
                    )
                else:
                    # v0.17.0: only paste PTT validated in Solar.app (copy / ask / hotkey: known bugs).
                    voice.add(
                        rumps.MenuItem(
                            "Push to talk (paste)",
                            callback=lambda *_: self._voice.toggle("paste"),
                        )
                    )
                    voice.add(
                        rumps.MenuItem(
                            "Permisos (mic + pegar)",
                            callback=lambda *_: _open_privacy_pane(),
                        )
                    )

            self._voice._menu_refresh = refresh_voice_menu
            refresh_voice_menu()

        def _setup_hotkey(self) -> None:
            try:
                from host_platform.macos.hotkey import (  # noqa: PLC0415
                    GlobalHotkeyListener,
                    hotkey_human_name,
                )

                def on_hold(down: bool) -> None:
                    if down:
                        self._voice.start(self._hotkey_mode)
                    else:
                        self._voice.stop_async()

                listener = GlobalHotkeyListener(on_hold)
                if listener.start():
                    self._hotkey_listener = listener
                    hk = hotkey_human_name()
                    notifications.show_notification(
                        "Solar",
                        f"{hk} = dictar",
                        "Mantén Right ⌥, suelta → pega en la app activa. "
                        "Fn/F5 suelen ser del sistema. Menú Voice = dos clics.",
                    )
                else:
                    notifications.show_notification(
                        "Solar",
                        "Atajo global no disponible",
                        "Activa Solar en Privacidad → Accessibility/Input Monitoring.",
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"hotkey setup: {exc}", file=sys.stderr)

        @rumps.timer(0.05)
        def _poll_hotkey(self, _: object) -> None:
            if self._hotkey_listener:
                self._hotkey_listener.poll()

        def _open(self, url: str) -> None:
            subprocess.run(["open", url], check=False)

        def _use_workspace(self, path: str) -> None:
            if client.switch_workspace(path):
                notifications.show_notification(
                    "Solar",
                    "Workspace active",
                    Path(path).name,
                )
            else:
                notifications.show_notification("Solar", "Error", "Could not switch workspace")
            self._refresh_workspaces()
            self.refresh_badge(None)

        def _refresh_workspaces(self) -> None:
            if getattr(self._workspace_menu, "_menu", None) is None:
                return
            self._workspace_menu.clear()
            workspaces = client.list_workspaces()
            if not workspaces:
                self._workspace_menu.add(
                    rumps.MenuItem("(Host offline)", callback=lambda *_: None)
                )
                return
            for ws in workspaces:
                path = str(ws.get("path", ""))
                label = str(ws.get("label") or Path(path).name)
                suffix = " ✓" if ws.get("active") else ""
                self._workspace_menu.add(
                    rumps.MenuItem(
                        f"{label}{suffix}",
                        callback=lambda _, p=path: self._use_workspace(p),
                    )
                )

        @rumps.timer(30)
        def refresh_badge(self, _: object) -> None:
            if self._voice.recording:
                return
            n = client.pending_approval_count()
            self.title = f"Solar ({n})" if n else "Solar"

        @rumps.timer(15)
        def poll_notifications(self, _: object) -> None:
            for event in notifications.poll_new_events(self._seen_events):
                title, subtitle, message = notifications.format_notification(event)
                url = notifications.dashboard_focus_url(event)
                notifications.show_notification(title, subtitle, message, open_url=url)

        @rumps.clicked("Open Host")
        def open_host(self, _: object) -> None:
            self._open(client.host_url())

        @rumps.clicked("Open Inbox")
        def open_inbox(self, _: object) -> None:
            self._open(f"{client.host_url()}/dashboard")

        @rumps.clicked("Refresh")
        def refresh(self, _: object) -> None:
            self._refresh_workspaces()
            self.refresh_badge(None)
            for event in notifications.poll_new_events(self._seen_events):
                title, subtitle, message = notifications.format_notification(event)
                url = notifications.dashboard_focus_url(event)
                notifications.show_notification(title, subtitle, message, open_url=url)

    SolarHostApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
