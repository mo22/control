# control

A process manager for managing services via systemd.

## Installation

On a server, install **system-wide** so that root, systemd and every login user
resolve the same binary:

```bash
sudo env UV_TOOL_DIR=/usr/local/share/uv/tools UV_TOOL_BIN_DIR=/usr/local/bin \
  uv tool install --python /usr/bin/python3 git+https://github.com/mo22/control
```

`--python` matters: without it `uv` under `sudo` picks an interpreter under
`/root/.local/share/uv/python/`, which works for root and fails for everyone
else with `bad interpreter: Permission denied`. Use `/usr/bin/python3` where it
satisfies `requires-python`; otherwise add
`UV_PYTHON_INSTALL_DIR=/usr/local/share/uv/python` and pin a version
(`--python 3.10`) so the managed interpreter lands somewhere world-readable.

For a single-user machine, the plain per-user install is fine:

```bash
uv tool install git+https://github.com/mo22/control
```

Pick one per host. Running both leaves two copies at different versions, and
which one you get depends on `PATH` order.

## Configuration

Create a `control.yaml` file with your service definitions. Add the schema reference for editor autocompletion and validation:

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/mo22/control/master/control.schema.json

name: myproject
version: https://github.com/mo22/control

env:
  PORT: 3000

services:
  web:
    run: node server.js
    type: daemon

  cleanup:
    shell: rm -rf /tmp/cache/*
    type: periodic
    interval: 1h
```

### Referencing Environment Values

control injects the installer's `PATH` into generated systemd units and
launchd plists when a service does not set `env.PATH`. Service-level
`env` values can also reference explicit environment sources:

- `{user.VAR}` reads from the environment of the `control install` process.
- `{sys.PATH}` reads control's built-in fallback path.

Quote values that start with `{...}` so YAML treats them as strings:

```yaml
services:
  worker:
    shell: my-daemon
    type: daemon
    env:
      PATH: "{user.PATH}:/opt/custom/bin"
      API_KEY: "{user.API_KEY}"
```

If a referenced `{user.VAR}` or `{sys.VAR}` value is missing, install
fails instead of writing a unit with a silently empty value.

## Subprocess cleanup

Services run by control are tracked as a systemd cgroup with
`KillMode=mixed`. When a service is stopped, restarted, crashes with
`Restart=on-failure`, or (for cron/periodic jobs) finishes naturally,
systemd kills every process in the cgroup — including orphaned descendants
whose parent already exited. You don't need to set `PR_SET_PDEATHSIG` or
manage your own process groups for the common "service with subprocess
helpers" pattern.

This guarantee only applies to services managed by control. A process
started outside systemd (e.g. via a user-session `run.sh`) is not in any
tracked cgroup, and orphaned children there will keep running until killed
manually.

## Log rotation (macOS)

On the systemd backend service output goes to journald, which enforces its own
retention. On macOS launchd captures stdout/stderr into plain files under
`~/Library/Logs/control` and never bounds them, so control ships an optional
rotation agent:

```bash
control install-log-rotation                            # every 15 min, rotate over 50 MiB
control install-log-rotation --max-bytes 200M --interval 1h
control log-rotation --dry-run                          # what would be rotated right now
control uninstall-log-rotation
```

One agent per user account covers every control-managed service on the machine,
so it is installed once per Mac rather than once per project. While it is
missing, `control install` prints a one-line reminder — silence that with
`CONTROL_NO_LOG_ROTATION_HINT=1`.

Rotation is **copy-truncate, never rename**. launchd opens the log once at
service start and holds the fd for the life of the process, with no
reopen-on-signal, so renaming the file leaves the daemon writing into the
archive while the fresh file stays empty. control snapshots the log with an APFS
clone, truncates it in place, then compresses the snapshot to `<log>.1.gz`; one
gzipped generation is kept. Only output written between the clone and the
truncate is lost — measured at 10 ms against a service writing continuously.

These three commands are macOS-only and exit non-zero elsewhere.

## Schema

The JSON schema is available at:
```
https://raw.githubusercontent.com/mo22/control/master/control.schema.json
```

Works with VS Code (YAML extension), IntelliJ, and other editors supporting yaml-language-server.
