#!/usr/bin/env python3
"""Solar Interface interactive REPL — Claude-style TUI with / and @ completion."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import threading
import time
import urllib.error
import urllib.request

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
SOLAR_DIR = pathlib.Path.home() / ".solar"
HISTORY_FILE = SOLAR_DIR / "history"


# ── Config ────────────────────────────────────────────────────────────────────

def _load_providers() -> list[str]:
    env_file = REPO_ROOT / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("SOLAR_ROUTER_PROVIDER_PRIORITY="):
                value = line.split("=", 1)[1].strip()
                providers = [p.strip() for p in value.split(",") if p.strip()]
                if providers:
                    return providers
    except (OSError, ValueError):
        pass
    return ["codex", "claude", "gemini"]


BUILTIN_COMMANDS = {
    "/resume": ("resume", None,   "Show past conversations and resume one"),
    "/client": ("client", None,   "Show or switch AI client: /client [provider]"),
    "/thread": ("info",   None,   "Show current thread ID"),
    "/clear":  ("clear",  None,   "Clear the screen"),
    "/exit":   ("exit",   None,   "Exit chat"),
    "/quit":   ("quit",   None,   "Exit chat"),
    "/help":   ("help",   None,   "Show this help"),
}

STYLE = Style.from_dict({
    "completion-menu.completion":              "bg:#1e1e2e #cdd6f4",
    "completion-menu.completion.current":      "bg:#313244 #cba6f7 bold",
    "completion-menu.meta.completion":         "bg:#1e1e2e #6c7086",
    "completion-menu.meta.completion.current": "bg:#313244 #a6adc8",
    "scrollbar.background": "bg:#313244",
    "scrollbar.button":     "bg:#cba6f7",
})

PROV_COLORS = {
    "claude": "ansicyan", "gemini": "ansiblue",
    "codex": "ansigreen", "agent": "ansimagenta",
}

PROV_ANSI = {
    "claude": "\033[36m",
    "gemini": "\033[34m",
    "codex": "\033[32m",
    "agent": "\033[35m",
}

ORPHANED_CSI_U_RE = re.compile(r"(?:\x1b\[|\[)\d+(?:;\d+)*u")


def _sanitize_slash_text(text: str) -> str:
    stripped = text.lstrip()
    if not stripped.startswith("/"):
        return text
    return ORPHANED_CSI_U_RE.sub("", text)


# ── Resource discovery ────────────────────────────────────────────────────────

def _first_line(path: pathlib.Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                return line[:80]
    except (OSError, PermissionError):
        pass
    return ""


def _load_slash_items() -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()

    def add(name: str, kind: str, source: str, desc: str = "") -> None:
        key = f"{name}|{kind}"
        if key not in seen:
            seen.add(key)
            items.append({"name": name, "kind": kind, "source": source, "description": desc})

    core_skills = REPO_ROOT / "core" / "skills"
    if core_skills.exists():
        for d in sorted(core_skills.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                add(d.name, "skill", "core", _first_line(d / "SKILL.md"))

    planets = REPO_ROOT / "planets"
    if planets.exists():
        for planet in sorted(planets.iterdir()):
            if not planet.is_dir() or planet.name.startswith("."):
                continue
            for subdir, kind in (("agents", "agent"), ("commands", "command"), ("skills", "skill")):
                sdir = planet / subdir
                if sdir.exists():
                    for f in sorted(sdir.glob("*.md")):
                        add(f.stem, kind, planet.name, _first_line(f))

    return items


def _format_slash_list(items: list[dict]) -> str:
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item["kind"], []).append(item)
    lines: list[str] = []
    for kind, label in (("agent", "Agents"), ("command", "Commands"), ("skill", "Skills")):
        group = groups.get(kind, [])
        if not group:
            continue
        lines.append(f"\n  {label}:")
        for item in group:
            desc = f"  {item['description']}" if item.get("description") else ""
            lines.append(f"    /{item['name']:<34} [{item['source']}]{desc}")
    return "\n".join(lines)


def _load_file_items() -> list[tuple[str, bool, float]]:
    items: list[tuple[str, bool, float]] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        rel_root = pathlib.Path(root).relative_to(REPO_ROOT)

        for dirname in dirs:
            entry = pathlib.Path(root) / dirname
            rel = rel_root / dirname if str(rel_root) != "." else pathlib.Path(dirname)
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                mtime = 0.0
            items.append((str(rel) + "/", True, mtime))

        for filename in sorted(files):
            if filename.startswith("."):
                continue
            entry = pathlib.Path(root) / filename
            rel = rel_root / filename if str(rel_root) != "." else pathlib.Path(filename)
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                mtime = 0.0
            items.append((str(rel), False, mtime))
    return items


# ── Completer ─────────────────────────────────────────────────────────────────

class SolarCompleter(Completer):
    def __init__(self, slash_items: list[dict], providers: list[str], file_items: list[tuple[str, bool, float]]) -> None:
        self._slash = slash_items
        self._providers = providers
        self._files = file_items

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        parts = text.split()
        current_token = parts[-1] if parts else text.strip()

        if current_token.startswith("/"):
            word = current_token

            # Built-ins
            for cmd, (_, _, desc) in BUILTIN_COMMANDS.items():
                if cmd.startswith(word):
                    yield Completion(
                        cmd, start_position=-len(word),
                        display=HTML(f"<b>{cmd}</b>"),
                        display_meta=HTML(f"<ansiyellow>built-in</ansiyellow>  {desc}"),
                    )

            # /client <provider> sub-completions
            stripped = text.lstrip()
            if stripped.startswith("/client"):
                prov_prefix = stripped[len("/client"):].lstrip()
                for p in self._providers:
                    if p.startswith(prov_prefix):
                        yield Completion(
                            f"/client {p}", start_position=-len(stripped),
                            display=HTML(f"<b>/client</b> {p}"),
                            display_meta=HTML("<ansicyan>provider</ansicyan>"),
                        )

            # Repo resources
            prefix = word[1:]
            for item in self._slash:
                if item["name"].startswith(prefix):
                    yield Completion(
                        "/" + item["name"], start_position=-len(word),
                        display=HTML(f"<b>/{item['name']}</b>"),
                        display_meta=HTML(
                            f"<ansigreen>{item['kind']}</ansigreen>  {item['source']}"
                        ),
                    )
            return

        # @file completion
        at_idx = text.rfind("@")
        if at_idx >= 0:
            prefix = text[at_idx + 1:]
            for rel, is_dir, _mtime in self._file_completions(prefix):
                icon = "📁 " if is_dir else "📄 "
                label, meta = self._format_file_display(rel, is_dir)
                yield Completion(
                    rel, start_position=-len(prefix),
                    display=HTML(f"{icon}<b>{label}</b>"),
                    display_meta=HTML(f"<ansigray>{meta}</ansigray>"),
                )

    def _file_completions(self, prefix: str):
        query = prefix.strip().lower()
        if not query:
            return sorted(self._files, key=lambda item: item[2], reverse=True)[:50]

        path_matches: list[tuple[str, bool, float]] = []
        name_matches: list[tuple[str, bool, float]] = []
        fuzzy_matches: list[tuple[str, bool, float]] = []

        for rel, is_dir, mtime in self._files:
            rel_norm = rel.lower()
            base = rel.rstrip("/").split("/")[-1].lower()

            if rel_norm.startswith(query):
                path_matches.append((rel, is_dir, mtime))
            elif base.startswith(query):
                name_matches.append((rel, is_dir, mtime))
            elif query in base or query in rel_norm:
                fuzzy_matches.append((rel, is_dir, mtime))

        path_matches.sort(key=lambda item: item[2], reverse=True)
        name_matches.sort(key=lambda item: item[2], reverse=True)
        fuzzy_matches.sort(key=lambda item: item[2], reverse=True)

        seen: set[str] = set()
        ordered: list[tuple[str, bool, float]] = []
        for group in (path_matches, name_matches, fuzzy_matches):
            for rel, is_dir, mtime in group:
                if rel in seen:
                    continue
                seen.add(rel)
                ordered.append((rel, is_dir, mtime))
                if len(ordered) >= 50:
                    return ordered
        return ordered

    def _format_file_display(self, rel: str, is_dir: bool) -> tuple[str, str]:
        clean_rel = rel[:-1] if is_dir and rel.endswith("/") else rel
        base = clean_rel.split("/")[-1] if clean_rel else rel
        parent = clean_rel.rsplit("/", 1)[0] if "/" in clean_rel else ""

        if not parent:
            meta = "./"
        elif len(parent) > 44:
            meta = "…" + parent[-43:]
        else:
            meta = parent

        if is_dir:
            return base + "/", meta
        return base, meta


# ── API ───────────────────────────────────────────────────────────────────────

def api_get(base_url: str, path: str) -> dict:
    url = base_url + path
    try:
        with urllib.request.urlopen(url) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": exc.read().decode("utf-8")}


def api_post(base_url: str, path: str, payload: dict) -> dict:
    url = base_url + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": exc.read().decode("utf-8")}


def get_last_provider_for_thread(base_url: str, thread_id: str) -> str | None:
    data = api_get(base_url, f"/threads/{thread_id}/runs")
    runs = data.get("runs", [])
    if not isinstance(runs, list):
        return None
    for run in reversed(runs):
        if not isinstance(run, dict):
            continue
        provider = run.get("provider_used")
        if isinstance(provider, str) and provider.strip():
            return provider.strip()
    return None


def send_and_print(base_url: str, state: dict, text: str) -> None:
    def _fmt_tokens(value: object) -> str | None:
        if not isinstance(value, int):
            return None
        if value < 1000:
            return str(value)
        if value >= 100000:
            return f"{value // 1000}k"
        return f"{value / 1000:.1f}k"

    obj: dict = {"mode": "ask", "text": text, "provider": state["provider"]}

    url = base_url + f"/threads/{state['thread_id']}/stream"
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )

    provider_used = state["provider"]
    usage: dict | None = None
    started = False
    saw_non_whitespace = False
    spinner_stop = threading.Event()
    spinner_lock = threading.Lock()
    spinner_frames = [".", "..", "..."]
    spinner_provider = provider_used
    spinner_color = "\033[2m"

    def _spinner() -> None:
        idx = 0
        while not spinner_stop.is_set():
            with spinner_lock:
                frame = spinner_frames[idx % len(spinner_frames)]
                sys.stdout.write(
                    f"\r{spinner_color}[{spinner_provider}]\033[0m {frame}   "
                )
                sys.stdout.flush()
            idx += 1
            time.sleep(0.35)

    spinner_thread = threading.Thread(target=_spinner, daemon=True)
    spinner_thread.start()

    try:
        with urllib.request.urlopen(req) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\n")
                if not line.startswith("data: "):
                    continue
                payload_str = line[6:]
                try:
                    event = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "chunk":
                    chunk = event.get("text", "")
                    if chunk:
                        if not started:
                            spinner_stop.set()
                            spinner_thread.join(timeout=0.5)
                            with spinner_lock:
                                sys.stdout.write("\r\033[K")
                                sys.stdout.flush()
                            print(f"{spinner_color}[{provider_used}]\033[0m")
                            started = True
                        if chunk.strip():
                            saw_non_whitespace = True
                        sys.stdout.write(chunk)
                        sys.stdout.flush()
                elif event.get("type") == "done":
                    provider_used = event.get("provider") or provider_used
                    event_usage = event.get("usage")
                    if isinstance(event_usage, dict):
                        usage = event_usage
                    error = event.get("error")
                    if not started and error:
                        spinner_stop.set()
                        spinner_thread.join(timeout=0.5)
                        with spinner_lock:
                            sys.stdout.write("\r\033[K")
                            sys.stdout.flush()
                        print(f"\n\033[31mError: {error}\033[0m")
    except KeyboardInterrupt:
        spinner_stop.set()
        spinner_thread.join(timeout=0.5)
        with spinner_lock:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        print("\n\033[33mEjecucion cancelada por usuario.\033[0m\n")
        return
    except urllib.error.URLError as exc:
        spinner_stop.set()
        spinner_thread.join(timeout=0.5)
        with spinner_lock:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
        print(f"\n\033[31mConnection error: {exc}\033[0m")
        return

    spinner_stop.set()
    spinner_thread.join(timeout=0.5)
    if not started:
        with spinner_lock:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    provider_label = provider_used or "unknown"
    if started and saw_non_whitespace:
        usage_suffix = ""
        if isinstance(usage, dict):
            in_t = _fmt_tokens(usage.get("input_tokens"))
            out_t = _fmt_tokens(usage.get("output_tokens"))
            cached_t = _fmt_tokens(usage.get("cached_input_tokens"))
            parts: list[str] = []
            if in_t:
                parts.append(f"in {in_t}")
            if cached_t:
                parts.append(f"cached {cached_t}")
            if out_t:
                parts.append(f"out {out_t}")
            if parts:
                usage_suffix = " · " + ", ".join(parts)
        if usage_suffix:
            print(f"\n\033[2m· {usage_suffix.lstrip(' ·')}\033[0m\n")
        else:
            print("\n")
    else:
        provider_color = PROV_ANSI.get(provider_label, "\033[33m")
        print(f"\n{provider_color}[{provider_label}]\033[0m\n")


# ── /resume ───────────────────────────────────────────────────────────────────

def cmd_resume(base_url: str, state: dict, session: PromptSession) -> None:
    data = api_get(base_url, "/threads")
    threads = data.get("threads", [])

    if not threads:
        print("\n  No conversations yet.\n")
        return

    print("\n  Recent conversations:\n")
    for i, t in enumerate(threads[:20], 1):
        updated = (t.get("updated_at") or "")[:10]
        title = (t.get("title") or "Untitled")[:50]
        active = "  ◀" if t["thread_id"] == state["thread_id"] else ""
        print(f"  {i:>2}.  {title:<52} {updated}  {t['thread_id']}{active}")
    print()

    try:
        raw = session.prompt(HTML(
            '  <ansiblue>Select</ansiblue> (number or thread ID, Enter to cancel): '
        )).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not raw:
        return

    selected = None
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(threads):
            selected = threads[idx]
        else:
            print("  Invalid selection.\n")
            return
    else:
        selected = next((t for t in threads if t["thread_id"] == raw), None)
        if not selected:
            print("  Thread not found.\n")
            return

    state["thread_id"] = selected["thread_id"]

    print_thread_history(base_url, selected["thread_id"], selected.get("title", "Untitled"))


def print_thread_history(base_url: str, thread_id: str, title: str | None = None) -> None:
    runs_data = api_get(base_url, f"/threads/{thread_id}/runs")
    runs = runs_data.get("runs", [])

    for run in runs:
        run_dir = REPO_ROOT / "sun" / "runtime" / "interface" / "runs" / run["run_id"]
        input_file = run_dir / "input.md"
        output_file = run_dir / "output.md"

        user_text = ""
        reply_text = ""
        if input_file.exists():
            user_text = input_file.read_text(encoding="utf-8").strip()
        if output_file.exists():
            reply_text = output_file.read_text(encoding="utf-8").strip()

        if user_text:
            print(f"\033[1mYou\033[0m")
            print(user_text)
            print()

        if reply_text:
            used = run.get("provider_used") or "unknown"
            print(f"\033[2m[{used}]\033[0m")
            print(reply_text)
            print()



# ── REPL main ─────────────────────────────────────────────────────────────────

def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7741"
    initial_thread = sys.argv[2] if len(sys.argv) > 2 else ""
    provider = sys.argv[3] if len(sys.argv) > 3 else ""
    initial = sys.argv[4] if len(sys.argv) > 4 else ""

    SOLAR_DIR.mkdir(parents=True, exist_ok=True)
    slash_items = _load_slash_items()
    file_items = _load_file_items()
    providers = _load_providers()
    selected_provider = provider.strip().lower()
    if selected_provider in {"", "auto"}:
        selected_provider = ""
        if initial_thread:
            last_provider = get_last_provider_for_thread(base_url, initial_thread)
            if last_provider in providers:
                selected_provider = last_provider
        if not selected_provider:
            selected_provider = providers[0]
    elif selected_provider not in providers:
        selected_provider = providers[0]

    state = {"thread_id": initial_thread, "provider": selected_provider}
    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):
        buf = event.current_buffer
        # Cursor-like behavior: if completion menu is open, Enter accepts current suggestion.
        if buf.complete_state:
            current = buf.complete_state.current_completion
            if current is not None:
                buf.apply_completion(current)
                # For slash commands, execute immediately after accepting completion.
                if buf.text.strip().startswith("/"):
                    buf.validate_and_handle()
                return
            # If menu is open but nothing is actively selected, accept first candidate.
            completions = list(buf.complete_state.completions or [])
            if completions:
                buf.apply_completion(completions[0])
                # If slash completion resolves to a single command, execute in the same Enter.
                if len(completions) == 1 and buf.text.strip().startswith("/"):
                    buf.validate_and_handle()
                return
        buf.validate_and_handle()

    @kb.add("c-j")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    @kb.add("c-c", eager=True)
    def _interrupt(event):
        # Ensure Ctrl+C always exits REPL regardless of prompt-toolkit mode/terminal quirks.
        event.app.exit(result="/exit")

    @kb.add("/")
    def _slash_with_completion(event):
        buf = event.current_buffer
        buf.insert_text("/")
        buf.start_completion(select_first=True)
        if buf.complete_state and buf.complete_state.current_completion is None:
            buf.complete_next()

    @kb.add("c-space")
    def _manual_completion(event):
        buf = event.current_buffer
        buf.start_completion(select_first=True)
        if buf.complete_state and buf.complete_state.current_completion is None:
            buf.complete_next()

    @kb.add("escape", "[", "1", "3", ";", "2", "u")
    def _shift_enter_kitty_sequence(event):
        # Some terminals emit Shift+Enter as CSI u: ESC [ 13 ; 2 u
        event.current_buffer.insert_text("\n")

    # ── Welcome header ────────────────────────────────────────────────────────
    print("\033[1;34m")
    print("  ███████╗ ██████╗ ██╗      █████╗ ██████╗ ")
    print("  ██╔════╝██╔═══██╗██║     ██╔══██╗██╔══██╗")
    print("  ███████╗██║   ██║██║     ███████║██████╔╝")
    print("  ╚════██║██║   ██║██║     ██╔══██║██╔══██╗")
    print("  ███████║╚██████╔╝███████╗██║  ██║██║  ██║")
    print("  ╚══════╝ ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝")
    print("\033[0m")
    print("  \033[2mType / for resources, @ for files, /help for commands\033[0m")
    print()
    # ─────────────────────────────────────────────────────────────────────────

    session: PromptSession = PromptSession(
        history=FileHistory(str(HISTORY_FILE)),
        completer=SolarCompleter(slash_items, providers, file_items),
        complete_while_typing=True,
        complete_in_thread=True,
        style=STYLE,
        mouse_support=False,
        multiline=True,
        key_bindings=kb,
    )

    def bottom_toolbar():
        tid = state["thread_id"]
        short_id = tid[:22] + "…" if len(tid) > 22 else tid
        prov = state["provider"]
        color = PROV_COLORS.get(prov, "ansiyellow")
        return HTML(
            f' <b>thread</b> {short_id}   '
            f'<b>client</b> <{color}>{prov}</{color}>   '
            f'<style fg="#6c6c6c">'
            f'/  resources   @  files   /client  switch   /resume  conversations   /exit  /quit'
            f'</style>'
        )

    if initial:
        send_and_print(base_url, state, initial)
    elif initial_thread:
        thread_data = api_get(base_url, "/threads").get("threads", [])
        current = next((t for t in thread_data if t.get("thread_id") == initial_thread), None)
        print_thread_history(base_url, initial_thread, current.get("title") if current else "Untitled")

    while True:
        try:
            text = session.prompt(
                HTML('<ansiwhite>›</ansiwhite> '),
                bottom_toolbar=bottom_toolbar,
            )
        except (EOFError, KeyboardInterrupt):
            print()
            break

        text = _sanitize_slash_text(text).strip()
        if not text:
            continue
        if text in ("/exit", "/quit"):
            break
        if text == "/":
            print(_format_slash_list(slash_items))
            print()
            continue

        parts = text.split()
        cmd = parts[0].lower()

        if cmd == "/resume":
            cmd_resume(base_url, state, session)
            continue

        if cmd == "/client":
            if len(parts) >= 2:
                chosen = parts[1].lower()
                if chosen in providers:
                    state["provider"] = chosen
                    print(f"\n  Client → \033[1m{chosen}\033[0m\n")
                else:
                    print(f"\n  Unknown: '{chosen}'. Available: {', '.join(providers)}\n")
            else:
                print(f"\n  Available clients:\n")
                for p in providers:
                    active = "  ◀ active" if p == state["provider"] else ""
                    print(f"    /client {p}{active}")
                print()
            continue

        if cmd == "/thread":
            print(f"\n  Thread: {state['thread_id']}\n")
            continue

        if cmd == "/clear":
            print("\033[2J\033[H", end="")
            continue

        if cmd == "/help":
            print("\n  Built-in commands:")
            for c, (_, _, desc) in BUILTIN_COMMANDS.items():
                print(f"    {c:<20} {desc}")
            print(f"    /client <name>       Switch AI client ({', '.join(providers)})")
            print()
            continue

        send_and_print(base_url, state, text)


if __name__ == "__main__":
    main()
