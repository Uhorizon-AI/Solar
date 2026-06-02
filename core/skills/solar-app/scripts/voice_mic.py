#!/usr/bin/env python3
"""macOS microphone permission helpers for Solar voice (Solar.app + tray)."""
from __future__ import annotations

import threading
from typing import Optional, Tuple

# AVAuthorizationStatus (AVFoundation)
_AUTH_NOT_DETERMINED = 0
_AUTH_RESTRICTED = 1
_AUTH_DENIED = 2
_AUTH_AUTHORIZED = 3


def microphone_status() -> Tuple[str, bool]:
    """Return (human label, granted)."""
    try:
        import AVFoundation  # noqa: PLC0415

        status = AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(
            AVFoundation.AVMediaTypeAudio
        )
    except Exception:  # noqa: BLE001
        return ("unknown", True)

    labels = {
        _AUTH_NOT_DETERMINED: "not_determined",
        _AUTH_RESTRICTED: "restricted",
        _AUTH_DENIED: "denied",
        _AUTH_AUTHORIZED: "authorized",
    }
    label = labels.get(int(status), f"status_{status}")
    return label, label == "authorized"


def ensure_microphone_access(*, timeout: float = 120.0) -> bool:
    """Prompt for mic access if needed; return True when authorized."""
    label, granted = microphone_status()
    if granted:
        return True
    if label in ("denied", "restricted"):
        return False
    try:
        import AVFoundation  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return True

    done = threading.Event()
    result: list[bool] = [False]

    def _handler(granted: bool) -> None:
        result[0] = bool(granted)
        done.set()

    AVFoundation.AVCaptureDevice.requestAccessForMediaType_completion_(
        AVFoundation.AVMediaTypeAudio,
        _handler,
    )
    done.wait(timeout=timeout)
    return result[0]


def microphone_hint_for_denied() -> str:
    return (
        "Ajustes → Privacidad → Micrófono: activa Solar. "
        "Cierra y vuelve a abrir Solar.app tras conceder permiso."
    )
