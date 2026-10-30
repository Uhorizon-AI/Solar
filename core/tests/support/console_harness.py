"""Harness for the console identity and lifecycle tests.

Everything runs in a temporary workspace, runtime and app-data directory, on a
free loopback port selected with the test-only override (SOLAR_APP_TEST_MODE and
SOLAR_APP_TEST_PORT). Nothing here uses port 9000 or the machine runtime.

Doubles are tiny HTTP servers saved as ``host_server.py`` so their command line
looks like a console; where they live decides whose install they claim to be.
Teardown signals only processes this harness recorded (or the listeners of its
own private port that run a ``host_server.py``) and never removes directories:
pytest owns tmp_path.
"""
from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import port_watch
import pytest

CORE = Path(__file__).resolve().parents[2]
APP_SCRIPTS = CORE / "skills" / "solar-app" / "scripts"
STATE_PY = CORE / "skills" / "solar-state" / "scripts" / "solar_state.py"
SYSTEM_SCRIPTS = CORE / "skills" / "solar-system" / "scripts"

FAKE_CONSOLE = textwrap.dedent('''\
    import json, os, socketserver, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    port, mode, workspace, runtime = int(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]

    class Health(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            payload = {"service": "solar-console", "status": "available", "process_ok": True}
            if mode in ("full", "workspace_only", "runtime_only"):
                payload["pid"] = int(os.environ.get("FAKE_REPORT_PID") or os.getpid())
            if mode in ("full", "nopid", "workspace_only"):
                payload["workspace"] = workspace
            if mode in ("full", "nopid", "runtime_only"):
                payload["runtime"] = runtime
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    class Quick(HTTPServer):
        def server_bind(self):
            # HTTPServer.server_bind resolves the host name (getfqdn), which can take
            # many seconds on a CI runner with slow reverse DNS. A double needs none.
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address[:2]

    class Drop(socketserver.BaseRequestHandler):
        def handle(self):  # accepts and closes: listening, but never answers health
            pass

    if mode == "drop":
        socketserver.TCPServer.allow_reuse_address = True
        server = socketserver.TCPServer(("127.0.0.1", port), Drop)
    else:
        server = Quick(("127.0.0.1", port), Health)
    server.serve_forever()
''')


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def alive(pid: int) -> bool:
    """Running, not a zombie (ps works on Linux and macOS; /proc does not exist on macOS)."""
    state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def wait_dead(pid: int, seconds: float = 8.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return not alive(pid)


class Harness:
    def __init__(self, root: Path, baseline):
        self.root = root
        self.baseline = baseline
        self.port = free_port()
        self.ws = root / "ws"
        self.runtime = root / "runtime"
        self.data = root / "data"
        self.home = root / "home"
        self.bin = root / "bin"
        for path in (self.ws / "sun", self.ws / ".solar", self.runtime, self.data, self.home, self.bin):
            path.mkdir(parents=True, exist_ok=True)
        (self.ws / ".solar" / "settings.json").write_text(
            '{"layout":"solar-client-v1.1","core_source":"global","workspace_id":"harness-ws"}')
        self.workspace_phys = str(self.ws.resolve())
        self.runtime_phys = str(self.runtime.resolve())
        self.install_script = str((APP_SCRIPTS / "host_server.py").resolve())
        self.procs: list[subprocess.Popen] = []
        self._doubles = 0
        self.register_workspace()

    # -- environment -------------------------------------------------------
    def env(self, **extra) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("SOLAR_") and k.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
        env.update(
            HOME=str(self.home), SOLAR_APP_DATA=str(self.data), SOLAR_RUNTIME_ROOT=str(self.runtime),
            SOLAR_ROOT=str(CORE.parent), SOLAR_GLOBAL_ROOT=str(CORE.parent), SOLAR_WORKSPACE=str(self.ws),
            SOLAR_APP_TEST_MODE="1", SOLAR_APP_TEST_PORT=str(self.port),
            PATH=str(self.bin) + os.pathsep + env.get("PATH", ""),
        )
        env.update({k: v for k, v in extra.items() if v is not None})
        for key in [k for k, v in extra.items() if v is None]:
            env.pop(key, None)
        return env

    def register_workspace(self) -> None:
        for command in ("add", "use"):
            subprocess.run([sys.executable, str(APP_SCRIPTS / "host_registry.py"), command, str(self.ws)],
                           env=self.env(), check=True, capture_output=True)

    def claim_state(self) -> None:
        """Give the runtime an owner so the full (no flag) check can read storage."""
        subprocess.run([sys.executable, str(STATE_PY), "owner", "claim", "--workspace", str(self.ws),
                        "--id", "harness-ws"], env=self.env(), check=True, capture_output=True)
        # Migrate the empty temp runtime to sqlite (a fresh runtime has no format yet).
        subprocess.run([sys.executable, str(CORE / "skills/solar-state/scripts/solar_state_cutover.py"), "migrate"],
                       env=self.env(SOLAR_STATE_ALLOW_CUTOVER="1"), check=True, capture_output=True)

    # -- running scripts ---------------------------------------------------
    def script(self, name: str, *args: str, timeout: int = 90, **env) -> subprocess.CompletedProcess:
        if os.environ.get("SOLAR_CI_SLOW_HEALTH_PROBE") and name in ("start_host.sh", "ensure_host.sh"):
            # Measured on the GitHub macOS runner (issue 108): after the first start, every
            # check_host.sh --liveness takes 3.5 s, so start_host.sh's 2 s readiness window
            # (10 x 0.2 s plus the probes) fails or takes 35 s. Real hardware is not affected.
            pytest.skip("GitHub macOS runner: the health probe takes 3.5 s, past start_host.sh's readiness window")
        return subprocess.run(["bash", str(APP_SCRIPTS / name), *args], cwd=self.ws, env=self.env(**env),
                              capture_output=True, text=True, timeout=timeout)

    def lib(self, snippet: str, timeout: int = 90, **env) -> subprocess.CompletedProcess:
        code = f'source "{APP_SCRIPTS}/host_lib.sh"; solar_host_load_env; {snippet}'
        return subprocess.run(["bash", "-c", code], cwd=self.ws, env=self.env(**env),
                              capture_output=True, text=True, timeout=timeout)

    def fake_tool(self, name: str, body: str) -> Path:
        tool = self.bin / name
        tool.write_text("#!/bin/bash\n" + body)
        tool.chmod(0o755)
        return tool

    # -- doubles -----------------------------------------------------------
    def spawn(self, mode: str = "full", *, install: str = "other", workspace: str | None = None,
              runtime: str | None = None, interpreter: str | None = None, port: int | None = None,
              report_pid: int | None = None) -> subprocess.Popen:
        """A console double on the harness port.

        install="this" puts THIS install's host_server.py path on its command line;
        "other" runs it from a private directory (another install's console).
        """
        self._doubles += 1
        folder = self.root / f"double{self._doubles}"
        folder.mkdir()
        script = folder / "host_server.py"
        script.write_text(FAKE_CONSOLE)
        argv = [interpreter or sys.executable, "-u", str(script), str(port or self.port), mode,
                workspace if workspace is not None else self.workspace_phys,
                runtime if runtime is not None else self.runtime_phys]
        if install == "this":
            argv.append(self.install_script)
        env = dict(os.environ, **({"FAKE_REPORT_PID": str(report_pid)} if report_pid else {}))
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, start_new_session=True, env=env)
        self.procs.append(proc)
        self.wait_listening(port or self.port)
        return proc

    def spawn_sleeper(self) -> subprocess.Popen:
        proc = subprocess.Popen(["sleep", "300"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        self.procs.append(proc)
        return proc

    def wait_listening(self, port: int, seconds: float = 8.0) -> None:
        end = time.time() + seconds
        while time.time() < end:
            with socket.socket() as sock:
                sock.settimeout(0.2)
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    return
            time.sleep(0.1)
        raise AssertionError(f"double did not listen on {port}")

    def gone(self, target) -> bool:
        """True once a recorded Popen (reaped) or a bare pid has exited."""
        if isinstance(target, subprocess.Popen):
            try:
                target.wait(timeout=8)
            except subprocess.TimeoutExpired:
                return False
            return True
        return wait_dead(int(target))

    def write_pid_file(self, pid: int) -> Path:
        path = self.runtime / "host" / "host.pid"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{pid}\n")
        return path

    def pid_file(self) -> Path:
        return self.runtime / "host" / "host.pid"

    def start_real_console(self) -> int:
        result = self.script("start_host.sh")
        assert result.returncode == 0, result.stdout + result.stderr
        return int(self.pid_file().read_text().strip())

    def fake_lsof(self, *entries: tuple[int, str]) -> None:
        """An lsof that lists the given (pid, address) listeners in lsof -F format."""
        lines = "".join(f"printf 'p%s\\nn%s:%s\\n' {pid} {addr} {self.port}\n" for pid, addr in entries)
        self.fake_tool("lsof", lines)

    def scrubbed_path(self) -> str:
        """A PATH holding the tools the scripts need and no lsof."""
        folder = self.root / "nolsof"
        folder.mkdir(exist_ok=True)
        for tool in ("bash", "ps", "sleep", "cat", "tr", "grep", "dirname", "basename", "uname", "mkdir",
                     "rm", "cksum", "sed", "sort", "head", "tail", "env", "id", "date", "mktemp", "readlink",
                     "touch", "tee", "wc", "cut", "awk", "ln", "kill"):
            found = shutil.which(tool)
            if found and not (folder / tool).exists():
                (folder / tool).symlink_to(found)
        if not (folder / "python3").exists():
            (folder / "python3").symlink_to(sys.executable)
        return str(folder)

    # -- teardown ----------------------------------------------------------
    def _terminate(self, pid: int) -> None:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if not alive(pid):
                return
            try:
                os.kill(pid, sig)
            except OSError:
                return
            if wait_dead(pid, 2.0):
                return

    def cleanup(self) -> None:
        for proc in self.procs:
            if proc.poll() is None:  # known children: poll() also reaps, no zombie wait
                self._terminate(proc.pid)
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        # A console started through start_host.sh: only the recorded pid and the
        # listeners of this harness's private port, and only host_server.py ones.
        pids = set()
        if self.pid_file().exists():
            text = self.pid_file().read_text().strip()
            if text.isdigit():
                pids.add(int(text))
        pids |= {int(pid) for pid, *_ in (port_watch.snapshot(self.port) or ())}
        for pid in pids:
            try:
                args = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "args="], capture_output=True,
                                      text=True).stdout
            except OSError:
                continue
            if "host_server.py" in args:
                self._terminate(pid)
