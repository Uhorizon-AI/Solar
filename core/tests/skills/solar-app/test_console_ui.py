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
    "/api/console/task-detail?task_id=",
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
  links: [], history: [{ task_id: "err-1", ts: "2026-09-01T10:00:00Z", from_status: "active", to_status: "error", actor: "history-fixture" }],
  statuses: ["draft", "planned", "queued", "active", "completed", "error", "archived", "cancelled"],
  transitions: [],
};
const ingress = { claim_telegram: false, stamp: null, hostname: null };

function boot(routes) {
  const els = {};
  const clicks = [];
  const requests = [];
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
      requests.push(url);
      let hit = routes[url];
      if (hit && Array.isArray(hit.sequence)) hit = hit.sequence.length > 1 ? hit.sequence.shift() : hit.sequence[0];
      if (!hit) return Promise.reject(new Error("missing " + url));
      const status = hit.status || 200;
      const reply = () => Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(hit.body) });
      return hit.hold ? hit.hold.then(reply) : reply();
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
    requests,
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

  const need = (html, text, why) => { if (!html.includes(text)) throw new Error(why + ": missing " + text); };
  const lack = (html, text, why) => { if (html.includes(text)) throw new Error(why + ": found " + text); };
  const curated = {
    id: "err-1",
    context: {
      agent: "fixture-agent",
      planet: "fixture-planet",
      continuity_checkpoint: {
        next_check: { action: "Compare the weekly report", at: "2026-10-13" },
        wait: "<script>waiting()</script>",
      },
    },
    context_error: null,
    configuration: {
      scheduled_time: "09:30", scheduled_timezone: "Europe/Madrid", scheduled_weekdays: [1, 3],
      recurring_max_runs: 5, resources: ["res-a", "res-b"],
    },
  };
  const complete = Object.assign({}, curated, {
    record: {
      id: "err-1", agent: "fixture",
      future_column: { nested: "2026-10-14", zero: 0, flag: false },
      frontmatter: [["unknown_field", "<script>unsafe()</script>"], ["broken", { detail: "still visible" }], null],
      body: "# Instructions", empty: null,
    },
    body_html: "<h1>Instructions</h1><p>Safe body</p>",
  });
  const detailRoutes = (extra) => Object.assign({
    "/api/console/tasks": { body: tasks },
    "/api/console/task-detail?task_id=err-1": { body: curated },
    "/api/console/task-detail?task_id=err-1&full=1": { body: complete },
  }, extra || {}, calm);

  page = boot(detailRoutes({
    "/api/console/task-detail?task_id=ok-1": {
      body: { id: "ok-1", context: null, context_error: null, configuration: { scheduled_time: "07:00" } },
    },
  }));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  let view = page.els.health.innerHTML;
  need(view, "Context and follow-up", "curated title");
  need(view, "<dt>Agent</dt><dd>fixture-agent</dd>", "curated agent");
  need(view, "Compare the weekly report", "next check");
  need(view, "2026-10-13", "check date");
  need(view, "&lt;script&gt;waiting()&lt;/script&gt;", "escaped wait");
  lack(view, "<script>waiting", "curated block escaping");
  need(view, "09:30", "configured time");
  need(view, "Europe/Madrid", "stored zone");
  need(view, "1, 3", "weekdays");
  need(view, "res-a, res-b", "resources");
  need(view, "does not verify an effect", "effect note");
  need(view, "history-fixture", "stored history actor");
  need(view, ">History<", "history heading");
  need(view, "Active → Error", "history transition");
  need(view, "Complete record", "full record button");
  need(view, 'aria-expanded="false"', "button collapsed");
  lack(view, "future_column", "record before click");
  lack(view, "Safe body", "body before click");
  lack(view, "task-markdown", "body container before click");
  if (page.requests.some((url) => url.includes("full=1"))) throw new Error("full=1 requested before the click");

  page.click({ "data-full": "err-1" });
  await settled();
  view = page.els.health.innerHTML;
  if (!page.requests.includes("/api/console/task-detail?task_id=err-1&full=1")) throw new Error("click did not request full=1");
  if (page.requests.filter((url) => url.includes("full=1")).length !== 1) throw new Error("full=1 requested more than once");
  need(view, 'aria-expanded="true"', "button expanded");
  need(view, "future_column", "future column");
  need(view, "2026-10-14", "nested value");
  need(view, "unknown_field", "unknown frontmatter field");
  need(view, "still visible", "malformed entry");
  need(view, "<dd><span", "scalar values");
  need(view, ">false<", "false value");
  need(view, ">0<", "zero value");
  need(view, ">null<", "null value");
  need(view, "<dt>Instructions</dt>", "body label");
  need(view, '<div class="task-markdown"><h1>Instructions</h1><p>Safe body</p></div>', "body html");
  need(view, "&lt;script&gt;unsafe()&lt;/script&gt;", "escaped frontmatter");
  lack(view, "<script>unsafe", "frontmatter escaping");
  need(view, "history-fixture", "history after the click");
  page.click({ "data-full": "err-1" });
  view = page.els.health.innerHTML;
  lack(view, "future_column", "record after collapsing");
  need(view, 'aria-expanded="false"', "button collapsed again");
  page.click({ "data-full": "err-1" });
  await settled();
  need(page.els.health.innerHTML, "future_column", "record reopened from cache");
  if (page.requests.filter((url) => url.includes("full=1")).length !== 1) throw new Error("reopening refetched the record");

  page.click({ "data-filter": "todos" });
  page.click({ "data-task": "ok-1" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, "07:00", "second task time");
  need(view, "Host timezone (no stored zone)", "zone fallback");
  need(view, "No recorded context", "empty context note");
  lack(view, "future_column", "record leaked to another task");

  const broken = { id: "err-1", context: null, context_error: "checkpoint_invalid", configuration: curated.configuration };
  page = boot(detailRoutes({ "/api/console/task-detail?task_id=err-1": { body: broken } }));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, "continuity checkpoint is not valid", "localized checkpoint error");
  lack(view, "checkpoint_invalid", "raw error code");
  need(view, "09:30", "configuration beside the error");
  need(view, "history-fixture", "history beside the error");
  const unknownCode = Object.assign({}, broken, { context_error: "surprise_code" });
  page = boot(detailRoutes({ "/api/console/task-detail?task_id=err-1": { body: unknownCode } }));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, "context could not be read", "generic error");
  lack(view, "surprise_code", "unknown error code");
  need(view, "09:30", "configuration beside the generic error");

  page = boot(detailRoutes({
    "/api/console/task-detail?task_id=err-1": { status: 503, body: { error: "Task detail unavailable", refused: true } },
    "/api/console/task-detail?task_id=err-1&full=1": { status: 503, body: { error: "Task detail unavailable", refused: true } },
  }));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, "context could not be read.", "refused curated block");
  need(view, "history-fixture", "history after refusal");
  page.click({ "data-full": "err-1" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, "The complete record could not be read.", "refused complete record");
  lack(view, "future_column", "record after refusal");

  const spanishTasks = Object.assign({}, tasks, { language: "es" });
  page = boot(detailRoutes({
    "/api/console/tasks": { body: spanishTasks },
    "/api/console/task-detail?task_id=err-1": { body: Object.assign({}, curated, { configuration: { scheduled_time: "09:30" } }) },
  }));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, "Contexto y seguimiento", "spanish title");
  need(view, "<dt>Agente</dt>", "spanish agent label");
  need(view, "Próxima comprobación", "spanish next check");
  need(view, "Zona del equipo (sin zona guardada)", "spanish zone fallback");
  need(view, "no verifica el efecto", "spanish effect note");
  need(view, "Registro completo", "spanish button");
  page.click({ "data-full": "err-1" });
  await settled();
  need(page.els.health.innerHTML, "<dt>Instrucciones</dt>", "spanish body label");

  // Recurring cadence is visible even without a fixed time.
  const cadence = (extra) => Object.assign({}, curated, { context: null, configuration: extra });
  const interval = async (configuration, language) => {
    const tasksFor = language ? Object.assign({}, tasks, { language }) : tasks;
    const open = boot(detailRoutes({
      "/api/console/tasks": { body: tasksFor },
      "/api/console/task-detail?task_id=err-1": { body: cadence(configuration) },
    }));
    await settled();
    open.click({ "data-screen": "tareas" });
    await settled();
    return open.els.health.innerHTML;
  };
  view = await interval({ recurring: "true", recurring_min_interval: "86400" });
  need(view, "<dt>Recurrence</dt><dd>Recurring</dd>", "recurrence");
  need(view, "<dt>Minimum interval</dt><dd>24 h</dd>", "daily cadence without a fixed time");
  need(await interval({ recurring: true, recurring_min_interval: "5400" }), "<dd>90 min</dd>", "minutes");
  need(await interval({ recurring: "true", recurring_min_interval: 45 }), "<dd>45 s</dd>", "seconds");
  lack(await interval({ recurring: "false" }), "Minimum interval", "no interval when none stored");
  lack(await interval({ recurring_min_interval: "soon" }), "Minimum interval", "unreadable interval");
  view = await interval({ recurring: "true", recurring_min_interval: "86400" }, "es");
  need(view, "<dt>Intervalo mínimo</dt><dd>24 h</dd>", "spanish cadence");
  need(view, "<dt>Recurrencia</dt><dd>Recurrente</dd>", "spanish recurrence");

  // A newer updated_at refreshes the data but keeps the open record open.
  const newer = JSON.parse(JSON.stringify(tasks));
  newer.tasks[0].updated_at = "2026-09-05";
  let release;
  const hold = new Promise((resolve) => { release = resolve; });
  page = boot(detailRoutes({ "/api/console/tasks": { sequence: [{ body: tasks }, { body: newer, hold }] } }));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-screen": "resumen" });
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-full": "err-1" });
  await settled();
  need(page.els.health.innerHTML, "future_column", "record open before the refresh");
  const fullCount = () => page.requests.filter((url) => url.includes("full=1")).length;
  const curatedCount = () => page.requests.filter((url) => url === "/api/console/task-detail?task_id=err-1").length;
  const before = [fullCount(), curatedCount()];
  release();
  await settled();
  view = page.els.health.innerHTML;
  need(view, 'aria-expanded="true"', "record stays open after the refresh");
  need(view, "future_column", "record reloaded after the refresh");
  if (fullCount() !== before[0] + 1 || curatedCount() !== before[1] + 1) throw new Error("newer updated_at must reload each block once: " + JSON.stringify([before, fullCount(), curatedCount(), page.requests]));

  // An older "Complete record" response that arrives last must not replace the newer one.
  const marked = (label) => Object.assign({}, complete, { record: Object.assign({}, complete.record, { future_column: label }) });
  let releaseTasks, releaseOld, releaseNew;
  const holdTasks = new Promise((resolve) => { releaseTasks = resolve; });
  const holdOld = new Promise((resolve) => { releaseOld = resolve; });
  const holdNew = new Promise((resolve) => { releaseNew = resolve; });
  page = boot(detailRoutes({
    "/api/console/tasks": { sequence: [{ body: tasks }, { body: newer, hold: holdTasks }] },
    "/api/console/task-detail?task_id=err-1&full=1": { sequence: [{ body: marked("OLD-RESPONSE"), hold: holdOld }, { body: marked("NEW-RESPONSE"), hold: holdNew }] },
  }));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-screen": "resumen" });
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-full": "err-1" });
  await settled();
  releaseTasks();
  await settled();
  if (page.requests.filter((url) => url.includes("full=1")).length !== 2) throw new Error("the newer updated_at must start a second record request");
  releaseNew();
  await settled();
  need(page.els.health.innerHTML, "NEW-RESPONSE", "newer record response");
  releaseOld();
  await settled();
  view = page.els.health.innerHTML;
  need(view, "NEW-RESPONSE", "newer record survives the late old response");
  lack(view, "OLD-RESPONSE", "late old response");

  // Context in an unexpected shape is announced, never drawn as raw objects.
  const shaped = async (context, language) => {
    const open = boot(detailRoutes({
      "/api/console/tasks": { body: language ? Object.assign({}, tasks, { language }) : tasks },
      "/api/console/task-detail?task_id=err-1": { body: { id: "err-1", context, context_error: null, configuration: {} } },
    }));
    await settled();
    open.click({ "data-screen": "tareas" });
    await settled();
    return open.els.health.innerHTML;
  };
  const odd = { continuity_checkpoint: { next_check: "tomorrow", decision: "someone", wait: { nested: { deep: 1 } } } };
  view = await shaped(odd);
  need(view, "open it in Complete record", "unshown context note");
  lack(view, "native code", "inherited members of a string are not read");
  lack(view, "No recorded context", "context exists but is not shown");
  lack(view, "[object", "no raw objects");
  lack(view, "nested", "raw nested keys");
  need(await shaped(odd, "es"), "ábrelos en Registro completo", "spanish unshown note");
  need(await shaped({}), "No recorded context", "truly empty context");
  need(await shaped(null), "No recorded context", "null context");
  lack(await shaped({ agent: "shown-agent", continuity_checkpoint: { next_check: "tomorrow" } }), "open it in Complete record", "no note when something is shown");

  // workspace_id is part of the contract and is shown.
  view = await shaped({ workspace_id: "ws-fixture-1", agent: "fixture-agent" });
  need(view, "<dt>Workspace</dt><dd>ws-fixture-1</dd>", "workspace id");
  need(await shaped({ workspace_id: "ws-fixture-1" }, "es"), "<dt>Espacio de trabajo</dt><dd>ws-fixture-1</dd>", "spanish workspace id");

  // A context or configuration that is not an object must not be read by key.
  const wrongShapes = async (context, configuration) => {
    const open = boot(detailRoutes({
      "/api/console/task-detail?task_id=err-1": { body: { id: "err-1", context, context_error: null, configuration } },
    }));
    await settled();
    open.click({ "data-screen": "tareas" });
    await settled();
    return open.els.health.innerHTML;
  };
  for (const [context, configuration] of [[[], "x"], ["text", []], [7, 7], [null, null], [["a"], { scheduled_time: "08:15" }]]) {
    view = await wrongShapes(context, configuration);
    need(view, "Context and follow-up", "block still drawn for " + JSON.stringify([context, configuration]));
    need(view, "history-fixture", "history still drawn");
    lack(view, "native code", "inherited members");
    lack(view, "undefined", "undefined text");
    lack(view, "[object", "raw objects");
  }
  need(await wrongShapes([], "x"), "No recorded context", "array context is empty context");
  need(await wrongShapes(["a"], { scheduled_time: "08:15" }), "08:15", "real configuration beside a wrong context");

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
