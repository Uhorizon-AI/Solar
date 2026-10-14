"""Read-only routes for the existing status, activity and execution log views."""
from pathlib import Path
import logging

import app_solar
import console_data
import solar_state
import operation_dashboards
from task_markdown import render_markdown

LOGGER = logging.getLogger("solar.app")
ASSETS = Path(__file__).resolve().parent.parent / "assets"


def get(handler, path, qs, workspace):
    if path.startswith('/dashboards/'):
        try:
            body, mime = operation_dashboards.published_dashboard_file(workspace, path)
        except operation_dashboards.PublicationUnavailable:
            handler._send_json({'error': 'Dashboard unavailable'}, 503)
            return
        except (OSError, ValueError, TypeError):
            handler._send_json({'error': 'Dashboard unavailable'}, 404)
            return
        handler.send_response(200)
        handler.send_header('Content-Type', mime)
        handler.send_header('Content-Length', str(len(body)))
        handler.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox")
        handler.send_header('X-Content-Type-Options', 'nosniff')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('Referrer-Policy', 'no-referrer')
        handler.end_headers()
        handler.wfile.write(body)
        return
    if path == '/api/console/dashboards':
        try:
            handler._send_json(operation_dashboards.dashboard_index(workspace))
        except (OSError, ValueError, TypeError):
            handler._send_json({'error': 'Dashboard settings unavailable', 'refused': True}, 503)
        return
    if path in ("/", "/dashboard"):
        handler.send_response(302)
        handler.send_header("Location", "/app")
        handler.end_headers()
        return
    if path in ("/app", "/app.js", "/app.css"):
        asset = {"/app": "app.html", "/app.js": "app.js", "/app.css": "app.css"}[path]
        mime = "text/javascript" if asset.endswith(".js") else "text/css" if asset.endswith(".css") else "text/html"
        handler._send((ASSETS / asset).read_bytes(), content_type=mime + "; charset=utf-8")
        return
    fonts = {
        "/assets/fonts/inter.woff2": ("fonts/inter.woff2", "font/woff2"),
        "/assets/fonts/montserrat.woff2": ("fonts/montserrat.woff2", "font/woff2"),
        "/assets/fonts/OFL.txt": ("fonts/OFL.txt", "text/plain; charset=utf-8"),
    }
    if path in fonts:
        name, mime = fonts[path]
        handler._send((ASSETS / name).read_bytes(), content_type=mime)
        return
    if path == "/health":
        handler._send_json({"service": "solar-console", "status": "available", "process_ok": True,
                            "workspace": str(workspace)})
        return
    if path == "/api/app/activity":
        value = lambda key, default='': qs.get(key, [default])[0]
        offset = max(0, int(value('offset', '0')))
        limit = min(100, max(1, int(value('limit', '40'))))
        handler._send_json(app_solar.activity_page(Path(workspace), value('source'), value('state'), offset, limit))
        return
    if path == "/api/console/task-detail":
        task_id = qs.get("task_id", [""])[0]
        if not task_id or len(task_id) > 200:
            handler._send_json({"error": "A bounded task_id is required"}, 400)
            return
        full = qs.get("full") == ["1"]
        try:
            result = console_data.task_detail(Path(workspace), task_id, full)
        except Exception as exc:  # any unexpected read or decode failure: fixed text, no detail
            # Route-specific line (the body says "Task detail unavailable"); the generic handler in
            # host_server logs "console route ... failed". Class only, never the message.
            LOGGER.warning("task-detail failed: %s", type(exc).__name__)
            handler._send_json({"error": "Task detail unavailable", "refused": True}, 503)
            return
        if result is None:
            handler._send_json({"error": "Task not found"}, 404)
            return
        if full:
            result["body_html"] = render_markdown(result["record"].get("body"))
        handler._send_json(result)
        return
    console = {
        "/api/console/health": console_data.health,
        "/api/console/tasks": console_data.tasks,
        "/api/console/executions": console_data.executions,
        "/api/console/continuity": console_data.continuity,
        "/api/console/mandates": console_data.mandates,
        "/api/console/ides": console_data.ides,
        "/api/console/ingress": console_data.ingress,
        "/api/console/requester": console_data.requester,
    }
    if path in console:
        try:
            handler._send_json(console[path](Path(workspace)))
        except solar_state.StateError as exc:
            handler._send_json({"error": str(exc), "refused": True}, 503)
        return
    if path in ("/api/app/bootstrap", "/api/app/logs", "/api/async/jobs", "/api/runtime/health"):
        data = app_solar.snapshot(Path(workspace))
        if path == "/api/runtime/health":
            payload = {"service": "solar-console", **data["health"], "workspace": str(workspace), "solar_root": data["solar_root"]}
            handler._send_json(payload, 200 if payload["storage_ok"] else 503)
        elif path == "/api/async/jobs":
            handler._send_json({"jobs": data["tasks"], "checked_at": data["checked_at"]})
        else:
            handler._send_json(data)
        return
    handler._send_json({"error": "Not found"}, 404)
