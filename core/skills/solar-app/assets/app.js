/* Read-only console. Screens read /api/console/* and do not recompute the verdict. */
(function () {
  "use strict";

  var TZ = "Europe/Madrid";
  var GAP = "disponible cuando Solar sepa quién le habla";
  var SCREENS = [
    ["resumen", "Resumen", "¿Está sana mi instalación, y desde cuándo no hace nada?", "/api/console/health"],
    ["tareas", "Tareas", "¿Qué tareas hay y qué les ha pasado?", "/api/console/tasks"],
    ["ejecuciones", "Ejecuciones", "¿Qué ha ejecutado Solar y cómo le ha ido?", "/api/console/executions"],
    ["continuidad", "Continuidad", "¿Dónde se quedó?", "/api/console/continuity"],
    ["autonomia", "Autonomía", "¿Qué hace Solar sin preguntarme?", "/api/console/mandates"],
    ["ides", "IDEs", "¿Qué ve cada IDE?", "/api/console/ides"],
    ["entrada", "Entrada externa", "¿Qué puede entrar desde fuera?", "/api/console/ingress"],
    ["solicitante", "Solicitante", "¿Quién pidió esto?", "/api/console/requester"]
  ];
  var TS = {
    draft: ["neu", "○", "Borrador"], planned: ["info", "◔", "Planificada"], queued: ["info", "◑", "En cola"],
    active: ["info", "▶", "Activa"], completed: ["ok", "✓", "Completada"], error: ["err", "▲", "Error"],
    archived: ["neu", "▭", "Archivada"], cancelled: ["neu", "⊘", "Cancelada"]
  };
  var ES = { success: ["ok", "✓", "Bien"], failed: ["err", "▲", "Fallida"], reconciled: ["warn", "⇄", "Reconciliada"] };
  var ATT = ["error", "queued", "active", "planned"];
  var RANK = { error: 0, active: 1, queued: 2, planned: 3, draft: 4, completed: 5, archived: 6, cancelled: 7 };
  var VERDICT = {
    calm: ["CALMA", "✓", "v-ok"],
    fault: ["AVERÍA", "✕", "v-bad"],
    unverified: ["SIN VERIFICAR", "?", "v-unk"]
  };
  var REASON = {
    database: "La base de estado es ilegible.",
    port: "El puerto de la consola está ocupado por otro proceso.",
    launchagent: "El LaunchAgent no tiene una pasada reciente.",
    system: "System en fallo.",
    router: "El router es desconocido porque el estado se niega.",
    gateway: "El gateway no está sano."
  };
  var CHECK = {
    database: "Base", port: "Puerto 9000", system: "System", router: "Router",
    launchagent: "LaunchAgent", gateway: "Gateway"
  };

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
  function nf(n) { return String(n == null ? 0 : n).replace(/\B(?=(\d{3})+(?!\d))/g, "."); }
  function pc(part, total) {
    if (!total) return "0,0 %";
    return ((part / total) * 100).toFixed(1).replace(".", ",") + " %";
  }
  function ageFrom(value) {
    var date = parseTs(value);
    if (!date) return null;
    var seconds = (Date.now() - date.getTime()) / 1000;
    return seconds < 0 ? 0 : seconds;
  }
  function ageLabel(value) {
    var seconds = ageFrom(value);
    return seconds == null ? "sin dato" : ("hace " + ageText(seconds));
  }
  function ageText(seconds) {
    if (seconds == null || seconds < 0) return "sin dato";
    var m = Math.floor(seconds / 60);
    if (m < 1) return "menos de 1 min";
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
    if (!date) return "sin dato";
    var opts = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: TZ };
    if (withSeconds) opts.second = "2-digit";
    return date.toLocaleString("es-ES", opts);
  }
  function fmtDay(value) {
    var date = parseTs(value);
    if (!date) return "sin dato";
    return date.toLocaleDateString("es-ES", { day: "numeric", month: "short", timeZone: TZ });
  }
  function fmtYear(value) {
    var date = parseTs(value);
    if (!date) return "sin dato";
    return date.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: "numeric", timeZone: TZ });
  }
  function dur(value) {
    if (value == null || value === "") return "—";
    var v = Number(value);
    if (!isFinite(v)) return "—";
    if (v < 1000) return Math.round(v) + " ms";
    if (v < 60000) return (v / 1000).toFixed(1).replace(".", ",") + " s";
    if (v < 3600000) return Math.floor(v / 60000) + " min " + Math.round((v % 60000) / 1000) + " s";
    if (v < 86400000) return Math.floor(v / 3600000) + " h " + Math.round((v % 3600000) / 60000) + " min";
    return (v / 86400000).toFixed(1).replace(".", ",") + " d";
  }
  function ts(status) {
    var row = TS[status] || ["neu", "·", status || "sin estado"];
    return { tone: row[0], glyph: row[1], label: row[2] };
  }
  function refusedBox(reason) {
    return '<div class="card" style="display:flex;flex-direction:column;gap:8px">' +
      pill("err", "▲", "La ruta se negó") +
      '<div>' + esc(reason || "sin motivo") + "</div></div>";
  }
  function plain(value) {
    if (value == null || value === "") return "sin dato";
    if (typeof value === "string" || typeof value === "number") return String(value);
    try { return JSON.stringify(value); } catch (error) { return "sin dato"; }
  }
  function showCount(value) {
    if (value == null || value === "") return "—";
    if (Array.isArray(value)) return String(value.length);
    if (typeof value === "object") return String(Object.keys(value).length);
    return String(value);
  }

  function screenOf(id) {
    for (var i = 0; i < SCREENS.length; i++) if (SCREENS[i][0] === id) return SCREENS[i];
    return SCREENS[0];
  }

  function paintChrome() {
    var app = $("app");
    app.className = "app " + (ui.theme === "light" ? "t-light" : "t-dark");
    $("theme").textContent = ui.theme === "light" ? "Oscuro" : "Claro";
    var current = screenOf(ui.screen);
    $("title").textContent = current[1];
    $("question").textContent = current[2];
    var html = "";
    SCREENS.forEach(function (row, index) {
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
    $("updated").textContent = healthStamp ? ("Actualizado " + fmt(healthStamp, true)) : "Actualizado —";
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
        if (response.status === 503 && body && body.refused) return { refused: body.error || "refused" };
        if (!response.ok) return { refused: (body && body.error) || ("HTTP " + response.status) };
        return { data: body };
      });
    }).catch(function (error) {
      return { refused: error && error.message ? error.message : "sin respuesta" };
    });
  }

  function openScreen(id) {
    ui.screen = id;
    clearInterval(timer);
    timer = 0;
    paintChrome();
    var box = $("health");
    var known = cache[id];
    if (!known) box.innerHTML = '<div class="note">Leyendo…</div>';
    else if (id === "entrada" && !known.refused) box.innerHTML = renderIngress(known.data, null);
    else paint(id, known);
    var jobs = [load(screenOf(id)[3])];
    if (id === "entrada") jobs.push(load("/api/console/health"));
    Promise.all(jobs).then(function (parts) {
      var payload = parts[0];
      var health = id === "entrada" ? (parts[1] || { refused: "sin respuesta" }) : null;
      if (ui.screen !== id) {
        cache[id] = payload;
        return;
      }
      cache[id] = payload;
      if (id === "resumen" && payload.data) healthStamp = new Date().toISOString();
      if (id === "entrada") {
        box.innerHTML = payload.refused ? refusedBox(payload.refused) : renderIngress(payload.data, health);
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
      var label = CHECK[check.id] || check.id;
      var tip = REASON[check.id] || label;
      if (check.id === "launchagent" && verdict.launchagent && verdict.launchagent.age_seconds != null && check.state !== "unverified") {
        label += ": hace " + ageText(verdict.launchagent.age_seconds);
      }
      if (check.state === "ok") return '<span class="pill ok" title="' + esc(tip) + '">✓ ' + esc(label) + "</span>";
      if (check.state === "fault") return '<span class="pill err" title="' + esc(tip) + '">▲ ' + esc(label) + "</span>";
      return '<span class="pill info" title="' + esc(tip) + '">? ' + esc(label) + ": sin dato</span>";
    }).join("");
  }

  function verdictReason(verdict) {
    var reasons = verdict.reasons || [];
    if (verdict.verdict === "calm") {
      var age = verdict.launchagent && verdict.launchagent.age_seconds;
      var ready = verdict.gateway && verdict.gateway.connector_ready;
      var pass = age == null ? "Pasada sin hora." : ("Última pasada hace " + ageText(age) + ".");
      return pass + (ready ? " Gateway con el conector listo." : "");
    }
    if (reasons.length) return reasons.map(function (code) { return REASON[code] || code; }).join(" ");
    if ((verdict.unverified || []).length) return "Sin avería, pero hay comprobaciones sin dato.";
    return "";
  }

  function gatewayCause(gateway) {
    if (!gateway || gateway.state === "unverified") return "Sin dato.";
    if (gateway.state === "healthy") return "Procesos, /health local y conector listos.";
    var bits = [];
    if (!gateway.local_health) bits.push("/health local no responde");
    if (!gateway.connector_ready) bits.push("conector no listo");
    if (!gateway.processes_alive) bits.push("algún proceso caído");
    return bits.join(" · ") || "Con problemas.";
  }

  function renderHealth(data) {
    var verdict = data.verdict || {};
    var face = VERDICT[verdict.verdict] || VERDICT.unverified;
    var launch = verdict.launchagent || {};
    var gateway = verdict.gateway || { state: "unverified" };
    var activity = data.last_activity || {};
    var owner = data.owner || {};
    var cutover = data.cutover || {};
    var backups = data.backups || [];
    var lastBackup = backups.length ? backups[backups.length - 1] : null;
    var features = (data.stamp && data.stamp.features) || null;
    var featureText = features ? Object.keys(features).map(function (name) { return name + " " + features[name]; }).join(", ") : "sin dato";
    var pass = launch.state === "unverified" || launch.at == null
      ? '<div class="gap">no consta</div>'
      : '<div class="' + (launch.state === "stale" ? "txt-err" : "") + '">hace ' + esc(ageText(launch.age_seconds)) + "</div>";
    var cards = [
      ["Base", data.database ? ["err", "▲", "Se negó"] : ["ok", "✓", "Legible"], data.database ? data.database.refused : "La base se puede leer.", data.database ? "" : ""],
      ["Gateway", gateway.state === "healthy" ? ["ok", "✓", "Listo"] : (gateway.state === "problems" ? ["err", "▲", "Con problemas"] : ["info", "?", "Sin dato"]), gatewayCause(gateway), launch.at ? ("Sello " + fmt(launch.at, true)) : "Sin sello"],
      ["Continuidad", data.continuity_at ? ["neu", "◷", "Registrada"] : ["info", "?", "Sin dato"], data.continuity_at ? ("Actualizada hace " + ageText(data.continuity_age_seconds) + ".") : "Sin registro.", data.continuity_at ? fmt(data.continuity_at) : ""]
    ];
    var compHtml = cards.map(function (card) {
      return '<div class="card" style="display:flex;flex-direction:column;gap:6px"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><div class="h3">' +
        esc(card[0]) + "</div>" + pill(card[1][0], card[1][1], card[1][2]) + "</div><div>" + esc(card[2]) + '</div><div class="note">' + esc(card[3]) + "</div></div>";
    }).join("");
    var acts = [
      ["Router", activity.router],
      ["Tareas", activity.tasks],
      ["Mandatos", activity.mandates]
    ].map(function (row) {
      var item = row[1] || {};
      var when = item.at ? ("hace " + ageText(item.age_seconds)) : "sin dato";
      return '<div class="card"><div class="lbl">' + esc(row[0]) + '</div><div class="big" style="margin:4px 0">' +
        esc(when) + '</div><div class="note">' + esc(item.at ? fmt(item.at) : "sin dato") + "</div></div>";
    }).join("");
    var backupAge = "sin dato";
    if (lastBackup) {
      var then = parseTs(lastBackup);
      backupAge = then ? ageText((Date.now() - then.getTime()) / 1000) : "sin dato";
    }
    return '<div class="vbox ' + face[2] + '"><div class="vglyph" aria-hidden="true">' + face[1] + '</div>' +
      '<div style="flex:1 1 300px;min-width:0;display:flex;flex-direction:column;gap:6px"><div class="vword">' + face[0] +
      '</div><div style="font-size:14px">' + esc(verdictReason(verdict)) + "</div></div>" +
      '<div style="flex:1 1 300px;display:flex;flex-wrap:wrap;gap:6px">' + checksFrom(verdict) + "</div></div>" +
      '<div class="tiles3">' + compHtml + "</div>" +
      '<div class="tiles3">' + acts + "</div>" +
      '<div class="tiles3" style="align-items:start">' +
      '<div class="card"><div class="h3" style="margin-bottom:10px">Instalación</div><div class="kv">' +
      kv("Versión", data.version || "sin dato", "mono") + kv("Modo", data.mode || "sin dato", "") +
      kv("Dueño", owner.workspace_id ? owner.workspace_id.slice(0, 8) + "…" : "sin dato", "mono") +
      kv("Último corte", cutover.identity ? String(cutover.identity).slice(0, 8) + (cutover.format ? " · " + cutover.format : "") : "sin dato", "mono") +
      "</div></div>" +
      '<div class="card"><div class="h3" style="margin-bottom:10px">LaunchAgent</div><div class="kv">' +
      '<div class="k">Etiqueta</div><div class="mono">com.solar.system</div>' +
      '<div class="k">Intervalo</div><div>cada 60 s</div>' +
      '<div class="k">Última pasada</div>' + pass +
      '<div class="k">Funciones</div><div class="muted">' + esc(featureText) + "</div></div></div>" +
      '<div class="card"><div class="h3" style="margin-bottom:10px">Copia diaria</div><div class="big" style="margin-bottom:4px">' +
      esc(lastBackup ? ("hace " + backupAge) : "sin dato") + '</div><div class="note">' + esc(lastBackup ? fmt(lastBackup) : "sin copia") + " · " + backups.length + " copias guardadas</div></div>" +
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
    var filters = [{ key: "atencion", label: "Atención", n: attN, rec: "", tone: "err", glyph: "▲" }, { key: "todos", label: "Todas", n: total, rec: "", tone: "neu", glyph: "≡" }];
    (data.statuses || []).forEach(function (status) {
      var spec = ts(status);
      var row = count(status);
      filters.push({ key: status, label: spec.label, n: row.n, rec: row.recurring ? " ↻" + row.recurring : "", tone: spec.tone, glyph: spec.glyph });
    });
    var filterHtml = filters.map(function (filter) {
      return '<button type="button" class="chip' + (ui.filter === filter.key ? " on" : "") + '" data-filter="' + esc(filter.key) + '">' +
        pill(filter.tone, filter.glyph, "") + esc(filter.label) + " <b>" + filter.n + "</b>" +
        (filter.rec ? '<span class="muted" title="recurrentes">' + esc(filter.rec) + "</span>" : "") + "</button>";
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
        '<div class="mono muted" style="font-size:10.5px">' + esc(String(task.id).slice(0, 8)) + (nKids ? " · " + nKids + " subtareas" : "") + (task.recurring ? " · ↻" : "") + "</div></div>" +
        '<div class="' + (task.provider ? "" : "note") + '">' + esc(task.provider || "sin proveedor") + "</div>" +
        '<div class="opt ' + (task.channel ? "" : "note") + '">' + esc(task.channel || "sin canal") + "</div>" +
        '<div class="opt note">' + esc(fmtDay(task.created_at)) + "</div>" +
        '<div class="opt req" title="Solicitante: ' + GAP + '"></div></div>';
    });
    var visible = rows.length;
    var selected = ui.task ? byId[ui.task] : null;
    var detail = selected ? taskDetail(selected, byId, kids, history) : '<div class="note">Sin tareas.</div>';
    var machine = ui.machine ? machineTable(data, selected) : "";
    return '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">' + filterHtml + "</div>" +
      '<div class="split"><div class="card" style="padding:0;overflow:hidden"><div style="padding:10px 12px" class="note">Mostrando ' +
      visible + " de " + (filters.filter(function (filter) { return filter.key === ui.filter; })[0] || { n: total }).n + "</div>" +
      '<div class="row hd" style="grid-template-columns:108px minmax(0,1fr) 68px 76px 52px 112px"><div>Estado</div><div>Tarea</div><div>Proveedor</div><div>Canal</div><div>Creada</div><div>Solicitante<div class="reqh">' +
      GAP + "</div></div></div>" + rows.join("") + "</div>" + detail + "</div>" +
      '<div class="card" style="padding:0;overflow:hidden"><button type="button" class="chip" style="margin:10px 12px" data-machine="1" aria-expanded="' +
      (ui.machine ? "true" : "false") + '">' + (ui.machine ? "▾ " : "▸ ") + "Máquina de estados</button>" + machine + "</div>";
  }

  function taskDetail(task, byId, kids, history) {
    var spec = ts(task.status);
    var children = (kids[task.id] || []).map(function (id) { return byId[id]; }).filter(Boolean);
    var events = history.filter(function (event) { return event.task_id === task.id; });
    var lines = events.map(function (event, index) {
      var what = (event.from_status ? ts(event.from_status).label + " → " : "") + ts(event.to_status).label;
      if (event.actor) what += " · " + event.actor;
      return '<div class="' + (index === events.length - 1 ? "now" : "") + '"><div style="font-weight:500">' + esc(what) + '</div><div class="note">' + esc(fmt(event.ts, true)) + "</div></div>";
    }).join("") || '<div class="note">Sin historia.</div>';
    var kidHtml = children.map(function (child) {
      var childSpec = ts(child.status);
      return '<div class="row pick" style="grid-template-columns:auto minmax(0,1fr);padding:6px 4px;min-height:36px" data-task="' + esc(child.id) + '">' +
        pill(childSpec.tone, childSpec.glyph, "") + "<span>" + esc(child.title || child.id) + "</span></div>";
    }).join("");
    return '<div class="card sticky" style="display:flex;flex-direction:column;gap:12px"><div class="lbl">Detalle</div><div style="font-weight:600">' +
      esc(task.title || task.id) + '</div><div style="display:flex;gap:8px;flex-wrap:wrap">' + pill(spec.tone, spec.glyph, spec.label) +
      '<span class="tag' + (task.recurring ? "" : " gap-hide") + '">↻ recurrente</span></div>' +
      '<div class="kv" style="grid-template-columns:88px minmax(0,1fr)">' +
      kv("Id", task.id, "mono") + kv("Proveedor", task.provider || "sin proveedor", task.provider ? "" : "note") +
      kv("Canal", task.channel || "sin canal", task.channel ? "" : "note") +
      kv("Padre", task.parent_id ? String(task.parent_id).slice(0, 8) : "raíz", task.parent_id ? "mono" : "note") +
      '<div class="k">Solicitante</div><div><span class="gap">' + GAP + "</span></div></div>" +
      (children.length ? '<div><div class="lbl" style="margin-bottom:4px">Subtareas (' + children.length + ")</div>" + kidHtml + "</div>" : "") +
      '<div><div class="lbl" style="margin-bottom:8px">Historia</div><div class="tl">' + lines + "</div></div></div>";
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
        (outs ? "" : '<span class="note">final</span>') + "</div></div>";
    }).join("");
    return '<div class="row hd" style="grid-template-columns:130px 60px minmax(0,1fr)"><div>Estado</div><div>Tareas</div><div>Puede pasar a</div></div>' + rows;
  }

  function renderExec(data) {
    var total = data.total || 0;
    var byStatus = data.by_status || {};
    var success = byStatus.success || 0;
    var failed = byStatus.failed || 0;
    var reconciled = byStatus.reconciled || 0;
    var noProv = data.no_provider || {};
    var statusHtml = ["success", "failed", "reconciled"].map(function (key) {
      var spec = ES[key];
      var n = byStatus[key] || 0;
      return '<div class="card"><div class="lbl">' + spec[2] + '</div><div style="display:flex;align-items:baseline;gap:8px;flex-wrap:wrap"><div class="big">' +
        nf(n) + "</div>" + pill(spec[0], spec[1], pc(n, total)) + "</div></div>";
    }).join("");
    var providers = (data.providers || []).map(function (row) {
      var avg = row.avg_duration_ms;
      return '<div class="row" style="grid-template-columns:100px 64px 56px minmax(0,1fr)"><div style="font-weight:500">' + esc(row.provider) +
        '</div><div class="mono">' + nf(row.n) + '</div><div class="note">' + pc(row.n, total) +
        '</div><div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap"><span class="mono">' + esc(dur(avg)) +
        '</span><span class="pill sm warn' + (avg > 86400000 ? "" : " gap-hide") + '" title="No es una duración creíble">▲ atípico</span></div></div>';
    }).join("");
    var channels = data.channels || [];
    var widest = channels.reduce(function (max, row) { return Math.max(max, row.n || 0); }, 0) || 1;
    var channelHtml = channels.map(function (row) {
      return '<div class="row" style="grid-template-columns:90px 56px minmax(0,1fr)"><div style="font-weight:500">' + esc(row.channel) +
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
      var spec = ES[row.status] || ["neu", "·", row.status || "sin resultado"];
      return '<div class="row' + (row.status === "failed" ? " err" : "") + '" style="grid-template-columns:130px 120px 90px 100px 100px minmax(0,1fr)">' +
        '<div class="note">' + esc(fmt(row.ts, true)) + "</div><div>" + pill(spec[0], spec[1], spec[2]) + "</div><div>" +
        esc(row.provider || "sin proveedor") + '</div><div class="opt ' + (row.channel ? "" : "note") + '">' + esc(row.channel || "sin canal") +
        '</div><div class="mono">' + esc(dur(row.duration_ms)) + '</div><div class="opt req" style="max-width:240px" title="Solicitante: ' + GAP + '"></div></div>';
    }).join("");
    return '<div class="tiles"><div class="card"><div class="lbl">Total</div><div class="big">' + nf(total) + '</div><div class="note">' +
      esc(fmtYear(data.first)) + " – " + esc(fmtYear(data.last)) + "</div></div>" + statusHtml + "</div>" +
      '<div class="bar" style="height:14px" role="img" aria-label="Bien ' + pc(success, total) + ", fallida " + pc(failed, total) + ", reconciliada " + pc(reconciled, total) + '">' +
      '<div class="seg-ok" style="width:' + (total ? success / total * 100 : 0) + '%"></div>' +
      '<div class="seg-err" style="width:' + (total ? failed / total * 100 : 0) + '%"></div>' +
      '<div class="seg-rec" style="width:' + (total ? reconciled / total * 100 : 0) + '%"></div></div>' +
      '<div class="tiles2"><div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">Por proveedor</div>' +
      '<div class="row hd" style="grid-template-columns:100px 64px 56px minmax(0,1fr)"><div>Proveedor</div><div>Ejec.</div><div>%</div><div>Media</div></div>' +
      providers + '<div style="padding:12px 16px 4px" class="lbl">Sin proveedor · antes de elegir proveedor</div>' +
      '<div class="row" style="grid-template-columns:150px minmax(0,1fr) 90px"><div>' + pill("err", "▲", (noProv.failed || 0) + " fallidas") +
      '</div><div class="note w100">media ' + esc(dur(noProv.failed_avg_duration_ms)) + '</div><div class="mono"></div></div>' +
      '<div class="row" style="grid-template-columns:150px minmax(0,1fr) 90px"><div>' + pill("warn", "⇄", (noProv.reconciled || 0) + " reconciliadas") +
      '</div><div class="note w100">sin duración de ejecución</div><div class="mono muted">—</div></div></div>' +
      '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">Por canal</div>' +
      '<div class="row hd" style="grid-template-columns:90px 56px minmax(0,1fr)"><div>Canal</div><div>Ejec.</div><div>Peso</div></div>' +
      channelHtml + "</div></div>" +
      '<div class="card"><div class="h3" style="margin-bottom:10px">Por día <span class="note" style="font-family:\'Inter\',sans-serif;font-weight:400">· días con actividad · escala raíz</span></div>' +
      '<div style="display:flex;align-items:flex-end;height:140px;gap:2px;border-bottom:1px solid var(--muted)">' + dayHtml + "</div>" +
      '<div class="dlabels" style="display:flex;gap:2px;margin-top:3px">' + dayLabels + "</div></div>" +
      '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">Últimas ejecuciones</div>' +
      '<div class="row hd" style="grid-template-columns:130px 120px 90px 100px 100px minmax(0,1fr)"><div>Cuándo</div><div>Resultado</div><div>Proveedor</div><div>Canal</div><div>Duración</div><div>Solicitante<div class="reqh">' +
      GAP + "</div></div></div>" + recent + "</div>";
  }

  function renderContinuity(data) {
    var channels = data.channels || [];
    if (!Array.isArray(channels)) channels = channels ? [String(channels)] : [];
    var summaries = (data.summaries || []).map(function (row) {
      var kind = String(row.file || "").indexOf("task_") === 0 ? "Tarea" : "Canal";
      var when = parseTs(row.date);
      var ago = when ? ageText((Date.now() - when.getTime()) / 1000) : "sin dato";
      return '<div class="row" style="grid-template-columns:80px minmax(0,1fr) 90px 100px"><div>' + pill("neu", "", kind) +
        '</div><div class="w100"><div class="mono" style="word-break:break-all;font-size:11.5px">' + esc(row.file) +
        '</div><div class="note">' + esc(row.first_line || "") + '</div></div><div>' + esc(fmtDay(row.date)) +
        '</div><div class="note">' + esc(ago) + "</div></div>";
    }).join("");
    var next = data.next_owner ? esc(data.next_owner) : '<span class="gap">sin asignar</span>';
    return '<div class="card" style="display:flex;flex-direction:column;gap:8px"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap"><div class="lbl">Intención activa</div>' +
      pill("neu", "◷", ageLabel(data.at)) +
      '</div><div style="font-size:15px">' + esc(plain(data.active)) + "</div></div>" +
      '<div class="tiles"><div class="card"><div class="lbl">Pendientes</div><div class="big">' + esc(showCount(data.pending)) + "</div></div>" +
      '<div class="card"><div class="lbl">Decisiones</div><div class="big">' + esc(showCount(data.decisions)) + "</div></div>" +
      '<div class="card"><div class="lbl">Siguiente responsable</div><div style="margin-top:8px">' + next + "</div></div>" +
      '<div class="card"><div class="lbl">Actualizada</div><div class="big">' + esc(ageLabel(data.at)) +
      '</div><div class="note">' + esc(data.at ? fmt(data.at) : "sin dato") + "</div></div></div>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center"><span class="lbl">Canales vistos</span>' +
      channels.map(function (name) { return '<span class="tag" style="color:var(--text)">' + esc(name) + "</span>"; }).join("") + "</div>" +
      '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">Resúmenes por canal</div>' +
      '<div class="row hd" style="grid-template-columns:80px minmax(0,1fr) 90px 100px"><div>Origen</div><div>Fichero</div><div>Fecha</div><div>Hace</div></div>' +
      summaries + "</div>";
  }

  function modePill(mode) {
    if (mode === "active") return pill("ok", "●", "Activo");
    if (mode === "shadow") return pill("neu", "◐", "Shadow");
    if (mode === "paused") return pill("warn", "◔", "En pausa");
    if (mode === "revoked") return pill("err", "⊘", "Revocado");
    return pill("info", "?", mode || "sin modo");
  }

  function renderMandates(data) {
    var events = data.events || {};
    var rows = (data.defined || []).map(function (item) {
      var event = events[item.name];
      var when = event ? "" : " note";
      return '<div class="row" style="grid-template-columns:190px 110px 210px 90px 90px minmax(0,1fr)"><div class="w100" style="font-weight:500">' +
        esc(item.name) + "</div><div>" + modePill(item.mode) + '</div><div><div><span class="mono">' +
        nf(event ? event.events : 0) + '</span> <span class="note">eventos</span></div><div class="note' + (event && event.shadow ? "" : " gap-hide") + '">' +
        (event ? event.shadow + " en sombra" : "") + "</div></div>" +
        '<div class="opt' + when + '">' + esc(event && event.first ? fmtDay(event.first) : "sin uso") + "</div>" +
        '<div class="' + when.trim() + '">' + esc(event && event.last ? fmtDay(event.last) : "sin uso") + "</div>" +
        '<div class="' + when.trim() + '">' + esc(event && event.last && parseTs(event.last) ? ageText((Date.now() - parseTs(event.last).getTime()) / 1000) : "—") + "</div></div>";
    }).join("");
    var gate = data.gate || { total: 0, allowed: 0, last: [] };
    var denied = (gate.total || 0) - (gate.allowed || 0);
    var last = (gate.last || []).map(function (row) {
      var tone = row.allowed ? "ok" : (row.code === "approval_required" ? "warn" : "err");
      var glyph = row.allowed ? "✓" : (row.code === "approval_required" ? "◔" : "✕");
      var label = row.allowed ? "Permitida" : (row.code === "approval_required" ? "Pide aprobación" : "Denegada");
      return '<div class="row' + (!row.allowed && row.code !== "approval_required" ? " err" : "") + '" style="grid-template-columns:130px 180px 120px 170px minmax(0,1fr)">' +
        '<div class="note">' + esc(fmt(row.ts, true)) + '</div><div class="mono">' + esc(row.tool) + "</div><div>" + pill(tone, glyph, label) +
        '</div><div class="opt" title="' + esc(row.code) + '">' + esc(row.code || "") + '</div><div class="opt req" style="max-width:240px" title="Solicitante: ' + GAP + '"></div></div>';
    }).join("");
    return '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">Mandatos A3</div>' +
      '<div class="row hd" style="grid-template-columns:190px 110px 210px 90px 90px minmax(0,1fr)"><div>Mandato</div><div>Modo</div><div>Eventos</div><div>Primer uso</div><div>Último uso</div><div>Hace</div></div>' +
      rows + "</div>" +
      '<div class="card"><div class="h3" style="margin-bottom:10px">Gate MCP</div><div style="display:flex;gap:28px;align-items:baseline;margin-bottom:10px;flex-wrap:wrap">' +
      '<div><div class="big">' + nf(gate.total) + '</div><div class="note">decisiones</div></div>' +
      '<div><div class="big" style="color:var(--ok)">' + nf(gate.allowed) + '</div><div class="note">permitidas</div></div>' +
      '<div><div class="big" style="color:var(--warn)">' + nf(denied) + '</div><div class="note">no permitidas</div></div></div>' +
      '<div class="bar" style="height:14px" role="img" aria-label="' + gate.allowed + " permitidas y " + denied + " no permitidas de " + gate.total + '">' +
      '<div class="seg-ok" style="width:' + (gate.total ? gate.allowed / gate.total * 100 : 0) + '%"></div>' +
      '<div class="seg-rec" style="width:' + (gate.total ? denied / gate.total * 100 : 0) + '%"></div></div>' +
      '<div class="note" style="margin-top:8px">Sin permitir = pide aprobación o se deniega; los datos no las separan.</div></div>' +
      '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">Últimas decisiones</div>' +
      '<div class="row hd" style="grid-template-columns:130px 180px 120px 170px minmax(0,1fr)"><div>Cuándo</div><div>Herramienta</div><div>Decisión</div><div>Motivo</div><div>Solicitante<div class="reqh">' +
      GAP + "</div></div></div>" + last + "</div>";
  }

  function renderIdes(rows) {
    rows = rows || [];
    var broken = rows.reduce(function (sum, row) { return sum + ((row.broken || []).length); }, 0);
    var names = { ".claude/skills": "Claude", ".gemini/skills": "Gemini", ".cursor/skills": "Cursor", ".agents/skills": "Codex + Antigravity" };
    var body = rows.map(function (row) {
      var shared = row.kind === "copy" && (row.shared_with || []).length;
      var how = shared ? "Copia compartida" : (row.kind === "copy" ? "Copia" : "Enlace");
      var tone = row.kind === "copy" ? "neu" : "info";
      var glyph = row.kind === "copy" ? "▭" : "↪";
      var brokenText = (row.broken || []).length ? row.broken.join(", ") : "0";
      return '<div class="row' + ((row.broken || []).length ? " err" : "") + '" style="grid-template-columns:160px 160px 150px 70px minmax(0,1fr)">' +
        '<div style="font-weight:600">' + esc(names[row.destination] || row.destination) + "</div><div>" + pill(tone, glyph, how) +
        '</div><div class="mono opt">' + esc(row.destination) + '</div><div class="mono">' + esc(row.skills) +
        '</div><div class="' + ((row.broken || []).length ? "" : "muted") + '">' + esc(brokenText) + "</div></div>";
    }).join("");
    var counts = rows.map(function (row) { return row.skills; });
    var skillCount = counts.length && counts.every(function (n) { return n === counts[0]; }) ? counts[0] : "—";
    return '<div class="tiles"><div class="card"><div class="lbl">IDEs</div><div class="big">' + rows.length + "</div></div>" +
      '<div class="card"><div class="lbl">Skills por IDE</div><div class="big">' + esc(skillCount) + "</div></div>" +
      '<div class="card"><div class="lbl">Enlaces rotos</div><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><div class="big">' +
      broken + "</div>" + pill(broken ? "err" : "ok", broken ? "▲" : "✓", broken ? "Reparar" : "Ninguno") + "</div></div></div>" +
      '<div class="card" style="padding:0;overflow:hidden"><div class="row hd" style="grid-template-columns:160px 160px 150px 70px minmax(0,1fr)"><div>IDE</div><div>Recibe</div><div>Ruta</div><div>Skills</div><div>Rotos</div></div>' +
      body + "</div>";
  }

  function renderIngress(data, health) {
    var stamp = data.stamp || {};
    var gateway = health && health.data && health.data.verdict ? health.data.verdict.gateway : null;
    var tunnel = health && health.refused
      ? pill("err", "▲", "Se negó") + '<div class="note">' + esc(health.refused) + "</div>"
      : (!gateway || gateway.state === "unverified"
        ? pill("info", "?", "Sin dato")
        : (gateway.state === "healthy" ? pill("ok", "✓", "Conector listo") : pill("err", "▲", gateway.connector_ready ? "Con problemas" : "Conector no listo")));
    var claim = data.claim_telegram ? pill("ok", "✓", "Sí") : pill("err", "✕", "No");
    var keys = stamp && stamp.keys_present;
    var keyText = Array.isArray(keys) ? keys.join(",") : String(keys || "");
    var n8n = keyText.indexOf("SOLAR_N8N_WEBHOOK_SECRET") >= 0 ? pill("ok", "✓", "Configurado") : pill("neu", "○", "No consta");
    var httpAddr = stamp.http_host && stamp.http_port ? stamp.http_host + ":" + stamp.http_port : "sin dato";
    return '<div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">Canales HTTP</div>' +
      '<div class="row hd" style="grid-template-columns:180px 200px minmax(0,1fr)"><div>Canal</div><div>Dirección</div><div>Alcance</div></div>' +
      '<div class="row" style="grid-template-columns:180px 200px minmax(0,1fr)"><div style="font-weight:500">Consola</div><div class="mono">' + esc(location.host || "127.0.0.1:9000") + "</div><div>" + pill("ok", "✓", "Solo local") + "</div></div>" +
      '<div class="row" style="grid-template-columns:180px 200px minmax(0,1fr)"><div style="font-weight:500">HTTP del gateway</div><div class="mono">' + esc(httpAddr) + "</div><div>" + pill("ok", "✓", "Local; fuera vía túnel") + "</div></div>" +
      '<div class="row" style="grid-template-columns:180px 200px minmax(0,1fr)"><div style="font-weight:500">WebSocket</div><div class="mono">' + esc(stamp.ws_port ? "puerto " + stamp.ws_port : "sin dato") + "</div><div>" + pill("info", "?", "Puerto del sello") + "</div></div></div>" +
      '<div class="tiles2"><div class="card" style="display:flex;flex-direction:column;gap:10px"><div class="h3">Webhook de Telegram</div><div class="kv" style="grid-template-columns:170px minmax(0,1fr)">' +
      '<div class="k">Configurado para reclamar</div><div>' + claim + '</div><div class="k">Estado real</div><div>' + pill("info", "?", "No verificado") +
      '</div><div class="k">Secreto n8n</div><div>' + n8n + "</div></div></div>" +
      '<div class="card" style="display:flex;flex-direction:column;gap:10px"><div class="h3">Túnel</div><div class="kv" style="grid-template-columns:120px minmax(0,1fr)">' +
      kv("Modo", stamp.tunnel_mode === "named" ? "Con nombre" : (stamp.tunnel_mode || "sin dato"), "") +
      kv("Nombre", stamp.tunnel_name || "sin dato", "mono") +
      kv("Hostname", data.hostname || "sin dato", "mono") +
      '<div class="k">Estado</div><div>' + tunnel + "</div></div></div></div>";
  }

  function renderRequester(data) {
    var rows = [
      ["tasks", "Tareas", "tareas"],
      ["executions", "Ejecuciones", "ejecuciones"],
      ["approvals", "Decisiones del gate MCP", "autonomia"]
    ].map(function (row) {
      var item = (data && data[row[0]]) || {};
      return '<div class="row" style="grid-template-columns:220px 110px minmax(0,1fr)"><div style="font-weight:500">' + esc(row[1]) +
        '</div><div class="mono">—</div><div><button type="button" class="chip" data-screen="' + row[2] + '">' + esc(row[1]) +
        ' →</button><div class="note">' + (item.recorded ? esc(item.label) : GAP) + "</div></div></div>";
    }).join("");
    return '<div class="card" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap"><span class="gap">' + GAP +
      "</span></div>" +
      '<div class="card" style="padding:0;overflow:hidden"><div class="row hd" style="grid-template-columns:220px 110px minmax(0,1fr)"><div>Dónde aparece</div><div>Registros</div><div>Ir</div></div>' +
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
