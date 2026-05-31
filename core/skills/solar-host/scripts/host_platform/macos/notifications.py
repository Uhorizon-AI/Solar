#!/usr/bin/env python3
"""Poll Host event bus and surface approval.pending / run.failed on macOS."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from host_platform.macos import client

NOTIFY_TYPES = frozenset({"approval.pending", "run.failed"})
NOTIFY_GROUP = "ai.uhorizon.solar.host"
APP_DISPLAY_NAME = "Solar"
ShowFn = Callable[[str, str, str, Optional[str]], None]

_WARNED_NO_TN = False

_TERMINAL_NOTIFIER_CANDIDATES = (
    "/opt/homebrew/bin/terminal-notifier",
    "/usr/local/bin/terminal-notifier",
)


def terminal_notifier_path() -> Optional[str]:
    found = shutil.which("terminal-notifier")
    if found:
        return found
    for candidate in _TERMINAL_NOTIFIER_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def running_in_solar_app() -> bool:
    """True when tray runs inside py2app Solar.app (notifications show as Solar)."""
    if "Solar.app" in sys.executable:
        return True
    try:
        from Foundation import NSBundle  # type: ignore

        bundle_id = NSBundle.mainBundle().bundleIdentifier()
        return bundle_id == NOTIFY_GROUP
    except Exception:  # noqa: BLE001
        return False


def _warn_no_notifier() -> None:
    global _WARNED_NO_TN  # noqa: PLW0603
    if _WARNED_NO_TN:
        return
    _WARNED_NO_TN = True
    print(
        "WARN: no Solar notification channel — install terminal-notifier or rebuild Solar.app\n"
        "      brew install terminal-notifier\n"
        "      bash core/skills/solar-host/scripts/build_solar_tray_app.sh && open …/dist/Solar.app",
        file=sys.stderr,
    )


def _notify_via_terminal_notifier(
    title: str,
    subtitle: str,
    message: str,
    *,
    open_url: Optional[str] = None,
) -> bool:
    tn = terminal_notifier_path()
    if not tn:
        return False
    cmd = [
        tn,
        "-title",
        title or APP_DISPLAY_NAME,
        "-subtitle",
        subtitle,
        "-message",
        message,
        "-group",
        NOTIFY_GROUP,
    ]
    if running_in_solar_app():
        # Attribute alerts to Solar.app, not embedded org.python.python (py2app).
        cmd.extend(["-sender", NOTIFY_GROUP])
    if open_url:
        cmd.extend(["-open", open_url])
    subprocess.run(cmd, check=False)
    return True


def show_notification(
    title: str,
    subtitle: str,
    message: str,
    *,
    open_url: Optional[str] = None,
    show_fn: Optional[ShowFn] = None,
) -> None:
    if show_fn is not None:
        show_fn(title, subtitle, message, open_url)
        return
    if sys.platform != "darwin":
        return

    # terminal-notifier for dev tray and Solar.app (-sender ai.uhorizon.solar.host).
    # Never rumps.notification or osascript — both register "Python" in Settings.
    if _notify_via_terminal_notifier(title, subtitle, message, open_url=open_url):
        return

    _warn_no_notifier()


def event_dedupe_key(event: dict) -> str:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return ":".join(
        [
            str(event.get("type", "")),
            str(event.get("ts", "")),
            str(payload.get("approval_id", "")),
            str(payload.get("run_id", "")),
        ]
    )


def should_notify(event_type: str) -> bool:
    return event_type in NOTIFY_TYPES


def format_notification(event: dict) -> tuple[str, str, str]:
    etype = str(event.get("type", ""))
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    summary = str(payload.get("summary") or payload.get("label") or payload.get("run_id") or "")
    if etype == "approval.pending":
        return (APP_DISPLAY_NAME, "Approval pending", summary or "Review required")
    if etype == "run.failed":
        return (APP_DISPLAY_NAME, "Run failed", summary or "Check dashboard inbox")
    return (APP_DISPLAY_NAME, etype, summary)


def dashboard_focus_url(event: dict, base: Optional[str] = None) -> str:
    base_url = (base or client.host_url()).rstrip("/")
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    etype = str(event.get("type", ""))
    if etype.startswith("approval"):
        aid = str(payload.get("approval_id", ""))
        if aid:
            return f"{base_url}/dashboard?focus=approval:{aid}"
    return f"{base_url}/dashboard"


def process_events(events: list[dict], seen: set[str]) -> list[dict]:
    """Return newly seen notify-worthy events; updates *seen* in place."""
    fresh: list[dict] = []
    for event in events:
        etype = str(event.get("type", ""))
        if not should_notify(etype):
            continue
        key = event_dedupe_key(event)
        if key in seen:
            continue
        seen.add(key)
        fresh.append(event)
    return fresh


def poll_new_events(seen: set[str]) -> list[dict]:
    types = ",".join(sorted(NOTIFY_TYPES))
    events = client.fetch_events(limit=30, types=types)
    return process_events(events, seen)


def notify_events(
    events: list[dict],
    seen: set[str],
    *,
    show_fn: Optional[ShowFn] = None,
) -> int:
    shown = 0
    for event in process_events(events, seen):
        title, subtitle, message = format_notification(event)
        url = dashboard_focus_url(event)
        show_notification(title, subtitle, message, open_url=url, show_fn=show_fn)
        shown += 1
    return shown


def solar_app_bundle() -> Optional[Path]:
    """Built Solar.app (py2app) — notifications use app name Solar."""
    candidate = Path(__file__).resolve().parent / "dist" / "Solar.app"
    exe = candidate / "Contents" / "MacOS" / "Solar"
    if exe.is_file():
        return candidate
    return None
