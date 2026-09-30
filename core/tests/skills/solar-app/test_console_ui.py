"""The console page is the design, served locally, and it only calls /api/console/*."""
import json
import re
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[3] / "skills/solar-app/scripts"
ASSETS = SCRIPTS.parent / "assets"
sys.path.insert(0, str(SCRIPTS))
import host_server
from http.server import ThreadingHTTPServer

QUESTIONS = (
    "¿Está sana mi instalación, y desde cuándo no hace nada?",
    "¿Qué tareas hay y qué les ha pasado?",
    "¿Qué ha ejecutado Solar y cómo le ha ido?",
    "¿Dónde se quedó?",
    "¿Qué hace Solar sin preguntarme?",
    "¿Qué ve cada IDE?",
    "¿Qué puede entrar desde fuera?",
    "¿Quién pidió esto?",
)
ROUTES = (
    "/api/console/health",
    "/api/console/tasks",
    "/api/console/executions",
    "/api/console/continuity",
    "/api/console/mandates",
    "/api/console/ides",
    "/api/console/ingress",
    "/api/console/requester",
)
EXTERNAL = re.compile(r"https?://|fonts\.googleapis|cdn\.", re.I)
API_PATH = re.compile(r"""['"](/api/[^'"]+)['"]""")


class ConsoleUiTests(unittest.TestCase):
    def test_page_has_no_external_host_and_calls_only_console_routes(self):
        html = (ASSETS / "app.html").read_text(encoding="utf-8")
        css = (ASSETS / "app.css").read_text(encoding="utf-8")
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="health"', html)
        self.assertNotIn("<textarea", html)
        self.assertNotIn("data-action=", html)
        self.assertIsNone(EXTERNAL.search(html))
        self.assertIsNone(EXTERNAL.search(css))
        self.assertIsNone(EXTERNAL.search(js))
        self.assertIn("/assets/fonts/inter.woff2", css)
        self.assertIn("/assets/fonts/montserrat.woff2", css)
        self.assertIn(".t-dark", css)
        self.assertIn(".t-light", css)
        for question in QUESTIONS:
            self.assertIn(question, js)
        paths = API_PATH.findall(js)
        self.assertCountEqual(set(paths), set(ROUTES))
        for banned in ("/api/app/", "/api/runtime/", "/api/async/", "stampOpts", "Caducado",
                       "5f951e37-ebd2-4399-bc58-9fe8c9a5a7e8",
                       "bc4bb31d-d500-4bd0-a992-e5ad0840776b",
                       "calendar-busy-sync"):
            self.assertNotIn(banned, js)
            self.assertNotIn(banned, html)
        self.assertIn("Europe/Madrid", js)
        self.assertIn("30000", js)
        self.assertIn("refused", js)
        copy = js + "\n" + html
        self.assertNotIn("Mandatos A3", copy)
        for token in ("A0", "A1", "A2", "A3", "A4"):
            self.assertIsNone(re.search(rf"\b{token}\b", copy), token)

    def test_app_serves_the_console_and_its_fonts(self):
        with patch.object(host_server, "_active_workspace", return_value=ASSETS):
            server = ThreadingHTTPServer(("127.0.0.1", 0), host_server.HostHandler)
            port = server.server_address[1]
            with patch.object(host_server, "PORT", port):
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    base = "http://127.0.0.1:" + str(port)
                    with urllib.request.urlopen(base + "/app") as response:
                        html = response.read().decode()
                        self.assertIn("text/html", response.headers.get("Content-Type", ""))
                    self.assertIn('id="health"', html)
                    self.assertIn('href="/app.css"', html)
                    self.assertIn('src="/app.js"', html)
                    self.assertIsNone(EXTERNAL.search(html))
                    for path, magic, mime in (
                        ("/app.js", b"/api/console/health", "javascript"),
                        ("/app.css", b"/assets/fonts/inter.woff2", "text/css"),
                        ("/assets/fonts/inter.woff2", b"wOF2", "font/woff2"),
                        ("/assets/fonts/montserrat.woff2", b"wOF2", "font/woff2"),
                        ("/assets/fonts/OFL.txt", b"SIL OPEN FONT LICENSE", "text/plain"),
                    ):
                        with urllib.request.urlopen(base + path) as response:
                            body = response.read()
                            self.assertIn(mime, response.headers.get("Content-Type", ""))
                        self.assertIn(magic, body)
                    for path in ("/assets/fonts/../app.html", "/assets/fonts/inter.woff2/../../app.js"):
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(base + path)
                        self.assertEqual(raised.exception.code, 404)
                        raised.exception.close()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()


    def test_screens_follow_the_routes(self):
        result = subprocess.run(
            ["node", "-e", _JS_HARNESS, str(ASSETS / "app.js")],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(report, {"ok": True})


_JS_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const checks = [
  { id: "database", state: "ok" },
  { id: "port", state: "ok" },
  { id: "system", state: "ok" },
  { id: "router", state: "ok" },
  { id: "launchagent", state: "ok" },
  { id: "gateway", state: "ok" },
];
const health = {
  verdict: {
    verdict: "calm", label: "calm", reasons: [], unverified: [], checks,
    launchagent: { state: "observed", at: "2026-09-29T09:00:00Z", age_seconds: 40 },
    gateway: { state: "healthy", connector_ready: true, local_health: true, processes_alive: true, processes: {} },
  },
  version: "v0", mode: "global", owner: null, cutover: null, backups: [],
  stamp: { features: { "async-tasks": "ok" } }, last_activity: {}, continuity_at: null,
  continuity_age_seconds: null, database: null,
  language: "en",
  attention: "All working · 7 tasks in error · 15 drafts · no activity for 4 days",
};
const tasks = {
  tasks: [
    { id: "err-1", status: "error", title: "Broken", provider: null, channel: null, created_at: "2026-04-01", updated_at: "2026-09-01", recurring: false, parent_id: null },
    { id: "ok-1", status: "completed", title: "Finished", provider: null, channel: null, created_at: "2026-04-02", updated_at: "2026-09-02", recurring: false, parent_id: null },
  ],
  by_status: { error: { n: 1, recurring: 0 }, completed: { n: 1, recurring: 0 } },
  links: [], history: [],
  statuses: ["draft", "planned", "queued", "active", "completed", "error", "archived", "cancelled"],
  transitions: [],
};
const ingress = { claim_telegram: false, stamp: null, hostname: null };

function boot(routes) {
  const els = {};
  const clicks = [];
  function make(id) {
    const node = { id, innerHTML: "", textContent: "", className: "" };
    node.addEventListener = () => {};
    els[id] = node;
    return node;
  }
  const sandbox = {
    document: {
      getElementById(id) { return els[id] || make(id); },
      addEventListener(type, fn) { if (type === "click") clicks.push(fn); },
    },
    location: { host: "127.0.0.1:9000" },
    fetch(url) {
      const hit = routes[url];
      if (!hit) return Promise.reject(new Error("missing " + url));
      const status = hit.status || 200;
      return Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(hit.body) });
    },
    setInterval() { return 1; },
    clearInterval() {},
    localStorage: { getItem() { return null; }, setItem() {} },
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return {
    document: sandbox.document,
    els,
    click(attrs) {
      const target = {
        getAttribute(name) { return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null; },
        closest(sel) {
          const name = (String(sel).match(/\[([^\]=\s]+)/) || [])[1];
          return name && Object.prototype.hasOwnProperty.call(attrs, name) ? target : null;
        },
      };
      clicks.forEach((fn) => fn({ target }));
    },
  };
}
function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}
async function settled() {
  await flush();
  await flush();
  await flush();
}

(async () => {
  const calm = { "/api/console/health": { body: health } };
  let page = boot(Object.assign({}, calm));
  await settled();
  const summary = page.els.health.innerHTML;
  ["Database", "Port 9000", "System", "Router", "LaunchAgent", "Gateway"].forEach((name) => {
    if (!summary.includes("✓ " + name)) throw new Error("calm summary omits " + name);
  });
  if (!summary.includes(health.attention)) throw new Error("summary did not show the attention line");
  if (!summary.includes("The last thing Solar was holding when you spoke to it through Telegram, n8n, or a task.")) {
    throw new Error("summary continuity card has no explanation");
  }
  if (summary.includes("async-tasks")) throw new Error("feature id stayed visible");
  if (!summary.includes("Background tasks ok")) throw new Error("feature was not named");
  if (page.els.title.textContent !== "Summary") throw new Error("opened on " + page.els.title.textContent);
  if (page.document.title !== "Solar local console") throw new Error("browser title stayed " + page.document.title);

  page = boot(Object.assign({ "/api/console/tasks": { body: tasks } }, calm));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  if (page.els.title.textContent !== "Tasks") throw new Error("nav did not open tasks");
  if (!page.els.health.innerHTML.includes("Broken")) throw new Error("attention filter hid the error");
  if (page.els.health.innerHTML.includes("Finished")) throw new Error("attention filter showed a completed task");
  page.click({ "data-filter": "completed" });
  await settled();
  const filtered = page.els.health.innerHTML;
  if (!filtered.includes("Finished")) throw new Error("completed filter hid the visible task");
  if (filtered.includes("Broken")) throw new Error("detail kept a task outside the filter");

  page = boot(Object.assign({ "/api/console/tasks": { body: tasks } }, calm));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-filter": "todos" });
  page.click({ "data-task": "ok-1" });
  page.click({ "data-filter": "error" });
  const selected = page.els.health.innerHTML;
  if (!selected.includes("Broken") || selected.includes("Finished")) throw new Error("detail stayed on the hidden task");

  const refused = { "/api/console/tasks": { status: 503, body: { error: "state lock missing", refused: true } } };
  page = boot(Object.assign({}, calm, refused));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  const denied = page.els.health.innerHTML;
  if (!denied.includes("state lock missing") || !denied.includes("The route refused")) throw new Error("503 did not show the refusal");
  if (denied.includes("Showing")) throw new Error("503 rendered an empty task list");

  const live = {
    "/api/console/health": { body: health },
    "/api/console/ingress": { body: ingress },
  };
  page = boot(live);
  await settled();
  live["/api/console/health"] = { status: 503, body: { error: "health refused now", refused: true } };
  page.click({ "data-screen": "entrada" });
  await settled();
  const entry = page.els.health.innerHTML;
  if (!entry.includes("health refused now")) throw new Error("entrada hid the current health refusal");
  if (entry.includes("Connector ready")) throw new Error("entrada reused a stale gateway");

  page = boot(Object.assign({
    "/api/console/continuity": { body: { at: "not-a-date", active: "sigue aqui", channels: [], summaries: [] } },
  }, calm));
  await settled();
  page.click({ "data-screen": "continuidad" });
  await settled();
  const continuity = page.els.health.innerHTML;
  if (!continuity.includes("sigue aqui") || !continuity.includes("no data")) throw new Error("invalid continuity date broke the screen");
  if (!continuity.includes("The last thing Solar was holding when you spoke to it through Telegram, n8n, or a task.")) {
    throw new Error("continuity screen has no explanation");
  }
  if (!continuity.includes("Saved text, not a message from this console.")) {
    throw new Error("active intention is not marked as saved text");
  }

  const mandates = {
    defined: [
      { name: "live-one", file: "live-one.yaml", mode: "active", revoked_at: null },
      { name: "old-one", file: "old-one.yaml", mode: "revoked", revoked_at: "2026-09-01T00:00:00Z" },
      { name: "trial-one", file: "trial-one.yaml", mode: "shadow", revoked_at: null },
      { name: "paused-one", file: "paused-one.yaml", mode: "paused", revoked_at: null },
      { name: "dated-one", file: "dated-one.yaml", mode: "active", revoked_at: "2026-09-01T00:00:00Z" },
    ],
    active: 1,
    events: {},
    gate: {
      total: 1,
      allowed: 0,
      last: [{ ts: "2026-09-01T00:00:00Z", tool: "solar_task_approve", allowed: false, code: "a3_refused" }],
    },
  };
  page = boot(Object.assign({ "/api/console/mandates": { body: mandates } }, calm));
  await settled();
  page.click({ "data-screen": "autonomia" });
  await settled();
  const autonomy = page.els.health.innerHTML;
  if (!autonomy.includes("Delegations")) throw new Error("delegations section missing");
  if (autonomy.includes("Mandatos A3") || /\bA[0-4]\b/.test(autonomy)) throw new Error("authority code on the page");
  if (!autonomy.includes("1 active")) throw new Error("revoked delegation counted as active");
  if (autonomy.includes("2 active")) throw new Error("active count included a revoked delegation");
  if (!autonomy.includes("Trial (no real effects)")) throw new Error("shadow mode was not named");
  if (!autonomy.includes("Paused")) throw new Error("paused mode was not named");
  if (!autonomy.includes('class="row dim"')) throw new Error("revoked row is not dimmed");
  const revokedAt = autonomy.indexOf("old-one");
  const revokedRow = autonomy.slice(autonomy.lastIndexOf("<div", revokedAt), autonomy.indexOf("trial-one"));
  if (!revokedRow.includes("Revoked on")) throw new Error("revoked row has no revocation date");
  if (revokedRow.includes(">Active<") || revokedRow.includes(" Active")) throw new Error("revoked row looks active");
  const datedAt = autonomy.indexOf("dated-one");
  const datedRow = autonomy.slice(autonomy.lastIndexOf('<div class="row', datedAt), datedAt + 500);
  if (!datedRow.includes("dim")) throw new Error("revoked_at with mode active is not dimmed");
  if (!datedRow.includes("Revoked")) throw new Error("revoked_at row is not labeled revoked");
  if (datedRow.includes("Active")) throw new Error("revoked_at row still looks active");
  if (autonomy.includes("a3_refused")) throw new Error("gate code stayed visible");
  if (!autonomy.includes("Approving a task is outside a delegation")) throw new Error("gate reason was not named");

  const spanishHealth = Object.assign({}, health, { language: "es" });
  page = boot({ "/api/console/health": { body: spanishHealth } });
  await settled();
  if (page.els.title.textContent !== "Resumen") throw new Error("spanish setting left the title in English");
  if (page.document.title !== "Consola local de Solar") throw new Error("browser title stayed " + page.document.title);
  if (!page.els.health.innerHTML.includes("Lo último que Solar tenía entre manos cuando le hablaste por Telegram, n8n o una tarea.")) {
    throw new Error("spanish setting left the continuity card in English");
  }
  console.log(JSON.stringify({ ok: true }));
})().catch((error) => {
  console.error(error && error.stack || error);
  process.exit(1);
});
"""


if __name__ == "__main__":
    unittest.main()
