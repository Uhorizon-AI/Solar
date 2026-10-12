---
name: solar-app
description: >
  Read-only Solar console on :9000. Inspect runtime health, async tasks, gateway
  failures, continuity freshness and router executions with injected context.
---

# Solar Console

Open `http://localhost:9000/app`. Status, logs and activity come from the views in
`state.sqlite` (`runtime_views`). No conversation store, voice runtime, execution
worker or mutation endpoints are provided.

## Required MCP

None

## CLI

```bash
solar app start|stop|status|open
solar app workspace list|add|remove|use <path>
solar status
```

The global dispatcher is `core/skills/solar-client/scripts/solar`.
`app_http.py` serves the console; `app_solar.py` reads its canonical sources.
`host_registry.py` and `host_workspace_context.py` retain workspace selection.
The console port is fixed at 9000. The registry and metrics keep their current
machine-local paths; runtime files remain under `<runtime root>/`.

Health requires a fresh source read. Task failures describe the task, not the
health of Solar. A router start without a recent end is not proof of a live
process. History turns and summaries are traceability, not a contamination detector.
A missing gateway probe is unverified, not healthy. Recorded failures retain their
date.

The page at `/app` is the eight-question console. It is HTML, CSS and JS with no
build step and no request to another host. Inter and Montserrat (SIL Open Font
License) are served from `/assets/fonts/`. Each screen reads one `/api/console/*`
route. Entrada also reads `/api/console/health` for the gateway state already
decided there. A 503 with `refused` is shown with its reason. The verdict, its
reasons and the unverified checks come from `/api/console/health`; the page does
not apply the rule again. `attention` on that route is the summary headline.
Copy is English unless `.solar/settings.json` sets `"language"` to `es`
(also `es-ES` or `spanish`). Set that key with `solar client language set es`.
Do not edit `.solar/settings.json` by hand. A workspace with no `language`
key stays English. Health returns that `language`. Calm starts with "All
working" ("Todo funciona" in Spanish) and adds only non-zero counts: tasks
in error, drafts, and whole days since the newest router, task, or mandate
activity. A fault names the cause. Unverified names the checks that have no
data. The page prints that sentence and does not compose it. The summary
screen reloads every 30 seconds. The other screens reload when opened.
Times use Europe/Madrid.
Nothing on the page mutates Solar. The requester column and screen stay empty
until part 2. Older `/api/app/*`, `/api/async/jobs` and `/api/runtime/health`
routes still answer; the page does not call them.

## Console data

Eight read-only routes under `/api/console/`: `health`, `tasks`, `executions`,
`continuity`, `mandates`, `ides`, `ingress`, `requester`. `console_data.py`
answers them. Database rows come from `read_session()` in solar-state. Files
outside the database (owner, cutover, pass stamp, daily backups, IDE trees,
gateway stamp, mandate YAML, MCP gate audit) are read through solar-paths.
`console_data.py` loads `solar-client/scripts/console_language.py`.
A missing file raises ImportError and names that path. These routes
create no runtime file. Execution channel and `user_id` come from the
audit start with the same `router_id`. An end with no start is channel
`other`. The requester screen shows how many distinct `user_id` values
that is, and does not present them as people.

`verdict` is `calm`, `fault`, or `unverified`. `verdict.checks` states
`database`, `port`, `system`, `router`, `launchagent`, and `gateway` as
`ok`, `fault`, or `unverified`. The page renders that list. A fresh pass stamp
is healthy only when local `/health`, the connector, and the ws, http, and
tunnel processes are all up. A stamp older than five minutes is a fault. No stamp leaves the pass and
the gateway unverified. The system result stays unverified until a fresh
pass, unless that stamp recorded a feature failure. The
router is a fault when the state refuses, and quiet time is not a fault by
itself.
The host refuses to bind when `SOLAR_APP_HOST` is not a loopback address.

The continuity screen and its card on the summary explain that the record is
what Solar last held from Telegram, n8n, or a task, and that it does not move
when work happens in the IDE. The active intention is labeled as stored text.
The continuity payload is unchanged.

Delegation modes are labeled Active, Trial (no real effects), Paused, and
Revoked. With `"language": "es"` those labels are Activa, En prueba (sin
efectos reales), Pausada, and Revocada. A filled `revoked_at` marks the
file revoked even when `mode` still says active. That file stays in the
list, dimmed, with the date, and is left out of `active`. Visible copy uses
those names. It does not show authority codes.

## Validation commands

```bash
python3 -m unittest discover -s core/tests/skills/solar-app -p 'test_*.py'
python3 -m py_compile core/skills/solar-app/scripts/host_server.py
bash -n core/skills/solar-client/scripts/solar
python3 core/skills/solar-skill-creator/scripts/package_skill.py core/skills/solar-app /tmp
```

## Task status filters

One toolbar over the list and the detail, in this order: Errors (`error`),
Running (`active`), Drafts (`draft`), a 1 px separator, Queue (`planned`,
`queued`), Done (`completed`), Closed (`cancelled`, `archived`) and All; a real
"Recurring" checkbox sits on the right and is not a chip. Errors never hides: at 0
it shows a green check, and selecting it shows "No tasks in error" with a link to
the next pending group. Running exists only while a task is active. Every other
group hides at 0 unless selected. The default filter is the first non-empty of
Errors, Running and Drafts, else All, decided at each opening and never remembered
between sessions; only the URL hash (`#tasks/<group>` with `+recurring`) carries it
over a reload. The Recurring checkbox intersects the group and the chip counts
follow it. Active tasks sort first inside any group that holds them. Rows show all
eight states as a pill with glyph and text (red only for `error`, blue only for
`active`); recurring tasks carry a "↻" mark after the id.

Accessibility: the chips sit in a `role="toolbar"` with one tab stop (roving
tabindex), arrows, Home and End move between chips, Enter and Space select, each
chip is labelled with its count ("Errors, 2 tasks"), "Showing N of M" is a polite
live region, and the focus ring is 2 px in the text colour. Below 900 px the bar
wraps into two touch-sized rows (Errors, Drafts and the checkbox first). Filtering is
presentation only: the route, the data and the state machine are unchanged.

## Laptop runtime note

Host sleep stops availability. Only one active host should serve the same public
route. This console is local and does not replace the gateway or transports.

## Task detail: curated context and opt-in complete record

Selecting a task reads `GET /api/console/task-detail?task_id=<id>` on demand
(`task_id` is required and at most 200 characters).

| Status | Body |
|---|---|
| 400 | `{"error": "A bounded task_id is required"}` |
| 404 | `{"error": "Task not found"}` |
| 503 | `{"error": "Task detail unavailable", "refused": true}` (fixed text, never the exception text) |
| 200 | `{"id", "context", "context_error", "configuration"}` |
| 200 with `full=1` | the same keys plus `record` and `body_html` |

By default the console shows a "Context and follow-up" block: the recorded
checkpoint (owner, next check, wait, decision) and the stored schedule. It comes
from solar-state `runtime_views.console_task_detail`, which shares its checkpoint
parser with the MCP task views. `context_error` is a stable code
(`checkpoint_invalid` or `frontmatter_unreadable`) that affects only that task;
the schedule and history stay visible, and an unreadable frontmatter still answers
200. Reading the record does not verify an effect nor authorize retrying it.

The complete record is opt-in: only the "Complete record" button requests
`full=1` (exactly the string `1`). It adds the whole solar-state row, including
columns added later and malformed frontmatter as stored text, and `body_html`,
sanitized HTML derived only from the Markdown body. `task_markdown.py` renders a
conservative subset (headings, paragraphs, lists, quotes, rules, tables, code,
`*` emphasis, and links); underscores are never emphasis, only explicit http,
https and mailto links are links, and raw HTML and images stay inert text. No
dependencies or network fetches. Not supported, by design: link destinations
containing parentheses (the link ends at the first `)`); a `|` inside a table
cell, including inside inline code (it always splits the cell); and
internationalized host names such as `https://münchen.de` (links need an ASCII
host, a valid bracketed IPv6 address if any, and a port from 1 to 65535, so they
stay text). The parser is not extended for these. The view is read only: no write
session, event, queue or verification. An unexpected failure in this route
answers the fixed 503 and logs one warning with the exception class (never its
message) through the `solar.app` logger. The host adds a stderr handler only when
neither that logger nor the root logger has one; a configured root is trusted and
propagation is unchanged. If the root is configured after the console started, the
warning can print twice (accepted). Other console routes answer a fixed "Console
data unavailable" on unexpected read errors.

Tasks screen layout: list and detail share the width evenly and stack below 900
px. The list keeps Status, Task and Created up to 1600 px of viewport width,
where the list is about half of the content (measured: 490 px at 1280 and
570 px at 1440), and hides Provider, Channel and Requester; wider than 1600 px every
column shows. The detail shows the newest history event first. Schedule days
show names, a run limit of 0 shows as unlimited, and the complete record keeps
its frontmatter folded until opened.

Landing these sources does not mean installed acceptance: install and client
publication are still required before claiming it.
