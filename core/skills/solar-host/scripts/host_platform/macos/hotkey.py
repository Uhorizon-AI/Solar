#!/usr/bin/env python3
"""Global hold-to-talk hotkey for Solar.app (CGEventTap via PyObjC Quartz).

KNOWN BUG (v0.17.0): global hotkey does not work reliably in production (event tap /
permissions / rumps thread). Use tray Voice menu (two-click PTT) or CLI. Code kept for
future fix; tray skips listener unless SOLAR_VOICE_HOTKEY_ENABLE=1.
"""
from __future__ import annotations

import os
import sys
import threading
from typing import Callable, Optional

HotkeyCallback = Callable[[bool], None]  # True = key down (start), False = key up (stop)

# Default: Right Option — Fn/F5 are often taken by macOS (input source / dictation).
_DEFAULT_HOTKEY = "right_option"

_KEY_ALIASES = {
    "right_option": 61,
    "roption": 61,
    "f6": 97,
    "f8": 100,
    "f5": 96,
    "fn": 63,
}

_FN_FLAG_MASKS = (
    0x00800000,
    0x00080000,
)

_MODIFIER_KEY_CODES = frozenset({56, 58, 59, 60, 61, 62, 63})


def _config_hotkey() -> str:
    try:
        import voice_config as vcfg  # noqa: PLC0415

        hk = vcfg.load_voice_config().get("hotkey")
        if isinstance(hk, str) and hk.strip():
            return hk.strip().lower()
    except ImportError:
        pass
    return os.environ.get("SOLAR_VOICE_HOTKEY", _DEFAULT_HOTKEY).strip().lower()


def default_hotkey_spec() -> str:
    return _config_hotkey()


def hotkey_human_name(spec: Optional[str] = None) -> str:
    key = (spec or default_hotkey_spec()).strip().lower()
    names = {
        "right_option": "Right ⌥ (mantener)",
        "roption": "Right ⌥ (mantener)",
        "fn": "Fn (puede abrir idioma)",
        "f5": "F5 (dictado/Siri del sistema)",
        "f6": "F6",
        "f8": "F8",
    }
    return names.get(key, key.upper())


def quartz_available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import Quartz  # noqa: F401, PLC0415

        return True
    except ImportError:
        return False


def _hotkey_log(message: str) -> None:
    try:
        import voice_config as vcfg  # noqa: PLC0415

        vcfg.voice_log(f"hotkey {message}")
    except Exception:  # noqa: BLE001
        pass


def _resolve_key_code(spec: str) -> Optional[int]:
    low = spec.strip().lower()
    if low in _KEY_ALIASES:
        return _KEY_ALIASES[low]
    if low.startswith("f") and low[1:].isdigit():
        num = int(low[1:])
        if 1 <= num <= 20:
            return 122 + num
    return None


def _fn_flags_down(flags: int) -> bool:
    for mask in _FN_FLAG_MASKS:
        if flags & mask:
            return True
    return False


class GlobalHotkeyListener:
    """Poll-friendly hotkey state for rumps main thread (50ms timer)."""

    def __init__(
        self,
        on_hold: HotkeyCallback,
        *,
        key_spec: Optional[str] = None,
    ) -> None:
        self._on_hold = on_hold
        self._key_spec = (key_spec or default_hotkey_spec()).strip().lower()
        self._use_fn = self._key_spec == "fn"
        self._pressed = False
        self._hotkey_down = False
        self._thread: Optional[threading.Thread] = None
        self._enabled = False
        self._key_code = _resolve_key_code(self._key_spec)
        self._started = threading.Event()
        self._tap_ready = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def hotkey_pressed(self) -> bool:
        return self._hotkey_down

    def start(self) -> bool:
        if not quartz_available():
            return False
        if not self._use_fn and self._key_code is None:
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._enabled = True
        self._tap_ready = False
        self._started.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._started.wait(timeout=1.0)
        return self._tap_ready

    def poll(self) -> None:
        if not self._enabled:
            return
        down = self._hotkey_down
        if down and not self._pressed:
            self._pressed = True
            self._on_hold(True)
        elif not down and self._pressed:
            self._pressed = False
            self._on_hold(False)

    def stop(self) -> None:
        self._enabled = False
        self._hotkey_down = False

    def _run_loop(self) -> None:
        try:
            import Quartz  # noqa: PLC0415
        except ImportError:
            self._enabled = False
            self._started.set()
            return

        key_code = self._key_code
        alternate_mask = int(getattr(Quartz, "kCGEventFlagMaskAlternate", 0x00080000))

        def _callback(proxy, etype, event, refcon):  # noqa: ANN001
            if not self._enabled:
                return event
            try:
                if self._use_fn:
                    if etype == Quartz.kCGEventFlagsChanged:
                        flags = Quartz.CGEventGetFlags(event)
                        self._hotkey_down = _fn_flags_down(flags)
                    elif etype in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp):
                        key = Quartz.CGEventGetIntegerValueField(
                            event, Quartz.kCGKeyboardEventKeycode
                        )
                        if key == key_code:
                            self._hotkey_down = etype == Quartz.kCGEventKeyDown
                elif etype == Quartz.kCGEventFlagsChanged and key_code in _MODIFIER_KEY_CODES:
                    key = Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGKeyboardEventKeycode
                    )
                    if key == key_code:
                        flags = Quartz.CGEventGetFlags(event)
                        if self._key_spec in ("right_option", "roption"):
                            self._hotkey_down = bool(flags & alternate_mask)
                        else:
                            self._hotkey_down = not self._hotkey_down
                elif etype in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp):
                    key = Quartz.CGEventGetIntegerValueField(
                        event, Quartz.kCGKeyboardEventKeycode
                    )
                    if key == key_code:
                        self._hotkey_down = etype == Quartz.kCGEventKeyDown
            except Exception:  # noqa: BLE001
                pass
            return event

        mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
            | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        )
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            mask,
            _callback,
            None,
        )
        if not tap:
            self._enabled = False
            self._tap_ready = False
            _hotkey_log(
                "event tap unavailable; grant Accessibility/Input Monitoring to Solar.app"
            )
            self._started.set()
            return
        self._tap_ready = True
        _hotkey_log(f"event tap ready key={self._key_spec} code={key_code}")
        self._started.set()
        loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(), loop_source, Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(tap, True)
        Quartz.CFRunLoopRun()
