# control Agent Notes

## Release

- Release convention: commit feature changes first, make a separate `Bump version to X.Y` commit that includes `pyproject.toml` and `uv.lock`, push `master`, tag `vX.Y`, push the tag, then reinstall with `uv tool install --force git+https://github.com/mo22/control`.
- The project has no CI release workflow. Verify locally before tagging.

## Testing

- Unit tests use stdlib `unittest`; run `uv run python -m unittest discover -v`.
- Template-rendering smoke tests can run on macOS without real systemd by monkey-patching `SystemD.systemd_version` to a fixed int and stubbing subprocess calls such as `systemd-analyze calendar` when timer calendar validation is involved.
- Use `/usr/bin/true` or `shutil.which("true")` in cross-platform fixtures; `/bin/true` does not exist on macOS.

## Service Env Semantics

- control does not copy the full user environment into services by default. systemd units get installer `PATH`; launchd plists get installer `PATH` plus `HOME`.
- v0.5 service env references are explicit-source only: `{user.VAR}` reads the `control install` process environment and `{sys.PATH}` reads control's built-in fallback path. The temporary `${PATH}` idea was rejected before tagging.

## Behavior (install / runtime)

- `cwd` defaults to the **config file's directory** when omitted (api.py `_generate_plist`/systemd codegen). So `shell:` commands resolve relative paths (e.g. tcc-venv finding `./.venv`) against the repo holding `control.yaml`.
- `shell:` runs via `/bin/sh -c` with PATH **baked from the install-time shell** (`_detect_path` = `os.environ.get("PATH")`). Bare `uvx`/`uv`/etc. resolve only if you `control install` from your interactive shell. A config change needs a **reinstall** to take effect.
- `install`, `enable`, `start` are **separate** steps — `install` alone writes the unit/plist but does not run it. Typical deploy: `control --config control.yaml install <svc> && … enable <svc> && … start <svc>`.
- Renaming a service key orphans the old unit: control only manages services present in the *current* config. To swap (e.g. periodic→daemon under a new name) you must tear down the old one yourself — on macOS `launchctl bootout gui/$UID/control.<name>.<svc>` + remove `~/Library/LaunchAgents/control.<name>.<svc>.plist`.
- On macOS launchd, `stop` unloads the plist so `KeepAlive` daemons stay down; `start` reloads an unloaded plist before `launchctl start`, and `restart` is clean stop+start.
- `type: daemon` → launchd `KeepAlive` + `RunAtLoad` (restart-on-crash, long-running); `type: periodic` → `StartInterval`. No `--version` flag on the CLI.

## Systemd Fields

- `systemd:` appends only to the generated `.service` `[Service]` section.
- `systemd_timer:` appends only to the generated `.timer` `[Timer]` section.
- `[Unit]` additions use separate fields: `systemd_unit:` for `.service` `[Unit]`, and `systemd_timer_unit:` for `.timer` `[Unit]`.
