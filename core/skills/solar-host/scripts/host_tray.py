#!/usr/bin/env python3
"""Optional macOS menu bar helper for Solar Host (requires rumps)."""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
import host_registry as reg  # noqa: E402


def _host_url() -> str:
    host = os.environ.get("SOLAR_HOST_HOST", "127.0.0.1")
    port = os.environ.get("SOLAR_HOST_PORT", "9000")
    return f"http://{host}:{port}"


def _pending_count() -> int:
    active = reg.get_active_path()
    if not active:
        return 0
    iface = reg.list_workspaces()
    base = next((w["interface_base"] for w in iface if w.get("path") == active), None)
    if not base:
        iface_port = reg._interface_port_from_env(active) or reg.port_offsets(active)[0]
        base = f"http://127.0.0.1:{iface_port}"
    try:
        with urllib.request.urlopen(f"{base}/approvals", timeout=4) as resp:
            import json

            data = json.loads(resp.read().decode())
            approvals = data.get("approvals", []) if isinstance(data, dict) else []
            return sum(1 for a in approvals if a.get("status") == "pending")
    except Exception:  # noqa: BLE001
        return 0


def main() -> int:
    try:
        import rumps  # type: ignore
    except ImportError:
        print("WARN: rumps not installed — tray unavailable. Use: pip install rumps", file=sys.stderr)
        print(f"Open Host in browser: {_host_url()}", file=sys.stderr)
        return 0

    class SolarHostApp(rumps.App):
        def __init__(self) -> None:
            title = "Solar"
            super().__init__(title, quit_button="Quit")
            self.menu = ["Open Host", "Refresh", None, "Quit"]

        @rumps.timer(30)
        def refresh_badge(self, _: object) -> None:
            n = _pending_count()
            self.title = f"Solar ({n})" if n else "Solar"

        @rumps.clicked("Open Host")
        def open_host(self, _: object) -> None:
            url = _host_url()
            subprocess.run(["open", url], check=False)

        @rumps.clicked("Refresh")
        def refresh(self, _: object) -> None:
            self.refresh_badge(None)

    SolarHostApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
