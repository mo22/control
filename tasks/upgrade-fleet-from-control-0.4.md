# Follow-up: upgrade control 0.4 → 0.7 across the fleet

Opened: 2026-07-31
Status: open — decision needed, not urgent

## Situation

Every server runs **control 0.4**. Only the MacBook has 0.7.

| Host | Installed | Path |
|---|---|---|
| clippy (46.225.105.77) | 0.4 ×3 | `/usr/local/share/uv/tools`, `/root/.local/...`, `/home/mmoeller/.local/...` |
| kirk.mxs.de | 0.4 | `/usr/local/share/uv/tools/control` |
| alpha.mxs.de | 0.4 | `/usr/local/share/uv/tools/control` |
| delta.mxs.de | 0.4 | `/usr/local/share/uv/tools/control` |
| lemon | 0.4 | `/usr/local/share/uv/tools/control` |
| spock-ubuntu.local | 0.4 | `/usr/local/share/uv/tools/control` |
| MacBook | 0.7 | `~/.local/share/uv/tools/control` |

This surfaced while investigating the clippy `ModuleNotFoundError: No module named yaml`
incident on 2026-07-31. Root cause was the pre-0.6 `os.path.realpath()` in
`ExecutableModel.to_executable_args()` dereferencing `.venv/bin/python` into the
uv-managed base interpreter, which starts Python outside the virtualenv. Fixed in
a2fc103, shipped in **v0.6** — so clippy's 0.4 simply predates the fix.

## Why it is not urgent

- No unit on any host has a dereferenced interpreter in `ExecStart` (checked for
  `uv/python/cpython-` across `/etc/systemd/system` and user units on all six hosts).
- Clippy's only path-form command already uses the `shell:` workaround
  (`control.yaml:46`), which is committed there and should be left alone.
- Its other service (`control.yaml:19`) is `run: uv run …` — a bare command, resolved
  via `shutil.which()`, never affected.

## Why it is still worth doing

Any *new* service pointing at a venv interpreter with `run:` will silently break on
these hosts, and the failure mode is a confusing ModuleNotFoundError rather than
anything naming control.

## Before upgrading — check this

0.4 → 0.7 crosses the **v0.5 explicit-source env change**: `{user.VAR}` reads the
`control install` process environment, `{sys.PATH}` reads control's built-in fallback.
Review each host's `control.yaml` for env references before upgrading.

Note the tool upgrade itself is inert — units are only regenerated on `control install`,
so the behaviour change lands at reinstall time, not at upgrade time. That means the
upgrade can be staged separately from the reinstall.

```bash
uv tool install --force git+https://github.com/mo22/control
```

## Verify installed version on a host

```bash
grep 'os.path.join(cwd, path)' <uv-tools>/control/lib/python*/site-packages/control/models.py
# realpath -> <= 0.5 (affected) | abspath -> >= 0.6 (fixed)
```
