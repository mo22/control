# control

A process manager for managing services via systemd.

## Installation

```bash
uv tool install git+https://github.com/mo22/control
```

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

### Extending PATH

control injects the installer's `PATH` into generated systemd units and
launchd plists. If a service needs to add directories without replacing
that detected path, set `env.PATH` with `${PATH}`:

```yaml
services:
  worker:
    shell: my-daemon
    type: daemon
    env:
      PATH: ${PATH}:/opt/custom/bin
```

`${PATH}` expansion is only supported in service-level `env.PATH`.
Other `${VAR}` strings are left literal.

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

## Schema

The JSON schema is available at:
```
https://raw.githubusercontent.com/mo22/control/master/control.schema.json
```

Works with VS Code (YAML extension), IntelliJ, and other editors supporting yaml-language-server.
