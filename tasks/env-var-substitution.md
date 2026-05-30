# Add `${VAR}` substitution to env values

Requested 2026-05-31 from the isidore project (mmoeller). Use case
below is the immediate motivation, but the feature is general.

## Motivation

`control.yaml` can declare per-service `env:` blocks. Today the values
are literal strings — there's no way to reference the installer's
shell environment. That forces operators into bad choices:

1. **Hard-code values** that should be installer-relative
   (`PATH: /opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`). This is
   exactly what bit isidore on 2026-05-30: the operator's shell PATH
   included `~/.local/bin` (where `claude` lives), but the literal
   PATH in `control.yaml` didn't. Result: the daemon ran for hours
   producing `claude CLI not found on PATH` failures every minute,
   silently degrading the entire monitoring stack.
2. **Omit the env block entirely** and rely on `_detect_path()` /
   auto-`HOME` (which is what we fell back to in the isidore fix).
   Works for the two keys control already special-cases — useless for
   any other env var the daemon actually needs.
3. **Commit secrets to `control.yaml`** (e.g. `ANTHROPIC_API_KEY_X:
   sk-ant-...`). Obviously bad — `control.yaml` is checked into git.

There's no clean way today to say "pass through whatever the operator
has in their shell".

## Proposal

Allow `${VAR}` placeholders in the values of every env block (service
+ top-level config). Substitute against `os.environ` at install time,
inside both `LaunchD._generate_plist` (api.py:736) and
`SystemD.service_template` (api.py:413).

Syntax:

```yaml
services:
  monitor:
    shell: my-daemon
    env:
      PATH: ${PATH}:/opt/custom/bin               # append
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}     # pass-through secret
      LOG_LEVEL: info                             # literal (unchanged)
```

Substitution rule: regex `\$\{([A-Za-z_][A-Za-z0-9_]*)\}` → value of
`os.environ[name]`. Anything not matching the pattern (bare `$FOO`,
`$$`, `${}`) is left literal. Keep it simple — no default-value or
nested-expansion syntax.

### Missing-var policy

Raise `KeyError` at install time if any referenced var isn't in
`os.environ`. Silent-empty is a footgun:
`PATH: ${PATH}:/opt/x` silently becoming `:/opt/x` is exactly the
class of "silent breakage" the feature exists to prevent. An install-
time error surfaces immediately, before launchd/systemd ever loads
the bad unit.

## Scope

- `LaunchD._generate_plist` — substitute in
  `EnvironmentVariables` after `service.env` is merged in.
- `SystemD.service_template` — substitute in the env loop at
  api.py:413.
- `models.py` — no schema change needed; values remain `str`.
- Probably belongs in a small helper `_expand_env(d: dict[str, str])
  -> dict[str, str]` shared by both backends.
- Tests: add unit coverage for the regex, the missing-var error, and
  the no-op pass-through of literals.
- README: one short section explaining substitution + the missing-var
  error + the "don't commit secrets" angle.

## Out of scope (deliberately)

- Default-value syntax (`${VAR:-fallback}`) — adds complexity for
  questionable benefit. If you need a fallback, set the var in your
  shell.
- Nested expansion (`${${PREFIX}_HOST}`) — never.
- Loading values from a `.env` file. If somebody wants that, they can
  source it before running `control install`.

## Asks

1. Implement `_expand_env` + wire into both backends.
2. Raise on missing vars; include the var name in the error.
3. README + unit tests.
4. Bump version; reinstall via uv tool, verify with a small synthetic
   service that prints its env.

## Cross-references

- isidore-side hardening that prompted this: pinned
  `runtime.claude_bin` in `destinations.yaml` and added a meta-notify
  Pushover when a `watch` tick fails (2026-05-30 session against
  `~/workspace/isidore`).
- Reference for the control source paths above:
  `~/.local/share/uv/tools/control/lib/python3.12/site-packages/control/api.py`
  at commit `1f7877fcb38abf0e300abb69d8c6a00fa6f10912` (per
  `direct_url.json` of the installed dist-info).
