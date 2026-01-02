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

## Schema

The JSON schema is available at:
```
https://raw.githubusercontent.com/mo22/control/master/control.schema.json
```

Works with VS Code (YAML extension), IntelliJ, and other editors supporting yaml-language-server.
