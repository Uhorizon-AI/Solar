# Test isolation

Shell tests in `core/tests/` run against the machine they are executed on. Two
rules keep a test from touching what a real Solar installation is serving: it
must not use the machine runtime, and it must not drive the real service
manager. A third, opt-in check covers the one path that can stop real services.

## `solar_test_guard` (always run)

Source `core/tests/support/shell_runtime_guard.sh` and call `solar_test_guard`
after pointing `SOLAR_RUNTIME_ROOT` (or `SOLAR_APP_DATA`) at a temporary
directory and `launchctl` at a test double. It runs two checks and aborts with
exit 97 when either fails:

- **Temporary runtime.** `solar_runtime.py` resolves the runtime the test would
  use; its `realpath` must differ from the `realpath` of the machine runtime
  (resolved with the test overrides removed). This keeps a suite from reading or
  writing the machine's queue, audit rows or pid files.
- **Launchctl double.** `SOLAR_CLIENT_LAUNCHCTL` or `PATH` must resolve to
  something other than `/bin/launchctl` or `/usr/bin/launchctl`. A test that
  loads a LaunchAgent must drive its own double.

Both checks compare physical paths, never strings.

## `solar_test_guard --services` (opt-in)

A full `client_sync.sh` run reaches `solar_client_state_cutover`, which reads
the running services of the install it is handed and stops them. `SYNC_INSTALL_ROOT`
is `SOLAR_ROOT`, so a test whose effective install is the machine's real global
install can restart or stop the services the machine is using.

Every test that invokes `client_sync.sh` in full (no subcommand) must pass the
opt-in flag:

```bash
bash -c 'source "$1"; solar_test_guard --services; bash "$2" --codex-only' _ \
  "$CORE/tests/support/shell_runtime_guard.sh" "$CORE/skills/solar-client/scripts/client_sync.sh"
```

The flag is opt-in on purpose: tests that never reach the cutover keep the two
unconditional checks, and a test that calls the guard before setting
`SOLAR_ROOT` must not abort for a path it never takes. Because the protection is
not automatic, this document is what closes the gap for a new test.

The third check aborts (exit 97) when all hold:

- neither `SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE` nor `SOLAR_CLIENT_PS_OUTPUT_FILE`
  is set, so detection is not pinned;
- the effective install (`SOLAR_ROOT`, else the resolved global install) and the
  Client's global install resolve to the same physical path.

The Client's global install is `SOLAR_CLIENT_GLOBAL_INSTALL_OVERRIDE` when that
variable is pinned (an empty value means "no global install"), otherwise the
install `solar-paths` resolves. This is the same resolution production uses, and
it is compared on `realpath`, never as a string.

## Hooks

- `SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE` — pins service detection. `none` (or
  any explicit value) means the test never detects a real process by itself.
- `SOLAR_CLIENT_PS_OUTPUT_FILE` — feeds a captured `ps` listing instead of
  running `ps`, so a test can assert what detection sees.

**The overrides cover detection only.** The LaunchAgent `bootout`/`bootstrap`
step of the cutover stays reachable with
`SOLAR_CLIENT_RUNNING_SERVICES_OVERRIDE=none`. Full isolation therefore needs
the `launchctl` double that `solar_test_guard` already requires,
in addition to the override.

## Resources

Sync tests must not start the real console or take port 9000. Any test that does
need a server must:

- bind a stub on `127.0.0.1:0`, never on the console port;
- keep its own stubs off 9000 through `SOLAR_APP_PORT_OVERRIDE` (the console port
  stays fixed at 9000; the override exists only for tests);
- release processes and ports at the end: kill and `wait` for the stub in the
  `trap`, and leave no new listener behind.

The acceptance criterion for a suite is "no new residue", not "port free": on a
machine with the real console running, port 9000 is already held before the
suite starts.
