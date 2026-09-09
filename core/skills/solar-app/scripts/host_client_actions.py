#!/usr/bin/env python3
"""Loopback, Host and Origin validation for the local console."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_loopback_client(handler: Any) -> bool:
    addr = str(getattr(handler, "client_address", ("", 0))[0] or "")
    return addr in (*_LOCAL_HOSTS, "")


def _local_hostname(hostname: str) -> bool:
    return (hostname or "").lower().strip("[]") in _LOCAL_HOSTS


def validate_origin(handler: Any, host_port: int) -> bool:
    origin = (handler.headers.get("Origin") or "").strip()
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
        return _local_hostname(parsed.hostname or "") and parsed.port in (None, host_port)
    except ValueError:
        return False


def validate_host_header(handler: Any, host_port: int) -> bool:
    raw = (handler.headers.get("Host") or "").strip()
    if not raw or ("@" not in raw and "/" not in raw and " " not in raw):
        try:
            parsed = urlparse("//" + raw)
            return not raw or (_local_hostname(parsed.hostname or "") and parsed.port in (None, host_port))
        except ValueError:
            return False
    return False


def validate_client_request(handler: Any, host_port: int) -> bool:
    return validate_origin(handler, host_port) and validate_host_header(handler, host_port)
