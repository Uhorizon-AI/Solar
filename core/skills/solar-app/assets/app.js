/* Read-only console. Screens read /api/console/* and do not recompute the verdict. */
(function () {
  "use strict";

  // The port of the host that served this page; 80/443 when location.host names none (proxies).
  // (Console port rule: 9000, movable only by tests, see core/docs/console-identity.md.)
  function consolePort() {
    var host = (typeof location !== "undefined" && location.host) || "";
    var match = host.match(/:(\d+)$/);
    if (match) return match[1];
    return typeof location !== "undefined" && location.protocol === "https:" ? "443" : "80";
  }

  var TZ = "Europe/Madrid";
  var LANG = "en";
  var COPY = {
    en: {
      usage_title: "Token consumption",
      usage_scope: "CLI-reported tokens from Solar async questions only. Other client activity is not observed.",
      usage_empty: "No token data recorded for this task.",
      usage_native: "Categories follow each CLI. Cache or reasoning may be included in other counts; no combined total or subscription price is inferred.",
      usage_attempt: "Attempt",
      usage_execution: "Execution",
      usage_provider: "Provider",
      usage_model: "Observed model",
      usage_input_tokens: "Input",
      usage_output_tokens: "Output",
      usage_cache_read_tokens: "Cache read",
      usage_cache_write_tokens: "Cache write",
      usage_reasoning_tokens: "Reasoning",
      usage_available: "Available",
      usage_partial: "Partial",
      usage_not_available: "Not available",
      usage_coverage: "Attempts with data / confirmed launches",
      usage_evidence: "Original measurement evidence",
      usage_subtotal: "Known subtotal by provider, observed model and CLI version",
      usage_pending: "Incomplete or interrupted capture",
      usage_reason_failed: "Execution failed",
      usage_reason_timeout: "Execution timed out",
      usage_reason_ambiguous_terminals: "Conflicting terminal events",
      usage_reason_no_validated_counters: "No validated counters reported",
      usage_reason_terminal_missing: "Terminal event not received",
      usage_reason_unfinished: "Final measurement status was not saved",
      usage_reason_not_launched: "CLI was not launched",
      usage_reason_owner_lost: "Previous execution owner was lost",
      usage_reason_observation_rejected: "Measurement exceeded validation limits",
      usage_reason_event_too_large: "An intermediate event exceeded capture limits",
      usage_reason_persistence_failed: "Measurement could not be saved",
      usage_reason_malformed_event: "An invalid measurement event was received",
      usage_reason_unknown_event_shape: "An unrecognized measurement event was received",
      usage_reason_cli_timeout: "CLI execution timed out",
      page_title: "Solar local console",
      gap: "available once Solar knows who is speaking",
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
      tc_this_task_s_stored_continuity_checkpoint: "This task's stored continuity checkpoint is not valid.",
      tc_this_task_s_stored_record_could_not_be_r: "This task's stored record could not be read.",
      tc_this_task_s_context_could_not_be_read: "This task's context could not be read.",
      tc_context_and_follow_up: "Context and follow-up",
      tc_workspace: "Workspace",
      tc_agent: "Agent",
      tc_planet: "Planet",
      tc_responsibility: "Responsibility",
      tc_contract: "Contract",
      tc_recorded_result: "Recorded result",
      tc_recorded_verification: "Recorded verification",
      tc_next_check: "Next check",
      tc_check_date: "Check date",
      tc_check_source: "Check source",
      tc_waiting: "Waiting",
      tc_decision_owner: "Decision owner",
      tc_subject: "Subject",
      tc_decision_source: "Decision source",
      tc_valid_from: "Valid from",
      tc_valid_until: "Valid until",
      tc_decision: "Decision",
      tc_pending: "Pending",
      tc_recorded_status_check_source: "Recorded status; check source",
      tc_effect_state: "Effect state",
      tc_uncertain_verify_before_retrying: "Uncertain; verify before retrying",
      tc_recorded_state_not_verified_on_opening: "Recorded state; not verified on opening",
      tc_recurrence: "Recurrence",
      tc_recurring: "Recurring",
      tc_minimum_interval: "Minimum interval",
      tc_configured_time: "Configured time",
      tc_time_zone: "Time zone",
      tc_host_timezone_no_stored_zone: "Host timezone (no stored zone)",
      tc_weekdays: "Days",
      tc_day_1: "Mon", tc_day_2: "Tue", tc_day_3: "Wed", tc_day_4: "Thu", tc_day_5: "Fri", tc_day_6: "Sat", tc_day_7: "Sun",
      tc_unlimited: "Unlimited",
      tc_no_recorded_checkpoint: "No recorded checkpoint. Execution state and history remain available.",
      tc_frontmatter: "Frontmatter",
      tc_maximum_runs: "Maximum runs",
      tc_reserved_resources: "Reserved resources",
      tc_context_shape_note: "There is context data in a shape this view does not show; open it in Complete record.",
      tc_no_recorded_context_execution_state_and: "No recorded context. Execution state and history remain available.",
      tc_reading_this_record_does_not_verify_an_e: "Reading this record does not verify an effect or authorize retrying it.",
      tc_complete_record: "Complete record",
      tc_the_complete_record_could_not_be_read: "The complete record could not be read.",
      tc_record_unavailable: "Record unavailable.",
      tc_instructions: "Instructions",
      no_reply: "no reply",
      no_data: "no data",
      less_than_min: "less than 1 min",
      route_refused: "The route refused",
      no_reason: "no reason",
      nav_summary: "Summary",
      nav_tasks: "Tasks",
      nav_runs: "Runs",
      nav_autonomy: "Autonomy",
      nav_ides: "Apps",
      nav_entry: "Channels",
      nav_dashboards: "Dashboards",
      q_dashboards: "Where can I work with each planet?",
      channels_note: "Entry diagnostics only. Conversation history is not available here.",
      nav_requester: "Requester",
      q_summary: "Is the installation healthy, and how long has it been idle?",
      q_tasks: "Which tasks exist and what happened to them?",
      q_runs: "What has Solar run and how did it go?",
      q_autonomy: "What does Solar do without asking?",
      q_ides: "What does each app see?",
      q_entry: "Which channels receive requests and how are they working?",
      q_requester: "Who asked for this?",
      st_draft: "Draft", st_planned: "Planned", st_queued: "Queued", st_active: "Active",
      st_completed: "Completed", st_error: "Error", st_archived: "Archived", st_cancelled: "Cancelled", st_none: "No status",
      ex_ok: "Ok", ex_failed: "Failed", ex_reconciled: "Reconciled", ex_none: "No result",
      cap_title: "Capacity and waiting", cap_used: "places in use", cap_of: "of", cap_simul: "Running at once",
      cap_free: "free", cap_waiting: "Waiting", cap_none_waiting: "Nothing is waiting.", cap_none_running: "Nothing is running.",
      wait_dependency: "Dependency", wait_resource: "Resource", wait_provider: "Provider limit", wait_capacity: "Capacity",
      wait_authorization: "Authorization pending", wait_recovery: "Recovery", wait_other: "Other",
      cfg_title: "Applied configuration", cfg_revision: "Revision", cfg_global: "Global capacity", cfg_provider: "Provider limits",
      cfg_exclusive: "Exclusive wait (s)", cfg_none_provider: "none", cfg_no_pending: "The proposal file has no pending differences.",
      cfg_pending: "Pending differences (not applied until confirmed):", cfg_applied: "applied", cfg_proposed: "proposed",
      cfg_proposal_error: "The proposal file is invalid; the applied revision stays.",
      sup_title: "Supervisor", sup_none: "No supervisor has published its identity.", sup_stale: "heartbeat stopped",
      sup_blocked: "Blocked executions (need attention)",
      v_calm: "CALM", v_fault: "FAULT", v_unverified: "UNVERIFIED",
      r_database: "The state database cannot be read.",
      r_port: "Another process is using the console port.",
      r_launchagent: "The LaunchAgent has no recent pass.",
      r_system: "A system feature has failed.",
      r_router: "The router is unknown because the state refuses.",
      r_gateway: "The gateway is not healthy.",
      c_database: "Database", c_port: "Port " + consolePort(), c_system: "System", c_router: "Router",
      c_launchagent: "LaunchAgent", c_gateway: "Gateway",
      no_channel: "no channel", other_channel: "Other",
      mode_global: "Global", mode_portable: "Portable copy",
      tunnel_named: "Named", tunnel_quick: "Quick",
      feat_tasks: "Background tasks", feat_gateway: "Gateway", feat_ok: "ok", feat_failed: "failed", feat_starting: "starting", feat_blocked: "needs attention",
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
      f_errors: "Errors", f_running: "Running", f_drafts: "Drafts", f_queue: "Queue", f_done: "Done", f_closed: "Closed",
      f_toolbar: "Filter tasks by status", f_task: "task", f_tasks: "tasks", f_recurring: "↻ Recurring",
      f_no_error: "No tasks in error", f_no_error_hint: "Nothing needs retrying.",
      f_no_error_rec: "No recurring tasks in error", f_no_error_rec_hint: "Nothing recurring needs retrying.", f_next: "Next pending: ",
      all_tasks: "All", subtasks: "subtasks", versions: "versions", earlier_versions: "Earlier versions",
      revises: "Revises", approval: "Approval", not_approved: "Approval needed",
      mm_absent: "no approval is recorded for it", mm_legacy: "it was approved under an older rule",
      mm_mismatch: "it changed after it was approved",
      mm_text: "The worker will not start this task: ", mm_fix: ". Approve it again to queue it.",
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
      ides: "Apps", app_col: "App", skills_per: "Skills per app", broken_links: "Broken links", repair: "Repair", none_broken: "None",
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
      usage_title: "Consumo de tokens",
      usage_scope: "Tokens informados por los CLI de preguntas async de Solar. La actividad fuera de Solar no se observa.",
      usage_empty: "No hay datos de tokens registrados para esta tarea.",
      usage_native: "Las categorías siguen a cada CLI. Caché o razonamiento pueden estar incluidos en otros contadores; no se deduce un total combinado ni precio de suscripción.",
      usage_attempt: "Intento",
      usage_execution: "Ejecución",
      usage_provider: "Proveedor",
      usage_model: "Modelo observado",
      usage_input_tokens: "Entrada",
      usage_output_tokens: "Salida",
      usage_cache_read_tokens: "Lectura de caché",
      usage_cache_write_tokens: "Escritura de caché",
      usage_reasoning_tokens: "Razonamiento",
      usage_available: "Disponible",
      usage_partial: "Parcial",
      usage_not_available: "No disponible",
      usage_coverage: "Intentos con datos / lanzamientos confirmados",
      usage_evidence: "Evidencia original de medición",
      usage_subtotal: "Subtotal conocido por proveedor, modelo observado y versión CLI",
      usage_pending: "Captura incompleta o interrumpida",
      usage_reason_failed: "La ejecución falló",
      usage_reason_timeout: "La ejecución agotó el tiempo",
      usage_reason_ambiguous_terminals: "Eventos finales contradictorios",
      usage_reason_no_validated_counters: "Sin contadores validados",
      usage_reason_terminal_missing: "No se recibió el evento final",
      usage_reason_unfinished: "No se guardó el cierre de la medición",
      usage_reason_not_launched: "No se inició el CLI",
      usage_reason_owner_lost: "Se perdió el responsable de la ejecución anterior",
      usage_reason_observation_rejected: "La medición superó los límites de validación",
      usage_reason_event_too_large: "Un evento intermedio superó los límites de captura",
      usage_reason_persistence_failed: "No se pudo guardar la medición",
      usage_reason_malformed_event: "Se recibió un evento de medición inválido",
      usage_reason_unknown_event_shape: "Se recibió un evento de medición no reconocido",
      usage_reason_cli_timeout: "El CLI agotó el tiempo de ejecución",
      page_title: "Consola local de Solar",
      gap: "disponible cuando Solar sepa quién le habla",
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
      tc_this_task_s_stored_continuity_checkpoint: "El punto de continuidad guardado de esta tarea no es válido.",
      tc_this_task_s_stored_record_could_not_be_r: "No se pudo leer el registro guardado de esta tarea.",
      tc_this_task_s_context_could_not_be_read: "No se pudo leer el contexto de esta tarea.",
      tc_context_and_follow_up: "Contexto y seguimiento",
      tc_workspace: "Espacio de trabajo",
      tc_agent: "Agente",
      tc_planet: "Planeta",
      tc_responsibility: "Responsabilidad",
      tc_contract: "Contrato",
      tc_recorded_result: "Resultado registrado",
      tc_recorded_verification: "Verificación registrada",
      tc_next_check: "Próxima comprobación",
      tc_check_date: "Fecha de comprobación",
      tc_check_source: "Fuente de comprobación",
      tc_waiting: "Espera",
      tc_decision_owner: "Decide",
      tc_subject: "Asunto",
      tc_decision_source: "Fuente de la decisión",
      tc_valid_from: "Válida desde",
      tc_valid_until: "Válida hasta",
      tc_decision: "Decisión",
      tc_pending: "Pendiente",
      tc_recorded_status_check_source: "Estado guardado; revisar fuente",
      tc_effect_state: "Situación del efecto",
      tc_uncertain_verify_before_retrying: "Incierto; verificar antes de repetir",
      tc_recorded_state_not_verified_on_opening: "Estado registrado; no verificado al abrir",
      tc_recurrence: "Recurrencia",
      tc_recurring: "Recurrente",
      tc_minimum_interval: "Intervalo mínimo",
      tc_configured_time: "Hora configurada",
      tc_time_zone: "Zona horaria",
      tc_host_timezone_no_stored_zone: "Zona del equipo (sin zona guardada)",
      tc_weekdays: "Días",
      tc_day_1: "lun", tc_day_2: "mar", tc_day_3: "mié", tc_day_4: "jue", tc_day_5: "vie", tc_day_6: "sáb", tc_day_7: "dom",
      tc_unlimited: "Sin límite",
      tc_no_recorded_checkpoint: "Sin checkpoint registrado. El estado de ejecución y su historial se conservan.",
      tc_frontmatter: "Frontmatter",
      tc_maximum_runs: "Máximo de ejecuciones",
      tc_reserved_resources: "Recursos reservados",
      tc_context_shape_note: "Hay datos de contexto con una forma que esta vista no muestra; ábrelos en Registro completo.",
      tc_no_recorded_context_execution_state_and: "Sin contexto registrado. El estado de ejecución y su historial se conservan.",
      tc_reading_this_record_does_not_verify_an_e: "Leer este registro no verifica el efecto ni autoriza repetirlo.",
      tc_complete_record: "Registro completo",
      tc_the_complete_record_could_not_be_read: "No se pudo leer el registro completo.",
      tc_record_unavailable: "Registro no disponible.",
      tc_instructions: "Instrucciones",
      no_reply: "sin respuesta",
      no_data: "sin dato",
      less_than_min: "menos de 1 min",
      route_refused: "La ruta se negó",
      no_reason: "sin motivo",
      nav_summary: "Resumen",
      nav_tasks: "Tareas",
      nav_runs: "Ejecuciones",
      nav_autonomy: "Autonomía",
      nav_ides: "Apps",
      nav_entry: "Canales",
      nav_dashboards: "Dashboards",
      q_dashboards: "¿Dónde puedo trabajar con cada planeta?",
      channels_note: "Diagnósticos de entrada. Esta pantalla no muestra historial de conversaciones.",
      nav_requester: "Solicitante",
      q_summary: "¿Está sana mi instalación, y desde cuándo no hace nada?",
      q_tasks: "¿Qué tareas hay y qué les ha pasado?",
      q_runs: "¿Qué ha ejecutado Solar y cómo le ha ido?",
      q_autonomy: "¿Qué hace Solar sin preguntarme?",
      q_ides: "¿Qué ve cada app?",
      q_entry: "¿Qué canales reciben encargos y cómo funcionan?",
      q_requester: "¿Quién pidió esto?",
      st_draft: "Borrador", st_planned: "Planificada", st_queued: "En cola", st_active: "Activa",
      st_completed: "Completada", st_error: "Error", st_archived: "Archivada", st_cancelled: "Cancelada", st_none: "Sin estado",
      ex_ok: "Bien", ex_failed: "Fallida", ex_reconciled: "Reconciliada", ex_none: "Sin resultado",
      cap_title: "Capacidad y esperas", cap_used: "plazas en uso", cap_of: "de", cap_simul: "En marcha a la vez",
      cap_free: "libres", cap_waiting: "En espera", cap_none_waiting: "Nada está esperando.", cap_none_running: "No hay nada en marcha.",
      wait_dependency: "Dependencia", wait_resource: "Recurso", wait_provider: "Límite de proveedor", wait_capacity: "Capacidad",
      wait_authorization: "Autorización pendiente", wait_recovery: "Recuperación", wait_other: "Otro",
      cfg_title: "Configuración aplicada", cfg_revision: "Revisión", cfg_global: "Capacidad global", cfg_provider: "Límites por proveedor",
      cfg_exclusive: "Espera exclusiva (s)", cfg_none_provider: "ninguno", cfg_no_pending: "El archivo de propuesta no tiene diferencias pendientes.",
      cfg_pending: "Diferencias pendientes (no se aplican hasta confirmarlas):", cfg_applied: "aplicado", cfg_proposed: "propuesto",
      cfg_proposal_error: "El archivo de propuesta no es válido; se mantiene la revisión aplicada.",
      sup_title: "Supervisor", sup_none: "Ningún supervisor ha publicado su identidad.", sup_stale: "latido detenido",
      sup_blocked: "Ejecuciones bloqueadas (necesitan atención)",
      v_calm: "CALMA", v_fault: "AVERÍA", v_unverified: "SIN VERIFICAR",
      r_database: "La base de estado es ilegible.",
      r_port: "El puerto de la consola está ocupado por otro proceso.",
      r_launchagent: "El LaunchAgent no tiene una pasada reciente.",
      r_system: "Una función del sistema ha fallado.",
      r_router: "El router es desconocido porque el estado se niega.",
      r_gateway: "El gateway no está sano.",
      c_database: "Base", c_port: "Puerto " + consolePort(), c_system: "Sistema", c_router: "Router",
      c_launchagent: "LaunchAgent", c_gateway: "Gateway",
      no_channel: "sin canal", other_channel: "Otro",
      mode_global: "Global", mode_portable: "Copia portable",
      tunnel_named: "Con nombre", tunnel_quick: "Rápido",
      feat_tasks: "Tareas en segundo plano", feat_gateway: "Gateway", feat_ok: "bien", feat_failed: "fallo", feat_starting: "arrancando", feat_blocked: "necesita atención",
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
      f_errors: "Errores", f_running: "En ejecución", f_drafts: "Borradores", f_queue: "En cola", f_done: "Completadas", f_closed: "Cerradas",
      f_toolbar: "Filtrar tareas por estado", f_task: "tarea", f_tasks: "tareas", f_recurring: "↻ Recurrentes",
      f_no_error: "No hay tareas con error", f_no_error_hint: "Nada que reintentar.",
      f_no_error_rec: "No hay tareas recurrentes con error", f_no_error_rec_hint: "Nada recurrente que reintentar.", f_next: "Siguiente pendiente: ",
      all_tasks: "Todas", subtasks: "subtareas", versions: "versiones", earlier_versions: "Versiones anteriores",
      revises: "Revisa", approval: "Aprobación", not_approved: "Falta aprobación",
      mm_absent: "no tiene aprobación registrada", mm_legacy: "se aprobó con una regla anterior",
      mm_mismatch: "cambió después de aprobarse",
      mm_text: "El worker no arrancará esta tarea: ", mm_fix: ". Apruébala de nuevo para ponerla en cola.",
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
      ides: "Apps", app_col: "App", skills_per: "Skills por app", broken_links: "Enlaces rotos", repair: "Reparar", none_broken: "Ninguno",
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
  // Status filter groups over the eight stored statuses, in display order.
  // Errors never hides; every other group hides at 0 unless selected. Done is only
  // `completed`; Closed is `cancelled` and `archived`.
  var GROUPS = [
    { key: "errors", label: "f_errors", statuses: ["error"], fill: true, glyph: "▲" },
    { key: "running", label: "f_running", statuses: ["active"], fill: true, glyph: "▶" },
    { key: "drafts", label: "f_drafts", statuses: ["draft"], fill: true, glyph: "◌" },
    { key: "queue", label: "f_queue", statuses: ["planned", "queued"] },
    { key: "done", label: "f_done", statuses: ["completed"] },
    { key: "closed", label: "f_closed", statuses: ["cancelled", "archived"] }
  ];
  var FILTER_KEYS = GROUPS.map(function (group) { return group.key; }).concat(["all"]);
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
      ["dashboards", t("nav_dashboards"), t("q_dashboards"), "/api/console/dashboards"],
      ["ejecuciones", t("nav_runs"), t("q_runs"), "/api/console/executions"],
      ["autonomia", t("nav_autonomy"), t("q_autonomy"), "/api/console/mandates"],
      ["ides", t("nav_ides"), t("q_ides"), "/api/console/ides"],
      ["entrada", t("nav_entry"), t("q_entry"), "/api/console/ingress"],
      ["solicitante", t("nav_requester"), t("q_requester"), "/api/console/requester"]
    ];
  }
  function statusRow(status) {
    // Red only for error, blue only for active; the rest are neutral and say their state in text too.
    var labels = {
      draft: ["draft", "◌", "st_draft"], planned: ["plain", "◷", "st_planned"], queued: ["plain", "≡", "st_queued"],
      active: ["run", "▶", "st_active"], completed: ["plain", "✓", "st_completed"], error: ["err", "▲", "st_error"],
      archived: ["dim", "▭", "st_archived"], cancelled: ["dim", "⊘", "st_cancelled"]
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
    filter: null,
    filterAuto: true,
    recurring: false,
    focusKey: null,
    refocus: null,
    announce: null,
    task: null,
    machine: false
  };
  var cache = {};
  var taskContexts = {};
  var taskFull = {};
  var contextEpoch = 0;
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
    $("host").textContent = location.host || ("127.0.0.1:" + consolePort());
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

  function readFilterHash() {
    var match = /^#tasks\/([a-z]+)(\+recurring)?$/.exec(String((typeof location !== "undefined" && location.hash) || ""));
    return match && FILTER_KEYS.indexOf(match[1]) >= 0 ? { filter: match[1], recurring: !!match[2] } : null;
  }
  function writeFilterHash() {
    var url = "#tasks/" + ui.filter + (ui.recurring ? "+recurring" : "");
    try {
      if (typeof history !== "undefined" && history.replaceState) history.replaceState(null, "", url);
      else location.hash = url;
    } catch (error) { /* the filter still works without a hash */ }
  }
  function clearFilterHash() {
    try {
      if (typeof location === "undefined" || !/^#tasks\//.test(String(location.hash || ""))) return;
      if (typeof history !== "undefined" && history.replaceState) history.replaceState(null, "", String(location.pathname || "") + String(location.search || ""));
      else location.hash = "";
    } catch (error) { /* a stale hash only affects a reload */ }
  }
  // The chip (or the Recurring checkbox) that holds focus, read before a repaint replaces
  // the toolbar; otherwise the one-shot intent set by a click or an arrow key.
  function focusedTarget() {
    var active = (typeof document !== "undefined" && document.activeElement) || null;
    if (!active || !active.getAttribute) return null;
    if (active.getAttribute("data-recurring") != null) return { kind: "recurring" };
    if (active.getAttribute("data-chip") != null) return { kind: "filter", key: active.getAttribute("data-filter") };
    return null;
  }
  function restoreFocus(box, target) {
    // A repaint (a delayed detail load, a refresh) rebuilds the toolbar and drops focus, so
    // the control that had it is captured before the swap and restored after. An explicit
    // intent left by a click or an arrow key wins over the captured element, so arrow keys
    // still move the tab stop right after a repaint.
    var want = (ui.refocus === "recurring" ? { kind: "recurring" } : (ui.refocus === "filter" ? { kind: "filter", key: ui.focusKey } : null)) || target;
    ui.refocus = null;
    if (!want || !box || !box.querySelector) return;
    var el = box.querySelector(want.kind === "recurring" ? "[data-recurring]" : '[data-filter="' + String(want.key || "") + '"][data-chip]');
    if (el && el.focus) el.focus();
  }
  // A live region outside the repainted block, so a filter change still announces the count.
  // When the group is empty the count says nothing useful, so the empty-state title is what
  // gets announced; #live is then the only status region, not a second voice beside the panel.
  function announce(text, emptyText) {
    var node = $("live");
    if (!node) return;
    // An empty group prefers its own title; "Showing 0 of 0" would say nothing useful.
    var message = emptyText || text || "";
    if (message) node.textContent = message;
  }

  function openScreen(id, seed) {
    if (id === "tareas") {
      taskContexts = {}; taskFull = {}; contextEpoch += 1;
      // The filter is decided at every opening; only the URL hash can carry it over a reload,
      // so it seeds the first opening of a page load and is cleared on any other opening.
      var saved = seed || null;
      if (!saved) clearFilterHash();
      ui.filterAuto = !saved;
      ui.filter = saved ? saved.filter : null;
      ui.recurring = saved ? saved.recurring : false;
      ui.focusKey = null;
    }
    else clearFilterHash();
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
    if (id === "ejecuciones") jobs.push(load("/api/console/capacity"));
    Promise.all(jobs).then(function (parts) {
      var payload = parts[0];
      if (id === "ejecuciones") cache.capacity = parts[1] || { refused: t("no_reply") };
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
    else if (id === "tareas") {
      var keep = focusedTarget();
      box.innerHTML = renderTasks(data);
      restoreFocus(box, keep);
      announce(ui.announce, ui.empty);
    }
    else if (id === "ejecuciones") box.innerHTML = renderCapacity(cache.capacity) + renderExec(data);
    else if (id === "dashboards") box.innerHTML = renderDashboards(data);
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
    var states = { ok: t("feat_ok"), failed: t("feat_failed"), starting: t("feat_starting"), blocked: t("feat_blocked") };
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
    var cards = [
      [t("c_database"), data.database ? ["err", "▲", t("pill_refused")] : ["ok", "✓", t("pill_readable")], data.database ? data.database.refused : t("db_readable"), data.database ? "" : ""],
      ["Gateway", gateway.state === "healthy" ? ["ok", "✓", t("pill_ready")] : (gateway.state === "problems" ? ["err", "▲", t("pill_trouble")] : ["info", "?", t("pill_no_data")]), gatewayCause(gateway), launch.at ? (t("no_pass") === "No pass" ? ("Pass " + fmt(launch.at, true)) : ("Pasada " + fmt(launch.at, true))) : t("no_pass")]
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
    // Counts follow the Recurring switch.
    function groupCount(statuses) {
      return statuses.reduce(function (sum, status) { var row = count(status); return sum + (ui.recurring ? (row.recurring || 0) : row.n); }, 0);
    }
    function rawCount(statuses) { return statuses.reduce(function (sum, status) { return sum + count(status).n; }, 0); }
    var totalAll = (data.statuses || []).reduce(function (sum, status) { return sum + (ui.recurring ? (count(status).recurring || 0) : count(status).n); }, 0);
    if (ui.filterAuto) {
      // Decided at every opening: first non-empty of Errors, Running, Drafts; else All.
      ui.filter = "all";
      for (var g = 0; g < 3; g += 1) { if (rawCount(GROUPS[g].statuses) > 0) { ui.filter = GROUPS[g].key; break; } }
    }
    var filters = GROUPS.map(function (group) {
      return { key: group.key, label: t(group.label), statuses: group.statuses, fill: !!group.fill, glyph: group.glyph, n: groupCount(group.statuses) };
    }).filter(function (filter) { return filter.key === "errors" || filter.n > 0 || filter.key === ui.filter; });
    filters.push({ key: "all", label: t("all_tasks"), statuses: null, fill: false, n: totalAll });
    var activeFilter = filters.filter(function (filter) { return filter.key === ui.filter; })[0] || filters[filters.length - 1];
    var focusKey = filters.some(function (filter) { return filter.key === ui.focusKey; }) ? ui.focusKey : activeFilter.key;
    function chipHtml(filter) {
      var selectedChip = filter.key === activeFilter.key;
      var isErrors = filter.key === "errors";
      var glyph = "";
      if (isErrors) glyph = filter.n > 0 ? '<span class="fg err" aria-hidden="true">▲</span>' : '<span class="fg ok" aria-hidden="true">✓</span>';
      else if (filter.key === "running") glyph = '<span class="fg run" aria-hidden="true">▶</span>';
      else if (filter.key === "drafts") glyph = '<span class="fg" aria-hidden="true">◌</span>';
      var word = filter.n === 1 ? t("f_task") : t("f_tasks");
      return '<button type="button" class="fchip' + (filter.fill ? " fill" : "") + (selectedChip ? " on" : "") + (isErrors && filter.n > 0 ? " bad" : "") +
        '" data-filter="' + esc(filter.key) + '" data-chip="1" aria-pressed="' + (selectedChip ? "true" : "false") + '" tabindex="' + (filter.key === focusKey ? "0" : "-1") +
        '" aria-label="' + esc(filter.label + ", " + filter.n + " " + word) + '">' + glyph + '<span class="fl">' + esc(filter.label) + '</span> <b class="fn">' + filter.n + "</b></button>";
    }
    var lead = filters.filter(function (filter) { return filter.fill; }).map(chipHtml).join("");
    var rest = filters.filter(function (filter) { return !filter.fill; }).map(chipHtml).join("");
    // The Recurring switch lives inside the toolbar box so it shares the first mobile row
    // with Errors, Drafts and Running; the .fbreak forces the rest onto the second row.
    var filterHtml = '<div class="fbar"><div class="ftool" role="toolbar" aria-label="' + esc(t("f_toolbar")) + '">' + lead +
      '<span class="fsep" aria-hidden="true"></span>' +
      '<span class="fbreak" aria-hidden="true"></span>' + rest +
      '<label class="rsw"><input type="checkbox" data-recurring="1"' + (ui.recurring ? " checked" : "") + '> <span>' + esc(t("f_recurring")) + "</span></label></div></div>";
    ui.chipKeys = filters.map(function (filter) { return filter.key; });
    function match(task) {
      if (ui.recurring && !task.recurring) return false;
      return !activeFilter.statuses || activeFilter.statuses.indexOf(task.status) >= 0;
    }
    // One row per logical task. A finished older version that a newer task revises
    // (revises_task_id, never a similar title) is folded under the newest version in
    // that chain and listed in its detail. A version that can still run, or that has
    // subtasks of its own, stays a row of its own.
    var successors = {};
    tasks.forEach(function (task) {
      var source = task.revises_task_id;
      if (source && source !== task.id && byId[source]) (successors[source] = successors[source] || []).push(task);
    });
    function newestFirst(a, b) { return String(b.created_at || "").localeCompare(String(a.created_at || "")) || String(a.id).localeCompare(String(b.id)); }
    function headOf(task) {
      var seen = {}, current = task;
      while (current && !seen[current.id]) {
        seen[current.id] = true;
        var next = (successors[current.id] || []).slice().sort(newestFirst)[0];
        if (!next) return current === task ? null : current;
        current = next;
      }
      return null;
    }
    var FOLDS = { completed: true, cancelled: true, archived: true };
    var folded = {}, versions = {}, headId = {};
    tasks.forEach(function (task) {
      if (!FOLDS[task.status] || (kids[task.id] || []).length) return;
      var head = headOf(task);
      if (!head) return;
      folded[task.id] = true;
      headId[task.id] = head.id;
      (versions[head.id] = versions[head.id] || []).push(task);
    });
    Object.keys(versions).forEach(function (id) { versions[id].sort(newestFirst); });
    var roots = tasks.filter(function (task) { return !folded[task.id] && (!task.parent_id || !byId[task.parent_id]); }).slice().sort(function (a, b) {
      return ((b.status === "active") - (a.status === "active")) || (RANK[a.status] - RANK[b.status]) || String(b.updated_at || "").localeCompare(String(a.updated_at || ""));
    });
    var planned = [];
    // "Showing N" counts only tasks that match the group; a parent kept as context for a
    // matching child is drawn dimmed but is not a member of the group.
    var visible = 0;
    roots.forEach(function (parent) {
      var children = (kids[parent.id] || []).map(function (id) { return byId[id]; }).filter(Boolean);
      var parentMatch = match(parent);
      var childMatch = children.filter(match);
      if (parentMatch || childMatch.length) {
        if (parentMatch) visible += 1;
        visible += childMatch.length;
        planned.push([parent, 0, children.length, !parentMatch]);
        childMatch.forEach(function (child) { planned.push([child, 1, 0, false]); });
      }
    });
    var visibleIds = planned.map(function (row) { return row[0].id; });
    // An older version opened from its newer one's detail stays selected while that one is listed.
    var keepFolded = folded[ui.task] && visibleIds.indexOf(headId[ui.task]) >= 0;
    if (visibleIds.indexOf(ui.task) < 0 && !keepFolded) ui.task = visibleIds[0] || null;
    var rows = planned.map(function (row) {
      var task = row[0], level = row[1], nKids = row[2], dim = row[3];
      var spec = ts(task.status);
      var cls = (task.status === "error" ? "err " : "") + (ui.task === task.id ? "sel " : "") + (dim ? "dim" : "");
      return '<div class="row trow pick ' + cls + '" data-task="' + esc(task.id) + '">' +
        "<div>" + pill(spec.tone, spec.glyph, spec.label) + "</div>" +
        '<div class="w100" style="min-width:0;padding-left:' + (level ? 18 : 0) + 'px"><div class="trunc">' + (level ? "└ " : "") + esc(task.title || task.id) + "</div>" +
        '<div class="mono muted" style="font-size:10.5px">' + esc(String(task.id).slice(0, 8)) + (task.recurring ? ' <span class="rmark" role="img" aria-label="' + esc(t("recurring")) + '">↻</span>' : "") + (nKids ? " · " + nKids + " " + t("subtasks") : "") +
        ((versions[task.id] || []).length ? " · " + versions[task.id].length + " " + t("versions") : "") +
        (task.approval_digest_mismatch ? ' <span class="pill warn">⚠ ' + esc(t("not_approved")) + "</span>" : "") + "</div></div>" +
        '<div class="' + (task.provider ? "" : "note") + '">' + esc(task.provider || t("no_provider")) + "</div>" +
        '<div class="opt ' + (task.channel ? "" : "note") + '">' + esc(channelLabel(task.channel)) + "</div>" +
        '<div class="opt note">' + esc(fmtDay(task.created_at)) + "</div>" +
        '<div class="opt req" title="' + esc(t("col_requester")) + ": " + t("gap") + '"></div></div>';
    });
    var selected = ui.task ? byId[ui.task] : null;
    var detail = selected ? taskDetail(selected, byId, kids, history, versions[selected.id] || []) : "<div></div>";
    var empty = "";
    var emptyTitle = "";
    if (!visible) {
      if (activeFilter.key === "errors") {
        var nextGroup = filters.filter(function (filter) { return ["running", "drafts", "queue"].indexOf(filter.key) >= 0 && filter.n > 0; })[0];
        // With the Recurring switch on, an empty Errors group means no recurring error, not no error at all.
        var errorTitle = ui.recurring ? t("f_no_error_rec") : t("f_no_error");
        var errorHint = ui.recurring ? t("f_no_error_rec_hint") : t("f_no_error_hint");
        emptyTitle = errorTitle;
        empty = '<div class="good"><div class="goodt"><span class="fg ok" aria-hidden="true">✓</span> ' + esc(errorTitle) + '</div><div class="note">' + esc(errorHint) + "</div>" +
          (nextGroup ? '<button type="button" class="fnext" data-filter="' + esc(nextGroup.key) + '">' + esc(t("f_next") + nextGroup.label + " (" + nextGroup.n + ")") + "</button>" : "") + "</div>";
      } else { emptyTitle = t("no_tasks"); empty = '<div class="note" style="padding:12px">' + esc(emptyTitle) + "</div>"; }
    }
    var machine = ui.machine ? machineTable(data, selected) : "";
    // The count text the list shows; a stable live region (in app.html) repeats it so a
    // repaint of this block still announces the change.
    ui.announce = t("showing") + visible + t("of") + activeFilter.n;
    // When the group is empty the count says nothing useful; #live then announces this title.
    ui.empty = emptyTitle;
    return filterHtml +
      '<div class="split"><div class="card" style="padding:0;overflow:hidden"><div style="padding:10px 12px" class="note">' + esc(ui.announce) + "</div>" +
      '<div class="row hd trow"><div>' + esc(t("col_status")) + "</div><div>" + esc(t("col_task")) + "</div><div>" + esc(t("col_provider")) + "</div><div>" + esc(t("col_channel")) + "</div><div>" + esc(t("col_created")) + '</div><div>' + esc(t("col_requester")) + '<div class="reqh">' +
      t("gap") + "</div></div></div>" + rows.join("") + empty + "</div>" + detail + "</div>" +
      '<div class="card" style="padding:0;overflow:hidden"><button type="button" class="chip" style="margin:10px 12px" data-machine="1" aria-expanded="' +
      (ui.machine ? "true" : "false") + '">' + (ui.machine ? "▾ " : "▸ ") + esc(t("state_machine")) + "</button>" + machine + "</div>";
  }

  function taskDetail(task, byId, kids, history, olderVersions) {
    var spec = ts(task.status);
    var children = (kids[task.id] || []).map(function (id) { return byId[id]; }).filter(Boolean);
    // The endpoint lists events oldest first (ts, seq); the detail shows the newest on top.
    var events = history.filter(function (event) { return event.task_id === task.id; }).reverse();
    var lines = events.map(function (event, index) {
      var what = (event.from_status ? ts(event.from_status).label + " → " : "") + ts(event.to_status).label;
      if (event.actor) what += " · " + event.actor;
      return '<div class="' + (index === 0 ? "now" : "") + '"><div style="font-weight:500">' + esc(what) + '</div><div class="note">' + esc(fmt(event.ts, true)) + "</div></div>";
    }).join("") || '<div class="note">' + esc(t("no_history")) + "</div>";
    var kidHtml = children.map(function (child) {
      var childSpec = ts(child.status);
      return '<div class="row pick" style="grid-template-columns:auto minmax(0,1fr);padding:6px 4px;min-height:36px" data-task="' + esc(child.id) + '">' +
        pill(childSpec.tone, childSpec.glyph, "") + "<span>" + esc(child.title || child.id) + "</span></div>";
    }).join("");
    var versionHtml = (olderVersions || []).map(function (old) {
      var oldSpec = ts(old.status);
      return '<div class="row pick" style="grid-template-columns:auto minmax(0,1fr);padding:6px 4px;min-height:36px" data-task="' + esc(old.id) + '">' +
        pill(oldSpec.tone, oldSpec.glyph, oldSpec.label) + "<span>" + esc(old.title || old.id) + ' <span class="note">' + esc(fmtDay(old.created_at)) + "</span></span></div>";
    }).join("");
    var mismatch = task.approval_digest_mismatch;
    var mismatchHtml = mismatch ? '<div class="card" style="padding:8px 10px">' + pill("warn", "⚠", t("not_approved")) + '<div class="note" style="margin-top:6px">' +
      esc(t("mm_text") + (t("mm_" + mismatch.reason) === "mm_" + mismatch.reason ? mismatch.reason : t("mm_" + mismatch.reason)) + t("mm_fix")) + "</div></div>" : "";
    return '<div class="card sticky" style="display:flex;flex-direction:column;gap:12px"><div class="lbl">' + esc(t("detail")) + '</div><div style="font-weight:600">' +
      esc(task.title || task.id) + '</div><div style="display:flex;gap:8px;flex-wrap:wrap">' + pill(spec.tone, spec.glyph, spec.label) +
      '<span class="tag' + (task.recurring ? "" : " gap-hide") + '">↻ ' + esc(t("recurring")) + "</span></div>" +
      '<div class="kv" style="grid-template-columns:88px minmax(0,1fr)">' +
      kv("Id", task.id, "mono") + kv(t("col_provider"), task.provider || t("no_provider"), task.provider ? "" : "note") +
      kv(t("col_channel"), channelLabel(task.channel), task.channel ? "" : "note") +
      kv(t("parent"), task.parent_id ? String(task.parent_id).slice(0, 8) : t("root"), task.parent_id ? "mono" : "note") +
      '<div class="k">' + esc(t("col_requester")) + '</div><div><span class="gap">' + t("gap") + "</span></div></div>" +
      (task.revises_task_id && byId[task.revises_task_id] ? '<div class="kv" style="grid-template-columns:88px minmax(0,1fr)">' + kv(t("revises"), String(task.revises_task_id).slice(0, 8), "mono") + "</div>" : "") +
      mismatchHtml +
      (children.length ? '<div><div class="lbl" style="margin-bottom:4px">' + esc(t("subtasks")) + " (" + children.length + ")</div>" + kidHtml + "</div>" : "") +
      (versionHtml ? '<div><div class="lbl" style="margin-bottom:4px">' + esc(t("earlier_versions")) + " (" + olderVersions.length + ")</div>" + versionHtml + "</div>" : "") +
      taskContext(task) + '<div><div class="lbl" style="margin-bottom:8px">' + esc(t("history")) + '</div><div class="tl">' + lines + "</div></div></div>";
  }

  // Only a plain object is read by key; a string or array must not expose
  // inherited members such as String.prototype.at.
  function asObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function weekdaysText(value) {
    var parts = Array.isArray(value) ? value : (typeof value === "string" ? value.split(",") : (value == null ? [] : [value]));
    var names = [];
    parts.forEach(function (part) {
      if (part !== null && typeof part === "object") return;
      var token = String(part).trim();
      if (!token) return;
      names.push(/^[1-7]$/.test(token) ? t("tc_day_" + token) : token);
    });
    return names.length ? names.join(", ") : null;
  }

  function runsText(value) {
    if (value == null || value === "") return null;
    // Any integer-valued zero (0, "0", "00", " 0 ", 0.0) means no limit; everything else is shown as stored.
    return /^[-+]?0+(\.0+)?$/.test(String(value).trim()) ? t("tc_unlimited") : value;
  }

  function intervalText(value) {
    var seconds = Number(value);
    if (value == null || value === "" || !isFinite(seconds) || seconds <= 0) return null;
    if (seconds % 3600 === 0) return seconds / 3600 + " h";
    if (seconds % 60 === 0) return seconds / 60 + " min";
    return seconds + " s";
  }

  function contextErrorText(code) {
    if (code === "checkpoint_invalid") return t("tc_this_task_s_stored_continuity_checkpoint");
    if (code === "frontmatter_unreadable") return t("tc_this_task_s_stored_record_could_not_be_r");
    return t("tc_this_task_s_context_could_not_be_read");
  }

  function taskTokenUsage(usage) {
    usage = asObject(usage);
    var attempts = usage.attempts || [];
    var metrics = ["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens"];
    var html = '<section class="token-usage" aria-label="' + esc(t("usage_title")) + '"><h3>' + esc(t("usage_title")) + '</h3>';
    html += '<p class="note">' + esc(t("usage_scope")) + '</p>';
    if (!attempts.length) return html + '<p class="note">' + esc(t("usage_empty")) + '</p></section>';
    function counters(values) {
      return '<dl class="kv wide">' + metrics.map(function (key) {
        var value = asObject(values)[key];
        return '<dt class="k">' + esc(t("usage_" + key)) + '</dt><dd>' +
          esc(value == null ? t("usage_not_available") : String(value)) + '</dd>';
      }).join("") + '</dl>';
    }
    html += '<p class="note">' + esc(t("usage_native")) + '</p><dl class="kv wide">';
    metrics.forEach(function (key) {
      var c = asObject(asObject(usage.coverage)[key]);
      html += '<dt class="k">' + esc(t("usage_" + key)) + '</dt><dd>' + esc(String(c.available || 0) + " / " + String(c.launched || 0) + " · " + t("usage_coverage")) + '</dd>';
    });
    html += '</dl>';
    (usage.subtotals || []).forEach(function (group) {
      var vals = {};
      metrics.forEach(function (key) { vals[key] = asObject(asObject(group.metrics)[key]).subtotal; });
      html += '<details><summary>' + esc(t("usage_subtotal") + " · " + group.provider + " · " + (group.model || t("usage_not_available")) + " · " + (group.cli_version || t("usage_not_available"))) + '</summary>' + counters(vals) + '</details>';
    });
    attempts.forEach(function (a) {
      html += '<details><summary>' + esc(t("usage_attempt") + " " + a.id + " · " + a.provider + " · " + t("usage_" + a.coverage)) + '</summary>' +
        '<p>' + esc(t("usage_execution") + ": " + a.execution_id + " · " + a.status) + '</p>' +
        '<p>' + esc(t("usage_model") + ": " + (a.model || t("usage_not_available"))) + '</p>';
      if (!a.finished_at || a.capture_error) html += '<p class="note">' + esc(t("usage_pending")) + '</p>';
      if (a.reason) html += '<p class="note">' + esc(t('usage_reason_' + a.reason)) + '</p>';
      html += counters(a.metrics) + '<details><summary>' + esc(t("usage_evidence")) + '</summary><pre>' +
        esc(JSON.stringify(a.observations || [], null, 2)) + '</pre></details></details>';
    });
    return html + '</section>';
  }

  function taskContext(task) {
    var title = t("tc_context_and_follow_up");
    var stamp = task.updated_at || "";
    var saved = taskContexts[task.id];
    if (!saved || saved.stamp !== stamp) {
      var entry = { stamp: stamp, loading: true };
      taskContexts[task.id] = entry;
      var epoch = contextEpoch;
      load("/api/console/task-detail?task_id=" + encodeURIComponent(task.id)).then(function (reply) {
        if (epoch !== contextEpoch || taskContexts[task.id] !== entry) return;
        entry.loading = false;
        entry.data = reply.data;
        entry.refused = reply.refused;
        if (ui.screen === "tareas" && ui.task === task.id && cache.tareas) paint("tareas", cache.tareas);
      });
      saved = entry;
    }
    var heading = '<section aria-label="' + esc(title) + '"><h3>' + esc(title) + '</h3>';
    if (saved.loading) return heading + '<p class="note">' + esc(t("reading")) + '</p></section>';
    if (saved.refused) return heading + '<p class="note" role="alert">' + esc(t("tc_this_task_s_context_could_not_be_read")) + '</p>' + fullRecord(task) + '</section>';
    var data = saved.data || {};
    var context = asObject(data.context);
    var cp = asObject(context.continuity_checkpoint);
    var verified = asObject(cp.last_verified_result);
    var next = asObject(cp.next_check);
    var decision = asObject(cp.decision);
    var effect = asObject(cp.checkpoint).state;
    var fields = [];
    function field(label, value) {
      if (Array.isArray(value)) value = value.every(function (item) { return item == null || typeof item !== "object"; }) ? value.join(", ") : null;
      if (value != null && typeof value !== "object" && String(value)) fields.push('<dt class="k">' + esc(label) + '</dt><dd>' + esc(value) + '</dd>');
    }
    field(t("tc_workspace"), context.workspace_id);
    field(t("tc_agent"), context.agent);
    field(t("tc_planet"), context.planet);
    field(t("tc_responsibility"), context.responsibility);
    field(t("tc_contract"), context.agent_contract);
    field(t("tc_recorded_result"), verified.path || verified.artifact_ref);
    field(t("tc_recorded_verification"), verified.verified_at ? fmt(verified.verified_at, true) : null);
    field(t("tc_next_check"), next.action);
    field(t("tc_check_date"), next.at);
    field(t("tc_check_source"), next.source);
    field(t("tc_waiting"), typeof cp.wait === "string" ? cp.wait : asObject(cp.wait).reason);
    field(t("tc_decision_owner"), decision.owner);
    field(t("tc_subject"), decision.subject || decision.action);
    field(t("tc_decision_source"), decision.source);
    field(t("tc_valid_from"), decision.valid_from);
    field(t("tc_valid_until"), decision.valid_until);
    if (decision.status) field(t("tc_decision"), decision.status === "pending" ? (t("tc_pending")) : (t("tc_recorded_status_check_source")));
    if (effect) field(t("tc_effect_state"), effect === "effect_uncertain" ? (t("tc_uncertain_verify_before_retrying")) : (t("tc_recorded_state_not_verified_on_opening")));
    var contextFields = fields.length;
    var unshown = Object.keys(cp).length > 0 || Object.keys(context).some(function (name) { return context[name] !== null && typeof context[name] === "object"; });
    var configuration = asObject(data.configuration);
    if (configuration.recurring === true || configuration.recurring === "true") field(t("tc_recurrence"), t("tc_recurring"));
    field(t("tc_minimum_interval"), intervalText(configuration.recurring_min_interval));
    field(t("tc_configured_time"), configuration.scheduled_time);
    field(t("tc_time_zone"), configuration.scheduled_timezone || (configuration.scheduled_time ? t("tc_host_timezone_no_stored_zone") : null));
    field(t("tc_weekdays"), weekdaysText(configuration.scheduled_weekdays));
    field(t("tc_maximum_runs"), runsText(configuration.recurring_max_runs));
    field(t("tc_reserved_resources"), configuration.resources);
    var message = "";
    if (data.context_error) message = '<p class="note" role="alert">' + esc(contextErrorText(data.context_error)) + '</p>';
    else if (!contextFields) message = '<p class="note">' + esc(t(unshown ? "tc_context_shape_note" : (fields.length ? "tc_no_recorded_checkpoint" : "tc_no_recorded_context_execution_state_and"))) + '</p>';
    return heading + message + (fields.length ? '<dl class="kv wide">' + fields.join("") + '</dl>' : '') +
      '<p class="note">' + esc(t("tc_reading_this_record_does_not_verify_an_e")) + '</p>' +
      fullRecord(task) + '</section>' + taskTokenUsage(data.token_usage);
  }

  function fullRecord(task) {
    var state = taskFull[task.id] || {};
    if (state.open && state.stamp !== (task.updated_at || "")) loadFull(task, state);
    var label = t("tc_complete_record");
    var button = '<button type="button" class="chip" data-full="' + esc(task.id) + '" aria-expanded="' + (state.open ? "true" : "false") + '">' +
      (state.open ? "▾ " : "▸ ") + esc(label) + '</button>';
    if (!state.open) return button;
    if (state.loading) return button + '<p class="note">' + esc(t("reading")) + '</p>';
    if (state.refused) return button + '<p class="note" role="alert">' + esc(t("tc_the_complete_record_could_not_be_read")) + '</p>';
    var data = state.data || {};
    var record = data.record;
    if (!record || typeof record !== "object" || Array.isArray(record)) return button + '<p class="note">' + esc(t("tc_record_unavailable")) + '</p>';
    var names = Object.keys(record).filter(function (name) { return name !== "frontmatter" && name !== "body"; });
    var columns = '<dl class="kv wide task-record">' + names.map(function (name) {
      return '<dt class="k">' + esc(name) + '</dt><dd>' + recordValue(record[name]) + '</dd>';
    }).join("") + '</dl>';
    var body = "";
    if ("body" in record) {
      var text = record.body;
      // The only place server HTML enters: the allowlist-sanitized Markdown of the body.
      var inner = typeof text === "string" && typeof data.body_html === "string"
        ? '<div class="task-markdown">' + data.body_html + '</div>' : recordValue(text);
      body = '<div class="task-body"><div class="lbl">' + esc(t("tc_instructions")) + '</div>' + inner + '</div>';
    }
    var front = "";
    if ("frontmatter" in record) {
      var fm = record.frontmatter;
      front = '<div class="task-front"><button type="button" class="chip" data-front="' + esc(task.id) + '" aria-expanded="' + (state.frontOpen ? "true" : "false") + '">' +
        (state.frontOpen ? "▾ " : "▸ ") + esc(t("tc_frontmatter")) + '</button>';
      if (state.frontOpen) {
        front += Array.isArray(fm)
          ? '<dl class="kv wide">' + fm.map(function (pair) {
            if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[0] !== "string") return '<dt class="k"></dt><dd>' + recordValue(pair) + '</dd>';
            return '<dt class="k">' + esc(pair[0]) + '</dt><dd>' + recordValue(pair[1]) + '</dd>';
          }).join("") + '</dl>'
          : recordValue(fm);
      }
      front += '</div>';
    }
    return button + columns + body + front;
  }

  function loadFull(task, state) {
    var epoch = contextEpoch;
    state.seq = (state.seq || 0) + 1;
    var mine = state.seq;
    state.stamp = task.updated_at || "";
    state.loading = true;
    state.refused = null;
    state.data = null;
    load("/api/console/task-detail?task_id=" + encodeURIComponent(task.id) + "&full=1").then(function (reply) {
      if (epoch !== contextEpoch || taskFull[task.id] !== state || state.seq !== mine) return;
      state.loading = false;
      state.data = reply.data || null;
      state.refused = reply.refused || null;
      if (ui.screen === "tareas" && ui.task === task.id && cache.tareas) paint("tareas", cache.tareas);
    });
  }

  function toggleFront(id) {
    var state = taskFull[id] || (taskFull[id] = {});
    state.frontOpen = !state.frontOpen;
    if (ui.screen === "tareas" && cache.tareas) paint("tareas", cache.tareas);
  }

  function toggleFull(id) {
    var task = null;
    ((cache.tareas && cache.tareas.data && cache.tareas.data.tasks) || []).forEach(function (row) { if (row.id === id) task = row; });
    if (!task) return;
    var state = taskFull[task.id] || (taskFull[task.id] = {});
    state.open = !state.open;
    if (!state.open) state.frontOpen = false;
    if (state.open && (state.stamp !== (task.updated_at || "") || (!state.data && !state.loading))) loadFull(task, state);
    if (ui.screen === "tareas" && cache.tareas) paint("tareas", cache.tareas);
  }

  function recordValue(value) {
    if (value === null) return '<span class="note">null</span>';
    if (Array.isArray(value)) return '<ul>' + value.map(function (item) { return '<li>' + recordValue(item) + '</li>'; }).join("") + '</ul>';
    if (typeof value === "object") return '<dl class="kv wide">' + Object.keys(value).map(function (key) { return '<dt class="k">' + esc(key) + '</dt><dd>' + recordValue(value[key]) + '</dd>'; }).join("") + '</dl>';
    return '<span style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(value) + '</span>';
  }

  function safeToolLink(href) {
    if (typeof href !== "string" || /[\u0000-\u0020\u007f]/.test(href) || !/^http:\/\/(?:127\.0\.0\.1|localhost):[0-9]{1,5}\/$/.test(href)) return false;
    var port = Number(href.split(":")[2].slice(0, -1));
    return port >= 1 && port <= 65535;
  }

  // A file surface is served by the console itself; the route never carries a
  // filesystem path, only <planet>/<name>.
  function safeFileLink(href) {
    return typeof href === "string" && /^\/dashboards\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(href);
  }

  function safeDashboardLink(row) {
    if (row.kind === "file") return safeFileLink(row.href) ? row.href : null;
    return safeToolLink(row.href) ? row.href : null;
  }

  function renderDashboards(data) {
    var es = LANG === "es";
    var groups = Object.create(null);
    (data.dashboards || []).forEach(function (row) {
      var planet = row.planet || (es ? "Sin planeta" : "No planet");
      if (!groups[planet]) groups[planet] = [];
      groups[planet].push(row);
    });
    var rows = Object.keys(groups).sort().map(function (planet) {
      var cards = groups[planet].map(function (row) {
        var safe = safeDashboardLink(row);
        var mode = row.mode === "interactive"
          ? (es ? "Interactivo (puede modificar datos en esa herramienta)" : "Interactive (can modify data in that tool)")
          : (es ? "Solo lectura" : "Read only");
        var open = safe ? '<a href="' + esc(row.href) + '" target="_blank" rel="noopener noreferrer">' + esc(es ? "Abrir ↗" : "Open ↗") + '</a>' : '';
        if (row.kind === "file") {
          // A generated view has no service and no registration: it is always
          // available, read only, and belongs to the planet's data. Its freshness
          // is the file's mtime, not a date the HTML claims.
          var fresh = row.freshness
            ? '<p class="note">' + esc(es ? "Última escritura del fichero: " : "File last written: ") + esc(row.freshness) + '</p>'
            : '';
          return '<article class="card rep"><p class="note">' + esc(es ? "Vista" : "View") + ' · ' + esc(mode) + '</p><h3>' + esc(row.title) + '</h3><p>' + esc(row.description) + '</p><p>' + esc(es ? "Vista generada por el planeta; los datos permanecen en sus fuentes y la fecha no acredita frescura." : "View generated by the planet; the data stays in its own sources and the date does not prove freshness.") + '</p>' + fresh + '<p class="note">' + esc(row.owner) + ' · ' + esc(row.updated_at) + '</p>' + open + '</article>';
        }
        var command = row.registered
          ? (row.start_command
              ? '<p class="note">' + esc(es ? "Cómo arrancarlo (copiar):" : "How to start (copy):") + '</p><p class="dashboard-start">' + esc(row.start_command) + '</p>'
              : '<p class="note">' + esc(es ? "Sin comando de arranque registrado." : "No start command registered.") + '</p>')
          : '<p class="note">' + esc(es ? "No registrado: regístralo con solar client sync dashboards register" : "Not registered: use solar client sync dashboards register") + '</p>';
        var state = '<p class="note">' + esc(row.registered ? (es ? "Registrado en este equipo" : "Registered on this machine") : (es ? "Solo declarado aquí" : "Declared here only")) + '</p>';
        return '<article class="card rep"><p class="note">' + esc(es ? "Herramienta" : "Tool") + ' · ' + esc(mode) + '</p><h3>' + esc(row.title) + '</h3><p>' + esc(row.description) + '</p><p>' + esc(es ? "El servicio puede requerir arranque manual." : "The service may require a manual start.") + '</p>' + state + command + '<p class="note">' + esc(row.owner) + ' · ' + esc(row.updated_at) + '</p>' + open + '</article>';
      }).join("");
      return '<section class="dashboard-group"><h2>' + esc(planet) + '</h2><div class="tiles2">' + cards + '</div></section>';
    }).join("");
    var errors = (data.errors || []).map(function (row) { return '<p class="note">' + esc(row.id || row.planet) + ': ' + esc(row.source) + ' · ' + esc(row.error || (es ? "índice no disponible" : "index unavailable")) + '</p>'; }).join("");
    return '<p class="note">' + esc(es ? "Herramientas y vistas declaradas por cada planeta. Console es de solo lectura: nunca arranca ni sondea una herramienta, y el comando de arranque solo se copia." : "Tools and views declared by each planet. Console is read only: it never starts or probes a tool, and the start command is only copied.") + '</p>' + (rows || '<p>' + esc(es ? "Todavía no hay dashboards." : "No dashboards yet.") + '</p>') + errors;
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

  function waitKindLabel(kind) {
    var keys = { dependency: "wait_dependency", resource: "wait_resource", provider: "wait_provider",
                 capacity: "wait_capacity", authorization: "wait_authorization", recovery: "wait_recovery" };
    return t(keys[kind] || "wait_other");
  }
  function renderCapacity(reply) {
    if (!reply) return "";
    if (reply.refused) return '<div class="card"><div class="h3">' + esc(t("cap_title")) + "</div>" + refusedBox(reply.refused) + "</div>";
    var data = reply.data || {};
    var cap = data.capacity || {};
    var running = (data.running || []).map(function (row) {
      return '<div class="row" style="grid-template-columns:minmax(0,1fr) 110px 110px"><div style="font-weight:500">' +
        esc(row.title || row.id) + '</div><div class="mono">' + esc(row.provider || "—") + '</div><div class="note">' +
        esc(row.access === "declared" ? "read/write scoped" : "exclusive") + "</div></div>";
    }).join("");
    var waiting = (data.waiting || []).map(function (row) {
      return '<div class="row" style="grid-template-columns:minmax(0,1fr) 130px minmax(0,1fr)"><div style="font-weight:500">' +
        esc(row.title || row.id) + "</div><div>" + pill(row.kind === "recovery" ? "warn" : "neu", "…", waitKindLabel(row.kind)) +
        '</div><div class="note mono">' + esc(row.reason) + "</div></div>";
    }).join("");
    var recovery = (data.recovery || []).map(function (row) {
      return '<div class="row err" style="grid-template-columns:minmax(0,1fr) 170px minmax(0,1fr)"><div style="font-weight:500">' +
        esc(row.title || row.id) + '</div><div class="mono">' + esc(row.reason) + '</div><div class="note">' + esc(row.detail || "") + "</div></div>";
    }).join("");
    var counts = data.wait_counts || {};
    var countPills = Object.keys(counts).map(function (kind) {
      return pill(kind === "recovery" ? "warn" : "neu", "…", waitKindLabel(kind) + " " + counts[kind]);
    }).join(" ");
    var providers = cap.provider_capacity || {};
    var providerText = Object.keys(providers).length
      ? Object.keys(providers).map(function (name) { return name + " ≤ " + providers[name]; }).join(", ") : t("cfg_none_provider");
    var cfg = data.configuration || {};
    var applied = cfg.applied || {};
    var diffs = cfg.differences || {};
    var diffRows = Object.keys(diffs).map(function (key) {
      return '<div class="note mono">' + esc(key) + ": " + esc(t("cfg_applied")) + " " + esc(JSON.stringify(diffs[key].applied)) +
        " → " + esc(t("cfg_proposed")) + " " + esc(JSON.stringify(diffs[key].proposed)) + "</div>";
    }).join("");
    var proposal = cfg.proposal || {};
    var pendingHtml = cfg.pending
      ? '<div class="note">' + esc(t("cfg_pending")) + "</div>" + diffRows
      : '<div class="note">' + esc(t("cfg_no_pending")) + "</div>";
    if (proposal.error) pendingHtml += '<div class="note">' + esc(t("cfg_proposal_error")) + " " + esc(proposal.error) + "</div>";
    var sup = data.supervisor;
    var supHtml = !sup ? '<div class="note">' + esc(t("sup_none")) + "</div>"
      : '<div class="note mono">pid ' + esc(sup.pid) + " · " + esc(sup.state || "—") + (sup.fresh ? "" : " · " + esc(t("sup_stale"))) + "</div>";
    return '<div class="card"><div class="h3" style="margin-bottom:10px">' + esc(t("cap_title")) + "</div>" +
      '<div class="tiles"><div class="card"><div class="lbl">' + esc(t("cap_used")) + '</div><div class="big">' + nf(cap.used || 0) +
      '<span class="note"> ' + esc(t("cap_of")) + " " + nf(cap.global_capacity || 0) + "</span></div><div class=\"note\">" +
      nf(cap.free || 0) + " " + esc(t("cap_free")) + '</div></div><div class="card"><div class="lbl">' + esc(t("cap_simul")) +
      '</div><div class="big">' + nf(cap.simultaneous || 0) + '</div></div><div class="card"><div class="lbl">' + esc(t("cap_waiting")) +
      '</div><div class="big">' + nf((data.waiting || []).length + (data.recovery || []).length) + '</div><div>' + countPills + "</div></div></div>" +
      (running || '<div class="note">' + esc(t("cap_none_running")) + "</div>") +
      (waiting ? waiting : '<div class="note">' + esc(t("cap_none_waiting")) + "</div>") +
      (recovery ? '<div class="lbl" style="margin-top:8px">' + esc(t("sup_blocked")) + "</div>" + recovery : "") +
      '<div class="lbl" style="margin-top:12px">' + esc(t("cfg_title")) + '</div><div class="note mono">' + esc(t("cfg_revision")) + " " +
      esc(applied.revision) + " · " + esc(t("cfg_global")) + " " + esc(applied.global_capacity) + " · " + esc(t("cfg_provider")) + ": " +
      esc(providerText) + " · " + esc(t("cfg_exclusive")) + " " + esc(applied.exclusive_wait_seconds) + "</div>" + pendingHtml +
      '<div class="lbl" style="margin-top:12px">' + esc(t("sup_title")) + "</div>" + supHtml + "</div>";
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
      '<div class="card" style="padding:0;overflow:hidden"><div class="row hd" style="grid-template-columns:160px 160px 150px 70px minmax(0,1fr)"><div>' + esc(t("app_col")) + "</div><div>" + esc(t("receives")) + "</div><div>" + esc(t("path")) + "</div><div>" + esc(t("skills")) + "</div><div>" + esc(t("broken")) + "</div></div>" +
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
    return '<div class="note">' + esc(t("channels_note")) + '</div><div class="card" style="padding:0;overflow:hidden"><div style="padding:12px 16px 6px" class="h3">' + esc(t("http_channels")) + "</div>" +
      '<div class="row hd" style="grid-template-columns:180px 200px minmax(0,1fr)"><div>' + esc(t("channel")) + "</div><div>" + esc(t("address")) + "</div><div>" + esc(t("scope")) + "</div></div>" +
      '<div class="row" style="grid-template-columns:180px 200px minmax(0,1fr)"><div style="font-weight:500">' + esc(t("console")) + '</div><div class="mono">' + esc(location.host || ("127.0.0.1:" + consolePort())) + "</div><div>" + pill("ok", "✓", t("local_only")) + "</div></div>" +
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
    var recurring = event.target.closest("[data-recurring]");
    if (recurring) {
      ui.recurring = !ui.recurring;
      ui.refocus = "recurring";
      writeFilterHash();
      if (cache.tareas) paint("tareas", cache.tareas);
      return;
    }
    var filter = event.target.closest("[data-filter]");
    if (filter) {
      ui.filter = filter.getAttribute("data-filter");
      ui.filterAuto = false;
      ui.focusKey = ui.filter;
      ui.refocus = "filter";
      writeFilterHash();
      if (cache.tareas) paint("tareas", cache.tareas);
      return;
    }
    var task = event.target.closest("[data-task]");
    if (task) {
      ui.task = task.getAttribute("data-task");
      if (cache.tareas) paint("tareas", cache.tareas);
      return;
    }
    var front = event.target.closest("[data-front]");
    if (front) {
      toggleFront(front.getAttribute("data-front"));
      return;
    }
    var full = event.target.closest("[data-full]");
    if (full) {
      toggleFull(full.getAttribute("data-full"));
      return;
    }
    if (event.target.closest("[data-machine]")) {
      ui.machine = !ui.machine;
      if (cache.tareas) paint("tareas", cache.tareas);
    }
  });

  // Roving tabindex: one tab stop in the toolbar; arrows move between chips, Enter and Space
  // select through the button's own click.
  document.addEventListener("keydown", function (event) {
    var chip = event.target.closest && event.target.closest("[data-chip]");
    if (!chip) return;
    var keys = ui.chipKeys || [];
    var at = keys.indexOf(chip.getAttribute("data-filter"));
    if (at < 0) return;
    var move = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    var to = move ? (at + move + keys.length) % keys.length : (event.key === "Home" ? 0 : (event.key === "End" ? keys.length - 1 : -1));
    if (to < 0) return;
    if (event.preventDefault) event.preventDefault();
    ui.focusKey = keys[to];
    ui.refocus = "filter";
    if (cache.tareas) paint("tareas", cache.tareas);
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

  var bootFilter = readFilterHash();
  openScreen(bootFilter ? "tareas" : "resumen", bootFilter);
})();
