# macOS stop semantics: explicit ExitTimeOut, then a supervisor (tree kill + log rotation)

Status: **Step 1 done** (2026-09-24, session 01KvuMbh), **Step 2 proposal ready
for Moritz** — created 2026-09-24, dispatched from agent-setup session dc961425.
Step 1 is implemented, tested and verified with a scratch service (below). Step 2
is a design proposal (below) that Moritz confirms before anything is built.

## Why

On systemd, control guarantees no orphaned subprocesses (`KillMode=mixed`,
`TimeoutStopSec=30`, `control/api.py:415-420`, README "Subprocess cleanup"). On
macOS nothing comparable exists, and the README guarantee silently does not apply.

Incident 2026-09-24: the fileindex-mcp `watch` daemon
(`uvx tcc-venv run … uv run fileindex watch`) ignored SIGTERM for longer than launchd's
stop timeout. launchd SIGKILLed only `uvx`; the tcc-venv trampoline, `uv run` and the
python payload lived on with PPID 1 for days, held the instance lock (every restart
exited "Lock held by another process") and grew to a 103 GB footprint. The fileindex
side is fixed (fileindex-mcp `f6cb54f`); tcc-venv is getting a parent-death teardown
(`~/workspace/tcc-venv/tasks/kill-child-tree-on-parent-death.md`). This task is the
control side.

## Measured launchd behaviour (throwaway LaunchAgents, 2026-09-24)

1. Stop (`launchctl bootout` / `control stop|restart`): SIGTERM to the job's main pid;
   after `ExitTimeOut` a **SIGKILL to the main pid only**. `launchctl print` showed
   `exit timeout = 5` for control's jobs, although the generated plist sets no
   `ExitTimeOut`.
2. `AbandonProcessGroup=false` (default): the job's process group gets **one SIGTERM,
   never a SIGKILL**. A same-group child that ignores SIGTERM survives with PPID 1; a
   plain same-group child dies.
3. `AbandonProcessGroup=true`: the group is not signalled at all; both children survive.
4. Process groups are escapable anyway: tcc-venv (`POSIX_SPAWN_SETPGROUP`) and `uv run`
   each create their own group.

Probe used (ProgramArguments of the scratch job; `ExitTimeOut` 5):

```sh
/bin/sh -c "/usr/bin/python3 -c 'import signal,time; signal.signal(15, lambda *a: None); time.sleep(900)  # ignTERM' & /usr/bin/python3 -c 'import time; time.sleep(900)  # plain' & trap '' TERM; wait"
```

`launchctl bootstrap gui/$UID <plist>; launchctl kickstart gui/$UID/<label>`, then
`launchctl bootout`, wait 8 s, `pgrep -fl <marker>`; clean up with `kill -KILL`.

## Step 1 — explicit ExitTimeOut (DONE 2026-09-24)

Implemented: new `stop_timeout: int | None` field on `ServiceModel`
(`control/models.py`), surfaced as `Service.stop_timeout` (default 30). The
launchd `_generate_plist` now sets `ExitTimeOut = service.stop_timeout` and the
systemd `service_template` sets `TimeoutStopSec = service.stop_timeout` (was a
hardcoded `30`). Configurable per service in `control.yaml`, applied to both
backends. Schema regenerated (`control.schema.json`).

- ✅ Tests added (`tests/test_api.py::StopTimeoutTests`, 6 cases): default 30,
  explicit value, plist `ExitTimeOut` default+configured, systemd
  `TimeoutStopSec` default+configured. Full suite green (43 tests).
- ✅ Verified with a scratch launchd service: payload sleeps 10 s after SIGTERM
  before exiting 0; `control stop` took 10.1 s and the process exited cleanly
  (marker logged "cleanup done, exiting 0"), then was gone. Under launchd's old
  ~5 s default it would have been SIGKILLed mid-cleanup. Scratch service fully
  torn down (`control uninstall`, plist + logs removed).
- ✅ README "Subprocess cleanup" updated: documents that on macOS launchd SIGKILLs
  only the main pid and does **not** reap escaped descendants, plus the new
  `stop_timeout` field. AGENTS.md Behavior section updated too.
- ⚠️ **Live services not reinstalled.** Existing installed plists still have the
  old (short) `ExitTimeOut` until the next `control install` for that service.
  Which macOS launchd services would need a reinstall to pick up
  `ExitTimeOut=30` is listed at the end of this file — **ask Moritz before
  reinstalling any of them.**

## Step 2 — supervisor as the job's main program (design first, confirm before building)

Idea: the plist runs `control supervise <service>` (name open) instead of the service
command directly. The supervisor spawns the service command and:

1. **Kills the process tree on stop.** On SIGTERM: collect all descendants by walking the
   ppid tree (reaches layers that left the group via setpgid/setsid), SIGTERM them, wait
   a grace period, SIGKILL the rest, then exit. The supervisor exits last, so the tree
   is still intact when it collects it. Its grace period has to be below `ExitTimeOut`,
   or launchd SIGKILLs the supervisor first.
2. **Owns stdout/stderr.** It reads the service's output through pipes and writes the
   log files itself, so it can rotate by size (rename + reopen) with no copy-truncate
   and no separate `control.log-rotation` agent. That also settles
   `tasks/log-rotation-liveness.md`. Optionally timestamp lines.
3. Propagates the exit status, so `KeepAlive: {SuccessfulExit: false}` keeps working.

Questions the proposal has to answer:

- **Boot dependency:** every control daemon would depend on the supervisor starting
  at boot. It must not need the network or an unpinned tool (the columbo proxy refuses
  connections early at boot; see the tcc-venv/uvx notes in fileindex-mcp's AGENTS.md).
  Stdlib-only Python on a fixed interpreter, or a tiny compiled binary?
- **Supervisor killed hard** (SIGKILL, crash): children orphan exactly as today. Can a
  cheap parent-death check in the child layer help, or is that out of scope?
- **Forced kills from macOS** (shutdown, logout, memory pressure): make sure the
  supervisor never delays or blocks them. At shutdown launchd kills everything anyway.
- **TCC attribution:** the job's main program changes from `/bin/sh` to the
  supervisor. Check that FDA-dependent services (tcc-venv disclaim bootstrap) still
  resolve their responsible process the same way.
- **Output buffering:** a pipe instead of a file changes nothing for block buffering
  (both are non-TTY), but check Python services still flush as before.
- **Intentionally detached helpers:** tree kill also kills helpers meant to outlive
  the service (same as `KillMode=mixed`). Opt-out per service?
- Where the rotation settings live (`control.yaml` per service vs. global defaults).

Deliver the design as a section in this file and ask Moritz before implementing.

## Step 2 — Supervisor design proposal (2026-09-24, awaiting Moritz's confirmation)

**Nothing below is built.** This is the proposal to confirm before any code.
Step 1 (explicit `ExitTimeOut`/`TimeoutStopSec` = `stop_timeout`, default 30 s) is
landed and stands on its own — it gives a daemon's *own* SIGTERM handler time to
run. The supervisor builds on top of it and is the only thing that reaps
subprocesses that escaped the process group.

### Scope: macOS only, opt-in per service

The supervisor is a **launchd-backend-only** feature. systemd already reaps the
whole cgroup (`KillMode=mixed`) and journald already bounds logs, so on Linux the
service command stays the plist/unit's direct `ExecStart` — no wrapper, no change
to the boot path. On macOS it is **opt-in per service** at first
(`supervise: true` in `control.yaml`), not the default, because of the TCC risk
below. Once validated on the fileindex FDA service, making it the default for
`type: daemon` on macOS is a later, separate decision.

### Shape

`control install` (macOS, `supervise: true`) writes the plist's
`ProgramArguments` as:

```
/usr/bin/python3  <tooldir>/control/supervisor.py  <sidecar.json>
```

and, next to the plist, a **sidecar JSON** holding everything already resolved at
install time: the service argv, the env dict, cwd, the two log paths, rotation
settings, and the grace period. At boot the supervisor reads only that sidecar
(stdlib `json`) — it never re-parses `control.yaml`, so it pulls in **no pydantic,
no PyYAML, no click, no network**. Interpreter is pinned to `/usr/bin/python3`
(system, always present, no uv/uvx, so the columbo proxy is never on the boot
path). `supervisor.py` is stdlib-only.

At start the supervisor: opens two pipes (stdout, stderr); forks the service into
a **new session** (`setsid`, so it has its own pgid); records that pgid to a state
file next to the sidecar; installs a `SIGTERM` handler; then runs a `select()`
loop draining both pipes into the log files. It **owns the fds**, so it rotates by
size with plain rename + reopen — no copy-truncate, no separate
`control.log-rotation` agent needed for supervised services.

On `SIGTERM` (from launchd on `control stop`): enumerate all descendants by
walking the **ppid tree** (not the process group — that is exactly what
`uv run`/tcc-venv escape via `setsid`/`POSIX_SPAWN_SETPGROUP`; the ppid walk
reaches them). Descendant discovery is stdlib-only via `ps -axo pid,ppid,pgid`
(one subprocess at stop time is fine) or `libproc.proc_listchildpids` through
`ctypes`. SIGTERM the whole set, wait the grace period, SIGKILL survivors, then
exit **last** (so the tree is still intact when it is collected), propagating the
child's status (`0` → clean, signal death → `128+signum`) so
`KeepAlive {SuccessfulExit: false}` still restarts on crash.

### Grace period vs. ExitTimeOut

The supervisor's grace period **must be strictly below `ExitTimeOut`**, or
launchd SIGKILLs the supervisor before it finishes the tree kill — leaving the
exact orphans this is meant to prevent. Proposal: `stop_timeout` keeps meaning
"how long a process gets between SIGTERM and SIGKILL", the supervisor uses it as
the child grace period, and when a service is supervised `control install` sets
the plist `ExitTimeOut = stop_timeout + 5` (margin for the ps walk + the
supervisor's own exit). So `ExitTimeOut` stays the outer bound and the supervisor
always wins the race.

### Answers to the open questions

1. **Boot dependency.** Solved by the sidecar: fixed `/usr/bin/python3` +
   stdlib-only `supervisor.py` + no config parse + no network. The only new boot
   dependency is that the control tool dir stays intact (it already must, to run
   `control`). No uvx, no columbo proxy, no unpinned tool on the boot path.
2. **Supervisor killed hard (SIGKILL/crash).** Children orphan exactly as today —
   no regression, no improvement in that instant. Mitigation *without* needing the
   child's cooperation: the recorded **pgid state file**. `KeepAlive` relaunches
   the supervisor after a crash; on restart it reads the previous pgid from the
   state file and `kill(-pgid, SIGKILL)`s any survivors before spawning fresh. So
   a hard-killed supervisor's orphans are reaped on the next restart rather than
   surviving for days (which is what the incident was). A `PR_SET_PDEATHSIG`-style
   child check needs the service to opt in and there is no clean macOS equivalent
   — **out of scope**; the pgid-reap-on-restart is the recommended mitigation.
3. **Forced kills from macOS (shutdown/logout/memory pressure).** The supervisor
   never delays them: its SIGTERM path is hard-capped at the grace period, does no
   network and no unbounded wait, and it cannot and does not trap SIGKILL. At
   shutdown/logout launchd tears down the whole GUI session, so the tree dies
   regardless of the supervisor. Under jetsam, `ProcessType: Background` already
   sets the memory band; no special handling. Nothing to do here beyond "keep the
   SIGTERM path bounded and side-effect-free".
4. **TCC attribution — the real risk, needs a live test.** The job's main program
   changes from the service binary (or `/bin/sh`) to `/usr/bin/python3`. TCC keys
   FDA grants to the *responsible process*, normally the top of the launchd job
   tree. Inserting python3 as that top could change which binary TCC treats as
   responsible and break FDA for services that rely on it (tcc-venv's disclaim
   bootstrap sets responsibility explicitly with
   `responsibility_spawnattrs_setdisclaim`, so it *may* be unaffected — but that
   is a hypothesis). **Gate:** before making the supervisor the default, install a
   supervised copy of the fileindex FDA service and confirm it still resolves FDA
   (read a TCC-protected path). Keeping the feature opt-in until this passes is
   why opt-in is the recommended rollout, not default-on.
5. **Output buffering.** No change: a pipe and a file are both non-TTY, so libc
   block-buffers identically; services that already set `PYTHONUNBUFFERED`/flush
   keep working. The one new requirement is on *our* side — the supervisor must
   drain both pipes continuously (the `select()` loop), or a service that fills
   the 64 KiB pipe buffer blocks on write. Two separate pipes keep stdout/stderr
   distinct as today.
6. **Intentionally detached helpers.** Tree kill also kills helpers meant to
   outlive the service — the same trade-off as `KillMode=mixed`. Opt-out is simply
   `supervise: false` (the default): that service runs its command directly, as
   now. A finer "leave this one child" mark is not worth the intent-detection
   complexity; a service that needs a surviving helper should double-fork it under
   `launchd`/its own job instead.
7. **Where rotation settings live.** Global defaults stay (today's
   `install-log-rotation` defaults: 50 MiB, keep 4), overridable per service in
   `control.yaml` (e.g. `log_rotate: {max_bytes, keep}`). Supervised services
   rotate themselves via rename+reopen (the supervisor holds the fd, so the
   launchd-fd-liveness problem in `tasks/log-rotation-liveness.md` **does not
   apply to them** — that is the settlement noted in Step 2's intro). The existing
   `control.log-rotation` sweep agent stays for non-supervised/legacy logs; a
   supervised service's live log must be **excluded from that sweep** (it is
   already being rotated, and a copy-truncate from the agent racing the
   supervisor's rename would be a conflict). Simplest exclusion: the supervisor
   writes supervised logs under a subdir (e.g. `~/Library/Logs/control/supervised/`)
   that the global sweep glob skips, or drops a marker the sweep honours. Retire
   the global agent only once nothing is left unsupervised.

### Rollout plan (once confirmed)

1. Add `supervise: bool` + `log_rotate` to the model; `control install` writes the
   sidecar + wrapped `ProgramArguments` + bumped `ExitTimeOut` only when
   `supervise: true` on the launchd backend.
2. `control/supervisor.py`, stdlib-only, with unit tests driven by a scripted
   fake service (a child that spawns a `setsid` grandchild which ignores SIGTERM —
   assert the grandchild is dead after stop, reproducing the incident).
3. Validate TCC on the fileindex FDA service (question 4) **before** default-on.
4. Only then consider defaulting `type: daemon` on macOS to supervised.

**Open decisions for Moritz:** (a) opt-in `supervise: true` first vs. straight to
default-on for macOS daemons; (b) the `stop_timeout + 5` ExitTimeOut margin; (c)
supervised-log location for sweep exclusion (subdir vs. marker); (d) whether the
pgid-reap-on-restart mitigation (question 2) is in the first cut or deferred.

## Live macOS services that would need a `control install` to pick up ExitTimeOut

Checked 2026-09-24 on this Mac: **all 18** control-managed launchd services below
currently have **`ExitTimeOut` unset** (launchd's short default), so none has the
new 30 s grace until its config is reinstalled with the upgraded `control`.
Reinstalling restarts the service (`control install` rewrites + reloads the
plist). **Do not reinstall any of these without asking Moritz first.** Grouped by
`control.yaml`:

- `claude-remote-mcp`: chrome-mcp, gateway-agent, gateway-chrome, gateway-mac,
  mac-mcp, tunnel-agent, tunnel-chrome, tunnel-mac, webshell-agent-mcp
- `columbo`: columbo
- `file-butler`: kicktipp-watcher, whatsapp-watcher
- `fileindex`: watch  ← the incident service
- `hav-assistant`: gpt, respeaker
- `webshell`: tunnel-devmxsde, webshell
- `winmgr`: winmgr

`control.log-rotation` is generated by `install-log-rotation`, not `_generate_plist`,
so it is a **separate codepath** and would not gain `ExitTimeOut` from this change
even on reinstall — it is a periodic sweep, not a daemon, so it does not matter.

Note the upgrade is two-staged (AGENTS.md): the `control` tool upgrade is inert;
only a per-service `control install` regenerates that service's plist. So these can
be reinstalled one at a time, when convenient, after the tool is upgraded.
