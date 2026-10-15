# Test isolation: services, runtime and the console port

Tests must never stop, start or replace a real Solar service. Two incidents
shaped this contract: a test suite served the real console on port 9000 from a
pytest temporary directory, and a marker written by a test into the real runtime
suppressed the legitimate state cutover that followed.

## What reaches real services

`client_sync.sh` (and `client_update.sh`) end in `solar_client_state_cutover`
(`core/skills/solar-client/scripts/client_lib.sh`). It claims the resolved
runtime, writes the cutover marker there, detects running services with
`solar_client_running_services`, and then stops and restarts them. Only a test
that runs the **whole** sync path reaches it. Tests that call the publisher
`sync-clients.sh`, or sub-commands that exit before the cutover, do not.

Two hooks make the cutover safe in a test:

| Hook | Effect |
|---|---|
| `SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE` | `none`, or a comma list (`host,gateway`), replaces detection. With a list, also set the matching stop/start hooks (`SOLAR_CLIENT_HOST_STOP_SCRIPT`/`_START_SCRIPT`, `SOLAR_CLIENT_GATEWAY_STOP_SCRIPT`/`_SETUP_SCRIPT`). |
| `SOLAR_CLIENT_PS_OUTPUT_FILE` | A file of `ps` command lines used instead of the process table. |

**The override does not cover the LaunchAgent.** The cutover boots the agent out
and back in outside the service list, so full isolation also needs
`SOLAR_CLIENT_LAUNCHCTL` pointing at a test double (and `SOLAR_RUNTIME_ROOT` or
`SOLAR_APP_DATA` at a temporary directory, so the marker lands in a temporary
runtime).

## The guard

`core/tests/support/shell_runtime_guard.sh`:

- `solar_test_guard` aborts (exit 97) if the runtime is the machine runtime or
  `launchctl` is the system binary. Unconditional, as before.
- `solar_test_guard --services` additionally aborts unless service detection is
  disabled or simulated, or the effective install is not the real global install.
  A simulated process table (`SOLAR_CLIENT_PS_OUTPUT_FILE`) is judged by what it
  makes the cutover detect for the effective install (other installs' lines are ignored): if it lists the console or a gateway bridge, the matching
  stop/start hooks must be set, exactly as for an explicit override list.

**The `--services` check is opt-in and is not automatic.** Some tests call the
guard before they set `SOLAR_ROOT`, and many set `SOLAR_ROOT` to the repository
without any override; an unconditional check would abort them although they never
reach the cutover. A new test that runs the complete `client_sync.sh` must:

1. set `SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none` (or a ps file, or hooks),
2. set `SOLAR_CLIENT_LAUNCHCTL` to a double and the runtime to a temporary directory,
3. call `solar_test_guard --services` **after** steps 1 and 2 and after `SOLAR_ROOT` is set.

### "Real global install"

Compared on **physical paths** (`realpath`), never on strings:

- the global install is `SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE` when it is set
  (an empty value means "no global install"), otherwise the install that the
  framework itself resolves (`solar_global_install_root` in
  `core/skills/solar-paths/scripts/resolve_solar_paths.sh`);
- the effective install is `SOLAR_ROOT`, or the repository holding the guard when
  `SOLAR_ROOT` is unset.

When both are the same directory and detection is real, the guard aborts.

## The console port

No test starts the real console or occupies port 9000.

- `core/tests/conftest.py` records the listeners on 9000 **before the first test**
  (so before any double exists) and fails the run if a new listener is there at
  the end, compared by address **and command line** per listener: a listener on a new address, or
  on a known address with a different command line (a console replaced by one served
  from a pytest temp directory), fails the run. A new pid is accepted as a restart only with evidence: the same
  command line **and** the same `workspace`/`runtime` reported by `/health` before
  and after. The identity is read over HTTP from the very address that is listening
  (cached per pid, address and command line, one request each) and only counts if BOTH fields are
  reported; a listener that does not answer, is not a console, or reports no or partial
  identity cannot verify a restart, so its change is reported. Limit: a
  replacement that keeps pid, command line, address and reported identity is
  indistinguishable from the original; nothing else is observable. Listeners already present (a developer's live console) are in
  the baseline and are never touched. Without `lsof` nothing can be observed and
  the check is skipped.
- Tests that need a server use `core/tests/support/console_harness.py` (the
  `harness` fixture in `core/tests/skills/solar-app/conftest.py`): a temporary
  workspace, runtime and app-data directory, and a private free port selected with
  `SOLAR_APP_TEST_MODE=1` plus `SOLAR_APP_TEST_PORT=<port>`. The override is
  honoured only with both variables in the **process** environment, never selects
  9000, and cannot be set from a workspace `.env`; production always uses 9000.
- Teardown signals only the processes the harness started and the `host_server.py`
  listeners of its own private port. It never removes directories; pytest owns them.
