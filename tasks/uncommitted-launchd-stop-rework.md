# Follow-up: decide the fate of the uncommitted launchd stop/start rework

Opened: 2026-07-31
Status: open — needs a decision from Moritz

## What is sitting in the working tree

Uncommitted changes, left by session `019f419c` (2026-07-08), still present as of
2026-07-31:

- `control/api.py` — `LaunchD.stop()` switched from `launchctl stop` + PID wait to
  `launchctl unload`, plus a `is_enabled` guard and a post-condition that raises if the
  job is still loaded; `LaunchD.start()` gains a load-if-unloaded path.
- `tests/test_api.py` — three `LaunchDStartStopTests` covering the above.
- `AGENTS.md` — one line documenting the stop/start/restart semantics.
- `uv.lock` — editable `control` version 0.6 → 0.7.
- `tasks/check-uv-lock-version-mismatch.md` — untracked, from the same session.

## Why this needs a human decision

The uncommitted diff **partially reverts the commit right before it**. `f8fcdad`
("launchd: make stop() block until the process actually exits") is committed and
implements a *different* approach — `launchctl stop` plus a PID wait, with a docstring
explaining the sqlite-WAL race it was written for. The uncommitted work replaces that
mechanism and deletes that docstring.

So one of these is stale, and it is not clear from the outside which:

1. The unload rework is the intended successor to `f8fcdad` and just never got committed.
2. It is abandoned WIP that `f8fcdad` superseded.

The 2026-07-08 memory-log entry describes the unload approach as if it were the shipped
implementation, which suggests (1) — but the log records intent, not what landed, so it
is not proof.

## Also note

The uncommitted hunk carries lint debt that will land with whoever commits it:

- 3 × pyright `"kwargs" is not accessed` (`tests/test_api.py` in the mock `run()` helpers)
- 2 × ruff `SIM117` (nested `with` statements that should be combined)

Neither is present in committed code — the current tree is otherwise clean apart from
14 pre-existing pyright errors in `control/api.py:189` and `:374`.

## Related

`tasks/check-uv-lock-version-mismatch.md` is the same session's leftover and is really a
sub-question of this one: if the rework is committed, the `uv.lock` 0.6 → 0.7 hunk goes
with it (or into a separate lock-maintenance commit per the AGENTS.md release convention).
