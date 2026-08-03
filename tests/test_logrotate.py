import gzip
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from control import logrotate

MAX = 1024
darwin_only = unittest.skipUnless(sys.platform == "darwin", "requires launchd/APFS")


def write_log(
    directory: Path, name: str = "control.demo.svc.stderr.log", size: int = 4096
) -> Path:
    """Write an oversized log file and return its path."""
    path = directory / name
    line = b"x" * 63 + b"\n"
    with open(path, "wb") as f:
        f.write(line * (size // len(line)))
    return path


class RotateFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_rotation_preserves_the_inode(self):
        # The invariant the whole design rests on: launchd holds the fd for the
        # life of the process, so the log must keep its inode. A rename-based
        # implementation would still leave a plausible-looking .gz behind.
        path = write_log(self.dir)
        before = path.stat().st_ino

        logrotate.rotate_file(path, max_bytes=MAX)

        self.assertEqual(path.stat().st_ino, before)
        self.assertEqual(path.stat().st_size, 0)

    def test_append_writer_keeps_writing_after_truncation(self):
        # Simulates launchd's held O_APPEND fd: the writer must continue at
        # offset 0 rather than leaving a hole the size of the old log.
        path = self.dir / "control.demo.svc.stdout.log"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, b"y" * 4096)

            logrotate.rotate_file(path, max_bytes=MAX)

            os.write(fd, b"after\n")
        finally:
            os.close(fd)

        self.assertEqual(path.stat().st_size, len(b"after\n"))
        self.assertEqual(path.read_bytes(), b"after\n")

    def test_archive_round_trips_the_original_bytes(self):
        path = write_log(self.dir)
        original = path.read_bytes()

        result = logrotate.rotate_file(path, max_bytes=MAX)

        assert result is not None and result.archive is not None
        self.assertTrue(result.compressed)
        self.assertEqual(gzip.decompress(result.archive.read_bytes()), original)

    def test_file_under_the_threshold_is_untouched(self):
        path = write_log(self.dir, size=512)
        before = path.stat()

        result = logrotate.rotate_file(path, max_bytes=MAX)

        self.assertIsNone(result)
        self.assertEqual(path.stat().st_size, before.st_size)
        self.assertFalse(logrotate.archive_path(path, 1).exists())

    def test_dry_run_changes_nothing(self):
        path = write_log(self.dir)
        before = path.stat().st_size

        result = logrotate.rotate_file(path, max_bytes=MAX, dry_run=True)

        assert result is not None
        self.assertTrue(result.planned)
        self.assertEqual(path.stat().st_size, before)
        self.assertFalse(logrotate.archive_path(path, 1).exists())

    def test_leaves_log_intact_when_it_cannot_archive(self):
        # Losing the log outright is worse than letting it grow to the next
        # sweep, so nothing may be truncated before an archive exists.
        path = write_log(self.dir)
        before = path.read_bytes()

        with patch.object(logrotate, "_clonefile", side_effect=OSError("no clone")):
            with patch.object(
                logrotate, "_gzip_prefix", side_effect=OSError("disk full")
            ):
                result = logrotate.rotate_file(path, max_bytes=MAX)

        assert result is not None
        self.assertIn("archive failed", result.error or "")
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(Path(str(logrotate.archive_path(path, 1)) + ".tmp").exists())

    def test_falls_back_to_gzip_then_truncate_without_clonefile(self):
        path = write_log(self.dir)
        original = path.read_bytes()

        with patch.object(logrotate, "_clonefile", side_effect=OSError("ENOTSUP")):
            result = logrotate.rotate_file(path, max_bytes=MAX)

        assert result is not None and result.archive is not None
        self.assertFalse(result.cloned)
        self.assertEqual(path.stat().st_size, 0)
        self.assertEqual(gzip.decompress(result.archive.read_bytes()), original)

    @darwin_only
    def test_keeps_uncompressed_snapshot_when_compression_fails(self):
        # Once the live file is truncated the clone is the only copy, so a gzip
        # failure must not delete it.
        path = write_log(self.dir)
        original = path.read_bytes()

        with patch.object(logrotate, "_gzip_to", side_effect=OSError("disk full")):
            result = logrotate.rotate_file(path, max_bytes=MAX)

        assert result is not None and result.archive is not None
        self.assertFalse(result.compressed)
        self.assertIn("compression failed", result.error or "")
        self.assertEqual(result.archive.read_bytes(), original)
        self.assertEqual(path.stat().st_size, 0)

    def test_symlinked_log_is_refused(self):
        target = write_log(self.dir, name="real.log")
        link = self.dir / "control.demo.svc.stderr.log"
        link.symlink_to(target)

        result = logrotate.rotate_file(link, max_bytes=MAX)

        assert result is not None
        self.assertIn("open failed", result.error or "")
        self.assertEqual(target.stat().st_size, 4096)


class ArchiveNamingTests(unittest.TestCase):
    def test_generation_goes_before_the_extension(self):
        # So that gunzip yields a file that is still a .log.
        path = Path("/logs/control.demo.svc.stderr.log")

        self.assertEqual(
            logrotate.archive_path(path, 1).name, "control.demo.svc.stderr.1.log.gz"
        )
        self.assertEqual(
            logrotate.archive_path(path, 3).name, "control.demo.svc.stderr.3.log.gz"
        )
        self.assertEqual(
            logrotate.archive_path(path, 1, compressed=False).name,
            "control.demo.svc.stderr.1.log",
        )

    def test_archives_are_recognised_and_live_logs_are_not(self):
        self.assertTrue(
            logrotate.is_archive(Path("control.demo.svc.stderr.1.log.gz"))
        )
        # The uncompressed fallback also matches the sweep glob, so it has to be
        # recognised or the rotator would rotate its own archive.
        self.assertTrue(logrotate.is_archive(Path("control.demo.svc.stderr.2.log")))
        self.assertFalse(logrotate.is_archive(Path("control.demo.svc.stderr.log")))
        self.assertFalse(logrotate.is_archive(Path("control.log-rotation.stdout.log")))


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def rotate_n_times(self, count: int, keep: int = 4) -> Path:
        path = self.dir / "control.demo.svc.stderr.log"
        for i in range(count):
            with open(path, "wb") as f:
                f.write(f"generation {i}\n".encode() * 400)
            logrotate.rotate_file(path, max_bytes=MAX, keep=keep)
        return path

    def test_keeps_four_generations_by_default(self):
        path = self.rotate_n_times(6)

        present = sorted(p.name for p in self.dir.glob("*.gz"))
        self.assertEqual(
            present,
            [
                "control.demo.svc.stderr.1.log.gz",
                "control.demo.svc.stderr.2.log.gz",
                "control.demo.svc.stderr.3.log.gz",
                "control.demo.svc.stderr.4.log.gz",
            ],
        )
        self.assertEqual(path.stat().st_size, 0)

    def test_generation_1_is_newest_and_the_oldest_is_dropped(self):
        self.rotate_n_times(6)

        def content(n):
            return gzip.decompress(logrotate.archive_path(self.dir / "control.demo.svc.stderr.log", n).read_bytes())

        # Six rotations, four kept: .1 holds the newest (generation 5), .4 the
        # oldest surviving (generation 2). Generations 0 and 1 are gone.
        self.assertIn(b"generation 5", content(1))
        self.assertIn(b"generation 4", content(2))
        self.assertIn(b"generation 3", content(3))
        self.assertIn(b"generation 2", content(4))

    def test_keep_one_still_works(self):
        self.rotate_n_times(3, keep=1)

        self.assertEqual(
            sorted(p.name for p in self.dir.glob("*.gz")),
            ["control.demo.svc.stderr.1.log.gz"],
        )

    def test_a_failed_rotation_does_not_disturb_existing_generations(self):
        path = self.rotate_n_times(2)
        before = {p.name: p.read_bytes() for p in self.dir.glob("*.gz")}

        write_log(self.dir, size=4096)
        with patch.object(logrotate, "_clonefile", side_effect=OSError("no clone")):
            with patch.object(logrotate, "_gzip_prefix", side_effect=OSError("full")):
                logrotate.rotate_file(path, max_bytes=MAX)

        after = {p.name: p.read_bytes() for p in self.dir.glob("*.gz")}
        self.assertEqual(after, before)


class RotateLogDirTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_only_control_logs_are_considered(self):
        write_log(self.dir, name="control.demo.svc.stderr.log")
        write_log(self.dir, name="unrelated.log")
        write_log(self.dir, name="control.demo.svc.stderr.1.log.gz")
        # An uncompressed archive matches the sweep glob and must be skipped, or
        # the rotator would rotate its own history.
        write_log(self.dir, name="control.demo.svc.stdout.2.log")

        results = logrotate.rotate_log_dir(self.dir, max_bytes=MAX)

        self.assertEqual(
            [r.path.name for r in results], ["control.demo.svc.stderr.log"]
        )
        self.assertEqual((self.dir / "unrelated.log").stat().st_size, 4096)
        self.assertEqual((self.dir / "control.demo.svc.stdout.2.log").stat().st_size, 4096)

    def test_lock_is_not_reentrant(self):
        with logrotate.rotation_lock(self.dir) as first:
            self.assertTrue(first)
            pid = os.fork()
            if pid == 0:
                with logrotate.rotation_lock(self.dir) as second:
                    os._exit(0 if second is False else 1)
            self.assertEqual(os.waitpid(pid, 0)[1], 0)


class AgentPlistTests(unittest.TestCase):
    def test_plist_runs_the_rotation_command_on_a_schedule(self):
        plist = logrotate.agent_plist(max_bytes=123, interval=900, keep=4)

        self.assertEqual(plist["Label"], logrotate.LABEL)
        self.assertEqual(plist["StartInterval"], 900)
        self.assertEqual(plist["ProgramArguments"][0], sys.executable)
        self.assertEqual(
            plist["ProgramArguments"][1:],
            ["-m", "control", "log-rotation", "--max-bytes", "123", "--keep", "4"],
        )
        self.assertTrue(os.access(plist["ProgramArguments"][0], os.X_OK))

    def test_the_agent_rotates_its_own_logs(self):
        # Its output must match the glob it sweeps, or the rotator becomes the
        # next unbounded log.
        plist = logrotate.agent_plist()

        for key in ("StandardOutPath", "StandardErrorPath"):
            self.assertTrue(
                Path(plist[key]).match(logrotate.LOG_GLOB),
                f"{key} {plist[key]} does not match {logrotate.LOG_GLOB}",
            )


class SizeParsingTests(unittest.TestCase):
    def test_parses_plain_bytes_and_suffixes(self):
        self.assertEqual(logrotate.parse_size("52428800"), 52428800)
        self.assertEqual(logrotate.parse_size("50M"), 50 * 1024**2)
        self.assertEqual(logrotate.parse_size("50MiB"), 50 * 1024**2)
        self.assertEqual(logrotate.parse_size("1G"), 1024**3)

    def test_rejects_nonsense(self):
        with self.assertRaises(ValueError):
            logrotate.parse_size("plenty")


if __name__ == "__main__":
    unittest.main()
