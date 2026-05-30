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

## Systemd Fields

- `systemd:` appends only to the generated `.service` `[Service]` section.
- `systemd_timer:` appends only to the generated `.timer` `[Timer]` section.
- `[Unit]` additions use separate fields: `systemd_unit:` for `.service` `[Unit]`, and `systemd_timer_unit:` for `.timer` `[Unit]`.
