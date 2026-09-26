"""Read-only routes for the existing status, activity and execution log views."""
from pathlib import Path
import app_solar

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def get(handler, path, qs, workspace):
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
