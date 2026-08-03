"""Bounded log growth for the LaunchD backend.

WHY THIS EXISTS: the LaunchD backend writes ``StandardOutPath`` /
``StandardErrorPath`` into every plist, and launchd captures service output into
those plain files without ever bounding them. On the SystemD backend the same
services log to journald, which enforces its own retention -- so this is a
backend parity gap, not a feature. Left alone, ``~/Library/Logs/control`` grows
without limit (300 MB, with a single 104 MB stderr log, by 2026-08-01).

WHY COPY-TRUNCATE AND NOT RENAME: launchd opens the log once, at service start,
and hands the fd to the process for its whole lifetime. There is no
reopen-on-signal. Renaming the file (what newsyslog and default logrotate do)
leaves the daemon writing into the renamed inode while the fresh file stays
empty, and nothing reports it. The fd is ``O_APPEND`` (verified with ``lsof``:
flags ``R,W,AP``), so truncating in place is safe -- every write seeks to
end-of-file first, and the writer simply continues at offset 0.

WHY CLONE FIRST: a plain copy-truncate discards everything appended between the
start of the copy and the truncate, and compressing 100 MB takes seconds. APFS
``fclonefileat`` makes a copy-on-write snapshot in ~2 ms regardless of size, so
we clone, truncate immediately, and compress the snapshot afterwards where
nothing is racing us. The lost window shrinks to the gap between two syscalls.
Filesystems without cloning fall back to the classic gzip-then-truncate.
"""

from __future__ import annotations

import ctypes
import gzip
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# NOTE: api.py imports this module *lazily*, inside LaunchD.install(), precisely
# so that this module-level import cannot become a cycle. Keep it that way.
from .api import DEFAULT_PATH

LABEL = "control.log-rotation"
LOG_GLOB = "control.*.log"
LOG_EXT = ".log"
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_INTERVAL = 900
DEFAULT_KEEP = 4
HINT_ENV = "CONTROL_NO_LOG_ROTATION_HINT"

CLONE_SUFFIX = ".rotating"
LOCK_NAME = ".log-rotation.lock"
# <base>.<n>.log[.gz] — matches what archive_path() builds, and is what keeps the
# sweep from treating its own archives as logs to rotate.
ARCHIVE_RE = re.compile(r"\.\d+\.log$")

AT_FDCWD = -2  # Darwin value; see <fcntl.h>
COPY_CHUNK = 1024 * 1024

_hinted = False


class LogRotationUnsupported(Exception):
    """Raised when log rotation is requested on a non-launchd platform."""


@dataclass
class Rotation:
    """What happened (or would happen) to one log file."""

    path: Path
    size: int
    archive: Path | None = None
    compressed: bool = False
    cloned: bool = False
    planned: bool = False
    error: str | None = None


def is_supported() -> bool:
    """True on the platform where control captures service output to files."""
    return sys.platform == "darwin"


def require_supported() -> None:
    """Fail loudly rather than pretending to work on the systemd backend."""
    if not is_supported():
        raise LogRotationUnsupported(
            "log rotation is macOS-only: systemd services log to journald, "
            "which bounds itself"
        )


def log_dir() -> Path:
    """Directory the LaunchD backend points StandardOutPath/ErrorPath at."""
    return Path.home() / "Library" / "Logs" / "control"


def launchd_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    return launchd_dir() / f"{LABEL}.plist"


def is_installed() -> bool:
    return plist_path().exists()


def parse_size(value: str | int) -> int:
    """Parse a byte size, accepting plain bytes or a K/M/G suffix."""
    if isinstance(value, int):
        return value
    match = re.fullmatch(r"\s*(\d+)\s*([KMG])?(?:i?B)?\s*", value, re.I)
    if not match:
        raise ValueError(f"invalid size: {value}")
    scale = {"K": 1024, "M": 1024**2, "G": 1024**3}
    return int(match.group(1)) * scale.get((match.group(2) or "").upper(), 1)


def parse_interval(value: str | int) -> int:
    """Parse a schedule interval to seconds, reusing the backend's parser."""
    if isinstance(value, int):
        return value
    from .api import LaunchD

    seconds = LaunchD._parse_interval(value)
    if not seconds:
        raise ValueError(f"invalid interval: {value}")
    return seconds


def archive_path(path: Path, generation: int, compressed: bool = True) -> Path:
    """Archive name for a generation: ``<base>.<n>.log`` plus ``.gz``.

    The generation number goes *before* the extension so that decompressing an
    archive still yields a ``.log`` file.
    """
    name = path.name
    base = name[: -len(LOG_EXT)] if name.endswith(LOG_EXT) else name
    suffix = f".{generation}{LOG_EXT}" + (".gz" if compressed else "")
    return path.with_name(base + suffix)


def is_archive(path: Path) -> bool:
    """True for our own archives, which must never be rotated again.

    Uncompressed archives end in ``.log`` and would otherwise be picked up by
    the sweep glob.
    """
    name = path.name[: -len(".gz")] if path.name.endswith(".gz") else path.name
    return bool(ARCHIVE_RE.search(name))


def shift_generations(path: Path, keep: int) -> None:
    """Roll ``.1`` → ``.2`` … and drop anything past ``keep``.

    Archives are closed files that nothing holds open, so plain renames are safe
    here — the no-rename rule applies only to the live log.
    """
    for generation in range(keep, 0, -1):
        for compressed in (True, False):
            src = archive_path(path, generation, compressed)
            if not src.exists():
                continue
            if generation >= keep:
                src.unlink()
            else:
                os.replace(src, archive_path(path, generation + 1, compressed))


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


_libc = None


def _clonefile(src_fd: int, dst: Path) -> None:
    """fclonefileat(2): copy-on-write snapshot of an open file. Raises OSError.

    Anchored on the source *fd* rather than a path, so a pathname swap between
    the size check and the clone cannot make us archive a different inode than
    the one we truncate.
    """
    global _libc
    if _libc is None:
        _libc = ctypes.CDLL("libSystem.B.dylib", use_errno=True)
        _libc.fclonefileat.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        _libc.fclonefileat.restype = ctypes.c_int
    ctypes.set_errno(0)
    if _libc.fclonefileat(src_fd, AT_FDCWD, os.fsencode(str(dst)), 0) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(dst))


def _tmp_archive(path: Path) -> Path:
    return Path(str(archive_path(path, 1)) + ".tmp")


def _gzip_to(src: Path, tmp: Path) -> None:
    """Compress a snapshot into ``tmp``. The caller publishes it."""
    try:
        with open(src, "rb") as fsrc, gzip.open(tmp, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst, COPY_CHUNK)
            fdst.flush()
            os.fsync(fdst.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _gzip_prefix(src_fd: int, tmp: Path, length: int) -> None:
    """Compress exactly ``length`` bytes from the start of an open file.

    The fixed length matters: without it a fast writer keeps moving EOF and the
    archive never ends.
    """
    try:
        remaining = length
        with gzip.open(tmp, "wb") as fdst:
            os.lseek(src_fd, 0, os.SEEK_SET)
            while remaining > 0:
                chunk = os.read(src_fd, min(COPY_CHUNK, remaining))
                if not chunk:
                    break
                fdst.write(chunk)
                remaining -= len(chunk)
            fdst.flush()
            os.fsync(fdst.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def rotate_file(
    path: Path,
    max_bytes: int = DEFAULT_MAX_BYTES,
    keep: int = DEFAULT_KEEP,
    dry_run: bool = False,
) -> Rotation | None:
    """Rotate one log file if it is over ``max_bytes``.

    Returns None when the file is untouched (too small, not a regular file, or
    one of our own archives).
    """
    if is_archive(path):
        return None
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    except OSError as exc:
        return Rotation(path, 0, error=f"open failed: {exc}")

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        size = st.st_size
        if size <= max_bytes:
            return None
        if dry_run:
            return Rotation(path, size, planned=True)

        archive = archive_path(path, 1)
        tmp = _tmp_archive(path)
        clone = Path(str(path) + CLONE_SUFFIX)
        clone.unlink(missing_ok=True)

        try:
            _clonefile(fd, clone)
        except OSError:
            # No cloning on this filesystem: compress a fixed-length prefix
            # first and only truncate once the archive is safely on disk. The
            # classic copy-truncate trade-off applies -- lines written during
            # the compression are lost.
            try:
                _gzip_prefix(fd, tmp, size)
            except Exception as exc:
                return Rotation(path, size, error=f"archive failed: {exc}")
            shift_generations(path, keep)
            os.replace(tmp, archive)
            os.ftruncate(fd, 0)
            return Rotation(path, size, archive=archive, compressed=True)

        # The snapshot exists, so the live file can be emptied immediately. Only
        # what lands between these two syscalls is lost.
        os.ftruncate(fd, 0)

        try:
            _gzip_to(clone, tmp)
        except Exception as exc:
            # The data is already out of the live file; keep the uncompressed
            # snapshot rather than deleting the only copy.
            shift_generations(path, keep)
            fallback = archive_path(path, 1, compressed=False)
            try:
                os.replace(clone, fallback)
            except OSError:
                fallback = clone
            return Rotation(
                path,
                size,
                archive=fallback,
                compressed=False,
                cloned=True,
                error=f"compression failed, kept uncompressed: {exc}",
            )

        # Roll the older generations only once the new archive is on disk, so a
        # failed compression never disturbs the history that is already there.
        shift_generations(path, keep)
        os.replace(tmp, archive)
        clone.unlink(missing_ok=True)
        return Rotation(path, size, archive=archive, compressed=True, cloned=True)
    finally:
        os.close(fd)


def rotate_log_dir(
    directory: Path | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    keep: int = DEFAULT_KEEP,
    dry_run: bool = False,
) -> list[Rotation]:
    """Rotate every oversized control log in ``directory``."""
    directory = directory or log_dir()
    results = []
    for path in sorted(directory.glob(LOG_GLOB)):
        result = rotate_file(path, max_bytes=max_bytes, keep=keep, dry_run=dry_run)
        if result is not None:
            results.append(result)
    return results


@contextmanager
def rotation_lock(directory: Path):
    """Advisory lock so a manual run cannot overlap the scheduled agent.

    launchd already refuses to run two instances of one label, so this only
    guards hand-invoked runs. The lock lives on an open fd, not on the presence
    of a file, so a killed process cannot leave a stale lock behind.
    """
    import fcntl

    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        os.close(fd)


def agent_plist(
    max_bytes: int = DEFAULT_MAX_BYTES,
    interval: int = DEFAULT_INTERVAL,
    keep: int = DEFAULT_KEEP,
) -> dict:
    """Plist for the per-user rotation agent.

    Its own output lands in the same directory under a name matching LOG_GLOB,
    so the agent rotates its own logs too.
    """
    logs = log_dir()
    return {
        "Label": LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "control",
            "log-rotation",
            "--max-bytes",
            str(max_bytes),
            "--keep",
            str(keep),
        ],
        "StartInterval": interval,
        "StandardOutPath": str(logs / f"{LABEL}.stdout.log"),
        "StandardErrorPath": str(logs / f"{LABEL}.stderr.log"),
        "WorkingDirectory": str(Path.home()),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", DEFAULT_PATH),
            "HOME": str(Path.home()),
        },
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 1,
    }


def install_agent(
    max_bytes: int = DEFAULT_MAX_BYTES,
    interval: int = DEFAULT_INTERVAL,
    keep: int = DEFAULT_KEEP,
) -> bool:
    """Install and load the rotation agent. Returns True if it already existed.

    Unlike ``control install``, this loads the job as well: writing the plist
    alone leaves it inert until the next login, which would silently mean no
    rotation for the rest of the session.
    """
    require_supported()
    log_dir().mkdir(parents=True, exist_ok=True)
    launchd_dir().mkdir(parents=True, exist_ok=True)

    path = plist_path()
    existed = path.exists()
    if existed:
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    with open(path, "wb") as f:
        plistlib.dump(agent_plist(max_bytes, interval, keep), f)
    subprocess.run(["launchctl", "load", str(path)], check=True)
    return existed


def uninstall_agent() -> bool:
    """Unload and remove the rotation agent. Returns False if not installed."""
    require_supported()
    path = plist_path()
    if not path.exists():
        return False
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    path.unlink()
    return True


def hint_if_missing() -> None:
    """Nudge once per process when services are installed but nothing bounds them."""
    global _hinted
    if _hinted or os.environ.get(HINT_ENV) or not is_supported():
        return
    _hinted = True
    if not is_installed():
        print("note: log rotation is not installed (control install-log-rotation)")
