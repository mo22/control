# Log rotation agent has no liveness signal

Status: **open — offered 2026-08-03, deferred. Not urgent.**

## The problem

`control.log-rotation` prints nothing when it finds nothing to rotate — deliberate, so the
agent does not generate a line every 15 minutes forever. The cost is that a **successful
no-op and a dead agent are indistinguishable**: nothing is written, no exit status changes,
`launchctl list` shows the same `- 0 control.log-rotation` either way.

As of 2026-08-03 it has only ever been observed running via a manual
`launchctl start control.log-rotation`. It has never been seen firing on its own
`StartInterval` of 900 s.

## The first real test

`control.claude-remote-mcp.gateway-mac.stderr.log` (42.0 MB) and
`gateway-chrome.stderr.log` (41.4 MB) will cross the 50 MiB trigger on their own. If
`<base>.1.log.gz` appears for them without anyone intervening, the schedule works. If those
files quietly reach 100 MB instead, it does not.

Worth checking those two files once rather than building anything.

## If a signal is wanted anyway

Cheapest durable option: have each run write a timestamp to
`~/Library/Logs/control/.log-rotation.state` (mtime is enough — no content needed), so
`stat -f %m` answers "when did this last run". Costs one `utime` per sweep and no log noise.

Rejected alternatives: printing a line per run (24 lines/day of noise, and the agent's own
log then needs rotating for its own heartbeat); a `--verbose` flag (nobody would pass it in
the plist).
