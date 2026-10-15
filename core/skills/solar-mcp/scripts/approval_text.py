"""The human text of a confirmation: what the person is asked to approve.

Built only from the *validated* operation arguments and from the task as the
store holds it right now. Nothing the calling agent supplies as prose can reach
it (the operation schemas are closed, there is no summary field), and nothing
here grants or changes authority: the approval still binds the operation name,
the exact arguments, the workspace and the task `row_version` internally.

The text is short on purpose. Identifiers, hashes, row versions and empty fields
stay out of it; the full arguments stay in the server for validation, binding and
the gate audit. Only the language comes from configuration (`language` in
`.solar/settings.json`): English unless it is Spanish.
"""
from __future__ import annotations

import difflib
import functools
import os
import importlib.util
import json
import re
from pathlib import Path

import task_views
from mcp_context import OperationError, workspace

_LANGUAGE_PY = Path(__file__).resolve().parents[2] / "solar-client" / "scripts" / "console_language.py"

_EXCERPT = 400      # instructions shown when approving or creating a task
_VALUE = 160        # one changed field value
_DIFF_LINES = 4     # changed instruction lines listed in an edit
_DAYS = {
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "es": ("lun", "mar", "mié", "jue", "vie", "sáb", "dom"),
}
# C0/C1 controls (newline and tab aside) and characters that reorder or hide text.
_INVISIBLE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")

COPY = {
    "en": dict(
        approve_title="Approve this action",
        footer="Single use, valid {seconds} seconds. If it fails or is uncertain, a new approval is needed.",
        task="Task", reason="Reason", effect="Effect", to="To", message="Message", format="Format",
        warn="Warning", none="(none)", unlimited="unlimited",
        archive_head="Archive task",
        archive_queued="the task is cancelled first (it will not run) and then archived; its history is kept.",
        archive_queued_rec="the recurrence is stopped (the task will not run again), then the task is archived; its history is kept.",
        archive_plain="the task is archived and keeps its history.",
        archive_active="refused while the task is running. Cancel it first and archive it once it stopped.",
        archive_done="refused: the task is already archived.",
        archive_guard="Also refused if another task waits on it or one of its subtasks is still running.",
        create_head="Create draft task", revise_head="Create draft revision",
        revision_of="Revises", create_effect="stores one draft. Nothing is queued or run; approving it is a separate step.",
        revise_effect="stores one draft copy of that task with its settings and schedule; the original is untouched. Nothing is queued or run.",
        instructions="Instructions", chars="{n} characters in total",
        update_head="Edit task", changes="Changes", no_diff="no difference from the stored task",
        update_planned="the task returns to draft and must be approved again. Nothing is queued or run.",
        update_draft="the stored draft is rewritten. Nothing is queued or run.",
        edit_active="refused: a running task keeps the instructions it started with.",
        update_queued_rename="only the title changes. The task keeps its place in the queue and its approval; nothing is run.",
        update_queued_material="refused: this changes what was approved for a queued task. Return it to draft first.",
        draft_head="Return task to draft",
        draft_effect="the task leaves the queue and its approval is withdrawn: a worker will not take it. Its id, instructions, schedule and history are kept. It needs a new approval to be queued again. Nothing is run.",
        draft_refused="refused: only a queued task can be returned to draft.",
        edit_closed="refused: a task that is {status} is not edited; prepare a revision instead.",
        lines_changed="{n} lines changed",
        schedule_head="Schedule task", days="Days", time="Time", zone="Time zone", repeats="Repeats",
        yes="yes", no="no", every_day="every day", min_gap="minimum gap {h} h", max_runs="at most {n} runs",
        next_runs="Next runs", schedule_effect="stores the schedule. The task is not queued; approving it is a separate step.",
        schedule_planned="the task returns to draft and must be approved again.",
        approve_head="Approve task for execution", status="Status", declared="Declared effect", scope="Scope", object="Object",
        approve_effect="authorizes the task to run: it is queued with the instructions stored now and a worker will execute them. Editing it afterwards invalidates this approval.",
        approve_recurring="It then repeats on its schedule.",
        approve_refused="refused: only a draft or planned task can be approved.",
        cancel_head_now="Cancel task", cancel_head_req="Request task stop",
        cancel_now="the queued task is cancelled immediately and will not run.",
        cancel_req="this only records a request to stop. The task stays active until its worker stops it; work already done is not undone.",
        cancel_refused="refused: only a queued or active task can be cancelled.",
        requeue_head="Requeue task",
        requeue_effect="the task goes back to the queue and runs again with the same instructions; the recorded execution error is dropped.",
        requeue_refused="refused: only a task in error can be requeued.",
        send_head="Send Telegram message", send_effect="sends the message below outside this machine; it cannot be recalled.",
        parse_mode="interpreted as {mode}",
        generic_head="Approve action", operation="Operation",
        missing="refused: the task was not found.",
        changed="This task changed after it was read, so this approval will be refused.",
        unreadable="The task could not be read, so the effect below could not be verified.",
    ),
    "es": dict(
        approve_title="Aprobar esta acción",
        footer="Un solo uso, válida {seconds} segundos. Si falla o es incierta, hace falta una nueva aprobación.",
        task="Tarea", reason="Motivo", effect="Efecto", to="Destinatario", message="Mensaje", format="Formato",
        warn="Aviso", none="(ninguno)", unlimited="sin límite",
        archive_head="Archivar tarea",
        archive_queued="la tarea se cancela primero (no se ejecutará) y después se archiva; conserva su historial.",
        archive_queued_rec="la repetición se detiene (la tarea no volverá a ejecutarse) y después se archiva; conserva su historial.",
        archive_plain="la tarea queda archivada y conserva su historial.",
        archive_active="se rechaza mientras la tarea se ejecuta. Cancélala primero y archívala cuando se haya detenido.",
        archive_done="se rechaza: la tarea ya está archivada.",
        archive_guard="También se rechaza si otra tarea depende de ella o si alguna subtarea sigue en curso.",
        create_head="Crear tarea en borrador", revise_head="Crear revisión en borrador",
        revision_of="Revisa", create_effect="guarda un borrador. No se encola ni se ejecuta nada; aprobarlo es un paso aparte.",
        revise_effect="guarda una copia en borrador de esa tarea con su configuración y programación; la original no cambia. No se encola ni se ejecuta nada.",
        instructions="Instrucciones", chars="{n} caracteres en total",
        update_head="Editar tarea", changes="Cambios", no_diff="sin diferencias con la tarea guardada",
        update_planned="la tarea vuelve a borrador y debe aprobarse de nuevo. No se encola ni se ejecuta nada.",
        update_draft="se reescribe el borrador guardado. No se encola ni se ejecuta nada.",
        edit_active="se rechaza: una tarea en ejecución conserva las instrucciones con las que empezó.",
        update_queued_rename="solo cambia el título. La tarea conserva su sitio en la cola y su aprobación; no se ejecuta nada.",
        update_queued_material="se rechaza: esto cambia lo aprobado de una tarea en cola. Devuélvela antes a borrador.",
        draft_head="Devolver tarea a borrador",
        draft_effect="la tarea sale de la cola y se retira su aprobación: ningún worker la tomará. Se conservan su id, instrucciones, programación e historial. Necesita una nueva aprobación para volver a la cola. No se ejecuta nada.",
        draft_refused="se rechaza: solo se devuelve a borrador una tarea en cola.",
        edit_closed="se rechaza: una tarea en estado {status} no se edita; prepara una revisión.",
        lines_changed="{n} líneas cambiadas",
        schedule_head="Programar tarea", days="Días", time="Hora", zone="Zona horaria", repeats="Repite",
        yes="sí", no="no", every_day="todos los días", min_gap="separación mínima {h} h", max_runs="como máximo {n} ejecuciones",
        next_runs="Próximas ejecuciones", schedule_effect="guarda la programación. La tarea no se encola; aprobarla es un paso aparte.",
        schedule_planned="la tarea vuelve a borrador y debe aprobarse de nuevo.",
        approve_head="Aprobar tarea para ejecución", status="Estado", declared="Efecto declarado", scope="Alcance", object="Objeto",
        approve_effect="autoriza su ejecución: se encola con las instrucciones guardadas ahora y un worker las ejecutará. Editarla después invalida esta aprobación.",
        approve_recurring="Después se repite según su programación.",
        approve_refused="se rechaza: solo se aprueba una tarea en borrador o planificada.",
        cancel_head_now="Cancelar tarea", cancel_head_req="Solicitar la parada de la tarea",
        cancel_now="la tarea en cola se cancela de inmediato y no se ejecutará.",
        cancel_req="solo registra una solicitud de parada. La tarea sigue activa hasta que su worker la detenga; lo ya hecho no se deshace.",
        cancel_refused="se rechaza: solo se cancela una tarea en cola o activa.",
        requeue_head="Reencolar tarea",
        requeue_effect="la tarea vuelve a la cola y se ejecuta de nuevo con las mismas instrucciones; se elimina el error de ejecución registrado.",
        requeue_refused="se rechaza: solo se reencola una tarea en error.",
        send_head="Enviar mensaje de Telegram", send_effect="envía el mensaje de abajo fuera de esta máquina; no se puede retirar.",
        parse_mode="interpretado como {mode}",
        generic_head="Aprobar acción", operation="Operación",
        missing="se rechaza: no se encontró la tarea.",
        changed="La tarea cambió después de leerla, así que esta aprobación será rechazada.",
        unreadable="No se pudo leer la tarea, así que no se pudo verificar el efecto de abajo.",
    ),
}


# ---------------------------------------------------------------------------
# language and text hygiene
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _tokens():
    """The console's language table, loaded once. solar-app reads it the same way."""
    spec = importlib.util.spec_from_file_location("console_language", _LANGUAGE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def language() -> str:
    """`es` only when `.solar/settings.json` says Spanish; English otherwise."""
    try:
        data = json.loads((workspace() / ".solar" / "settings.json").read_text(encoding="utf-8"))
        return _tokens().effective_language(data.get("language") if isinstance(data, dict) else None)
    except Exception:  # noqa: BLE001 - a missing setting means English, never a failed prompt
        return "en"


def _escape(match) -> str:
    code = ord(match.group())
    return f"\\x{code:02x}" if code < 256 else f"\\u{code:04x}"


def _line(value, limit: int = 0) -> str:
    """One visible line: control and direction characters shown, whitespace collapsed."""
    text = " ".join(_INVISIBLE.sub(_escape, str(value if value is not None else "")).split())
    return text[:limit].rstrip() + "…" if limit and len(text) > limit else text


def _verbatim(value) -> str:
    """Exact text, line breaks kept; only characters that hide or reorder are made visible."""
    return _INVISIBLE.sub(_escape, str(value)).replace("\r\n", "\n")


def _quote(text: str) -> str:
    return "\n".join("  " + row for row in text.split("\n"))


# ---------------------------------------------------------------------------
# stored task facts
# ---------------------------------------------------------------------------

def _facts(task_id: str) -> dict | None:
    """The task as stored now, for the summary only. None when it cannot be read."""
    import solar_state

    try:
        with solar_state.read_session() as store:
            task = store.task_get(task_id)
        if task is None:
            return dict(missing=True)
        values = task_views._values(task)
        title = task["title"] or ""
        heading = f"\n# {title}\n"
        body = task["body"] or ""
        instructions = body[len(heading):] if body.startswith(heading) else body
        return dict(title=title, status=task["status"], row_version=task["row_version"],
                    values=values, priority=task["priority"], object=task["object"] or "",
                    scope=task["scope"] or "", effect=task["effect"] or "",
                    recurring=str(values.get("recurring") or "").lower() == "true",
                    instructions=instructions.strip("\n").rstrip(), schedule=task_views._schedule(values))
    except Exception:  # noqa: BLE001 - the prompt must still appear, flagged as unverified
        return None


def _stored(arguments: dict):
    """(facts, notes) with the notes that apply to every task operation."""
    facts = _facts(arguments["task_id"])
    notes = []
    if facts is None:
        notes.append("unreadable")
    elif facts.get("missing"):
        notes.append("missing")
    elif "expected_row_version" in arguments and facts["row_version"] != arguments["expected_row_version"]:
        notes.append("changed")
    return facts, notes


def _head(copy: dict, title: str, rows: list, notes: list, extra: list = ()) -> str:
    out = [title]
    out += [f"{label}: {value}" for label, value in rows if value not in (None, "")]
    out += list(extra)
    out += [f"{copy['warn']}: {copy[note]}" for note in notes]
    return "\n".join(out)


def _excerpt(copy: dict, text: str) -> str:
    """One displayed line of at most `_EXCERPT` characters, escapes counted; then the original length."""
    flat = _line(text)
    if len(flat) <= _EXCERPT:
        return flat
    cut = re.sub(r"\\(?:x[0-9a-f]?|u[0-9a-f]{0,3})?$", "", flat[:_EXCERPT])   # never end on half an escape
    return cut.rstrip() + "… (" + copy["chars"].format(n=len(text)) + ")"


def _exact(value, limit: int = 0, start: int = 0) -> str:
    """A single-line value as stored: spaces kept, hidden characters and line breaks made visible."""
    text = _INVISIBLE.sub(_escape, str(value if value is not None else "")).replace("\n", "\\n")
    cut = text[start:start + limit] if limit else text[start:]
    return ("…" if start else "") + cut + ("…" if limit and len(text) > start + limit else "")


def _pair(old, new) -> tuple:
    """Old and new text cut to the same window, starting just before the first difference."""
    old, new = str(old if old is not None else ""), str(new)
    first = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
    start = max(0, first - 20) if max(len(old), len(new)) > _VALUE else 0
    return _exact(old, _VALUE, start), _exact(new, _VALUE, start)


def _repeats(copy: dict, recurring: bool, interval, cap) -> str:
    """'yes (minimum gap …; at most N runs)' or 'no', from the values that will be stored."""
    if not recurring:
        return copy["no"]
    limits = []
    if str(interval or "").isdigit() and int(interval):
        limits.append(copy["min_gap"].format(h=round(int(interval) / 3600, 1)))
    limits.append(copy["max_runs"].format(n=cap) if str(cap or "0") not in ("", "0") else copy["unlimited"])
    return copy["yes"] + " (" + "; ".join(limits) + ")"


def _days(copy: dict, weekdays) -> str:
    names = _DAYS[copy["lang"]]
    return ", ".join(names[d - 1] for d in sorted(weekdays)) if weekdays else copy["every_day"]


# ---------------------------------------------------------------------------
# one renderer per operation
# ---------------------------------------------------------------------------

def _archive(copy, args):
    facts, notes = _stored(args)
    if not facts or facts.get("missing"):
        return _head(copy, copy["archive_head"], [(copy["reason"], _line(args["reason"]))], notes)
    status = facts["status"]
    if status == "active":
        effect = copy["archive_active"]
    elif status == "archived":
        effect = copy["archive_done"]
    elif status == "queued":
        effect = copy["archive_queued_rec" if facts["recurring"] else "archive_queued"]
    else:
        effect = copy["archive_plain"]
    rows = [(copy["task"], _line(facts["title"], _VALUE)), (copy["reason"], _line(args["reason"])),
            (copy["effect"], effect)]
    return _head(copy, copy["archive_head"], rows, notes, [copy["archive_guard"]])


def _create(copy, args):
    rows = [(copy["task"], _line(args["title"], _VALUE))]
    notes = []
    source = args.get("revises_task_id")
    if source:
        facts = _facts(source)
        if facts and not facts.get("missing"):
            rows.append((copy["revision_of"], _line(facts["title"], _VALUE)))
        else:
            notes.append("missing" if facts else "unreadable")
    for key in ("object", "scope", "effect", "priority", "provider", "planet", "agent", "responsibility"):
        if key in args:
            rows.append((key, _line(args[key], _VALUE)))
    rows.append((copy["instructions"], _excerpt(copy, args["instructions"])))
    rows.append((copy["effect"], copy["revise_effect" if source else "create_effect"]))
    return _head(copy, copy["revise_head" if source else "create_head"], rows, notes)


# Work bounds for the edit diff. It runs before the confirmation timer starts and while the server
# answers nothing else, so its cost must not depend on how repetitive the instructions are.
_DIFF_BUDGET = 10_000   # line pairs (after trimming) that may go through difflib; beyond: one block
_MATCH_ROWS = 128       # lines per side considered when pairing a removal with its addition
_MATCH_CHARS = 300      # characters compared at each end of a line


def _similar(a: str, b: str) -> float:
    """Common prefix plus common suffix as a share of the longer line; -1 when too little is shared.

    Only the first and last `_MATCH_CHARS` characters are compared, so the cost per pair is
    bounded whatever the line length. A long line needs 100 shared characters, a short one half
    (never fewer than 4).
    """
    longest = max(len(a), len(b), 1)
    head = len(os.path.commonprefix([a[:_MATCH_CHARS], b[:_MATCH_CHARS]]))
    room = max(min(len(a), len(b)) - head, 0)
    tail = min(len(os.path.commonprefix([a[-_MATCH_CHARS:][::-1], b[-_MATCH_CHARS:][::-1]])), room)
    return (head + tail) / longest if head + tail >= max(4, min(longest / 2, 100)) else -1.0


def _match(removed: list, added: list) -> dict:
    """removed index -> (added index, similarity) of the most similar line (one to one).

    A replaced block can hold unrelated inserted lines next to the edited one, so position alone
    mispairs them. The first `_MATCH_ROWS` lines of each side are scored (at most 128 x 128 cheap
    comparisons per block, and a block is itself bounded by `_DIFF_BUDGET`); an edited line
    further down than that is shown unpaired.
    """
    scored = sorted(((_similar(a, b), -k, -j) for k, a in enumerate(removed[:_MATCH_ROWS])
                     for j, b in enumerate(added[:_MATCH_ROWS])), reverse=True)
    match, taken = {}, set()
    for score, k, j in scored:
        if score >= 0 and -k not in match and -j not in taken:
            match[-k] = (-j, score)
            taken.add(-j)
    return match


def _blocks(old_rows: list, new_rows: list) -> list:
    """(removed, added) blocks of changed lines, in bounded time.

    Common leading and trailing lines are trimmed in linear time first, which settles the usual
    edit (a few lines changed in a long text) however repetitive the text is. What remains goes
    through difflib only while its size is small; otherwise it is one block.
    """
    head = 0
    while head < min(len(old_rows), len(new_rows)) and old_rows[head] == new_rows[head]:
        head += 1
    tail = 0
    while tail < min(len(old_rows), len(new_rows)) - head and old_rows[-1 - tail] == new_rows[-1 - tail]:
        tail += 1
    old_mid, new_mid = old_rows[head:len(old_rows) - tail], new_rows[head:len(new_rows) - tail]
    if not old_mid and not new_mid:
        return []
    if len(old_mid) * len(new_mid) > _DIFF_BUDGET:
        return [(old_mid, new_mid)]
    ops = difflib.SequenceMatcher(None, old_mid, new_mid, autojunk=False).get_opcodes()
    return [(old_mid[a1:a2], new_mid[b1:b2]) for tag, a1, a2, b1, b2 in ops if tag != "equal"]


def _diff_lines(copy, old: str, new: str) -> list:
    """Changed lines, the quota shared between removals and additions so neither side vanishes.

    Within each changed block a removal is paired with the most similar addition (see `_match`),
    so an inserted line does not shift the pairs, and edited lines are listed before pure
    insertions and deletions; a pair is cut to one window (see `_pair`), so a
    long line whose change lies far to the right shows the difference on both sides.
    """
    minus, plus = [], []          # (line, partner or None, similarity)
    for removed, added in _blocks(old.split("\n"), new.split("\n")):
        match = _match(removed, added)
        minus += [(row, added[match[k][0]] if k in match else None, match[k][1] if k in match else 0)
                  for k, row in enumerate(removed)]
        back = {j: (k, score) for k, (j, score) in match.items()}
        plus += [(row, removed[back[j][0]] if j in back else None, back[j][1] if j in back else 0)
                 for j, row in enumerate(added)]
    # Edited lines (those with a partner, the most similar first) come before pure insertions and
    # deletions.
    minus.sort(key=lambda entry: (entry[1] is None, -entry[2]))
    plus.sort(key=lambda entry: (entry[1] is None, -entry[2]))
    keep_minus = min(len(minus), max(_DIFF_LINES // 2, _DIFF_LINES - len(plus)))
    keep_plus = min(len(plus), _DIFF_LINES - keep_minus)
    out = []
    for row, partner, _score in minus[:keep_minus]:
        out.append("− " + (_pair(row, partner)[0] if partner is not None else _exact(row, _VALUE)))
    for row, partner, _score in plus[:keep_plus]:
        out.append("+ " + (_pair(partner, row)[1] if partner is not None else _exact(row, _VALUE)))
    if len(minus) + len(plus) > keep_minus + keep_plus:
        out.append("… " + copy["lines_changed"].format(n=len(minus) + len(plus)))
    return out


def _update(copy, args):
    facts, notes = _stored(args)
    if not facts or facts.get("missing"):
        return _head(copy, copy["update_head"], [(copy["task"], None)], notes)
    lines = []
    material = False
    for key in ("title", "object", "scope", "effect", "priority", "provider", "planet", "agent", "responsibility"):
        if key not in args:
            continue
        old = facts[key] if key in ("object", "scope", "effect", "priority") else (
            facts["title"] if key == "title" else facts["values"].get(key))
        if (old or "") != args[key]:
            material = material or key != "title"
            before, after = _pair(old, args[key])
            lines.append(f"{key}: {before or copy['none']} → {after}")
    if "instructions" in args and args["instructions"].rstrip() != facts["instructions"]:
        material = True
        lines.append(copy["instructions"] + ":")
        lines += ["  " + row for row in _diff_lines(copy, facts["instructions"], args["instructions"].rstrip())]
    status = facts["status"]
    if status == "active":
        effect = copy["edit_active"]
    elif status == "queued":
        effect = copy["update_queued_material" if material else "update_queued_rename"]
    elif status not in ("draft", "planned"):
        effect = copy["edit_closed"].format(status=status)
    else:
        effect = copy["update_planned" if status == "planned" else "update_draft"]
    rows = [(copy["task"], _line(facts["title"], _VALUE))]
    extra = [copy["changes"] + ":"] + ["  " + row if not row.startswith(" ") else row for row in lines] \
        if lines else [copy["changes"] + ": " + copy["no_diff"]]
    extra.append(f"{copy['effect']}: {effect}")
    return _head(copy, copy["update_head"], rows, notes, extra)


def _merged_schedule(stored: dict, args: dict):
    """(merged fields, plan): the same merge `_do_task_schedule` applies; plan_schedule may raise."""
    def old(key):
        return stored["schedule"].get(key)
    merged = dict(
        time=args.get("scheduled_time", old("time")),
        zone=args.get("scheduled_timezone", old("timezone")),
        recurring=args.get("recurring", bool(old("recurring"))),
        weekdays=args["scheduled_weekdays"] if "scheduled_weekdays" in args else list(old("weekdays") or []))
    interval = args.get("recurring_min_interval")
    if interval is None and str(old("recurring_min_interval") or "").isdigit():
        interval = int(old("recurring_min_interval"))
    plan = task_views.plan_schedule(time=merged["time"], weekdays=merged["weekdays"], zone=merged["zone"],
                                    recurring=merged["recurring"], min_interval=interval)
    return merged, plan


def _schedule(copy, args):
    facts, notes = _stored(args)
    if not facts or facts.get("missing"):
        return _head(copy, copy["schedule_head"], [], notes)
    rows = [(copy["task"], _line(facts["title"], _VALUE))]
    extra = []
    try:
        merged, plan = _merged_schedule(facts, args)
        time = merged["time"] if merged["time"] not in (None, "now") else None
        if time:
            rows.append((copy["days"], _days(copy, merged["weekdays"])))
            rows.append((copy["time"], time))
            rows.append((copy["zone"], merged["zone"]))
        cap = args.get("recurring_max_runs", facts["values"].get("recurring_max_runs"))
        rows.append((copy["repeats"], _repeats(copy, merged["recurring"], plan["recurring_min_interval"], cap)))
        names = _DAYS[copy["lang"]]
        if plan["next_occurrences"]:
            rows.append((copy["next_runs"], "; ".join(
                f"{names[o['weekday'] - 1]} {o['local'][:16].replace('T', ' ')}" for o in plan["next_occurrences"][:2])))
        extra += [f"{copy['warn']}: {note}" for note in plan["notes"]]
    except OperationError as exc:
        extra.append(f"{copy['warn']}: {exc}")
    status = facts["status"]
    if status in ("draft", "planned"):
        effect = copy["schedule_effect"] + (" " + copy["schedule_planned"] if status == "planned" else "")
    elif status == "queued":
        effect = copy["update_queued_material"]
    else:
        effect = copy["edit_active"] if status == "active" else copy["edit_closed"].format(status=status)
    rows.append((copy["effect"], effect))
    return _head(copy, copy["schedule_head"], rows, notes, extra)


def _context_rows(copy: dict, facts: dict) -> list:
    """What a run would do, as stored: task, declared object/scope/effect, instructions, schedule, limits."""
    schedule = facts["schedule"]
    rows = [(copy["task"], _line(facts["title"], _VALUE)),
            (copy["object"], _line(facts["object"], _VALUE)), (copy["scope"], _line(facts["scope"], _VALUE)),
            (copy["declared"], _line(facts["effect"], _VALUE)),
            (copy["instructions"], _excerpt(copy, facts["instructions"]))]
    if schedule.get("time") and schedule["time"] != "now":
        rows.append((copy["time"], f"{_days(copy, schedule['weekdays'])} {schedule['time']} "
                                   f"({schedule.get('timezone') or '—'})"))
    if facts["recurring"]:
        rows.append((copy["repeats"], _repeats(copy, True, schedule.get("recurring_min_interval"),
                                               schedule.get("recurring_max_runs"))))
    return rows


def _approve(copy, args):
    facts, notes = _stored(args)
    if not facts or facts.get("missing"):
        return _head(copy, copy["approve_head"], [], notes)
    effect = (copy["approve_effect"] + (" " + copy["approve_recurring"] if facts["recurring"] else "")) \
        if facts["status"] in ("draft", "planned") else copy["approve_refused"]
    return _head(copy, copy["approve_head"], _context_rows(copy, facts) + [(copy["effect"], effect)], notes)


def _cancel(copy, args):
    facts, notes = _stored(args)
    if not facts or facts.get("missing"):
        return _head(copy, copy["cancel_head_now"], [], notes)
    status = facts["status"]
    head = copy["cancel_head_req"] if status == "active" else copy["cancel_head_now"]
    effect = {"queued": copy["cancel_now"], "active": copy["cancel_req"]}.get(status, copy["cancel_refused"])
    return _head(copy, head, [(copy["task"], _line(facts["title"], _VALUE)), (copy["effect"], effect)], notes)


def _requeue(copy, args):
    facts, notes = _stored(args)
    if not facts or facts.get("missing"):
        return _head(copy, copy["requeue_head"], [], notes)
    effect = copy["requeue_effect"] if facts["status"] == "error" else copy["requeue_refused"]
    return _head(copy, copy["requeue_head"], _context_rows(copy, facts) + [(copy["effect"], effect)], notes)


def _return_to_draft(copy, args):
    facts, notes = _stored(args)
    if not facts or facts.get("missing"):
        return _head(copy, copy["draft_head"], [], notes)
    effect = copy["draft_effect"] if facts["status"] == "queued" else copy["draft_refused"]
    return _head(copy, copy["draft_head"], _context_rows(copy, facts) + [(copy["effect"], effect)], notes)


def _telegram(copy, args):
    rows = [(copy["to"], _line(args["chat_id"]))]
    if args.get("parse_mode"):
        rows.append((copy["format"], copy["parse_mode"].format(mode=args["parse_mode"])))
    rows.append((copy["effect"], copy["send_effect"]))
    return _head(copy, copy["send_head"], rows, [], [copy["message"] + ":", _quote(_verbatim(args["text"]))])


# Defence in depth: a renderer that fails (or a future operation without one) must not print
# identifiers or versions; today only action.run and forced failures reach the fallback.
_INTERNAL = {"task_id", "expected_row_version", "approval_id", "revises_task_id"}


def _generic(copy, name, args):
    """Fallback: the operation name and the readable fields; identifiers and versions stay out."""
    rows = [(copy["operation"], name)] + [
        (key, _line(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value, _VALUE))
        for key, value in args.items() if key not in _INTERNAL]
    return _head(copy, copy["generic_head"], rows, [])


RENDERERS = {"task.archive": _archive, "task.create": _create, "task.update": _update,
             "task.schedule": _schedule, "task.approve": _approve, "task.cancel": _cancel,
             "task.requeue": _requeue, "task.return_to_draft": _return_to_draft,
             "telegram.send": _telegram}


def render(name: str, arguments: dict, *, seconds: int, lang: str | None = None) -> tuple[str, str]:
    """(message, localized checkbox title) for one validated operation."""
    lang = lang or language()
    copy = dict(COPY[lang], lang=lang)
    try:
        body = RENDERERS[name](copy, arguments) if name in RENDERERS else _generic(copy, name, arguments)
    except Exception:  # noqa: BLE001 - never block the prompt; fall back to the plain argument list
        body = _generic(copy, name, arguments)
    return body + "\n\n" + copy["footer"].format(seconds=seconds), copy["approve_title"]
