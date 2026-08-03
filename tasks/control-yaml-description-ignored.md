# `description:` in control.yaml is silently dropped

Status: **open — noticed 2026-08-03 while working in WebShell's config. Not urgent.**

## What happens

`~/workspace/webshell/control.yaml` sets `description:` on every service:

```yaml
  webshell:
    run: ./webshell-tcc
    cwd: backend
    type: daemon
    description: WebShell backend server
```

`ServiceModel` (`control/models.py`) has no `description` field, and pydantic v2 defaults to
`extra="ignore"`, so the value is parsed and thrown away. No warning, no schema error, and
`control.schema.json` does not flag it either. Someone wrote those strings expecting them to
show up somewhere — most plausibly in `control status`.

At least one other config on this machine may do the same; worth a grep before deciding.

## Options

1. **Add the field** and surface it — `description: str | None = None`, shown in
   `control status` (and as `Description=` in the systemd unit, which currently hardcodes
   `<config>-<service>`; launchd has no equivalent key). Makes the existing configs
   meaningful with no edits to them.
2. **Reject unknown keys** — `model_config = ConfigDict(extra="forbid")` on `ServiceModel`.
   Honest, and catches typos like `typ:` or `intervall:` that today do nothing silently. But
   it turns every existing `description:` into a hard install failure until those lines are
   removed, so it needs a sweep of every `control.yaml` on every host first.

Option 1 is the smaller change and loses nothing; option 2 is the one that prevents the
*next* silently-ignored key. They are not mutually exclusive — 1 then 2 is the safe order.

## Not urgent because

Nothing is broken; a documentation string is being ignored. The risk it points at is the
general one — a mistyped service key does nothing and says nothing.
