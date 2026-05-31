#!/usr/bin/env python3
"""Shared HTTP dispatch for Solar Interface API (Host :9000 and legacy daemon :7741)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Callable
from urllib.parse import urlparse

from interface_store import InterfaceStore, now_iso

EventCallback = Callable[[str, dict], None]

INTERFACE_ROOT_PATHS = frozenset({"/ready", "/status", "/threads", "/runs", "/approvals"})


def strip_solar_tags(text: str) -> str:
    text = re.sub(r"\s*<solar_decision>[^<]*</solar_decision>", "", text)
    text = re.sub(r"\s*<solar_summary>.*?</solar_summary>", "", text, flags=re.DOTALL)
    return text.strip()


def is_interface_path(path: str) -> bool:
    if path in INTERFACE_ROOT_PATHS:
        return True
    if path.startswith("/threads/") or path.startswith("/runs/"):
        return True
    if path.startswith("/approvals/"):
        return True
    return False


class HttpAdapter:
    """Minimal response adapter for BaseHTTPRequestHandler subclasses."""

    def __init__(
        self,
        handler: BaseHTTPRequestHandler,
        *,
        service_name: str = "solar-interface",
        host_port: int | None = None,
    ) -> None:
        self.handler = handler
        self.service_name = service_name
        self.host_port = host_port

    @property
    def raw_wfile(self):
        return self.handler.wfile

    def send_json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.handler.send_response(status)
        self.handler.send_header("Content-Type", "application/json; charset=utf-8")
        self.handler.send_header("Content-Length", str(len(raw)))
        self.handler.end_headers()
        self.handler.wfile.write(raw)

    def send_html(self, html: str, status: int = 200) -> None:
        raw = html.encode("utf-8")
        self.handler.send_response(status)
        self.handler.send_header("Content-Type", "text/html; charset=utf-8")
        self.handler.send_header("Content-Length", str(len(raw)))
        self.handler.end_headers()
        self.handler.wfile.write(raw)

    def read_json(self) -> tuple[dict | None, str | None]:
        length = int(self.handler.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}, None
        raw = self.handler.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw), None
        except json.JSONDecodeError as exc:
            snippet = raw[:200].replace("\n", "\\n")
            print(
                f"Invalid JSON body on {self.handler.command} {self.handler.path}: {exc.msg}; raw={snippet!r}",
                file=sys.stderr,
                flush=True,
            )
            return None, f"Invalid JSON body: {exc.msg}"

    def send_sse_headers(self, run_id: str) -> None:
        self.handler.send_response(200)
        self.handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.handler.send_header("Cache-Control", "no-cache")
        self.handler.send_header("X-Run-Id", run_id)
        self.handler.end_headers()


class InterfaceHttpDispatcher:
    def __init__(
        self,
        store: InterfaceStore,
        *,
        on_event: EventCallback | None = None,
    ) -> None:
        self.store = store
        self.on_event = on_event

    def _emit(self, event_type: str, payload: dict) -> None:
        if self.on_event:
            self.on_event(event_type, payload)

    def _service_label(self, adapter: HttpAdapter) -> str:
        if adapter.service_name == "host":
            return "solar-host"
        return "solar-interface"

    def _status_port(self, adapter: HttpAdapter, env: dict) -> int:
        if adapter.service_name == "host" and adapter.host_port is not None:
            return adapter.host_port
        return int(env.get("SOLAR_INTERFACE_PORT", "7741"))

    def handle_get(self, adapter: HttpAdapter, path: str) -> bool:
        store = self.store
        env = store.env
        service = self._service_label(adapter)

        if path == "/ready":
            ready, checks = store.readiness()
            status = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
            adapter.send_json(
                {
                    "status": "ready" if ready else "not_ready",
                    "service": service,
                    "ts": now_iso(),
                    "checks": checks,
                },
                status,
            )
            return True

        if path == "/status":
            ready, checks = store.readiness()
            runs = store.list_rows(
                "SELECT run_id, status, provider_used, thread_id, started_at FROM runs ORDER BY started_at DESC LIMIT 10"
            )
            host = env.get("SOLAR_INTERFACE_HOST", "127.0.0.1")
            port = self._status_port(adapter, env)
            adapter.send_json(
                {
                    "status": "ok",
                    "service": service,
                    "ready": ready,
                    "pid": os.getpid(),
                    "host": host,
                    "port": port,
                    "runtime_dir": str(store.runtime_dir.relative_to(store.workspace)),
                    "db_path": str(store.db_path.relative_to(store.workspace)),
                    "checks": checks,
                    "runs": runs,
                }
            )
            return True

        if path == "/threads":
            adapter.send_json({"threads": store.list_threads()})
            return True

        if path == "/runs":
            adapter.send_json({"runs": store.list_runs()})
            return True

        if path.startswith("/threads/") and path.endswith("/runs"):
            tid = path.strip("/").split("/")[1]
            adapter.send_json({"runs": store.list_thread_runs(tid)})
            return True

        if path.startswith("/threads/"):
            parts = path.strip("/").split("/")
            if len(parts) == 2:
                tid = parts[1]
                thread = store.get_thread(tid)
                if not thread:
                    adapter.send_json({"error": "Thread not found"}, 404)
                    return True
                adapter.send_json({"thread": thread})
                return True

        if path == "/approvals":
            adapter.send_json({"approvals": store.list_approvals()})
            return True

        if path.startswith("/runs/"):
            run_id = path.split("/", 2)[2]
            run = store.get_run(run_id)
            if not run:
                adapter.send_json({"error": "Run not found"}, 404)
                return True
            adapter.send_json({"run": run})
            return True

        return False

    def handle_post(self, adapter: HttpAdapter, path: str) -> bool:
        store = self.store
        data, read_error = adapter.read_json()
        if read_error:
            adapter.send_json({"error": read_error}, 400)
            return True
        assert data is not None

        if path == "/threads":
            thread = store.create_thread(
                title=data.get("title"),
                scope_layer=data.get("scope_layer", "sun"),
                scope_planet=data.get("scope_planet"),
            )
            adapter.send_json({"thread": thread}, 201)
            return True

        if path.startswith("/threads/") and path.endswith("/stream"):
            thread_id = path.strip("/").split("/")[1]
            if not store.get_thread(thread_id):
                adapter.send_json({"error": "Thread not found"}, 404)
                return True
            self._stream_run(adapter, thread_id, data)
            return True

        if path.startswith("/threads/") and path.endswith("/runs"):
            thread_id = path.strip("/").split("/")[1]
            if not store.get_thread(thread_id):
                adapter.send_json({"error": "Thread not found"}, 404)
                return True
            run_record, router_response = store.run_thread_message(
                thread_id=thread_id,
                mode=data.get("mode", "ask"),
                text=data.get("text", ""),
                provider=data.get("provider", "auto"),
            )
            reply_text = router_response.get("reply_text", "")
            status = 200 if run_record.get("status") == "succeeded" else 502
            run_status = run_record.get("status", "failed")
            event_type = "run.completed" if run_status == "succeeded" else "run.failed"
            self._emit(
                event_type,
                {
                    "run_id": run_record.get("run_id"),
                    "thread_id": thread_id,
                    "status": run_status,
                },
            )
            adapter.send_json(
                {"run": run_record, "reply_text": reply_text, "router": router_response},
                status,
            )
            return True

        if path.startswith("/approvals/") and path.endswith("/approve"):
            approval_id = path.strip("/").split("/")[1]
            payload, err_code = store.approve(approval_id)
            if err_code is None or err_code == 200:
                self._emit(
                    "approval.resolved",
                    {"approval_id": approval_id, "action": "approve", "status": payload.get("status")},
                )
            adapter.send_json(payload, err_code or 200)
            return True

        if path.startswith("/approvals/") and path.endswith("/reject"):
            approval_id = path.strip("/").split("/")[1]
            payload, err_code = store.reject(approval_id)
            if err_code is None or err_code == 200:
                self._emit(
                    "approval.resolved",
                    {"approval_id": approval_id, "action": "reject", "status": payload.get("status")},
                )
            adapter.send_json(payload, err_code or 200)
            return True

        return False

    def handle_delete(self, adapter: HttpAdapter, path: str) -> bool:
        store = self.store

        if path.startswith("/threads/"):
            thread_id = path.strip("/").split("/")[1]
            try:
                result = store.delete_thread(thread_id)
            except KeyError:
                adapter.send_json({"error": "Thread not found"}, 404)
                return True
            except ValueError as exc:
                adapter.send_json(
                    {"error": f"Thread has a non-terminal run: {exc}"},
                    HTTPStatus.CONFLICT,
                )
                return True

            adapter.send_json({"status": "deleted", **result})
            return True

        return False

    def dispatch_get(self, adapter: HttpAdapter, raw_path: str) -> bool:
        path = urlparse(raw_path).path
        return self.handle_get(adapter, path)

    def dispatch_post(self, adapter: HttpAdapter, raw_path: str) -> bool:
        path = urlparse(raw_path).path
        return self.handle_post(adapter, path)

    def dispatch_delete(self, adapter: HttpAdapter, raw_path: str) -> bool:
        path = urlparse(raw_path).path
        return self.handle_delete(adapter, path)

    def _stream_run(self, adapter: HttpAdapter, thread_id: str, data: dict) -> None:
        store = self.store
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        request_id = f"req_{uuid.uuid4().hex[:10]}"
        started_at = now_iso()
        provider = data.get("provider", "auto")
        text = data.get("text", "")
        mode = data.get("mode", "ask")

        conn = store.connect_db()
        try:
            conn.execute(
                "INSERT INTO runs(run_id, request_id, thread_id, status, provider_requested, provider_used, router_id, pid, started_at, ended_at, summary, error) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL)",
                (run_id, request_id, thread_id, "running", provider, started_at),
            )
            conn.commit()
        finally:
            conn.close()

        store.write_event(run_id, {"type": "run_created", "run_id": run_id, "ts": started_at})
        store.write_event(run_id, {"type": "status_changed", "run_id": run_id, "status": "running", "ts": started_at})
        store.write_event(run_id, {"type": "input_received", "run_id": run_id, "text": text, "ts": started_at})
        input_path = store.write_user_input(run_id, text)

        router_text = store.build_thread_context(thread_id, text, mode)
        payload = {
            "request_id": request_id,
            "session_id": thread_id,
            "user_id": thread_id,
            "text": router_text,
            "channel": "other",
            "mode": "direct_only",
            "stream": True,
        }
        if provider and provider != "auto":
            payload["provider"] = provider

        adapter.send_sse_headers(run_id)

        proc = subprocess.Popen(
            ["python3", str(store.router_script)],
            cwd=str(store.workspace),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        proc.stdin.write(json.dumps(payload, ensure_ascii=False))  # type: ignore[union-attr]
        proc.stdin.close()  # type: ignore[union-attr]

        full_text_parts: list[str] = []
        provider_used: str | None = None
        usage: dict | None = None
        status = "failed"
        error: str | None = None
        client_disconnected = False
        in_solar_tag = False
        wfile = adapter.raw_wfile

        try:
            for raw_line in proc.stdout:  # type: ignore[union-attr]
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "chunk":
                    chunk = event.get("text", "")
                    if not chunk:
                        continue
                    full_text_parts.append(chunk)
                    if in_solar_tag:
                        continue
                    tag_start = chunk.find("<solar_")
                    if tag_start != -1:
                        in_solar_tag = True
                        visible = chunk[:tag_start]
                        if not visible:
                            continue
                        chunk = visible
                    try:
                        sse = f"data: {json.dumps({'type': 'chunk', 'text': chunk}, ensure_ascii=False)}\n\n"
                        wfile.write(sse.encode("utf-8"))
                        wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        client_disconnected = True
                elif event.get("type") == "done":
                    status = event.get("status", "failed")
                    provider_used = event.get("provider")
                    event_usage = event.get("usage")
                    if isinstance(event_usage, dict):
                        usage = event_usage
                    error = event.get("error")

            proc.wait()
        except (BrokenPipeError, ConnectionResetError):
            client_disconnected = True
            status = "failed"
            error = "client disconnected"
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)

        reply_text = strip_solar_tags("".join(full_text_parts))
        ended_at = now_iso()
        run_dir = store.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        if reply_text and not client_disconnected:
            (run_dir / "output.md").write_text(reply_text, encoding="utf-8")

        conn = store.connect_db()
        try:
            conn.execute(
                "UPDATE runs SET status = ?, provider_used = ?, ended_at = ?, summary = ?, error = ? WHERE run_id = ?",
                (status, provider_used, ended_at, reply_text[:200] if reply_text else None, error, run_id),
            )
            conn.execute(
                "INSERT INTO artifacts(artifact_id, run_id, kind, path, title, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"artifact_{uuid.uuid4().hex[:10]}",
                    run_id,
                    "request",
                    str(input_path.relative_to(store.workspace)),
                    "User input",
                    started_at,
                ),
            )
            if reply_text and not client_disconnected:
                conn.execute(
                    "INSERT INTO artifacts(artifact_id, run_id, kind, path, title, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        f"artifact_{uuid.uuid4().hex[:10]}",
                        run_id,
                        "response",
                        str((run_dir / "output.md").relative_to(store.workspace)),
                        "Run output",
                        ended_at,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        store.update_thread_last_run(thread_id, run_id)

        event_type = "run.completed" if status == "succeeded" else "run.failed"
        self._emit(
            event_type,
            {
                "run_id": run_id,
                "thread_id": thread_id,
                "status": status,
                "provider": provider_used,
            },
        )

        if not client_disconnected:
            done_evt = json.dumps(
                {
                    "type": "done",
                    "run_id": run_id,
                    "provider": provider_used,
                    "status": status,
                    "usage": usage,
                    "error": error,
                },
                ensure_ascii=False,
            )
            try:
                wfile.write(f"data: {done_evt}\n\n".encode("utf-8"))
                wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
