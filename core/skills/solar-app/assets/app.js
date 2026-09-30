/* Read-only console. Screens read /api/console/* and do not recompute the verdict. */
(function () {
  "use strict";

  var TZ = "Europe/Madrid";
  var LANG = "en";
  var COPY = {
    en: {
      page_title: "Solar local console",
      gap: "available once Solar knows who is speaking",
      continuity: "The last thing Solar was holding when you spoke to it through Telegram, n8n, or a task. It does not update when you work directly in the IDE.",
      saved: "Saved text, not a message from this console.",
      delegation: "Solar acts without asking you, only inside a written permission with limits and an expiry.",
      nav_label: "Console questions",
      brand_note: "console · read only",
      madrid: "Madrid time",
      readonly: "Read only",
      theme_light: "Light",
      theme_dark: "Dark",
      updated: "Updated ",
      updated_empty: "Updated —",
      reading: "Reading…",
      no_reply: "no reply",
      no_data: "no data",
      less_than_min: "less than 1 min",
      route_refused: "The route refused",
      no_reason: "no reason",
      nav_summary: "Summary",
      nav_tasks: "Tasks",
      nav_runs: "Runs",
      nav_continuity: "Continuity",
      nav_autonomy: "Autonomy",
      nav_ides: "IDEs",
      nav_entry: "External entry",
      nav_requester: "Requester",
      q_summary: "Is the installation healthy, and how long has it been idle?",
      q_tasks: "Which tasks exist and what happened to them?",
      q_runs: "What has Solar run and how did it go?",
      q_continuity: "Where did it leave off?",
      q_autonomy: "What does Solar do without asking?",
      q_ides: "What does each IDE see?",
      q_entry: "What can come in from outside?",
      q_requester: "Who asked for this?",
      st_draft: "Draft", st_planned: "Planned", st_queued: "Queued", st_active: "Active",
      st_completed: "Completed", st_error: "Error", st_archived: "Archived", st_cancelled: "Cancelled", st_none: "No status",
      ex_ok: "Ok", ex_failed: "Failed", ex_reconciled: "Reconciled", ex_none: "No result",
      v_calm: "CALM", v_fault: "FAULT", v_unverified: "UNVERIFIED",
      r_database: "The state database cannot be read.",
      r_port: "Another process is using the console port.",
      r_launchagent: "The LaunchAgent has no recent pass.",
      r_system: "A system feature has failed.",
      r_router: "The router is unknown because the state refuses.",
      r_gateway: "The gateway is not healthy.",
      c_database: "Database", c_port: "Port 9000", c_system: "System", c_router: "Router",
      c_launchagent: "LaunchAgent", c_gateway: "Gateway",
      no_channel: "no channel", other_channel: "Other",
      mode_global: "Global", mode_portable: "Portable copy",
      tunnel_named: "Named", tunnel_quick: "Quick",
      feat_tasks: "Background tasks", feat_gateway: "Gateway", feat_ok: "ok", feat_failed: "failed",
      gate_read: "Read allowed", gate_ask: "Asks for your permission", gate_with: "With your permission",
      gate_unknown_perm: "Unknown permission", gate_used: "Permission already used", gate_expired: "Permission expired",
      gate_mismatch: "The permission does not match", gate_ok: "Valid delegation", gate_denied: "Delegation denied",
      gate_a3: "Approving a task is outside a delegation", gate_tool: "Unknown tool",
      gate_external: "External communication refused", gate_skill: "The skill is not registered",
      gate_action: "Action not allowed", gate_level: "That level is not granted here", gate_undescribed: "Reason not described",
      active_one: "1 active", active_none: "None active", active_many: "active",
      gw_none: "No data.", gw_ready: "Processes, local /health, and the connector are ready.",
      gw_health: "local /health is not responding", gw_connector: "connector not ready", gw_process: "a process is down", gw_trouble: "In trouble.",
      pill_refused: "Refused", pill_readable: "Readable", db_readable: "The database can be read.",
      pill_ready: "Ready", pill_trouble: "In trouble", pill_no_data: "No data", pill_recorded: "Recorded", no_pass: "No pass",
      not_recorded: "not recorded", updated_prefix: "Updated ", no_record: "No record.",
      act_router: "Router", act_tasks: "Tasks", act_mandates: "Delegations",
      install: "Installation", version: "Version", mode: "Mode", owner: "Owner", cutover: "Latest cutover",
      launch_title: "LaunchAgent", label: "Label", interval: "Interval", every_60: "every 60 s", last_pass: "Latest pass", functions: "Features",
      daily_copy: "Daily copy", copies: " saved copies", no_copy: "no copy",
      attention: "Attention", all_tasks: "All", recurring_title: "recurring", subtasks: "subtasks",
      no_provider: "no provider", no_tasks: "No tasks.", showing: "Showing ", of: " of ",
      col_status: "Status", col_task: "Task", col_provider: "Provider", col_channel: "Channel", col_created: "Created", col_requester: "Requester",
      state_machine: "State machine", no_history: "No history.", detail: "Detail", recurring: "recurring",
      parent: "Parent", root: "root", history: "History", final_state: "final", can_go: "Can move to",
      total: "Total", atypical: "unusual", by_provider: "By provider", runs_short: "Runs", average: "Average",
      no_provider_note: "No provider · before a provider is chosen", failed_n: "failed", reconciled_n: "reconciled",
      no_duration: "no run duration", mean: "average ", by_channel: "By channel", weight: "Weight",
      by_day: "By day ", day_note: "· days with activity · square-root scale", recent_runs: "Latest runs",
      when: "When", result: "Result", duration: "Duration",
      pending: "Pending", decisions: "Decisions", next_owner: "Next owner", unassigned: "unassigned",
      updated_label: "Updated", channels_seen: "Channels seen", summaries: "Summaries by channel",
      origin: "Origin", file: "File", date: "Date", ago_col: "Ago", task_kind: "Task", channel_kind: "Channel",
      mode_active: "Active", mode_trial: "Trial (no real effects)", mode_paused: "Paused", mode_revoked: "Revoked", mode_none: "No mode",
      revoked_on: "Revoked on ", no_revoke_date: "no revocation date", events: "events", in_trial: "in trial", no_use: "unused",
      delegations: "Delegations", delegation_col: "Delegation", mode_col: "Mode", events_col: "Events", first_use: "First use", last_use: "Last use",
      allowed: "Allowed", asks: "Asks for approval", denied: "Denied",
      perm_decisions: "Permission decisions", permitted: "allowed", not_permitted: "not allowed",
      perm_note: "Not allowed means it asks for approval or it is denied; the data does not split those.",
      recent_decisions: "Latest decisions", tool: "Tool", decision: "Decision", reason: "Reason",
      ides: "IDEs", skills_per: "Skills per IDE", broken_links: "Broken links", repair: "Repair", none_broken: "None",
      receives: "Receives", path: "Path", skills: "Skills", broken: "Broken",
      shared_copy: "Shared copy", copy: "Copy", link: "Link",
      connector_ready: "Connector ready", connector_down: "Connector not ready",
      yes: "Yes", no: "No", configured: "Configured", absent: "Not recorded",
      port_word: "port ", pass_port: "Pass port",
      http_channels: "HTTP channels", channel: "Channel", address: "Address", scope: "Scope",
      console: "Console", local_only: "Local only", gateway_http: "Gateway HTTP", local_tunnel: "Local; outside via tunnel",
      websocket: "WebSocket", telegram: "Telegram webhook", claim: "Set to claim", real_state: "Actual state",
      not_verified: "Not verified", n8n_secret: "n8n secret", tunnel: "Tunnel", name: "Name", hostname: "Hostname", state: "State",
      user_ids: " user identifiers in the record, not treated as people.",
      active_intent: "Active intention",
      unusual_tip: "Not a credible duration",
      where: "Where it appears", records: "Records", go: "Open",
      decisions_word: "decisions"
    },
    es: {
      page_title: "Consola local de Solar",
      gap: "disponible cuando Solar sepa quién le habla",
      continuity: "Lo último que Solar tenía entre manos cuando le hablaste por Telegram, n8n o una tarea. No se actualiza cuando trabajas directamente en el IDE.",
      saved: "Contenido guardado, no un mensaje de esta consola.",
      delegation: "Solar actúa sin preguntarte, solo dentro de un permiso escrito con límites y caducidad.",
      nav_label: "Preguntas de la consola",
      brand_note: "consola · solo lectura",
      madrid: "Horas de Madrid",
      readonly: "Solo lectura",
      theme_light: "Claro",
      theme_dark: "Oscuro",
      updated: "Actualizado ",
      updated_empty: "Actualizado —",
      reading: "Leyendo…",
      no_reply: "sin respuesta",
      no_data: "sin dato",
      less_than_min: "menos de 1 min",
      route_refused: "La ruta se negó",
      no_reason: "sin motivo",
      nav_summary: "Resumen",
      nav_tasks: "Tareas",
      nav_runs: "Ejecuciones",
      nav_continuity: "Continuidad",
      nav_autonomy: "Autonomía",
      nav_ides: "IDEs",
      nav_entry: "Entrada externa",
      nav_requester: "Solicitante",
      q_summary: "¿Está sana mi instalación, y desde cuándo no hace nada?",
      q_tasks: "¿Qué tareas hay y qué les ha pasado?",
      q_runs: "¿Qué ha ejecutado Solar y cómo le ha ido?",
      q_continuity: "¿Dónde se quedó?",
      q_autonomy: "¿Qué hace Solar sin preguntarme?",
      q_ides: "¿Qué ve cada IDE?",
      q_entry: "¿Qué puede entrar desde fuera?",
      q_requester: "¿Quién pidió esto?",
      st_draft: "Borrador", st_planned: "Planificada", st_queued: "En cola", st_active: "Activa",
      st_completed: "Completada", st_error: "Error", st_archived: "Archivada", st_cancelled: "Cancelada", st_none: "Sin estado",
      ex_ok: "Bien", ex_failed: "Fallida", ex_reconciled: "Reconciliada", ex_none: "Sin resultado",
      v_calm: "CALMA", v_fault: "AVERÍA", v_unverified: "SIN VERIFICAR",
      r_database: "La base de estado es ilegible.",
      r_port: "El puerto de la consola está ocupado por otro proceso.",
      r_launchagent: "El LaunchAgent no tiene una pasada reciente.",
      r_system: "Una función del sistema ha fallado.",
      r_router: "El router es desconocido porque el estado se niega.",
      r_gateway: "El gateway no está sano.",
      c_database: "Base", c_port: "Puerto 9000", c_system: "Sistema", c_router: "Router",
      c_launchagent: "LaunchAgent", c_gateway: "Gateway",
      no_channel: "sin canal", other_channel: "Otro",
      mode_global: "Global", mode_portable: "Copia portable",
      tunnel_named: "Con nombre", tunnel_quick: "Rápido",
      feat_tasks: "Tareas en segundo plano", feat_gateway: "Gateway", feat_ok: "bien", feat_failed: "fallo",
      gate_read: "Lectura permitida", gate_ask: "Pide tu permiso", gate_with: "Con tu permiso",
      gate_unknown_perm: "Permiso desconocido", gate_used: "Permiso ya usado", gate_expired: "Permiso caducado",
      gate_mismatch: "El permiso no coincide", gate_ok: "Delegación válida", gate_denied: "Delegación denegada",
      gate_a3: "Activar una tarea no entra en una delegación", gate_tool: "Herramienta desconocida",
      gate_external: "Comunicación externa rechazada", gate_skill: "La skill no está registrada",
      gate_action: "Acción no permitida", gate_level: "Ese nivel no se concede aquí", gate_undescribed: "Motivo no descrito",
      active_one: "1 activa", active_none: "Ninguna activa", active_many: "activas",
      gw_none: "Sin dato.", gw_ready: "Procesos, /health local y conector listos.",
      gw_health: "/health local no responde", gw_connector: "conector no listo", gw_process: "algún proceso caído", gw_trouble: "Con problemas.",
      pill_refused: "Se negó", pill_readable: "Legible", db_readable: "La base se puede leer.",
      pill_ready: "Listo", pill_trouble: "Con problemas", pill_no_data: "Sin dato", pill_recorded: "Registrada", no_pass: "Sin pasada",
      not_recorded: "no consta", updated_prefix: "Actualizada hace ", no_record: "Sin registro.",
      act_router: "Router", act_tasks: "Tareas", act_mandates: "Delegaciones",
      install: "Instalación", version: "Versión", mode: "Modo", owner: "Dueño", cutover: "Último corte",
      launch_title: "LaunchAgent", label: "Etiqueta", interval: "Intervalo", every_60: "cada 60 s", last_pass: "Última pasada", functions: "Funciones",
      daily_copy: "Copia diaria", copies: " copias guardadas", no_copy: "sin copia",
      attention: "Atención", all_tasks: "Todas", recurring_title: "recurrentes", subtasks: "subtareas",
      no_provider: "sin proveedor", no_tasks: "Sin tareas.", showing: "Mostrando ", of: " de ",
      col_status: "Estado", col_task: "Tarea", col_provider: "Proveedor", col_channel: "Canal", col_created: "Creada", col_requester: "Solicitante",
      state_machine: "Máquina de estados", no_history: "Sin historia.", detail: "Detalle", recurring: "recurrente",
      parent: "Padre", root: "raíz", history: "Historia", final_state: "final", can_go: "Puede pasar a",
      total: "Total", atypical: "atípico", by_provider: "Por proveedor", runs_short: "Ejec.", average: "Media",
      no_provider_note: "Sin proveedor · antes de elegir proveedor", failed_n: "fallidas", reconciled_n: "reconciliadas",
      no_duration: "sin duración de ejecución", mean: "media ", by_channel: "Por canal", weight: "Peso",
      by_day: "Por día ", day_note: "· días con actividad · escala raíz", recent_runs: "Últimas ejecuciones",
      when: "Cuándo", result: "Resultado", duration: "Duración",
      pending: "Pendientes", decisions: "Decisiones", next_owner: "Siguiente responsable", unassigned: "sin asignar",
      updated_label: "Actualizada", channels_seen: "Canales vistos", summaries: "Resúmenes por canal",
      origin: "Origen", file: "Fichero", date: "Fecha", ago_col: "Hace", task_kind: "Tarea", channel_kind: "Canal",
      mode_active: "Activa", mode_trial: "En prueba (sin efectos reales)", mode_paused: "Pausada", mode_revoked: "Revocada", mode_none: "Sin modo",
      revoked_on: "Revocada el ", no_revoke_date: "sin fecha de revocación", events: "eventos", in_trial: "en prueba", no_use: "sin uso",
      delegations: "Delegaciones", delegation_col: "Delegación", mode_col: "Modo", events_col: "Eventos", first_use: "Primer uso", last_use: "Último uso",
      allowed: "Permitida", asks: "Pide aprobación", denied: "Denegada",
      perm_decisions: "Decisiones de permiso", permitted: "permitidas", not_permitted: "no permitidas",
      perm_note: "Sin permitir = pide aprobación o se deniega; los datos no las separan.",
      recent_decisions: "Últimas decisiones", tool: "Herramienta", decision: "Decisión", reason: "Motivo",
      ides: "IDEs", skills_per: "Skills por IDE", broken_links: "Enlaces rotos", repair: "Reparar", none_broken: "Ninguno",
      receives: "Recibe", path: "Ruta", skills: "Skills", broken: "Rotos",
      shared_copy: "Copia compartida", copy: "Copia", link: "Enlace",
      connector_ready: "Conector listo", connector_down: "Conector no listo",
      yes: "Sí", no: "No", configured: "Configurado", absent: "No consta",
      port_word: "puerto ", pass_port: "Puerto de la pasada",
      http_channels: "Canales HTTP", channel: "Canal", address: "Dirección", scope: "Alcance",
      console: "Consola", local_only: "Solo local", gateway_http: "HTTP del gateway", local_tunnel: "Local; fuera vía túnel",
      websocket: "WebSocket", telegram: "Webhook de Telegram", claim: "Configurado para reclamar", real_state: "Estado real",
      not_verified: "No verificado", n8n_secret: "Secreto n8n", tunnel: "Túnel", name: "Nombre", hostname: "Hostname", state: "Estado",
      user_ids: " identificadores de usuario en el registro, sin traducir a personas.",
      active_intent: "Intención activa",
      unusual_tip: "No es una duración creíble",
      where: "Dónde aparece", records: "Registros", go: "Ir",
      decisions_word: "decisiones"
    }
  };
  var ATT = ["error", "queued", "active", "planned"];
  var RANK = { error: 0, active: 1, queued: 2, planned: 3, draft: 4, completed: 5, archived: 6, cancelled: 7 };

  function t(key) {
    var table = COPY[LANG] || COPY.en;
    if (table[key] != null) return table[key];
    return COPY.en[key] != null ? COPY.en[key] : key;
  }
  function useLanguage(code) {
    LANG = code === "es" ? "es" : "en";
    try {
      if (document.documentElement) document.documentElement.lang = LANG;
    } catch (error) { /* tests boot without documentElement */ }
    try {
      document.title = t("page_title");
    } catch (error) { /* tests may boot without a title */ }
  }
  function screens() {
    return [
      ["resumen", t("nav_summary"), t("q_summary"), "/api/console/health"],
      ["tareas", t("nav_tasks"), t("q_tasks"), "/api/console/tasks"],
      ["ejecuciones", t("nav_runs"), t("q_runs"), "/api/console/executions"],
      ["continuidad", t("nav_continuity"), t("q_continuity"), "/api/console/continuity"],
      ["autonomia", t("nav_autonomy"), t("q_autonomy"), "/api/console/mandates"],
      ["ides", t("nav_ides"), t("q_ides"), "/api/console/ides"],
      ["entrada", t("nav_entry"), t("q_entry"), "/api/console/ingress"],
      ["solicitante", t("nav_requester"), t("q_requester"), "/api/console/requester"]
    ];
  }
  function statusRow(status) {
    var labels = {
      draft: ["neu", "○", "st_draft"], planned: ["info", "◔", "st_planned"], queued: ["info", "◑", "st_queued"],
      active: ["info", "▶", "st_active"], completed: ["ok", "✓", "st_completed"], error: ["err", "▲", "st_error"],
      archived: ["neu", "▭", "st_archived"], cancelled: ["neu", "⊘", "st_cancelled"]
    };
    var row = labels[status] || ["neu", "·", "st_none"];
    return { tone: row[0], glyph: row[1], label: t(row[2]) };
  }
  function execRow(status) {
    var labels = { success: ["ok", "✓", "ex_ok"], failed: ["err", "▲", "ex_failed"], reconciled: ["warn", "⇄", "ex_reconciled"] };
    var row = labels[status] || ["neu", "·", "ex_none"];
    return [row[0], row[1], t(row[2])];
  }
  function verdictFace(state) {
    var labels = { calm: ["v_calm", "✓", "v-ok"], fault: ["v_fault", "✕", "v-bad"], unverified: ["v_unverified", "?", "v-unk"] };
    var row = labels[state] || labels.unverified;
    return [t(row[0]), row[1], row[2]];
  }
  function reasonText(id) {
    var keys = {
      database: "r_database", port: "r_port", launchagent: "r_launchagent",
      system: "r_system", router: "r_router", gateway: "r_gateway"
    };
    return keys[id] ? t(keys[id]) : "";
  }
  function checkLabel(id) {
    var keys = {
      database: "c_database", port: "c_port", system: "c_system", router: "c_router",
      launchagent: "c_launchagent", gateway: "c_gateway"
    };
    return keys[id] ? t(keys[id]) : id;
  }

  var ui = {
    screen: "resumen",
    theme: "dark",
    filter: "atencion",
    task: null,
    machine: false
  };
  var cache = {};
  var timer = 0;
  var healthStamp = null;

  function $(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }
  function pill(tone, glyph, text) {
    return '<span class="pill ' + tone + '">' + esc(glyph) + " " + esc(text) + "</span>";
  }
  function nf(n) {
    var sep = LANG === "es" ? "." : ",";
    return String(n == null ? 0 : n).replace(/\B(?=(\d{3})+(?!\d))/g, sep);
  }
  function pc(part, total) {
    if (!total) return LANG === "es" ? "0,0 %" : "0.0%";
    var text = ((part / total) * 100).toFixed(1);
    return LANG === "es" ? text.replace(".", ",") + " %" : text + "%";
  }
  function decimal(text) {
    return LANG === "es" ? String(text).replace(".", ",") : String(text);
  }
  function ageFrom(value) {
    var date = parseTs(value);
    if (!date) return null;
    var seconds = (Date.now() - date.getTime()) / 1000;
    return seconds < 0 ? 0 : seconds;
  }
  function agoPhrase(seconds) {
    var text = ageText(seconds);
    if (text === t("no_data")) return text;
    return LANG === "es" ? ("hace " + text) : (text + " ago");
  }
  function ageLabel(value) {
    var seconds = ageFrom(value);
    return seconds == null ? t("no_data") : agoPhrase(seconds);
  }
  function ageText(seconds) {
    if (seconds == null || seconds < 0) return t("no_data");
    var m = Math.floor(seconds / 60);
    if (m < 1) return t("less_than_min");
    var d = Math.floor(m / 1440), h = Math.floor((m % 1440) / 60), mi = m % 60;
    if (d > 0) return d + " d " + h + " h";
    if (h > 0) return h + " h " + mi + " min";
    return mi + " min";
  }
  function parseTs(value) {
    if (!value) return null;
    var text = String(value);
    if (text.length === 10) text += "T12:00:00Z";
    var date = new Date(text);
    return isNaN(date.getTime()) ? null : date;
  }
  function fmt(value, withSeconds) {
    var date = parseTs(value);
    if (!date) return t("no_data");
    var opts = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TZ };
    if (withSeconds) opts.second = "2-digit";
    return date.toLocaleString(LANG === "es" ? "es-ES" : "en-GB", opts);
  }
  function fmtDay(value) {
    var date = parseTs(value);
    if (!date) return t("no_data");
    return date.toLocaleDateString(LANG === "es" ? "es-ES" : "en-GB", { day: "numeric", month: "short", timeZone: TZ });
  }
  function fmtYear(value) {
    var date = parseTs(value);
    if (!date) return t("no_data");
    return date.toLocaleDateString(LANG === "es" ? "es-ES" : "en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: TZ });
  }
  function dur(value) {
    if (value == null || value === "") return "—";
    var v = Number(value);
    if (!isFinite(v)) return "—";
    if (v < 1000) return Math.round(v) + " ms";
    if (v < 60000) return decimal((v / 1000).toFixed(1)) + " s";
    if (v < 3600000) return Math.floor(v / 60000) + " min " + Math.round((v % 60000) / 1000) + " s";
    if (v < 86400000) return Math.floor(v / 3600000) + " h " + Math.round((v % 3600000) / 60000) + " min";
    return decimal((v / 86400000).toFixed(1)) + " d";
  }
  function ts(status) { return statusRow(status); }
  function refusedBox(reason) {
    return '<div class="card" style="display:flex;flex-direction:column;gap:8px">' +
      pill("err", "▲", t("route_refused")) +
      '<div>' + esc(reason || t("no_reason")) + "</div></div>";
  }
  function plain(value) {
    if (value == null || value === "") return t("no_data");
    if (typeof value === "string" || typeof value === "number") return String(value);
    try { return JSON.stringify(value); } catch (error) { return t("no_data"); }
  }
  function showCount(value) {
    if (value == null || value === "") return "—";
    if (Array.isArray(value)) return String(value.length);
    if (typeof value === "object") return String(Object.keys(value).length);
    return String(value);
  }

  function screenOf(id) {
    var rows = screens();
    for (var i = 0; i < rows.length; i++) if (rows[i][0] === id) return rows[i];
    return rows[0];
  }

  function paintChrome() {
    var app = $("app");
    app.className = "app " + (ui.theme === "light" ? "t-light" : "t-dark");
    $("theme").textContent = ui.theme === "light" ? t("theme_dark") : t("theme_light");
    var sidenav = $("sidenav");
    if (sidenav && sidenav.setAttribute) sidenav.setAttribute("aria-label", t("nav_label"));
    var brand = $("brand-note");
    if (brand) brand.textContent = t("brand_note");
    var zone = $("tz-note");
    if (zone) zone.textContent = t("madrid");
    var tag = $("readonly-tag");
    if (tag) tag.textContent = t("readonly");
    var current = screenOf(ui.screen);
    $("title").textContent = current[1];
    $("question").textContent = current[2];
    try { document.title = t("page_title"); } catch (error) { /* keep the shell title */ }
    var html = "";
    screens().forEach(function (row, index) {
      var on = row[0] === ui.screen;
      var badge = badgeFor(row[0]);
      html += '<button type="button" class="nav' + (on ? " on" : "") + '" data-screen="' + row[0] + '"' +
        (on ? ' aria-current="page"' : "") + ' title="' + esc(row[2]) + '" aria-label="' + esc(row[1]) + '">' +
        '<span class="num">' + (index + 1) + "</span>" +
        '<span class="ico" style="font-weight:700;font-size:14px" aria-hidden="true">' + (index + 1) + "</span>" +
        '<span class="nm">' + esc(row[1]) + "</span>" +
        badge + "</button>";
    });
    $("nav").innerHTML = html;
    $("host").textContent = location.host || "127.0.0.1:9000";
    $("updated").textContent = healthStamp ? (t("updated") + fmt(healthStamp, true)) : t("updated_empty");
  }

  function badgeFor(id) {
    if (id === "resumen" && cache.resumen && cache.resumen.data) {
      var verdict = (cache.resumen.data.verdict || {}).verdict;
      if (verdict === "calm") return '<span class="pill sm badge ok">✓</span>';
      if (verdict === "fault") return '<span class="pill sm badge err">▲</span>';
      return '<span class="pill sm badge info">?</span>';
    }
    if (id === "tareas" && cache.tareas && cache.tareas.data) {
      var n = ((cache.tareas.data.by_status || {}).error || {}).n || 0;
      if (n) return '<span class="pill sm badge err">' + esc(n) + "</span>";
    }
    if (id === "continuidad") return '<span class="pill sm badge neu">◷</span>';
    if (id === "entrada") return '<span class="pill sm badge info">?</span>';
    return '<span class="pill sm badge gap-hide"></span>';
  }

  function load(path) {
    return fetch(path, { headers: { Accept: "application/json" } }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (body && (body.language === "es" || body.language === "en")) useLanguage(body.language);
        if (response.status === 503 && body && body.refused) return { refused: body.error || "refused" };
        if (!response.ok) return { refused: (body && body.error) || ("HTTP " + response.status) };
        return { data: body };
      });
    }).catch(function (error) {
      return { refused: error && error.message ? error.message : t("no_reply") };
    });
  }

  function openScreen(id) {
    ui.screen = id;
    clearInterval(timer);
    timer = 0;
    paintChrome();
    var box = $("health");
    var known = cache[id];
    if (!known) box.innerHTML = '<div class="note">' + esc(t("reading")) + "</div>";
    else if (id === "entrada" && !known.refused) box.innerHTML = renderIngress(known.data, null);
    else if (id === "solicitante" && !known.refused) box.innerHTML = renderRequester(known.data, null);
    else paint(id, known);
    var jobs = [load(screenOf(id)[3])];
    if (id === "entrada") jobs.push(load("/api/console/health"));
    if (id === "solicitante") jobs.push(load("/api/console/executions"));
    Promise.all(jobs).then(function (parts) {
      var payload = parts[0];
      var extra = (id === "entrada" || id === "solicitante") ? (parts[1] || { refused: t("no_reply") }) : null;
      if (ui.screen !== id) {
        cache[id] = payload;
        return;
      }
      cache[id] = payload;
      if (id === "resumen" && payload.data) healthStamp = new Date().toISOString();
      if (id === "entrada") {
        box.innerHTML = payload.refused ? refusedBox(payload.refused) : renderIngress(payload.data, extra);
      } else if (id === "solicitante") {
        box.innerHTML = payload.refused ? refusedBox(payload.refused) : renderRequester(payload.data, extra);
      } else paint(id, payload);
      paintChrome();
    });
    if (id === "resumen") {
      timer = setInterval(function () { openScreen("resumen"); }, 30000);
    }
  }

  function paint(id, payload) {
    if (ui.screen !== id) return;
    var box = $("health");
    if (payload.refused) {
      box.innerHTML = refusedBox(payload.refused);
      return;
    }
    var data = payload.data;
    if (id === "resumen") box.innerHTML = renderHealth(data);
    else if (id === "tareas") box.innerHTML = renderTasks(data);
    else if (id === "ejecuciones") box.innerHTML = renderExec(data);
    else if (id === "continuidad") box.innerHTML = renderContinuity(data);
    else if (id === "autonomia") box.innerHTML = renderMandates(data);
    else if (id === "ides") box.innerHTML = renderIdes(data);
    else if (id === "entrada") box.innerHTML = renderIngress(data);
    else if (id === "solicitante") box.innerHTML = renderRequester(data);
  }

  function checksFrom(verdict) {
    return (verdict.checks || []).map(function (check) {
      var label = checkLabel(check.id);
      var tip = reasonText(check.id) || label;
      if (check.id === "launchagent" && verdict.launchagent && verdict.launchagent.age_seconds != null && check.state !== "unverified") {
        label += ": " + agoPhrase(verdict.launchagent.age_seconds);
      }
      if (check.state === "ok") return '<span class="pill ok" title="' + esc(tip) + '">✓ ' + esc(label) + "</span>";
      if (check.state === "fault") return '<span class="pill err" title="' + esc(tip) + '">▲ ' + esc(label) + "</span>";
      return '<span class="pill info" title="' + esc(tip) + '">? ' + esc(label) + ": " + esc(t("no_data")) + "</span>";
    }).join("");
  }

  function channelLabel(value) {
    if (!value) return t("no_channel");
    if (value === "other") return t("other_channel");
    return String(value);
  }
  function installMode(value) {
    if (value === "global") return { text: t("mode_global"), cls: "" };
    if (value === "workspace-snapshot") return { text: t("mode_portable"), cls: "" };
    if (!value) return { text: t("no_data"), cls: "" };
    return { text: String(value), cls: "mono" };
  }
  function tunnelMode(value) {
    if (value === "named") return t("tunnel_named");
    if (value === "quick") return t("tunnel_quick");
    if (!value) return t("no_data");
    return String(value);
  }
  function featureLine(features) {
    if (!features || !Object.keys(features).length) return t("no_data");
    var names = { "async-tasks": t("feat_tasks"), "transport-gateway": t("feat_gateway") };
    var states = { ok: t("feat_ok"), failed: t("feat_failed") };
    return Object.keys(features).map(function (name) {
      var label = names[name] ? esc(names[name]) : '<span class="mono">' + esc(name) + "</span>";
      var state = states[features[name]] || t("no_data");
      return label + " " + esc(state);
    }).join(", ");
  }
  function gateReason(code) {
    var labels = {
      read_allowed: "gate_read",
      approval_required: "gate_ask",
      approval_ok: "gate_with",
      approval_unknown: "gate_unknown_perm",
      approval_consumed: "gate_used",
      approval_expired: "gate_expired",
      approval_scope_mismatch: "gate_mismatch",
      mandate_ok: "gate_ok",
      mandate_denied: "gate_denied",
      a3_refused: "gate_a3",
      unknown_tool: "gate_tool",
      external_communication_refused: "gate_external",
      skill_not_registered: "gate_skill",
      action_not_allowed: "gate_action",
      authority_not_grantable: "gate_level"
    };
    if (!code) return t("no_reason");
    return labels[code] ? t(labels[code]) : t("gate_undescribed");
  }
  function activeLabel(n) {
    if (n == null || n === "") return t("no_data");
    n = Number(n);
    if (!isFinite(n)) return t("no_data");
    if (n === 1) return t("active_one");
    if (!n) return t("active_none");
    return nf(n) + " " + t("active_many");
  }

  function gatewayCause(gateway) {
    if (!gateway || gateway.state === "unverified") return t("gw_none");
    if (gateway.state === "healthy") return t("gw_ready");
    var bits = [];
    if (!gateway.local_health) bits.push(t("gw_health"));
    if (!gateway.connector_ready) bits.push(t("gw_connector"));
    if (!gateway.processes_alive) bits.push(t("gw_process"));
    return bits.join(" · ") || t("gw_trouble");
  }

  function renderHealth(data) {
    var verdict = data.verdict || {};
    var face = verdictFace(verdict.verdict);
    var launch = verdict.launchagent || {};
    var gateway = verdict.gateway || { state: "unverified" };
    var activity = data.last_activity || {};
    var owner = data.owner || {};
    var cutover = data.cutover || {};
    var backups = data.backups || [];
    var lastBackup = backups.length ? backups[backups.length - 1] : null;
    var features = (data.stamp && data.stamp.features) || null;
    var modeInfo = installMode(data.mode);
    var pass = launch.state === "unverified" || launch.at == null
      ? '<div class="gap">' + esc(t("not_recorded")) + "</div>"
      : '<div class="' + (launch.state === "stale" ? "txt-err" : "") + '">' + esc(agoPhrase(launch.age_seconds)) + "</div>";
    var continuityWhen = data.continuity_at
      ? (t("updated_prefix") + ageText(data.continuity_age_seconds) + (LANG === "es" ? "" : " ago") + " · " + fmt(data.continuity_at) + ".")
      : t("no_record");
    var cards = [
      [t("c_database"), data.database ? ["err", "▲", t("pill_refused")] : ["ok", "✓", t("pill_readable")], data.database ? data.database.refused : t("db_readable"), data.database ? "" : ""],
      ["Gateway", gateway.state === "healthy" ? ["ok", "✓", t("pill_ready")] : (gateway.state === "problems" ? ["err", "▲", t("pill_trouble")] : ["info", "?", t("pill_no_data")]), gatewayCause(gateway), launch.at ? (t("no_pass") === "No pass" ? ("Pass " + fmt(launch.at, true)) : ("Pasada " + fmt(launch.at, true))) : t("no_pass")],
      [t("nav_continuity"), data.continuity_at ? ["neu", "◷", t("pill_recorded")] : ["info", "?", t("pill_no_data")], t("continuity"), continuityWhen]
    ];
    var compHtml = cards.map(function (card) {
      return '<div class="card" style="display:flex;flex-direction:column;gap:6px"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><div class="h3">' +
        esc(card[0]) + "</div>" + pill(card[1][0], card[1][1], card[1][2]) + "</div><div>" + esc(card[2]) + '</div><div class="note">' + esc(card[3]) + "</div></div>";
    }).join("");
    var acts = [
      [t("act_router"), activity.router],
      [t("act_tasks"), activity.tasks],
      [t("act_mandates"), activity.mandates]
    ].map(function (row) {
      var item = row[1] || {};
      var when = item.at ? agoPhrase(item.age_seconds) : t("no_data");
      return '<div class="card"><div class="lbl">' + esc(row[0]) + '</div><div class="big" style="margin:4px 0">' +
        esc(when) + '</div><div class="note">' + esc(item.at ? fmt(item.at) : t("no_data")) + "</div></div>";
    }).join("");
    var then = lastBackup ? parseTs(lastBackup) : null;
    var backupWhen = lastBackup ? agoPhrase(then ? (Date.now() - then.getTime()) / 1000 : null) : t("no_data");
    return '<div class="vbox ' + face[2] + '"><div class="vglyph" aria-hidden="true">' + face[1] + '</div>' +
      '<div style="flex:1 1 320px;min-width:0"><div class="vtitle">' + esc(data.attention || face[0]) + "</div></div>" +
      '<div style="flex:1 1 300px;display:flex;flex-wrap:wrap;gap:6px">' + checksFrom(verdict) + "</div></div>" +
      '<div class="tiles3">' + compHtml + "</div>" +
      '<div class="tiles3">' + acts + "</div>" +
      '<div class="tiles3" style="align-items:start">' +
      '<div class="card"><div class="h3" style="margin-bottom:10px">' + esc(t("install")) + '</div><div class="kv">' +
      kv(t("version"), data.version || t("no_data"), "mono") + kv(t("mode"), modeInfo.text, modeInfo.cls) +
      kv(t("owner"), owner.workspace_id ? owner.workspace_id.slice(0, 8) + "…" : t("no_data"), "mono") +
      kv(t("cutover"), cutover.identity ? String(cutover.identity).slice(0, 8) + (cutover.format ? " · " + cutover.format : "") : t("no_data"), "mono") +
      "</div></div>" +
      '<div class="card"><div class="h3" style="margin-bottom:10px">' + esc(t("launch_title")) + '</div><div class="kv">' +
      '<div class="k">' + esc(t("label")) + '</div><div class="mono">com.solar.system</div>' +
      '<div class="k">' + esc(t("interval")) + '</div><div>' + esc(t("every_60")) + "</div>" +
      '<div class="k">' + esc(t("last_pass")) + "</div>" + pass +
      '<div class="k">' + esc(t("functions")) + '</div><div class="muted">' + featureLine(features) + "</div></div></div>" +
      '<div class="card"><div class="h3" style="margin-bottom:10px">' + esc(t("daily_copy")) + '</div><div class="big" style="margin-bottom:4px">' +
      esc(backupWhen) + '</div><div class="note">' + esc(lastBackup ? fmt(lastBackup) : t("no_copy")) + " · " + backups.length + esc(t("copies")) + "</div></div>" +
      "</div>";
  }

  function kv(key, value, cls) {
    return '<div class="k">' + esc(key) + '</div><div class="' + cls + '" style="word-break:break-all">' + esc(value) + "</div>";
  }

  function renderTasks(data) {
    var tasks = data.tasks || [];
    var links = data.links || [];
    var history = data.history || [];
    var byStatus = data.by_status || {};
    var byId = {};
    tasks.forEach(function (task) { byId[task.id] = task; });
    var kids = {};
    links.forEach(function (link) { (kids[link.parent_id] = kids[link.parent_id] || []).push(link.child_id); });
    tasks.forEach(function (task) {
      if (task.parent_id) (kids[task.parent_id] = kids[task.parent_id] || []).push(task.id);
    });
    Object.keys(kids).forEach(function (id) {
      var seen = {};
      kids[id] = kids[id].filter(function (child) { if (seen[child]) return false; seen[child] = true; return true; });
    });
    function count(status) { return byStatus[status] || { n: 0, recurring: 0 }; }
    var attN = ATT.reduce(function (sum, status) { return sum + count(status).n; }, 0);
    var total = (data.statuses || []).reduce(function (sum, status) { return sum + count(status).n; }, 0);
    var filters = [{ key: "atencion", label: t("attention"), n: attN, rec: "", tone: "err", glyph: "▲" }, { key: "todos", label: t("all_tasks"), n: total, rec: "", tone: "neu", glyph: "≡" }];
    (data.statuses || []).forEach(function (status) {
      var spec = ts(status);
      var row = count(status);
      filters.push({ key: status, label: spec.label, n: row.n, rec: row.recurring ? " ↻" + row.recurring : "", tone: spec.tone, glyph: spec.glyph });
    });
    var filterHtml = filters.map(function (filter) {
      return '<button type="button" class="chip' + (ui.filter === filter.key ? " on" : "") + '" data-filter="' + esc(filter.key) + '">' +
        pill(filter.tone, filter.glyph, "") + esc(filter.label) + " <b>" + filter.n + "</b>" +
        (filter.rec ? '<span class="muted" title="' + esc(t("recurring_title")) + '">' + esc(filter.rec) + "</span>" : "") + "</button>";
    }).join("");
    function match(task) {
      if (ui.filter === "todos") return true;
      if (ui.filter === "atencion") return ATT.indexOf(task.status) >= 0;
      return task.status === ui.filter;
    }
    var roots = tasks.filter(function (task) { return !task.parent_id || !byId[task.parent_id]; }).slice().sort(function (a, b) {
      return (RANK[a.status] - RANK[b.status]) || String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    });
    var planned = [];
    roots.forEach(function (parent) {
      var children = (kids[parent.id] || []).map(function (id) { return byId[id]; }).filter(Boolean);
      var parentMatch = match(parent);
      var childMatch = children.filter(match);
      if (parentMatch || childMatch.length) {
        planned.push([parent, 0, children.length, !parentMatch]);
        (parentMatch ? children : childMatch).forEach(function (child) { planned.push([child, 1, 0, false]); });
      }
    });
    var visibleIds = planned.map(function (row) { return row[0].id; });
    if (visibleIds.indexOf(ui.task) < 0) ui.task = visibleIds[0] || null;
    var rows = planned.map(function (row) {
      var task = row[0], level = row[1], nKids = row[2], dim = row[3];
      var spec = ts(task.status);
      var cls = (task.status === "error" ? "err " : "") + (ui.task === task.id ? "sel " : "") + (dim ? "dim" : "");
      return '<div class="row pick ' + cls + '" style="grid-template-columns:108px minmax(0,1fr) 68px 76px 52px 112px" data-task="' + esc(task.id) + '">' +
        "<div>" + pill(spec.tone, spec.glyph, spec.label) + "</div>" +
        '<div class="w100" style="min-width:0;padding-left:' + (level ? 18 : 0) + 'px"><div class="trunc">' + (level ? "└ " : "") + esc(task.title || task.id) + "</div>" +
        '<div class="mono muted" style="font-size:10.5px">' + esc(String(task.id).slice(0, 8)) + (nKids ? " · " + nKids + " " + t("subtasks") : "") + (task.recurring ? " · ↻" : "") + "</div></div>" +
        '<div class="' + (task.provider ? "" : "note") + '">' + esc(task.provider || t("no_provider")) + "</div>" +
        '<div class="opt ' + (task.channel ? "" : "note") + '">' + esc(channelLabel(task.channel)) + "</div>" +
        '<div class="opt note">' + esc(fmtDay(task.created_at)) + "</div>" +
        '<div class="opt req" title="' + esc(t("col_requester")) + ": " + t("gap") + '"></div></div>';
    });
    var visible = rows.length;
    var selected = ui.task ? byId[ui.task] : null;
    var detail = selected ? taskDetail(selected, byId, kids, history) : '<div class="note">' + esc(t("no_tasks")) + "</div>";
    var machine = ui.machine ? machineTable(data, selected) : "";
    return '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">' + filterHtml + "</div>" +
      '<div class="split"><div class="card" style="padding:0;overflow:hidden"><div style="padding:10px 12px" class="note">' + esc(t("showing")) +
      visible + esc(t("of")) + (filters.filter(function (filter) { return filter.key === ui.filter; })[0] || { n: total }).n + "</div>" +
      '<div class="row hd" style="grid-template-columns:108px minmax(0,1fr) 68px 76px 52px 112px"><div>' + esc(t("col_status")) + "</div><div>" + esc(t("col_task")) + "</div><div>" + esc(t("col_provider")) + "</div><div>" + esc(t("col_channel")) + "</div><div>" + esc(t("col_created")) + '</div><div>' + esc(t("col_requester")) + '<div class="reqh">' +
      t("gap") + "</div></div></div>" + rows.join("") + "</div>" + detail + "</div>" +
      '<div class="card" style="padding:0;overflow:hidden"><button type="button" class="chip" style="margin:10px 12px" data-machine="1" aria-expanded="' +
      (ui.machine ? "true" : "false") + '">' + (ui.machine ? "▾ " : "▸ ") + esc(t("state_machine")) + "</button>" + machine + "</div>";
  }

  function taskDetail(task, byId, kids, history) {
    var spec = ts(task.status);
    var children = (kids[task.id] || []).map(function (id) { return byId[id]; }).filter(Boolean);
    var events = history.filter(function (event) { return event.task_id === task.id; });
    var lines = events.map(function (event, index) {
      var what = (event.from_status ? ts(event.from_status).label + " → " : "") + ts(event.to_status).label;
      if (event.actor) what += " · " + event.actor;
      return '<div class="' + (index === events.length - 1 ? "now" : "") + '"><div style="font-weight:500">' + esc(what) + '</div><div class="note">' + esc(fmt(event.ts, true)) + "</div></div>";
    }).join("") || '<div class="note">' + esc(t("no_history")) + "</div>";
    var kidHtml = children.map(function (child) {
      var childSpec = ts(child.status);
      return '<div class="row pick" style="grid-template-columns:auto minmax(0,1fr);padding:6px 4px;min-height:36px" data-task="' + esc(child.id) + '">' +
        pill(childSpec.tone, childSpec.glyph, "") + "<span>" + esc(child.title || child.id) + "</span></div>";
    }).join("");
    return '<div class="card sticky" style="display:flex;flex-direction:column;gap:12px"><div class="lbl">' + esc(t("detail")) + '</div><div style="font-weight:600">' +
      esc(task.title || task.id) + '</div><div style="display:flex;gap:8px;flex-wrap:wrap">' + pill(spec.tone, spec.glyph, spec.label) +
      '<span class="tag' + (task.recurring ? "" : " gap-hide") + '">↻ ' + esc(t("recurring")) + "</span></div>" +
      '<div class="kv" style="grid-template-columns:88px minmax(0,1fr)">' +
      kv("Id", task.id, "mono") + kv(t("col_provider"), task.provider || t("no_provider"), task.provider ? "" : "note") +
      kv(t("col_channel"), channelLabel(task.channel), task.channel ? "" : "note") +
      kv(t("parent"), task.parent_id ? String(task.parent_id).slice(0, 8) : t("root"), task.parent_id ? "mono" : "note") +
      '<div class="k">' + esc(t("col_requester")) + '</div><div><span class="gap">' + t("gap") + "</span></div></div>" +
      (children.length ? '<div><div class="lbl" style="margin-bottom:4px">' + esc(t("subtasks")) + " (" + children.length + ")</div>" + kidHtml + "</div>" : "") +
      '<div><div class="lbl" style="margin-bottom:8px">' + esc(t("history")) + '</div><div class="tl">' + lines + "</div></div></div>";
  }

  function machineTable(data, selected) {
    var byStatus = data.by_status || {};
    var rows = (data.statuses || []).map(function (status) {
      var spec = ts(status);
      var outs = (data.transitions || []).filter(function (pair) { return pair[0] === status; }).map(function (pair) {
        var next = ts(pair[1]);
        return '<span class="pill sm ' + next.tone + '">→ ' + esc(next.label) + "</span>";
      }).join("");
      return '<div class="row' + (selected && selected.status === status ? " sel" : "") + '" style="grid-template-columns:130px 60px minmax(0,1fr)"><div>' +
        pill(spec.tone, spec.glyph, spec.label) + '</div><div class="mono opt">' + ((byStatus[status] || {}).n || 0) +
        '</div><div class="w100" style="display:flex;gap:6px;flex-wrap:wrap">' + outs +
        (outs ? "" : '<span class="note">' + esc(t("final_state")) + "</span>") + "</div></div>";
    }).join("");
    return '<div class="row hd" style="grid-template-columns:130px 60px minmax(0,1fr)"><div>' + esc(t("col_status")) + "</div><div>" + esc(t("act_tasks")) + "</div><div>" + esc(t("can_go")) + "</div></div>" + rows;
  }

  function renderExec(data) {
    var total = data.total || 0;
    var byStatus = data.by_status || {};
    var success = byStatus.success || 0;
    var failed = byStatus.failed || 0;
    var reconciled = byStatus.reconciled || 0;
    var noProv = data.no_provider || {};
    var statusHtml = ["success", "failed", "reconciled"].map(function (key) {
      var spec = execRow(key);
      var n = byStatus[key] || 0;
      return '<div class="card"><div class="lbl">' + spec[2] + '</div><div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap"><div class="big">' +
        nf(n) + "</div>" + pill(spec[0], spec[1], pc(n, total)) + "</div></div>";
    }).join("");
    var providers = (data.providers || []).map(function (row) {
      var avg = row.avg_duration_ms;
      return '<div class="row" style="grid-template-columns:100px 64px 56px minmax(0,1fr)"><div style="font-weight:500">' + esc(row.provider) +
        '</div><div class="mono">' + nf(row.n) + '</div><div class="note">' + pc(row.n, total) +
        '</div><div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap"><span class="mono">' + esc(dur(avg)) +
        '</span><span class="pill sm warn' + (avg > 86400000 ? "" : " gap-hide") + '" title="' + esc(t("unusual_tip")) + '">▲ ' + esc(t("atypical")) + "</span></div></div>";
    }).join("");
    var channels = data.channels || [];
    var widest = channels.reduce(function (max, row) { return Math.max(max, row.n || 0); }, 0) || 1;
    var channelHtml = channels.map(function (row) {
      return '<div class="row" style="grid-template-columns:90px 56px minmax(0,1fr)"><div style="font-weight:500">' + esc(channelLabel(row.channel)) +
        '</div><div class="mono">' + nf(row.n) + '</div><div style="display:flex;align-items:center;gap:8px"><div class="bar" style="flex:1"><div style="background:var(--info);width:' +
        ((row.n / widest) * 100) + '%"></div></div><span class="note" style="width:44px;text-align:right">' + pc(row.n, total) + "</span></div></div>";
    }).join("");
    var days = data.days || [];
    var peak = days.reduce(function (max, row) { return Math.max(max, row.n || 0); }, 0) || 1;
    var dayHtml = days.map(function (row, index) {
      var height = Math.max(2, Math.round(Math.sqrt(row.n / peak) * 112));
      var label = index % 3 === 0 ? String(row.day).slice(8, 10) + "/" + String(row.day).slice(5, 7) : "";
      return '<div class="day" title="' + esc(fmtDay(row.day) + ": " + row.n) + '"><span class="v">' + (row.n >= 10 ? row.n : "") +
        '</span><div class="b" style="height:' + height + 'px"></div></div>';
    }).join("");
    var dayLabels = days.map(function (row, index) {
      var label = index % 3 === 0 ? String(row.day).slice(8, 10) + "/" + String(row.day).slice(5, 7) : "";
      return '<div style="flex:1;min-width:0;text-align:center;font-size:9.5px;color:var(--muted);font-family:ui-monospace,Menlo,monospace;white-space:nowrap">' + esc(label) + "</div>";
    }).join("");
    var recent = (data.recent || []).slice().reverse().map(function (row) {
      var spec = execRow(row.status);
      return '<div class="row' + (row.status === "failed" ? " err" : "") + '" style="grid-template-columns:130px 120px 90px 100px 100px minmax(0,1fr)">' +
        '<div class="note">' + esc(fmt(row.ts, true)) + "</div><div>" + pill(spec[0], spec[1], spec[2]) + "</div><div>" +
        esc(row.provider || t("no_provider")) + '</div><div class="opt ' + (row.channel ? "" : "note") + '">' + esc(channelLabel(row.channel)) +
        '</div><div class="mono">' + esc(dur(row.duration_ms)) + '</div><div class="opt req" style="max-width:240px" title="' + esc(t("col_requester")) + ": " + t("gap") + '"></div></div>';
    }).join("");
    return '<div class="tiles"><div class="card"><div class="lbl">' + esc(t("total")) + '</div><div class="big">' + nf(total) + '</div><div class="note">' +
      esc(fmtYear(data.first)) + " – " + esc(fmtYear(data.last)) + "</div></div>" + statusHtml + "</div>" +
      '<div class="bar" style="height:14px" role="img" aria-label="' + esc(t("ex_ok")) + " " + pc(success, total) + ", " + esc(t("ex_failed")) + " " + pc(failed, total) + ", " + esc(t("ex_reconciled")) + " " + pc(reconciled, total) + '">' +
      '<div class="seg-ok" style="width:' + (total ? success / total * 100 : 0) + '%"></div>' +
      '<div class="seg-err" style="width:' + (total ? failed / total * 100 : 0) + '%"></div>' +
      '<div class="seg-rec" style="width:' + (total ? reconciled / total * 100 : 0) + '%"></div></div>' +
      '<div class="tiles2"><div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">' + esc(t("by_provider")) + "</div>" +
      '<div class="row hd" style="grid-template-columns:100px 64px 56px minmax(0,1fr)"><div>' + esc(t("col_provider")) + "</div><div>" + esc(t("runs_short")) + "</div><div>%</div><div>" + esc(t("average")) + "</div></div>" +
      providers + '<div style="padding:12px 16px 4px" class="lbl">' + esc(t("no_provider_note")) + "</div>" +
      '<div class="row" style="grid-template-columns:150px minmax(0,1fr) 90px"><div>' + pill("err", "▲", (noProv.failed || 0) + " " + t("failed_n")) +
      '</div><div class="note w100">' + esc(t("mean")) + esc(dur(noProv.failed_avg_duration_ms)) + '</div><div class="mono"></div></div>' +
      '<div class="row" style="grid-template-columns:150px minmax(0,1fr) 90px"><div>' + pill("warn", "⇄", (noProv.reconciled || 0) + " " + t("reconciled_n")) +
      '</div><div class="note w100">' + esc(t("no_duration")) + '</div><div class="mono muted">—</div></div></div>' +
      '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">' + esc(t("by_channel")) + "</div>" +
      '<div class="row hd" style="grid-template-columns:90px 56px minmax(0,1fr)"><div>' + esc(t("channel")) + "</div><div>" + esc(t("runs_short")) + "</div><div>" + esc(t("weight")) + "</div></div>" +
      channelHtml + "</div></div>" +
      '<div class="card"><div class="h3" style="margin-bottom:10px">' + esc(t("by_day")) + '<span class="note" style="font-family:\'Inter\',sans-serif;font-weight:400">' + esc(t("day_note")) + "</span></div>" +
      '<div style="display:flex;align-items:flex-end;height:140px;gap:2px;border-bottom:1px solid var(--muted)">' + dayHtml + "</div>" +
      '<div class="dlabels" style="display:flex;gap:2px;margin-top:3px">' + dayLabels + "</div></div>" +
      '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">' + esc(t("recent_runs")) + "</div>" +
      '<div class="row hd" style="grid-template-columns:130px 120px 90px 100px 100px minmax(0,1fr)"><div>' + esc(t("when")) + "</div><div>" + esc(t("result")) + "</div><div>" + esc(t("col_provider")) + "</div><div>" + esc(t("col_channel")) + "</div><div>" + esc(t("duration")) + '</div><div>' + esc(t("col_requester")) + '<div class="reqh">' +
      t("gap") + "</div></div></div>" + recent + "</div>";
  }

  function renderContinuity(data) {
    var channels = data.channels || [];
    if (!Array.isArray(channels)) channels = channels ? [String(channels)] : [];
    var summaries = (data.summaries || []).map(function (row) {
      var kind = String(row.file || "").indexOf("task_") === 0 ? t("task_kind") : t("channel_kind");
      var when = parseTs(row.date);
      var ago = when ? ageText((Date.now() - when.getTime()) / 1000) : t("no_data");
      return '<div class="row" style="grid-template-columns:80px minmax(0,1fr) 90px 100px"><div>' + pill("neu", "", kind) +
        '</div><div class="w100"><div class="mono" style="word-break:break-all;font-size:11.5px">' + esc(row.file) +
        '</div><div class="note">' + esc(row.first_line || "") + '</div></div><div>' + esc(fmtDay(row.date)) +
        '</div><div class="note">' + esc(ago) + "</div></div>";
    }).join("");
    var next = data.next_owner ? esc(data.next_owner) : '<span class="gap">' + esc(t("unassigned")) + "</span>";
    return '<div class="card" style="display:flex;flex-direction:column;gap:8px"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap"><div class="lbl">' + esc(t("active_intent")) + "</div>" +
      pill("neu", "◷", ageLabel(data.at)) +
      '</div><div class="note">' + esc(t("continuity")) + '</div><div class="lbl">' + esc(t("saved")) +
      '</div><div style="font-size:15px">' + esc(plain(data.active)) + "</div></div>" +
      '<div class="tiles"><div class="card"><div class="lbl">' + esc(t("pending")) + '</div><div class="big">' + esc(showCount(data.pending)) + "</div></div>" +
      '<div class="card"><div class="lbl">' + esc(t("decisions")) + '</div><div class="big">' + esc(showCount(data.decisions)) + "</div></div>" +
      '<div class="card"><div class="lbl">' + esc(t("next_owner")) + '</div><div style="margin-top:8px">' + next + "</div></div>" +
      '<div class="card"><div class="lbl">' + esc(t("updated_label")) + '</div><div class="big">' + esc(ageLabel(data.at)) +
      '</div><div class="note">' + esc(data.at ? fmt(data.at) : t("no_data")) + "</div></div></div>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><span class="lbl">' + esc(t("channels_seen")) + "</span>" +
      channels.map(function (name) { return '<span class="tag" style="color:var(--text)">' + esc(channelLabel(name)) + "</span>"; }).join("") + "</div>" +
      '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">' + esc(t("summaries")) + "</div>" +
      '<div class="row hd" style="grid-template-columns:80px minmax(0,1fr) 90px 100px"><div>' + esc(t("origin")) + "</div><div>" + esc(t("file")) + "</div><div>" + esc(t("date")) + "</div><div>" + esc(t("ago_col")) + "</div></div>" +
      summaries + "</div>";
  }

  function mandateMode(item) {
    if (item && item.revoked_at) return "revoked";
    return item && item.mode;
  }
  function modePill(mode) {
    if (mode === "active") return pill("ok", "●", t("mode_active"));
    if (mode === "shadow") return pill("neu", "◐", t("mode_trial"));
    if (mode === "paused") return pill("warn", "◔", t("mode_paused"));
    if (mode === "revoked") return pill("neu", "⊘", t("mode_revoked"));
    return pill("info", "?", t("mode_none"));
  }

  function renderMandates(data) {
    var events = data.events || {};
    var cols = "170px 250px 150px 90px 90px minmax(0,1fr)";
    var rows = (data.defined || []).map(function (item) {
      var event = events[item.name];
      var when = event ? "" : " note";
      var mode = mandateMode(item);
      var revoked = mode === "revoked";
      var revokedNote = revoked
        ? '<div class="note">' + esc(item.revoked_at ? (t("revoked_on") + fmt(item.revoked_at)) : t("no_revoke_date")) + "</div>"
        : "";
      return '<div class="row' + (revoked ? " dim" : "") + '" style="grid-template-columns:' + cols + '"><div class="w100" style="font-weight:500">' +
        esc(item.name) + "</div><div>" + modePill(mode) + revokedNote + '</div><div><div><span class="mono">' +
        nf(event ? event.events : 0) + '</span> <span class="note">' + esc(t("events")) + '</span></div><div class="note' + (event && event.shadow ? "" : " gap-hide") + '">' +
        (event ? event.shadow + " " + t("in_trial") : "") + "</div></div>" +
        '<div class="opt' + when + '">' + esc(event && event.first ? fmtDay(event.first) : t("no_use")) + "</div>" +
        '<div class="' + when.trim() + '">' + esc(event && event.last ? fmtDay(event.last) : t("no_use")) + "</div>" +
        '<div class="' + when.trim() + '">' + esc(event && event.last && parseTs(event.last) ? ageText((Date.now() - parseTs(event.last).getTime()) / 1000) : "—") + "</div></div>";
    }).join("");
    var gate = data.gate || { total: 0, allowed: 0, last: [] };
    var denied = (gate.total || 0) - (gate.allowed || 0);
    var last = (gate.last || []).map(function (row) {
      var tone = row.allowed ? "ok" : (row.code === "approval_required" ? "warn" : "err");
      var glyph = row.allowed ? "✓" : (row.code === "approval_required" ? "◔" : "✕");
      var label = row.allowed ? t("allowed") : (row.code === "approval_required" ? t("asks") : t("denied"));
      return '<div class="row' + (!row.allowed && row.code !== "approval_required" ? " err" : "") + '" style="grid-template-columns:130px 180px 160px 220px minmax(0,1fr)">' +
        '<div class="note">' + esc(fmt(row.ts, true)) + '</div><div class="mono">' + esc(row.tool) + "</div><div>" + pill(tone, glyph, label) +
        '</div><div class="opt">' + esc(gateReason(row.code)) + '</div><div class="opt req" style="max-width:240px" title="' + esc(t("col_requester")) + ": " + t("gap") + '"></div></div>';
    }).join("");
    return '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 8px"><div class="h3">' + esc(t("delegations")) + "</div>" +
      '<div class="note" style="margin-top:6px">' + esc(t("delegation")) + '</div><div style="margin-top:8px">' +
      esc(activeLabel(data.active)) + "</div></div>" +
      '<div class="row hd" style="grid-template-columns:' + cols + '"><div>' + esc(t("delegation_col")) + "</div><div>" + esc(t("mode_col")) + "</div><div>" + esc(t("events_col")) + "</div><div>" + esc(t("first_use")) + "</div><div>" + esc(t("last_use")) + "</div><div>" + esc(t("ago_col")) + "</div></div>" +
      rows + "</div>" +
      '<div class="card"><div class="h3" style="margin-bottom:10px">' + esc(t("perm_decisions")) + '</div><div style="display:flex;gap:28px;align-items:baseline;margin-bottom:10px;flex-wrap:wrap">' +
      '<div><div class="big">' + nf(gate.total) + '</div><div class="note">' + esc(t("decisions_word")) + "</div></div>" +
      '<div><div class="big" style="color:var(--ok)">' + nf(gate.allowed) + '</div><div class="note">' + esc(t("permitted")) + "</div></div>" +
      '<div><div class="big" style="color:var(--warn)">' + nf(denied) + '</div><div class="note">' + esc(t("not_permitted")) + "</div></div></div>" +
      '<div class="bar" style="height:14px" role="img" aria-label="' + gate.allowed + " " + t("permitted") + ", " + denied + " " + t("not_permitted") + ", " + gate.total + '">' +
      '<div class="seg-ok" style="width:' + (gate.total ? gate.allowed / gate.total * 100 : 0) + '%"></div>' +
      '<div class="seg-rec" style="width:' + (gate.total ? denied / gate.total * 100 : 0) + '%"></div></div>' +
      '<div class="note" style="margin-top:8px">' + esc(t("perm_note")) + "</div></div>" +
      '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">' + esc(t("recent_decisions")) + "</div>" +
      '<div class="row hd" style="grid-template-columns:130px 180px 160px 220px minmax(0,1fr)"><div>' + esc(t("when")) + "</div><div>" + esc(t("tool")) + "</div><div>" + esc(t("decision")) + "</div><div>" + esc(t("reason")) + '</div><div>' + esc(t("col_requester")) + '<div class="reqh">' +
      t("gap") + "</div></div></div>" + last + "</div>";
  }

  function renderIdes(rows) {
    rows = rows || [];
    var broken = rows.reduce(function (sum, row) { return sum + ((row.broken || []).length); }, 0);
    var names = { ".claude/skills": "Claude", ".gemini/skills": "Gemini", ".cursor/skills": "Cursor", ".agents/skills": "Codex + Antigravity" };
    var body = rows.map(function (row) {
      var shared = row.kind === "copy" && (row.shared_with || []).length;
      var how = shared ? t("shared_copy") : (row.kind === "copy" ? t("copy") : t("link"));
      var tone = row.kind === "copy" ? "neu" : "info";
      var glyph = row.kind === "copy" ? "▭" : "↪";
      var brokenText = (row.broken || []).length
        ? '<span class="mono">' + esc(row.broken.join(", ")) + "</span>"
        : "0";
      return '<div class="row' + ((row.broken || []).length ? " err" : "") + '" style="grid-template-columns:160px 160px 150px 70px minmax(0,1fr)">' +
        '<div style="font-weight:600">' + esc(names[row.destination] || row.destination) + "</div><div>" + pill(tone, glyph, how) +
        '</div><div class="mono opt">' + esc(row.destination) + '</div><div class="mono">' + esc(row.skills) +
        '</div><div class="' + ((row.broken || []).length ? "" : "muted") + '">' + brokenText + "</div></div>";
    }).join("");
    var counts = rows.map(function (row) { return row.skills; });
    var skillCount = counts.length && counts.every(function (n) { return n === counts[0]; }) ? counts[0] : "—";
    return '<div class="tiles"><div class="card"><div class="lbl">' + esc(t("ides")) + '</div><div class="big">' + rows.length + "</div></div>" +
      '<div class="card"><div class="lbl">' + esc(t("skills_per")) + '</div><div class="big">' + esc(skillCount) + "</div></div>" +
      '<div class="card"><div class="lbl">' + esc(t("broken_links")) + '</div><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><div class="big">' +
      broken + "</div>" + pill(broken ? "err" : "ok", broken ? "▲" : "✓", broken ? t("repair") : t("none_broken")) + "</div></div></div>" +
      '<div class="card" style="padding:0;overflow:hidden"><div class="row hd" style="grid-template-columns:160px 160px 150px 70px minmax(0,1fr)"><div>IDE</div><div>' + esc(t("receives")) + "</div><div>" + esc(t("path")) + "</div><div>" + esc(t("skills")) + "</div><div>" + esc(t("broken")) + "</div></div>" +
      body + "</div>";
  }

  function renderIngress(data, health) {
    var stamp = data.stamp || {};
    var gateway = health && health.data && health.data.verdict ? health.data.verdict.gateway : null;
    var tunnel = health && health.refused
      ? pill("err", "▲", t("pill_refused")) + '<div class="note">' + esc(health.refused) + "</div>"
      : (!gateway || gateway.state === "unverified"
        ? pill("info", "?", t("pill_no_data"))
        : (gateway.state === "healthy" ? pill("ok", "✓", t("connector_ready")) : pill("err", "▲", gateway.connector_ready ? t("pill_trouble") : t("connector_down"))));
    var claim = data.claim_telegram ? pill("ok", "✓", t("yes")) : pill("err", "✕", t("no"));
    var keys = stamp && stamp.keys_present;
    var keyText = Array.isArray(keys) ? keys.join(",") : String(keys || "");
    var n8n = keyText.indexOf("SOLAR_N8N_WEBHOOK_SECRET") >= 0 ? pill("ok", "✓", t("configured")) : pill("neu", "○", t("absent"));
    var httpAddr = stamp.http_host && stamp.http_port ? stamp.http_host + ":" + stamp.http_port : t("no_data");
    return '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">' + esc(t("http_channels")) + "</div>" +
      '<div class="row hd" style="grid-template-columns:180px 200px minmax(0,1fr)"><div>' + esc(t("channel")) + "</div><div>" + esc(t("address")) + "</div><div>" + esc(t("scope")) + "</div></div>" +
      '<div class="row" style="grid-template-columns:180px 200px minmax(0,1fr)"><div style="font-weight:500">' + esc(t("console")) + '</div><div class="mono">' + esc(location.host || "127.0.0.1:9000") + "</div><div>" + pill("ok", "✓", t("local_only")) + "</div></div>" +
      '<div class="row" style="grid-template-columns:180px 200px minmax(0,1fr)"><div style="font-weight:500">' + esc(t("gateway_http")) + '</div><div class="mono">' + esc(httpAddr) + "</div><div>" + pill("ok", "✓", t("local_tunnel")) + "</div></div>" +
      '<div class="row" style="grid-template-columns:180px 200px minmax(0,1fr)"><div style="font-weight:500">' + esc(t("websocket")) + '</div><div class="mono">' + esc(stamp.ws_port ? t("port_word") + stamp.ws_port : t("no_data")) + "</div><div>" + pill("info", "?", t("pass_port")) + "</div></div></div>" +
      '<div class="tiles2"><div class="card" style="display:flex;flex-direction:column;gap:10px"><div class="h3">' + esc(t("telegram")) + '</div><div class="kv" style="grid-template-columns:170px minmax(0,1fr)">' +
      '<div class="k">' + esc(t("claim")) + '</div><div>' + claim + '</div><div class="k">' + esc(t("real_state")) + '</div><div>' + pill("info", "?", t("not_verified")) +
      '</div><div class="k">' + esc(t("n8n_secret")) + "</div><div>" + n8n + "</div></div></div>" +
      '<div class="card" style="display:flex;flex-direction:column;gap:10px"><div class="h3">' + esc(t("tunnel")) + '</div><div class="kv" style="grid-template-columns:120px minmax(0,1fr)">' +
      kv(t("mode"), tunnelMode(stamp.tunnel_mode), stamp.tunnel_mode === "named" || stamp.tunnel_mode === "quick" || !stamp.tunnel_mode ? "" : "mono") +
      kv(t("name"), stamp.tunnel_name || t("no_data"), "mono") +
      kv(t("hostname"), data.hostname || t("no_data"), "mono") +
      '<div class="k">' + esc(t("state")) + "</div><div>" + tunnel + "</div></div></div></div>";
  }

  function userIdNote(executions) {
    if (!executions) return t("no_data");
    if (executions.refused) return executions.refused;
    var count = executions.data && executions.data.user_id_values;
    if (count == null) return t("no_data");
    return nf(count) + t("user_ids");
  }
  function renderRequester(data, executions) {
    var rows = [
      ["tasks", t("nav_tasks"), "tareas"],
      ["executions", t("nav_runs"), "ejecuciones"],
      ["approvals", t("perm_decisions"), "autonomia"]
    ].map(function (row) {
      var item = (data && data[row[0]]) || {};
      return '<div class="row" style="grid-template-columns:220px 110px minmax(0,1fr)"><div style="font-weight:500">' + esc(row[1]) +
        '</div><div class="mono">—</div><div><button type="button" class="chip" data-screen="' + row[2] + '">' + esc(row[1]) +
        ' →</button><div class="note">' + (item.recorded ? esc(item.label) : t("gap")) + "</div></div></div>";
    }).join("");
    return '<div class="card" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap"><span class="gap">' + t("gap") +
      '</span><span class="note">' + esc(userIdNote(executions)) + "</span></div>" +
      '<div class="card" style="padding:0;overflow:hidden"><div class="row hd" style="grid-template-columns:220px 110px minmax(0,1fr)"><div>' + esc(t("where")) + "</div><div>" + esc(t("records")) + "</div><div>" + esc(t("go")) + "</div></div>" +
      rows + "</div>";
  }

  document.addEventListener("click", function (event) {
    var screen = event.target.closest("[data-screen]");
    if (screen && screen.getAttribute("data-screen") !== ui.screen) {
      openScreen(screen.getAttribute("data-screen"));
      return;
    }
    var filter = event.target.closest("[data-filter]");
    if (filter) {
      ui.filter = filter.getAttribute("data-filter");
      if (cache.tareas) paint("tareas", cache.tareas);
      return;
    }
    var task = event.target.closest("[data-task]");
    if (task) {
      ui.task = task.getAttribute("data-task");
      if (cache.tareas) paint("tareas", cache.tareas);
      return;
    }
    if (event.target.closest("[data-machine]")) {
      ui.machine = !ui.machine;
      if (cache.tareas) paint("tareas", cache.tareas);
    }
  });

  $("theme").addEventListener("click", function () {
    ui.theme = ui.theme === "light" ? "dark" : "light";
    try { localStorage.setItem("solar-console-theme", ui.theme); } catch (error) { /* keep the toggle for this view */ }
    paintChrome();
  });

  try {
    var stored = localStorage.getItem("solar-console-theme");
    if (stored === "light" || stored === "dark") ui.theme = stored;
  } catch (error) { /* default stays dark */ }

  openScreen("resumen");
})();
