# Follow-up: clippy's `shell:` workaround can go back to `run:`

Opened: 2026-07-31
Status: open — low priority, needs a change in the clippy repo (not this one)

## Context

`/srv/clippy/control.yaml:46` runs its git-pull service as

```yaml
shell: .venv/bin/python scripts/git-pull.py
```

with a comment block explaining that `run:` could not be used: pre-0.6 control
called `os.path.realpath()` in `ExecutableModel.to_executable_args()`, which
dereferenced `.venv/bin/python` into the uv-managed base interpreter and started
Python outside the virtualenv (`ModuleNotFoundError: No module named yaml`).

That is fixed — `abspath` since v0.6, and f765563 pinned venv interpreter
symlinks for relative `run:` paths specifically. Clippy now runs control 0.8, so
the workaround is no longer required.

## Why it is not done here

Reverting it means editing `/srv/clippy/control.yaml` (the clippy project's
repo, not control's) and then `control install` + restart for that service, which
regenerates the unit. Nothing is broken today, so it is not worth a service
restart on its own — fold it into the next clippy deploy.

`shell:` is also not strictly wrong: it bakes install-time PATH rather than
resolving the interpreter, which is a different but valid contract. The only
gain from reverting is dropping a comment block that now documents a fixed bug.

## Related

The fleet upgrade this came out of is done — all six hosts run control 0.8 as of
2026-07-31. Deployment gotchas are recorded in `AGENTS.md` under "Deploying to
Linux servers".
