#!/usr/bin/env python3
"""macOS phrase-streaming TTS for Solar voice (AVSpeechSynthesizer with fallbacks)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
from typing import List, Optional

_FLUSH_RE = re.compile(r"[.!?\n]")
_MAX_PHRASE = 120


class PhraseBuffer:
    """Accumulate SSE chunks; flush speakable phrases on punctuation or length."""

    def __init__(self, *, max_chars: int = _MAX_PHRASE) -> None:
        self._buf = ""
        self._max = max_chars

    def feed(self, text: str) -> List[str]:
        self._buf += text
        out: List[str] = []
        while True:
            m = _FLUSH_RE.search(self._buf)
            if m:
                idx = m.end()
                phrase = self._buf[:idx].strip()
                self._buf = self._buf[idx:]
                if phrase:
                    out.append(phrase)
                continue
            if len(self._buf) >= self._max:
                phrase = self._buf[: self._max].strip()
                self._buf = self._buf[self._max :]
                if phrase:
                    out.append(phrase)
                continue
            break
        return out

    def flush_remaining(self) -> Optional[str]:
        tail = self._buf.strip()
        self._buf = ""
        return tail or None


def avfoundation_available() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import AVFoundation  # noqa: F401, PLC0415

        return True
    except ImportError:
        return False


def speak_batch_fallback(text: str) -> None:
    if shutil.which("say"):
        subprocess.run(["say", text], check=False)


class StreamingSpeaker:
    """Queue phrases for AVSpeechSynthesizer; falls back to `say` per phrase."""

    def __init__(self) -> None:
        self._buffer = PhraseBuffer()
        self._lock = threading.Lock()
        self._stopped = False
        self._synth = None
        self._use_av = avfoundation_available() and os.environ.get(
            "SOLAR_VOICE_TTS", "stream"
        ).strip().lower() not in ("batch", "off", "0")
        if self._use_av:
            try:
                import AVFoundation  # noqa: PLC0415

                self._synth = AVFoundation.AVSpeechSynthesizer.alloc().init()
            except Exception:  # noqa: BLE001
                self._use_av = False

    def feed(self, chunk: str) -> None:
        if self._stopped or os.environ.get("SOLAR_VOICE_TTS", "").strip().lower() in (
            "off",
            "0",
        ):
            return
        for phrase in self._buffer.feed(chunk):
            self._speak_phrase(phrase)

    def stop(self) -> None:
        self._stopped = True
        if self._synth is not None:
            try:
                self._synth.stopSpeakingAtBoundary_(0)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    def finish(self) -> None:
        tail = self._buffer.flush_remaining()
        if tail and not self._stopped:
            self._speak_phrase(tail)

    def _speak_phrase(self, phrase: str) -> None:
        with self._lock:
            if self._stopped:
                return
            if self._use_av and self._synth is not None:
                try:
                    import AVFoundation  # noqa: PLC0415

                    utterance = AVFoundation.AVSpeechUtterance.speechUtteranceWithString_(
                        phrase
                    )
                    self._synth.speakUtterance_(utterance)  # type: ignore[attr-defined]
                    return
                except Exception:  # noqa: BLE001
                    pass
            speak_batch_fallback(phrase)


_speaker: Optional[StreamingSpeaker] = None


def streaming_speaker() -> StreamingSpeaker:
    global _speaker  # noqa: PLW0603
    if _speaker is None:
        _speaker = StreamingSpeaker()
    return _speaker


def reset_streaming_speaker() -> None:
    global _speaker  # noqa: PLW0603
    if _speaker is not None:
        _speaker.stop()
    _speaker = None
