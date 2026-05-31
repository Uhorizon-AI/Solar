#!/usr/bin/env python3
"""macOS menu bar tray for Solar Host (requires rumps)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from host_platform.macos import client, notifications  # noqa: E402


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
            self.menu = ["Open Host", "Open Inbox", self._workspace_menu, "Refresh"]
            self._bootstrapped = False

        @rumps.timer(1)
        def _bootstrap(self, _: object) -> None:
            """Populate submenu after Cocoa attaches the menu bar (clear() fails in __init__)."""
            if self._bootstrapped:
                return
            self._bootstrapped = True
            self._refresh_workspaces()
            self.refresh_badge(_)

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
