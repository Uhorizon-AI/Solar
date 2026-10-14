# Console identity contract

A console that answers on the loopback port is reusable only if it serves **this
workspace and this runtime**. A process that merely responds, or merely has
`host_server.py` in its command line, is not enough.

## Identity

`GET /health` reports two physical paths (after `realpath`):

| Field | Meaning |
|---|---|
| `workspace` | the workspace the console serves |
| `runtime` | the framework runtime root of the console process (resolved once at start) |
| `pid` | the console's own process id (`/health` only) |

`/api/runtime/health` reports the same `workspace` and `runtime` in the same canonical form. Nothing else is added: no tokens, secrets or file contents. The callers compute the
same two values from their own environment and compare physical paths, so a
symlinked path and its target are one identity.

## One decision point

`core/skills/solar-app/scripts/host_identity.py` (`compare`, `assess`) is the only
place the rule lives. States:

| State | Meaning | Reusable |
|---|---|---|
| `match` | workspace and runtime both reported and equal | yes |
| `mismatch` | a reported value differs | never; never stopped |
| `legacy` | reports neither value (older release) | only after proof of ownership |
| `partial` | reports one value, equal | only after proof of ownership |
| `unreachable` | nothing answers on loopback | no |
| `invalid` | answers, but is not a Solar console | no |

Applied by: `check_host.sh` (with `--liveness`, `--json`, `--quiet` **and with no
flag**, the mode the system supervisor runs), `ensure_host.sh`, `start_host.sh`,
`stop_host.sh` and `solar_host_stop_orphan_listeners`. The probe ignores any proxy
configured in the environment.

`solar status` reads the same JSON and shows the `error` as the host detail.

`check_host.sh` exit codes: `0` usable, `1` unavailable, `3` the console answers but
its identity is not accepted. The JSON form never fails open: it reports
`"available": false` with an error that names the identity. The supervisor
(`check_orchestrator.sh`) prints `status: UNTRUSTED` for exit `3` and counts the host
as DOWN.

## Proof of ownership (legacy and partial consoles)

A console without a complete identity cannot prove itself. It is adopted, and
replaced by a console that does report identity, only if the listener is also
shown to be this runtime's by one of:

1. the pid file of this runtime points to it and that pid is still a live
   `host_server.py` (a recycled pid is rejected);
2. its command line holds **this install's** `host_server.py` path (compared as
   given and as a physical path, independent of the interpreter, including macOS
   `Python.app`).

A console that cannot answer at all (hung) is recovered by the same two proofs.
The install-path comparison is anchored to the whole command-line argument, so
`/other/prefix/<this install path>/host_server.py` is not this install.

Residual risk: a hung process cannot be asked what it serves, so a hung console of
**another workspace served by the same install** (or another runtime) is recognised
by install path only and can be stopped. The pid file is the stronger proof and is
preferred; install path exists so that a console left without a pid file is not
stranded. An answering console is never judged this way.

## Active workspace switch

`stale_workspace` is not a state of `host_identity.py` (which only returns the six above). It is derived in `solar_host_assess` (`host_lib.sh`) from `mismatch` with only the workspace differing, the runtime equal, and this runtime's pid file pointing at the pid that answered. `check_host.sh` still reports `mismatch` and exits 3.

The real console re-reads the registry on every request, so `solar app workspace use`
moves a running console to the new workspace and it stays accepted. If a console of
this runtime still reports the previous workspace (pid file points at the pid that
answered, runtime equal), it is state `stale_workspace`: `check_host.sh` exits 3, but
`stop_host.sh`, `start_host.sh` and the cutover stop and replace it. A differing
**runtime** is always refused.

## Never kill what is not ours

- A process is signalled only if its command line is `host_server.py` (re-checked
  immediately before every signal) and ownership was shown by identity, pid file or
  install path.
- `solar_host_stop_orphan_listeners` stops proven-own listeners only, reports the
  rest and returns non-zero if nothing was stopped.
- Listeners are discovered with `lsof` and matched to exactly `SOLAR_APP_HOST:port` (not any loopback address); a listener on
  a LAN or wildcard address is not the console. Without `lsof` nothing is
  discovered, so an unidentified console is neither adopted nor stopped.
- The supervisor's healthy path runs no `lsof` and no process inspection.

## Foreign console on the port

`start_host.sh` and `ensure_host.sh` make one decision, print a diagnostic and exit
`3`; nothing retries in a loop. The diagnostic says what the console serves, that it
was not reused or stopped, and that whoever owns it removes it by hand: confirm its
identity with `check_host.sh --json`, then run `stop_host.sh` as its owner (its
workspace and runtime) or find the pid with `lsof -nP -iTCP:9000 -sTCP:LISTEN` and
stop it manually.

## Port

The console port is 9000 and cannot be changed by configuration. Tests alone can
move it with `SOLAR_APP_TEST_MODE=1` and `SOLAR_APP_TEST_PORT` in the process
environment (see `test-isolation.md`).

The console stays read-only and listens on loopback only.
