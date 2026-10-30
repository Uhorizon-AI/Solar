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
    "¿Dónde puedo trabajar con cada planeta?",
    "¿Qué hace Solar sin preguntarme?",
    "¿Qué ve cada app?",
    "¿Qué canales reciben encargos y cómo funcionan?",
    "¿Quién pidió esto?",
)
ROUTES = (
    "/api/console/health",
    "/api/console/tasks",
    "/api/console/task-detail?task_id=",
    "/api/console/executions",
    "/api/console/capacity",
    "/api/console/dashboards",
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


    def test_task_list_hides_provider_channel_and_requester_up_to_1600px(self):
        """Parses the CSS and the header markup, so spacing or ordering changes do not break it."""
        css = (ASSETS / "app.css").read_text(encoding="utf-8")
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        start = js.index('class="row hd trow"')
        order = re.findall(r't\("col_(\w+)"\)', js[start:js.index("rows.join", start)])
        self.assertEqual(len(order), 6)
        self.assertEqual(len(set(order)), 6, "six unique header columns")
        self.assertEqual(order, ["status", "task", "provider", "channel", "created", "requester"], "header column order")

        def block(source, opener):
            start = re.search(opener, source)
            self.assertIsNotNone(start, opener)
            depth, i = 0, start.end() - 1
            for j in range(i, len(source)):
                depth += {"{": 1, "}": -1}.get(source[j], 0)
                if depth == 0:
                    return source[i + 1:j]
            self.fail("unbalanced braces")

        media = block(css, r"@media\s*\(\s*max-width\s*:\s*1600px\s*\)\s*\{")
        self.assertEqual(len(re.findall(r"max-width\s*:\s*1600px", css)), 1)
        hidden = set()
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", media):
            if re.search(r"display\s*:\s*none", body):
                hidden |= {int(n) for n in re.findall(r"\.trow\s*>\s*div\s*:\s*nth-child\(\s*(\d+)\s*\)", selectors)}
        names = {order[i - 1] for i in hidden}
        self.assertEqual(names, {"provider", "channel", "requester"})
        self.assertEqual({n for n in order} - names, {"status", "task", "created"})

        def columns(body):
            value = re.search(r"\.trow\s*\{[^}]*grid-template-columns\s*:\s*([^;}]*)", body).group(1)
            return len(re.findall(r"(?:minmax\([^)]*\)|\S+)", value.strip()))

        self.assertEqual(columns(media), 3, "three columns up to 1600 px")
        self.assertEqual(columns(css.replace(media, "")), 6, "six columns when wider")

    def test_mobile_task_metrics_and_run_headers_survive_generic_row_rules(self):
        css = (ASSETS / "app.css").read_text(encoding="utf-8")
        # Match the small dedicated mobile override rather than another breakpoint.
        self.assertRegex(css, r"@media\s*\(max-width:760px\)\s*\{\s*\.task-when\s*\{[^}]*flex:1\s+1\s+100%")
        self.assertRegex(css, r"\.runs-scroll\s*\{[^}]*overflow-x:auto")
        rules = {selector.strip(): body for selector, body in
                 re.findall(r"([^{}]+)\{([^{}]*)\}", css)}
        # Both competing declarations are important. The runs-specific selectors
        # have more classes, so their grid headers win even inside the mobile media.
        for generic, specific in [(".row", ".runs-table .run-row"),
                                  (".row.hd", ".runs-table .run-row.hd")]:
            self.assertRegex(rules[generic], r"display:(?:flex|none)!important")
            self.assertRegex(rules[specific], r"display:grid!important")
            self.assertGreater(specific.count("."), generic.count("."))
        self.assertRegex(rules[".runs-table .run-row .opt"], r"display:block")

    def test_dashboard_cards_are_styled_for_the_dark_theme(self):
        css = (ASSETS / "app.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.rep a\{[^}]*color:var\(--info\)", "dashboard links use a theme token, not the browser blue")
        self.assertRegex(css, r"\.rep (?:h2|h3)\{[^}]*font-size:15px", "dashboard titles are not default headings")

    def test_filter_bar_styles_keep_the_agreed_rules(self):
        css = (ASSETS / "app.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.fchip:focus-visible[^{]*\{outline:2px solid var\(--text\)", "2 px light focus ring, not amber")
        self.assertRegex(css, r"\.fchip\{[^}]*flex:none", "chips never grow")
        self.assertRegex(css, r"\.fchip\.on\{[^}]*box-shadow:inset 0 -2px 0 var\(--brand\)", "amber 2 px underline on the selection")
        self.assertRegex(css, r"\.fchip \.fn\{[^}]*tabular-nums", "tabular numerals")
        self.assertRegex(css, r"\.sr-only\{[^}]*clip:rect\(0,0,0,0\)", "live region is out of sight but readable")
        narrow = re.search(r"@media \(max-width:900px\)\{(.*?)\n\}", css, re.S).group(1)
        self.assertIn("min-height:40px", narrow, "touch height when stacked")
        self.assertNotIn("display:contents", narrow, "the toolbar keeps its box so role=toolbar stays")
        self.assertRegex(narrow, r"\.ftool\{[^}]*flex:1 1 100%")
        self.assertRegex(narrow, r'\[data-filter="errors"\]\{order:1\}')
        self.assertRegex(narrow, r'\[data-filter="drafts"\],\.fchip\[data-filter="running"\]\{order:2\}', "Drafts and Running share the first mobile row")
        self.assertRegex(narrow, r"\.rsw\{order:3")
        # On desktop the switch is pushed to the bar's right edge (no media query); mobile
        # repeats it so it closes the first row after the primary chips.
        self.assertRegex(css, r"\.rsw\{[^}]*margin-left:auto", "the switch sits at the right edge on desktop")
        self.assertRegex(narrow, r"\.fbreak\{display:block;flex-basis:100%", "the rest of the chips drop to the second row")
        # At 800 px the first row is Errors, Drafts, Running and the Recurring switch. The
        # switch must sit inside the toolbar box (a sibling of the chips) and before the
        # .fbreak, or it cannot share that row; the box itself stays for role="toolbar".
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        bar = js[js.index('class="fbar"'):js.index("ui.chipKeys = filters")]
        self.assertIn('class="ftool" role="toolbar"', bar, "the toolbar keeps its box and role")
        self.assertLess(bar.index('class="fbreak"'), bar.index('class="rsw"'), "the switch stays on the first row")
        self.assertLess(bar.index("lead +"), bar.index('class="rsw"'), "the switch follows the primary chips")
        # The wide-bar comment must match the real breakpoint.
        self.assertRegex(css, r"from 1840 px[^*]*\*/\s*@media \(min-width:1840px\)", "comment matches the 1840 px value")
        # Red, blue and green belong to one thing each.
        self.assertRegex(css, r"\.fg\.err\{color:var\(--err\)\}")
        self.assertRegex(css, r"\.fg\.run\{color:var\(--info\)\}")
        self.assertRegex(css, r"\.fg\.ok\{color:var\(--ok\)\}")
        self.assertRegex(css, r"\.pill\.run\{color:var\(--info\)")

    def test_token_usage_scope_copy_in_both_languages_mentions_reviews(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        for text in ("task executions (questions and reviews)", "ejecuciones de tareas de Solar (preguntas y revisiones)"):
            self.assertIn(text, js)
        self.assertNotIn("async questions only", js)

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

function boot(routes, hash, clipboardMode) {
  const els = {};
  const clicks = [];
  const keys = [];
  const inputs = [];
  const copied = [];
  const location = { host: "127.0.0.1:9000", hash: hash || "" };
  const history = { replaceState(state, title, url) { location.hash = url; } };
  const requests = [];
  function make(id) {
    const node = { id, innerHTML: "", textContent: "", className: "" };
    node.addEventListener = () => {};
    els[id] = node;
    return node;
  }
  // The console captures document.activeElement before a repaint and calls .focus() on the
  // rebuilt chip, so the harness models focus: a focusable node is answered by querySelector
  // against the chips the current innerHTML holds.
  const chipsFrom = (html) => (html.match(/data-filter="([a-z]+)" data-chip="1"/g) || []).map((m) => m.match(/data-filter="([a-z]+)"/)[1]);
  const fake = (target) => {
    const attrs = target.kind === "search" ? { "data-task-search": "1" } : target.kind === "recurring" ? { "data-recurring": "1", "data-chip": null } : { "data-filter": target.key, "data-chip": "1" };
    return {
      selectionStart: target.start, selectionEnd: target.end,
      setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
      focus() { sandbox.document.activeElement = this; },
      getAttribute(name) { return attrs[name] == null ? null : attrs[name]; },
    };
  };
  function make(id) {
    let html = "";
    const node = {
      id, textContent: "", className: "",
      get innerHTML() { return html; },
      // Replacing the block drops any focused node inside it, as the real DOM does.
      set innerHTML(value) { html = value; if (sandbox.document.activeElement) sandbox.document.activeElement = null; },
      querySelector(sel) {
        if (/\[data-task-search\]/.test(sel)) return fake({ kind: "search" });
        if (/\[data-recurring\]/.test(sel)) return fake({ kind: "recurring" });
        const m = sel.match(/\[data-filter="([a-z]+)"\]/);
        return m && chipsFrom(html).includes(m[1]) ? fake({ kind: "filter", key: m[1] }) : null;
      },
    };
    node.addEventListener = () => {};
    els[id] = node;
    return node;
  }
  const sandbox = {
    document: {
      activeElement: null,
      getElementById(id) { return els[id] || make(id); },
      addEventListener(type, fn) { if (type === "click") clicks.push(fn); if (type === "keydown") keys.push(fn); if (type === "input") inputs.push(fn); },
    },
    location,
    history,
    navigator: clipboardMode === "missing" ? {} : { clipboard: { writeText(text) {
      if (clipboardMode === "rejected") return Promise.reject(new Error("clipboard denied"));
      copied.push(text); return Promise.resolve();
    } } },
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
    copied,
    input(value, caret) {
      const target = fake({ kind: "search", start: caret == null ? value.length : caret, end: caret == null ? value.length : caret });
      target.value = value;
      target.focus();
      inputs.forEach((fn) => fn({ target }));
    },
    get focusedSearch() { const a = sandbox.document.activeElement; return a && a.getAttribute("data-task-search") != null; },
    get searchCaret() { return sandbox.document.activeElement && sandbox.document.activeElement.selectionStart; },
    get focusedFilter() { const a = sandbox.document.activeElement; return a && a.getAttribute ? a.getAttribute("data-filter") : null; },
    get focusedRecurring() { const a = sandbox.document.activeElement; return a && a.getAttribute ? a.getAttribute("data-recurring") != null : false; },
    click(attrs) {
      const target = {
        setAttribute(name, value) { attrs[name] = value; },
        getAttribute(name) { return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null; },
        closest(sel) {
          const name = (String(sel).match(/\[([^\]=\s]+)/) || [])[1];
          return name && Object.prototype.hasOwnProperty.call(attrs, name) ? target : null;
        },
      };
      clicks.forEach((fn) => fn({ target }));
    },
    key(attrs, name) {
      const target = {
        getAttribute(attr) { return Object.prototype.hasOwnProperty.call(attrs, attr) ? attrs[attr] : null; },
        closest(sel) {
          const attr = (String(sel).match(/\[([^\]=\s]+)/) || [])[1];
          return attr && Object.prototype.hasOwnProperty.call(attrs, attr) ? target : null;
        },
      };
      let prevented = false;
      keys.forEach((fn) => fn({ target, key: name, preventDefault() { prevented = true; } }));
      return prevented;
    },
    location,
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
  if (summary.includes("The last thing Solar was holding")) throw new Error("global continuity card remained");
  if (summary.includes("async-tasks")) throw new Error("feature id stayed visible");
  if (!summary.includes("Background tasks ok")) throw new Error("feature was not named");
  if (page.els.title.textContent !== "Summary") throw new Error("opened on " + page.els.title.textContent);
  if (page.document.title !== "Solar local console") throw new Error("browser title stayed " + page.document.title);

  page = boot(Object.assign({ "/api/console/tasks": { body: tasks } }, calm));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  if (page.els.title.textContent !== "Tasks") throw new Error("nav did not open tasks");
  if (!page.els.health.innerHTML.includes("Broken")) throw new Error("default filter hid the error");
  if (page.els.health.innerHTML.includes("Finished")) throw new Error("default filter showed a completed task");
  page.click({ "data-filter": "done" });
  await settled();
  const filtered = page.els.health.innerHTML;
  if (!filtered.includes("Finished")) throw new Error("completed filter hid the visible task");
  if (filtered.includes("Broken")) throw new Error("detail kept a task outside the filter");

  page = boot(Object.assign({ "/api/console/tasks": { body: tasks } }, calm));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-filter": "all" });
  page.click({ "data-task": "ok-1" });
  page.click({ "data-filter": "errors" });
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

  // Tool metadata stays inert: only an exact loopback root becomes a link, and
  // the start command is shown as text for a registered surface only.
  page = boot(Object.assign({
    "/api/console/dashboards": { body: { dashboards: [
      { kind: "tool", id: "example:triage", planet: "example", title: "Triage", href: "http://127.0.0.1:8777/", mode: "interactive", registered: true, start_command: "python3 server.py <script>", description: "Contacts", owner: "Sales", updated_at: "Today" },
      { kind: "tool", id: "example:other", planet: "example", title: "Other", href: "https://example.com/", mode: "read_only", registered: false, start_command: null, description: "Unregistered", owner: "Sales", updated_at: "Today" },
      { kind: "file", id: "example:attention", planet: "example", title: "Attention", href: "/dashboards/example/attention", mode: "read_only", registered: false, start_command: null, description: "Daily view", owner: "CEO", updated_at: "2026-10-13" }
    ], errors: [] } }
  }, calm));
  await settled();
  page.click({ "data-screen": "dashboards" });
  await settled();
  const catalog = page.els.health.innerHTML;
  if (!catalog.includes('rel="noopener noreferrer"') || !catalog.includes('target="_blank"')) throw new Error("unsafe dashboard link");
  if (!catalog.includes("Interactive (can modify data in that tool)")) throw new Error("missing tool mode");
  if (!catalog.includes("Registered on this machine") || !catalog.includes("Not registered")) throw new Error("missing registration state");
  if (!catalog.includes("How to start (copy):") || !catalog.includes("python3 server.py")) throw new Error("missing start command");
  if (catalog.includes("&lt;script&gt;") === false) throw new Error("start command was not escaped");
  if (catalog.includes('href="https://example.com/"')) throw new Error("non-loopback tool link");
  // A file surface links to the console's own route and shows no registration text.
  if (!catalog.includes('href="/dashboards/example/attention"')) throw new Error("missing view link");
  if (!catalog.includes("View · Read only")) throw new Error("missing view label");
  const nav = page.els.nav.innerHTML;
  if (!(nav.indexOf('data-screen="tareas"') < nav.indexOf('data-screen="dashboards"') && nav.indexOf('data-screen="dashboards"') < nav.indexOf('data-screen="ejecuciones"'))) throw new Error("dashboard order");
  if (page.els.nav.innerHTML.includes('data-screen="continuidad"')) throw new Error("legacy navigation remained");

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
  curated.token_usage = {
    coverage: { input_tokens: { available: 1, launched: 2 } },
    subtotals: [
      { provider: "codex", model: "model-fixture", cli_version: "version-one", metrics: {} },
      { provider: "codex", model: "model-fixture", cli_version: "version-two", metrics: {} }
    ],
    attempts: [{ id: "attempt-fixture", execution_id: "activation-fixture", provider: "codex", model: "model-fixture",
      status: "success", coverage: "available", finished_at: "2026-10-24", metrics: { input_tokens: 0, output_tokens: 13 },
      observations: [{ original: { usage: { output_tokens: 13 }, event_id: "<script>unsafe()</script>" } }] },
      { id: "partial-fixture", execution_id: "activation-fixture", provider: "agent", coverage: "partial",
        status: "running", reason: "unfinished", metrics: {}, observations: [] },
      { id: "terminal-missing-fixture", execution_id: "activation-fixture", provider: "agent", coverage: "partial",
        status: "running", reason: "terminal_missing", metrics: {}, observations: [] },
      { id: "owner-lost-fixture", execution_id: "activation-fixture", provider: "agent", coverage: "partial",
        status: "failed", finished_at: "2026-10-25", capture_error: "owner_lost", reason: "owner_lost", metrics: {}, observations: [] },
      { id: "failed-fixture", execution_id: "activation-fixture", provider: "agent", coverage: "partial",
        status: "failed", finished_at: "2026-10-24", reason: "failed", metrics: {}, observations: [] }]
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
  need(view, "Token consumption", "token panel appears in task detail");
  need(view, "attempt-fixture", "attempt identity");
  need(view, "activation-fixture", "public activation identity");
  need(view, "<dd>0</dd>", "observed zero stays visible");
  need(view, "Not available", "missing counter stays absent");
  need(view, "Partial", "incomplete capture label");
  need(view, "Final measurement status was not saved", "unfinished reason remains visible");
  need(view, "Terminal event not received", "missing terminal reason remains visible");
  need(view, "Previous execution owner was lost", "capture error reason remains visible");
  need(view, "1 / 2", "coverage denominator is launched attempts");
  need(view, "Original measurement evidence", "evidence is expandable");
  need(view, "model-fixture · version-one", "first subtotal identifies CLI version");
  need(view, "model-fixture · version-two", "second subtotal identifies CLI version");
  const failedCapture = view.slice(view.indexOf("failed-fixture"));
  need(failedCapture, '<p class="note">Execution failed</p>', "finished failure explains status");
  lack(failedCapture, "Incomplete or interrupted capture", "finished failure is not a pending capture");
  lack(view, "<script>unsafe()", "evidence is escaped");

  need(view, "<dt class=\"k\">Agent</dt><dd>fixture-agent</dd>", "curated agent");
  need(view, "Compare the weekly report", "next check");
  need(view, "2026-10-13", "check date");
  need(view, "&lt;script&gt;waiting()&lt;/script&gt;", "escaped wait");
  lack(view, "<script>waiting", "curated block escaping");
  need(view, "09:30", "configured time");
  need(view, "Europe/Madrid", "stored zone");
  need(view, "<dt class=\"k\">Days</dt><dd>Mon, Wed</dd>", "weekday names");
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
  lack(view, "unknown_field", "frontmatter is folded by default");
  page.click({ "data-front": "err-1" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, "unknown_field", "unknown frontmatter field");
  need(view, "still visible", "malformed entry");
  need(view, "<dd><span", "scalar values");
  need(view, ">false<", "false value");
  need(view, ">0<", "zero value");
  need(view, ">null<", "null value");
  need(view, "<div class=\"lbl\">Instructions</div>", "body label");
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

  page.click({ "data-filter": "all" });
  page.click({ "data-task": "ok-1" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, "07:00", "second task time");
  need(view, "Host timezone (no stored zone)", "zone fallback");
  need(view, "No recorded checkpoint", "configuration without a checkpoint");
  lack(view, "No recorded context", "no contradictory note beside configured fields");
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
  need(view, "<dt class=\"k\">Agente</dt>", "spanish agent label");
  need(view, "Próxima comprobación", "spanish next check");
  need(view, "Zona del equipo (sin zona guardada)", "spanish zone fallback");
  need(view, "no verifica el efecto", "spanish effect note");
  need(view, "Registro completo", "spanish button");
  page.click({ "data-full": "err-1" });
  await settled();
  need(page.els.health.innerHTML, "<div class=\"lbl\">Instrucciones</div>", "spanish body label");

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
  need(view, "<dt class=\"k\">Recurrence</dt><dd>Recurring</dd>", "recurrence");
  need(view, "<dt class=\"k\">Minimum interval</dt><dd>24 h</dd>", "daily cadence without a fixed time");
  need(await interval({ recurring: true, recurring_min_interval: "5400" }), "<dd>90 min</dd>", "minutes");
  need(await interval({ recurring: "true", recurring_min_interval: 45 }), "<dd>45 s</dd>", "seconds");
  lack(await interval({ recurring: "false" }), "Minimum interval", "no interval when none stored");
  lack(await interval({ recurring_min_interval: "soon" }), "Minimum interval", "unreadable interval");
  view = await interval({ recurring: "true", recurring_min_interval: "86400" }, "es");
  need(view, "<dt class=\"k\">Intervalo mínimo</dt><dd>24 h</dd>", "spanish cadence");
  need(view, "<dt class=\"k\">Recurrencia</dt><dd>Recurrente</dd>", "spanish recurrence");

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
  need(view, "<dt class=\"k\">Workspace</dt><dd>ws-fixture-1</dd>", "workspace id");
  need(await shaped({ workspace_id: "ws-fixture-1" }, "es"), "<dt class=\"k\">Espacio de trabajo</dt><dd>ws-fixture-1</dd>", "spanish workspace id");

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

  // Message precedence: nothing / configuration only / unexpected shape.
  const configOnly = await wrongShapes({}, { recurring: "true", recurring_min_interval: "3600", recurring_max_runs: "0" });
  need(configOnly, "No recorded checkpoint", "configuration without checkpoint");
  lack(configOnly, "No recorded context", "no contradictory message beside configured fields");
  need(configOnly, "<dt class=\"k\">Maximum runs</dt><dd>Unlimited</dd>", "0 runs means unlimited");
  need(await wrongShapes({}, {}), "No recorded context", "nothing recorded at all");
  lack(await wrongShapes({}, {}), "Time zone", "no fallback zone without a configured time");
  need(await wrongShapes({}, { scheduled_time: "08:00" }), "Host timezone (no stored zone)", "fallback zone beside a configured time");
  need(await wrongShapes({}, { recurring_max_runs: 5 }), "<dd>5</dd>", "a real run limit is shown as is");

  // Weekday names, in both languages, with a fallback for odd values.
  const days = async (value, language) => {
    const open = boot(detailRoutes({
      "/api/console/tasks": { body: language ? Object.assign({}, tasks, { language }) : tasks },
      "/api/console/task-detail?task_id=err-1": { body: { id: "err-1", context: {}, context_error: null, configuration: { scheduled_weekdays: value } } },
    }));
    await settled();
    open.click({ "data-screen": "tareas" });
    await settled();
    return open.els.health.innerHTML;
  };
  need(await days([1, 2, 3, 4, 5, 6, 7]), "<dd>Mon, Tue, Wed, Thu, Fri, Sat, Sun</dd>", "all english names");
  need(await days("1,3, 5"), "<dd>Mon, Wed, Fri</dd>", "stored comma string");
  need(await days([5], "es"), "<dt class=\"k\">Días</dt><dd>vie</dd>", "spanish name");
  need(await days([1, 7], "es"), "<dd>lun, dom</dd>", "spanish names");
  need(await days([9, "x", 3]), "<dd>9, x, Wed</dd>", "odd values fall back to the raw token");
  lack(await days([]), "<dt class=\"k\">Days</dt>", "no days, no row");

  // The complete record keeps the frontmatter folded and the instructions apart.
  page = boot(detailRoutes());
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-full": "err-1" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, "future_column", "columns listed");
  need(view, "<div class=\"task-body\"><div class=\"lbl\">Instructions</div>", "instructions block");
  need(view, "<h1>Instructions</h1>", "markdown body");
  need(view, "Frontmatter", "frontmatter title");
  need(view, "data-front=\"err-1\" aria-expanded=\"false\"", "frontmatter folded");
  lack(view, "unknown_field", "frontmatter content hidden while folded");
  if (view.indexOf("task-body") > view.indexOf("task-front")) throw new Error("frontmatter must come after the instructions");
  page.click({ "data-front": "err-1" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, "data-front=\"err-1\" aria-expanded=\"true\"", "frontmatter unfolded");
  need(view, "unknown_field", "frontmatter content shown");
  need(view, "&lt;script&gt;unsafe()&lt;/script&gt;", "frontmatter escaped");
  lack(view, "<script>unsafe", "frontmatter not injected");
  need(view, "future_column", "columns remain after unfolding");
  page.click({ "data-front": "err-1" });
  await settled();
  lack(page.els.health.innerHTML, "unknown_field", "folded again");

  // The list adapts by class, not by inline widths.
  view = page.els.health.innerHTML;
  need(view, "class=\"row trow pick", "task rows use the responsive grid");
  need(view, "class=\"row hd trow\"", "header uses the responsive grid");
  lack(view, "grid-template-columns:108px", "no fixed inline columns on the list");

  // History: newest first, each event keeps its own date, the newest carries the highlight.
  const threeEvents = JSON.parse(JSON.stringify(tasks));
  threeEvents.history = [
    { task_id: "err-1", ts: "2026-09-01T08:00:00Z", from_status: null, to_status: "queued", actor: "first-actor" },
    { task_id: "err-1", ts: "2026-09-01T09:00:00Z", from_status: "queued", to_status: "active", actor: "second-actor" },
    { task_id: "err-1", ts: "2026-09-02T10:00:00Z", from_status: "active", to_status: "error", actor: "third-actor" },
    { task_id: "ok-1", ts: "2026-09-03T10:00:00Z", from_status: "active", to_status: "completed", actor: "other-task-actor" },
  ];
  page = boot(detailRoutes({ "/api/console/tasks": { body: threeEvents } }));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  view = page.els.health.innerHTML;
  const at = (text) => view.indexOf(text);
  if (!(at("third-actor") > 0 && at("third-actor") < at("second-actor") && at("second-actor") < at("first-actor"))) {
    throw new Error("history must list the newest event first");
  }
  lack(view, "other-task-actor", "another task's history");
  if (at('<div class="now"') < 0 || at('<div class="now"') > at("third-actor") || at('<div class="now"') < at("History")) {
    throw new Error("the newest event must carry the highlight");
  }
  if ((view.match(/class="now"/g) || []).length !== 1) throw new Error("exactly one highlighted event");
  need(view, "Active → Error · third-actor", "newest transition");
  need(view, "Queued → Active · second-actor", "middle transition");
  need(view, "Queued · first-actor", "first transition");
  // Dates are the events' own, in the same descending order.
  const dates = view.slice(at("History")).match(/<div class="note">[^<]*(?:Sept?|Oct)[^<]*<\/div>/g) || [];
  if (dates.length !== 3) throw new Error("each event keeps its date: " + JSON.stringify(dates));

  // Zero means no limit for any integer-valued zero; other values are shown as stored.
  const runs = async (value) => (await wrongShapes({}, { recurring_max_runs: value }));
  for (const zero of [0, "0", "00", " 0 ", 0.0]) {
    need(await runs(zero), "<dt class=\"k\">Maximum runs</dt><dd>Unlimited</dd>", "zero as " + JSON.stringify(zero));
  }
  for (const other of [-1, "abc", 1.5, 7, "10"]) {
    const html = await runs(other);
    need(html, "<dt class=\"k\">Maximum runs</dt><dd>" + other + "</dd>", "shown as stored: " + JSON.stringify(other));
    lack(html, "Unlimited", "not unlimited: " + JSON.stringify(other));
  }

  // Weekday tokens outside 1-7 are kept as they are beside valid ones.
  need(await days([0, 1, 8, true, 7]), "<dd>0, Mon, 8, true, Sun</dd>", "out-of-range tokens");
  need(await days("0, 3, x"), "<dd>0, Wed, x</dd>", "out-of-range tokens in a stored string");

  // The frontmatter folds when the record closes and survives a refresh while the record stays open.
  const newerAgain = JSON.parse(JSON.stringify(tasks));
  newerAgain.tasks[0].updated_at = "2026-09-09";
  let releaseAgain;
  const holdAgain = new Promise((resolve) => { releaseAgain = resolve; });
  page = boot(detailRoutes({ "/api/console/tasks": { sequence: [{ body: tasks }, { body: newerAgain, hold: holdAgain }] } }));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-screen": "resumen" });
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-full": "err-1" });
  await settled();
  page.click({ "data-front": "err-1" });
  await settled();
  need(page.els.health.innerHTML, "unknown_field", "frontmatter open before the refresh");
  releaseAgain();
  await settled();
  view = page.els.health.innerHTML;
  need(view, 'data-front="err-1" aria-expanded="true"', "frontmatter stays open across a refresh");
  need(view, "unknown_field", "frontmatter content after the refresh");
  page.click({ "data-full": "err-1" });
  await settled();
  page.click({ "data-full": "err-1" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, 'data-front="err-1" aria-expanded="false"', "frontmatter folds when the record closes");
  lack(view, "unknown_field", "folded content after reopening");
  // Toggling a frontmatter whose record state is unknown is a harmless no-op.
  page.click({ "data-front": "never-opened" });
  await settled();
  need(page.els.health.innerHTML, "Context and follow-up", "screen intact after a stray toggle");

  // ---- Status filter bar -------------------------------------------------------
  const STATES = ["draft", "planned", "queued", "active", "completed", "error", "archived", "cancelled"];
  const mk = (id, status, extra) => Object.assign({ id, status, title: "T-" + id, provider: null, channel: null, created_at: "2026-04-01", updated_at: "2026-09-01", recurring: false, parent_id: null }, extra || {});
  const fixture = (list) => {
    const by = {};
    list.forEach((task) => {
      by[task.status] = by[task.status] || { n: 0, recurring: 0 };
      by[task.status].n += 1;
      if (task.recurring) by[task.status].recurring += 1;
    });
    return { tasks: list, by_status: by, links: [], history: [], statuses: STATES, transitions: [] };
  };
  const open = async (body, options) => {
    const opened = boot(Object.assign({ "/api/console/tasks": { body: options && options.language ? Object.assign({}, body, { language: options.language }) : body } }, calm), options && options.hash, options && options.clipboardMode);
    await settled();
    opened.click({ "data-screen": "tareas" });
    await settled();
    return opened;
  };
  const chipKeys = (html) => (html.match(/data-chip="1"/g) ? (html.match(/data-filter="([a-z]+)" data-chip="1"/g) || []).map((m) => m.match(/data-filter="([a-z]+)"/)[1]) : []);
  const selectedChip = (html) => (html.match(/data-filter="([a-z]+)" data-chip="1" aria-pressed="true"/) || [])[1];
  const rowsOf = (html) => (html.match(/class="row trow[^"]*" data-task="([^"]+)"/g) || []).map((m) => m.match(/data-task="([^"]+)"/)[1]);
  const everything = fixture([
    mk("d1", "draft"), mk("d2", "draft"), mk("p1", "planned", { recurring: true }), mk("q1", "queued"), mk("a1", "active", { recurring: true }),
    mk("c1", "completed"), mk("c2", "completed", { recurring: true }), mk("e1", "error", { recurring: true }), mk("e2", "error"),
    mk("x1", "cancelled"), mk("x2", "archived", { recurring: true }),
  ]);

  // Groups, order and what each one holds.
  page = await open(everything);
  view = page.els.health.innerHTML;
  if (JSON.stringify(chipKeys(view)) !== JSON.stringify(["errors", "running", "drafts", "queue", "done", "closed", "all"])) throw new Error("chips: " + JSON.stringify(chipKeys(view)));
  need(view, 'aria-label="Errors, 2 tasks"', "errors label with count");
  need(view, 'aria-label="Running, 1 task"', "running label, singular");
  need(view, 'aria-label="Drafts, 2 tasks"', "drafts label");
  need(view, 'aria-label="Queue, 2 tasks"', "queue = planned + queued");
  need(view, 'aria-label="Done, 2 tasks"', "done = completed only");
  need(view, 'aria-label="Closed, 2 tasks"', "closed = cancelled + archived");
  need(view, 'aria-label="All, 11 tasks"', "all");
  lack(view, "Attention", "no derived Attention chip");
  lack(view, "↻1", "no per-chip recurring counters");
  const groupRows = {};
  for (const key of ["errors", "running", "drafts", "queue", "done", "closed", "all"]) {
    page.click({ "data-filter": key });
    groupRows[key] = rowsOf(page.els.health.innerHTML).sort();
  }
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  if (!same(groupRows.errors, ["e1", "e2"]) || !same(groupRows.running, ["a1"]) || !same(groupRows.drafts, ["d1", "d2"])) throw new Error("rows by group: " + JSON.stringify(groupRows));
  if (!same(groupRows.queue, ["p1", "q1"]) || !same(groupRows.done, ["c1", "c2"]) || !same(groupRows.closed, ["x1", "x2"])) throw new Error("rows by group: " + JSON.stringify(groupRows));
  if (groupRows.all.length !== 11) throw new Error("All lists every task");
  // Every row keeps its real status as a pill with glyph and text.
  page.click({ "data-filter": "all" });
  view = page.els.health.innerHTML;
  for (const [cls, glyph, word] of [["err", "▲", "Error"], ["run", "▶", "Active"], ["draft", "◌", "Draft"], ["plain", "◷", "Planned"], ["plain", "≡", "Queued"],
    ["plain", "✓", "Completed"], ["dim", "⊘", "Cancelled"], ["dim", "▭", "Archived"]]) {
    need(view, '<span class="pill ' + cls + '">' + glyph + " " + word + "</span>", "row pill " + word);
  }
  // Recurring mark after the id, always visible, labelled, not a pill.
  need(view, '<span class="rmark" role="img" aria-label="recurring">↻</span>', "recurring mark");

  // Default filter: first non-empty of Errors, Running, Drafts; else All. Decided at each opening.
  const only = (statuses) => fixture(statuses.map((status, i) => mk("s" + i, status)));
  page = await open(everything);
  if (selectedChip(page.els.health.innerHTML) !== "errors") throw new Error("default with errors");
  page = await open(only(["active", "draft", "completed"]));
  if (selectedChip(page.els.health.innerHTML) !== "running") throw new Error("default with only running and drafts");
  page = await open(only(["draft", "completed", "planned"]));
  if (selectedChip(page.els.health.innerHTML) !== "drafts") throw new Error("default with only drafts");
  page = await open(only(["completed", "planned", "cancelled"]));
  if (selectedChip(page.els.health.innerHTML) !== "all") throw new Error("default with the three empty");
  page = await open(only([]));
  if (selectedChip(page.els.health.innerHTML) !== "all") throw new Error("default with no tasks");
  // Nothing is remembered between openings.
  page = await open(everything);
  page.click({ "data-filter": "closed" });
  page.click({ "data-screen": "resumen" });
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  if (selectedChip(page.els.health.innerHTML) !== "errors") throw new Error("the filter must be decided again at each opening");

  // Hide at 0 except Errors and the selected group; Running only exists with active tasks.
  page = await open(only(["completed", "completed"]));
  view = page.els.health.innerHTML;
  if (JSON.stringify(chipKeys(view)) !== JSON.stringify(["errors", "done", "all"])) throw new Error("hidden groups: " + JSON.stringify(chipKeys(view)));
  need(view, "✓", "zero errors shows a check");
  need(view, '<span class="fg ok" aria-hidden="true">✓</span><span class="fl">Errors</span> <b class="fn">0</b>', "Errors 0 with a green check");
  lack(view, "fchip fill on bad", "Errors 0 is not red");
  lack(page.els.health.innerHTML, 'data-filter="running"', "no Running chip without active tasks");
  page = await open(everything);
  need(page.els.health.innerHTML, 'data-filter="running"', "Running chip with an active task");
  need(page.els.health.innerHTML, "fchip fill on bad", "Errors with N > 0 is red and selected by default");
  lack(page.els.health.innerHTML, 'data-filter="done" data-chip="1" aria-pressed="true"', "only the selected chip is pressed");
  // A selected group stays even when it empties.
  page = await open(only(["completed"]), { hash: "#tasks/running" });
  view = page.els.health.innerHTML;
  if (selectedChip(view) !== "running") throw new Error("a selected group stays at 0");
  need(view, "No tasks.", "empty selected group says so");

  // Zero errors selected: good news with a link to the next pending group.
  page = await open(only(["draft", "draft", "completed"]));
  page.click({ "data-filter": "errors" });
  view = page.els.health.innerHTML;
  need(view, "No tasks in error", "good-news title");
  need(view, "Nothing needs retrying.", "good-news hint");
  lack(view, 'role="status"', "the panel is not a second status region");
  need(page.els.live.textContent, "No tasks in error", "the live region alone announces the good news");
  need(view, '<button type="button" class="fnext" data-filter="drafts">Next pending: Drafts (2)</button>', "link to the next pending group");
  lack(view, "No tasks.", "not a bare empty state");
  page.click({ "data-filter": "drafts" });
  if (selectedChip(page.els.health.innerHTML) !== "drafts") throw new Error("the link selects the group");
  page = await open(only(["completed"]), { hash: "#tasks/errors" });
  need(page.els.health.innerHTML, "No tasks in error", "good news with nothing pending");
  lack(page.els.health.innerHTML, "fnext", "no link when nothing is pending");
  page = await open(only(["draft"]), { hash: "#tasks/errors", language: "es" });
  need(page.els.health.innerHTML, "No hay tareas con error", "spanish good news");
  need(page.els.health.innerHTML, "Nada que reintentar.", "spanish hint");
  need(page.els.health.innerHTML, "Siguiente pendiente: Borradores (1)", "spanish next link");
  // With the Recurring switch on, empty Errors means no recurring error, not no error at all.
  page = await open(only(["draft"]), { hash: "#tasks/errors+recurring" });
  view = page.els.health.innerHTML;
  need(view, "No recurring tasks in error", "recurring good-news title");
  need(view, "Nothing recurring needs retrying.", "recurring good-news hint");
  lack(view, "No tasks in error", "not the plain error message while the switch is on");
  page = await open(only(["draft"]), { hash: "#tasks/errors+recurring", language: "es" });
  need(page.els.health.innerHTML, "No hay tareas recurrentes con error", "spanish recurring good news");

  // Subtasks: a parent expands under All and hiding happens per task, not per parent.
  const tree = {
    tasks: [mk("rp", "planned", { recurring: true, title: "Parent-recurring" }), mk("rc", "planned", { title: "Child-plain", parent_id: "rp" })],
    by_status: { planned: { n: 2, recurring: 1 } }, links: [{ parent_id: "rp", child_id: "rc" }], history: [], statuses: STATES, transitions: [],
  };
  page = await open(tree);
  page.click({ "data-filter": "all" });
  view = page.els.health.innerHTML;
  if (!same(rowsOf(view).sort(), ["rc", "rp"])) throw new Error("parent and child both list: " + JSON.stringify(rowsOf(view)));
  need(view, "└ ", "child is indented");
  need(view, "Showing 2 of 2", "parent and child both count");
  // The switch hides the non-recurring child from the list; the parent stays (it matches).
  page.click({ "data-recurring": "1" });
  view = page.els.health.innerHTML;
  if (!same(rowsOf(view).sort(), ["rp"])) throw new Error("the switch filters the child row out: " + JSON.stringify(rowsOf(view)));
  need(view, "Parent-recurring", "recurring parent stays");
  need(view, "Showing 1 of 1", "the count follows the switch");
  // A parent kept only as context for a matching child is not a member of the group,
  // so the "Showing N of M" never counts it (no more "Showing 2 of 1").
  const context = {
    tasks: [mk("cp", "planned", { title: "Context-parent" }), mk("ce", "error", { title: "Error-child", parent_id: "cp" })],
    by_status: { planned: { n: 1, recurring: 0 }, error: { n: 1, recurring: 0 } }, links: [{ parent_id: "cp", child_id: "ce" }], history: [], statuses: STATES, transitions: [],
  };
  page = await open(context);
  page.click({ "data-filter": "errors" });
  view = page.els.health.innerHTML;
  const contextRows = rowsOf(view);
  if (!contextRows.includes("ce")) throw new Error("matching child must list: " + JSON.stringify(contextRows));
  need(view, "Context-parent", "parent kept as context for the matching child");
  need(view, "Showing 1 of 1", "the context parent is not counted as a member");
  if (!same(contextRows, ["cp", "ce"])) throw new Error("context parent must precede child in Errors");
  lack(view, 'class="task-parent"', "no redundant parent link on children");
  // The "N subtasks" on a parent counts every child, filtered or not (the detail lists them all).
  const many = {
    tasks: [mk("pe", "error", { title: "Parent-error" }), mk("k1", "completed", { parent_id: "pe" }), mk("k2", "completed", { parent_id: "pe" }), mk("k3", "completed", { parent_id: "pe" })],
    by_status: { error: { n: 1, recurring: 0 }, completed: { n: 3, recurring: 0 } }, links: [], history: [], statuses: STATES, transitions: [],
  };
  page = await open(many);
  page.click({ "data-filter": "errors" });
  view = page.els.health.innerHTML;
  need(view, "3 subtasks", "the parent counts every child, not only the matching ones");
  need(view, "Showing 1 of 1", "only the parent is a member under Errors");

  // A repaint while the detail loads (deferred) must not drop the focus: arrows keep working.
  let releaseDetail;
  const detailHold = new Promise((resolve) => { releaseDetail = resolve; });
  page = boot(Object.assign({}, detailRoutes(), {
    "/api/console/tasks": { body: tasks },
    "/api/console/task-detail?task_id=err-1": { hold: detailHold.then(() => ({ body: curated })) },
  }));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-filter": "all" });
  page.key({ "data-chip": "1", "data-filter": "all" }, "ArrowLeft");
  if (page.focusedFilter !== "done") throw new Error("arrow moved the focus before the repaint: " + page.focusedFilter);
  page.click({ "data-task": "err-1" });
  await settled();
  // The curated detail is still loading; the toolbar was repainted to show it.
  releaseDetail();
  await settled();
  if (page.focusedFilter !== "done") throw new Error("the deferred detail repaint dropped the focus: " + page.focusedFilter);
  page.key({ "data-chip": "1", "data-filter": "done" }, "ArrowLeft");
  if (page.focusedFilter !== "errors") throw new Error("arrows stopped working after the repaint: " + page.focusedFilter);
  // The Recurring checkbox survives a repaint too.
  page.click({ "data-recurring": "1" });
  if (!page.focusedRecurring) throw new Error("focus left the Recurring checkbox after its repaint");

  // Recurring switch: a real checkbox, intersects the group, counts follow it.
  page = await open(everything);
  view = page.els.health.innerHTML;
  need(view, '<input type="checkbox" data-recurring="1">', "real checkbox, off by default");
  need(view, "↻ Recurring", "switch label");
  lack(view, "data-recurring=\"1\" data-chip", "the switch is not a chip");
  page.click({ "data-recurring": "1" });
  view = page.els.health.innerHTML;
  need(view, '<input type="checkbox" data-recurring="1" checked>', "checkbox checked");
  need(view, 'aria-label="Errors, 1 task"', "errors count follows the switch");
  need(view, 'aria-label="Running, 1 task"', "running follows the switch");
  lack(view, 'data-filter="drafts"', "drafts hide when no recurring draft exists");
  need(view, 'aria-label="Queue, 1 task"', "queue follows the switch");
  need(view, 'aria-label="Done, 1 task"', "done follows the switch");
  need(view, 'aria-label="Closed, 1 task"', "closed follows the switch");
  need(view, 'aria-label="All, 5 tasks"', "all follows the switch");
  if (!same(rowsOf(view).sort(), ["e1"])) throw new Error("switch intersects the selected group: " + JSON.stringify(rowsOf(view)));
  page.click({ "data-filter": "all" });
  if (!same(rowsOf(page.els.health.innerHTML).sort(), ["a1", "c2", "e1", "p1", "x2"])) throw new Error("switch with All");
  page.click({ "data-recurring": "1" });
  need(page.els.health.innerHTML, 'aria-label="All, 11 tasks"', "switch off restores the counts");

  // Every filter uses Created, independent of state, updates, parent or timezone offset.
  const chronological = fixture(STATES.flatMap((status, index) => [
    mk(status + "-old", status, { created_at: "2026-10-24T09:00:00Z", updated_at: "2026-10-26" }),
    mk(status + "-new", status, { created_at: "2026-10-24T12:00:00+02:00", updated_at: "2026-01-01" })
  ]));
  page = await open(chronological);
  for (const filter of ["errors", "running", "drafts", "queue", "done", "closed", "all"]) {
    page.click({ "data-filter": filter });
    const ids = rowsOf(page.els.health.innerHTML);
    const firstOld = ids.findIndex((id) => id.endsWith("-old"));
    const lastNew = ids.reduce((last, id, i) => id.endsWith("-new") ? i : last, -1);
    if (lastNew >= firstOld) throw new Error("Created descending in " + filter + ": " + ids.join());
  }
  const family = fixture([
    mk("parent", "completed", { created_at: "2026-10-24T08:00:00Z" }),
    mk("child", "completed", { parent_id: "parent", created_at: "2026-10-24T10:00:00Z" }),
    mk("other", "completed", { created_at: "2026-10-24T09:00:00Z" })
  ]);
  page = await open(family);
  page.click({ "data-filter": "done" });
  if (!same(rowsOf(page.els.health.innerHTML), ["other", "parent", "child"])) throw new Error("parent stays before child within its date-sorted family");

  // Search intersects status, preserves parent context and input caret during repaint.
  const searchable = fixture([
    mk("parent-100", "completed", { title: "Parent work" }),
    mk("child-abc", "error", { title: "Review Consumer", parent_id: "parent-100" }),
    mk("other-200", "completed", { title: "Other delivery" })
  ]);
  page = await open(searchable);
  page.click({ "data-filter": "all" });
  page.input("CONSUM", 3);
  view = page.els.health.innerHTML;
  if (!same(rowsOf(view), ["parent-100", "child-abc"])) throw new Error("search must keep the matching child's parent");
  need(view, '1 / 3', "compact count excludes context parents");
  if (!page.focusedSearch || page.searchCaret !== 3) throw new Error("search lost focus or caret");
  need(view, 'title="Copy" aria-label="Copy"', "copy is an accessible icon-only control");
  page.click({ "data-copy-id": "child-abc" });
  await settled();
  if (!same(page.copied, ["child-abc"])) throw new Error("copy must use the complete ID");
  need(page.els.live.textContent, "Copied", "copy success is announced");
  page.input("ABC");
  if (!same(rowsOf(page.els.health.innerHTML), ["parent-100", "child-abc"])) throw new Error("partial case-insensitive ID search");
  page.click({ "data-filter": "done" });
  view = page.els.health.innerHTML;
  if (rowsOf(view).length) throw new Error("search must respect Done");
  need(view, "No matching tasks.", "query empty-state is not the errors good-news state");
  page.input("");
  if (rowsOf(page.els.health.innerHTML).length !== 2) throw new Error("clearing search restores status group");
  page.click({ "data-filter": "errors" });
  page.input('<img src=x onerror=alert(1)>');
  view = page.els.health.innerHTML;
  lack(view, '<img src=x', "search value is escaped");
  need(view, "No matching tasks.", "Errors search does not claim no tasks are in error");

  // Clipboard failures must never announce a successful copy or record a copied ID.
  for (const clipboardMode of ["missing", "rejected"]) {
    page = await open(searchable, { clipboardMode });
    page.els.live.textContent = "";
    page.click({ "data-copy-id": "child-abc" });
    await settled();
    need(page.els.live.textContent, "Copy failed", "copy failure is announced: " + clipboardMode);
    lack(page.els.live.textContent, "Copied", "no false copy success: " + clipboardMode);
    if (page.copied.length) throw new Error("failed copy recorded an ID: " + clipboardMode);
  }

  // Optional When statistics preserve zero, missing data and partial coverage.
  const tokenGroup = (input, output, available = 1, attempts = 1) => ({ provider: "codex", model: "m", cli_version: "1", attempts,
    metrics: { input_tokens: { subtotal: input, available }, output_tokens: { subtotal: output, available } } });
  page = await open(fixture([mk("metered", "completed", { token_groups: [tokenGroup(0, 5)], duration_ms: 200000, duration_source: "timestamps" })]));
  view = page.els.health.innerHTML;
  need(view, 'class="task-when note"', "When is not an optional cell hidden on mobile");
  need(view, "0 → 5", "zero input is a measurement, not absence");
  need(view, "3 min 20 s", "When includes known duration");
  need(view, "Last recorded run duration", "task duration describes the last run");
  page = await open(fixture([mk("partial", "completed", { token_groups: [tokenGroup(null, 5, 1, 2)], duration_ms: 0 })]));
  view = page.els.health.innerHTML;
  need(view, "— → 5 · Partial", "missing counter and partial coverage are distinct");
  need(view, "0 ms", "zero duration is visible");
  page = await open(fixture([mk("unmeasured", "draft")]));
  lack(page.els.health.innerHTML, 'class="token-summary compact"', "no token placeholder without measurements");
  lack(page.els.health.innerHTML, 'class="task-run-duration"', "no duration placeholder without recorded time");

  const execData = { total: 3, by_status: { success: 3 },
    providers: [{ provider: "codex", n: 2, avg_duration_ms: 200000 }, { provider: "other", n: 1, avg_duration_ms: null }],
    channels: [{ channel: "async-task", n: 2, avg_duration_ms: 200000 }, { channel: "other", n: 1, avg_duration_ms: null }],
    recent: [{ ts: "2026-10-24T10:00:00Z", provider: "codex", status: "success", token_groups: [tokenGroup(0, 5)], duration_ms: 200000, duration_source: "timestamps" },
             { ts: "2026-10-24T11:00:00Z", status: "success", token_groups: [], duration_ms: null }] };
  page = boot(Object.assign({}, calm, { "/api/console/executions": { body: execData }, "/api/console/capacity": { body: {} } }));
  await settled();
  page.click({ "data-screen": "ejecuciones" });
  await settled();
  view = page.els.health.innerHTML;
  need(view, 'class="runs-scroll" role="region" tabindex="0"', "recent runs scroll region is keyboard accessible");
  const recentRuns = view.slice(view.indexOf('class="runs-scroll"'));
  need(recentRuns, '<div>Input</div><div>Output</div>', "distinct persistent column labels");
  need(recentRuns, 'title="Approximate duration calculated from recorded start and end times"', "derived duration is labelled");
  need(recentRuns, 'title=""', "non-derived duration has no approximation tooltip");
  need(recentRuns, '</div><div class="mono"></div><div class="mono"></div>', "empty token cells without a measurement");
  lack(recentRuns, "≈", "no approximation symbol in values");
  const providerBlock = view.slice(view.indexOf("By provider"), view.indexOf("By channel"));
  const channelBlock = view.slice(view.indexOf("By channel"), view.indexOf("By day"));
  for (const block of [providerBlock, channelBlock]) {
    need(block, '<div>Runs</div><div>%</div><div>Average</div>', "same breakdown columns");
    need(block, "3 min 20 s", "measured breakdown average");
    const identities = [...block.matchAll(/<div style="font-weight:500">([^<]+)<\/div>/g)].map(match => match[1]);
    const expected = block === providerBlock ? ["codex", "other"] : ["async-task", "other"];
    if (!same(identities, expected)) throw new Error("other must be the final breakdown row: " + JSON.stringify(identities));
    lack(block, "excluded from this breakdown", "no obsolete no-provider note");
  }

  // URL hash: the selection survives a reload and nothing else does.
  page = await open(everything);
  page.click({ "data-filter": "queue" });
  if (page.location.hash !== "#tasks/queue") throw new Error("hash after selecting: " + page.location.hash);
  page.click({ "data-recurring": "1" });
  if (page.location.hash !== "#tasks/queue+recurring") throw new Error("hash with the switch: " + page.location.hash);
  const reloaded = boot(Object.assign({ "/api/console/tasks": { body: everything } }, calm), page.location.hash);
  await settled();
  if (reloaded.els.title.textContent !== "Tasks") throw new Error("a tasks hash reopens the Tasks screen");
  view = reloaded.els.health.innerHTML;
  if (selectedChip(view) !== "queue") throw new Error("reload restores the group");
  need(view, '<input type="checkbox" data-recurring="1" checked>', "reload restores the switch");
  if (!same(rowsOf(view), ["p1"])) throw new Error("reload restores the intersection");
  for (const bad of ["#tasks/bogus", "#other", "#tasks/queue+x", ""]) {
    const ignored = boot(Object.assign({ "/api/console/tasks": { body: everything } }, calm), bad);
    await settled();
    if (ignored.els.title.textContent !== "Summary") throw new Error("hash ignored: " + bad);
  }

  // Toolbar semantics, roving tabindex and keyboard.
  page = await open(everything);
  view = page.els.health.innerHTML;
  need(view, 'role="toolbar" aria-label="Filter tasks by status"', "toolbar");
  if (!page.els.live.textContent.includes("Showing ")) throw new Error("live region announces the count");
  need(view, "Showing 2 of 2", "count of the default group");
  const tabindexes = (html) => (html.match(/data-chip="1" aria-pressed="(?:true|false)" tabindex="(-?\d)"/g) || []).map((m) => m.slice(-2, -1)).join("");
  if ((view.match(/tabindex="0"/g) || []).length !== 1) throw new Error("one tab stop in the toolbar");
  if (tabindexes(view) !== "0111111") throw new Error("tabindex layout: " + tabindexes(view));
  // Arrows move the tab stop without selecting.
  if (!page.key({ "data-chip": "1", "data-filter": "errors" }, "ArrowRight")) throw new Error("arrows are handled");
  view = page.els.health.innerHTML;
  if (selectedChip(view) !== "errors") throw new Error("arrows do not select");
  need(view, 'data-filter="running" data-chip="1" aria-pressed="false" tabindex="0"', "tab stop moved to Running");
  page.key({ "data-chip": "1", "data-filter": "running" }, "ArrowLeft");
  page.key({ "data-chip": "1", "data-filter": "errors" }, "ArrowLeft");
  need(page.els.health.innerHTML, 'data-filter="all" data-chip="1" aria-pressed="false" tabindex="0"', "wraps to the last chip");
  page.key({ "data-chip": "1", "data-filter": "all" }, "Home");
  need(page.els.health.innerHTML, 'data-filter="errors" data-chip="1" aria-pressed="true" tabindex="0"', "Home");
  page.key({ "data-chip": "1", "data-filter": "errors" }, "End");
  need(page.els.health.innerHTML, 'data-filter="all" data-chip="1" aria-pressed="false" tabindex="0"', "End");
  if (page.key({ "data-chip": "1", "data-filter": "all" }, "a")) throw new Error("other keys are left alone");
  // Enter and Space activate the button natively (a click); the selection then holds the tab stop.
  page.click({ "data-filter": "closed" });
  view = page.els.health.innerHTML;
  need(view, 'data-filter="closed" data-chip="1" aria-pressed="true" tabindex="0"', "selected chip holds the tab stop");
  if ((view.match(/tabindex="0"/g) || []).length !== 1) throw new Error("still one tab stop");
  // Names do not rely on colour alone: each chip has text and a numeric count.
  for (const label of ["Errors", "Running", "Drafts", "Queue", "Done", "Closed", "All"]) need(view, '<span class="fl">' + label + "</span>", "chip text " + label);
  page = await open(everything, { language: "es" });
  view = page.els.health.innerHTML;
  need(view, 'aria-label="Filtrar tareas por estado"', "spanish toolbar");
  need(view, 'aria-label="Errores, 2 tareas"', "spanish count label");
  for (const label of ["Errores", "En ejecución", "Borradores", "En cola", "Completadas", "Cerradas", "Todas"]) need(view, '<span class="fl">' + label + "</span>", "spanish chip " + label);
  need(view, "↻ Recurrentes", "spanish switch");
  need(view, 'aria-label="Errores, 2 tareas"', "spanish count");

  // The IDEs screen is named Apps in both languages; its id and route are unchanged.
  for (const [language, nav, question, skills, column] of [["en", "Apps", "What does each app see?", "Skills per app", "App"], ["es", "Apps", "¿Qué ve cada app?", "Skills por app", "App"]]) {
    page = boot(Object.assign({ "/api/console/ides": { body: [] }, "/api/console/health": { body: Object.assign({}, health, { language }) } }));
    await settled();
    const navHtml = page.els.nav.innerHTML;
    if (!navHtml.includes('data-screen="ides"')) throw new Error("the internal id stays ides");
    if (!navHtml.includes(">" + nav + "<")) throw new Error("menu lacks " + nav);
    if (navHtml.includes("IDEs")) throw new Error("menu still says IDEs in " + language);
    page.click({ "data-screen": "ides" });
    await settled();
    const screen = page.els.health.innerHTML;
    if (page.els.title.textContent !== nav) throw new Error("title in " + language + ": " + page.els.title.textContent);
    if (page.els.question.textContent !== question) throw new Error("question in " + language + ": " + page.els.question.textContent);
    if (!screen.includes(skills)) throw new Error("tile label in " + language);
    if (!screen.includes(">" + column + "<")) throw new Error("column header in " + language);
    if (screen.includes("IDE")) throw new Error("IDE left on the Apps screen in " + language);
    if (!page.requests.includes("/api/console/ides")) throw new Error("the route is unchanged");
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
  if (page.els.health.innerHTML.includes("Lo último que Solar tenía")) throw new Error("global Spanish continuity card remained");
  // One row per logical task: older finished versions fold under the task that revises
  // them (by revises_task_id), a similar title alone folds nothing, and a version that
  // can still run keeps its own row.
  const row = (id, status, title, extra) => Object.assign({ id, status, title, provider: null, channel: null,
    created_at: "2026-10-0" + (extra && extra.n || 1), updated_at: "2026-10-0" + (extra && extra.n || 1), recurring: false, parent_id: null }, extra || {});
  const chain = {
    tasks: [
      row("v1-aaaaaaaa", "archived", "Weekly report", { n: 1 }),
      row("v2-bbbbbbbb", "cancelled", "Weekly report", { n: 2, revises_task_id: "v1-aaaaaaaa" }),
      row("v3-cccccccc", "queued", "Weekly report", { n: 3, revises_task_id: "v2-bbbbbbbb" }),
      row("twin-dddddd", "archived", "Weekly report", { n: 4 }),
      row("live-eeeeee", "queued", "Other", { n: 5 }),
      row("live-ffffff", "draft", "Other (revision)", { n: 6, revises_task_id: "live-eeeeee" }),
      row("stuck-gggggg", "queued", "Stuck", { n: 7, approval_digest_mismatch: { reason: "legacy", at: "2026-10-07T00:00:00Z" } }),
    ],
    by_status: { archived: { n: 2, recurring: 0 }, cancelled: { n: 1, recurring: 0 }, queued: { n: 3, recurring: 0 }, draft: { n: 1, recurring: 0 } },
    links: [], history: [],
    statuses: ["draft", "planned", "queued", "active", "completed", "error", "archived", "cancelled"],
    transitions: [],
  };
  page = boot(Object.assign({ "/api/console/tasks": { body: chain } }, calm));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-filter": "all" });
  view = page.els.health.innerHTML;
  const listed = (id) => (view.match(new RegExp('class="row trow pick[^"]*" data-task="' + id + '"', "g")) || []).length;
  if (listed("v1-aaaaaaaa") || listed("v2-bbbbbbbb")) throw new Error("older versions kept their own row");
  if (listed("v3-cccccccc") !== 1) throw new Error("the current version lost its row");
  if (listed("twin-dddddd") !== 1) throw new Error("a similar title folded a task that revises nothing");
  if (listed("live-eeeeee") !== 1 || listed("live-ffffff") !== 1) throw new Error("a version that can still run was folded");
  need(view, "2 versions", "version count on the current row");
  need(view, "Approval needed", "mismatch badge on the queued row");
  page.click({ "data-task": "v3-cccccccc" });
  view = page.els.health.innerHTML;
  need(view, "Earlier versions (2)", "versions listed in the detail");
  need(view, 'data-task="v1-aaaaaaaa"', "older version reachable from the detail");
  need(view, "Revises", "link to the version it revises");
  page.click({ "data-task": "v1-aaaaaaaa" });
  need(page.els.health.innerHTML, "Weekly report", "an older version opens from the detail");
  page.click({ "data-task": "stuck-gggggg" });
  view = page.els.health.innerHTML;
  need(view, "The worker will not start this task: it was approved under an older rule. Approve it again to queue it.", "mismatch explained");
  page = boot(Object.assign({ "/api/console/tasks": { body: Object.assign({}, chain, { language: "es" }) } }, calm));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-filter": "all" });
  need(page.els.health.innerHTML, "2 versiones", "spanish version count");
  need(page.els.health.innerHTML, "Falta aprobación", "spanish mismatch badge");
  // A cycle in the links must not hang or hide the tasks.
  const loop = { tasks: [row("c1", "archived", "A", { n: 1, revises_task_id: "c2" }), row("c2", "archived", "B", { n: 2, revises_task_id: "c1" })],
    by_status: { archived: { n: 2, recurring: 0 } }, links: [], history: [], statuses: chain.statuses, transitions: [] };
  page = boot(Object.assign({ "/api/console/tasks": { body: loop } }, calm));
  await settled();
  page.click({ "data-screen": "tareas" });
  await settled();
  page.click({ "data-filter": "all" });
  need(page.els.health.innerHTML, 'data-task="c1"', "cycle keeps c1 listed");
  need(page.els.health.innerHTML, 'data-task="c2"', "cycle keeps c2 listed");
  console.log(JSON.stringify({ ok: true }));
})().catch((error) => {
  console.error(error && error.stack || error);
  process.exit(1);
});
"""


if __name__ == "__main__":
    unittest.main()
