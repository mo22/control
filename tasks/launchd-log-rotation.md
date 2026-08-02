# Bound launchd log growth in the LaunchD backend

Status: **control side DONE (v0.9). The WebShell follow-through below is still open.**

## What shipped

`control/logrotate.py` plus three macOS-only CLI commands (`install-log-rotation`,
`uninstall-log-rotation`, `log-rotation`). One per-user agent (`control.log-rotation`)
sweeps all of `~/Library/Logs/control` every 15 min and rotates anything over 50 MiB,
keeping one gzipped generation.

Rotation is `fclonefileat` (APFS copy-on-write snapshot, ~2 ms regardless of size) →
`ftruncate(fd, 0)` → gzip the clone → atomic rename. That keeps the inode, which is the
non-negotiable constraint: launchd opens the log once at spawn and holds the fd for the
process lifetime with no reopen-on-signal, so a rename leaves the daemon writing into the
archive. The fd is `O_APPEND` (`lsof +fg` shows `R,W,AP`), so truncating in place is safe.

Cloning first shrinks the loss window from "duration of the compression" to two syscalls —
**measured at 10 ms** against a service writing continuously. Filesystems without cloning
fall back to gzip-a-fixed-prefix-then-truncate.

Installation is **explicit**, not implicit: `control install` only prints a one-line
reminder while the agent is missing (`CONTROL_NO_LOG_ROTATION_HINT=1` silences it).

Answers to the original open questions: (1) explicit, per the above. (2) constants with
CLI overrides, not `control.yaml` keys — a per-project key cannot own a shared per-user
agent. (3) systemd needs nothing, confirmed: `service_template` hardcodes
`StandardOutput=journal`/`StandardError=journal` and kirk's journald caps are set in
`/etc/systemd/journald.conf.d/retention.conf`. (4) orphan sweeping declined — control
keeps no registry of configs on a host, so "no service owns this file" is unknowable; the
sweep bounds orphans for free anyway, since nothing writes to them after one truncation.

## Still open: follow-through in WebShell

WebShell's local copy must be removed so both do not rotate the same files:

1. `cd ~/workspace/webshell && control uninstall log-rotate`
2. delete `backend/rotate-logs.sh` and the `log-rotate` service + its two `groups:` entries
   in `control.yaml`
3. drop the *Logging* rotation paragraph in `webshell/CLAUDE.md` (line ~210) to a pointer
   at control

Not urgent as long as nothing under `control.webshell.*` exceeds 50 MiB — WebShell's script
only globs `control.webshell.*.log`, and the one file currently over the threshold belongs
to hav-assistant, so the two rotators do not contend today.

Coordinate that half back to WebShell — do not edit that repo from here without saying so.
