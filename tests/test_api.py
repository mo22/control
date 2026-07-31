from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from control.api import Config, LaunchD, Service, SystemD
from control.models import ConfigModel, ServiceModel


def make_service(env: dict[str, str] | None = None) -> Service:
    model = ConfigModel(
        name="test",
        version="https://github.com/mo22/control",
        services={
            "demo": ServiceModel(
                shell="echo ok",
                type="daemon",
                env=env or {},
            )
        },
    )
    config = Config(model, "/tmp/control.yaml")
    service = config.get_service("demo")
    assert service is not None
    return service


class ServiceEnvTests(unittest.TestCase):
    def test_process_env_uses_default_path_when_service_has_no_path(self):
        service = make_service({"LOG_LEVEL": "info"})

        env = service.process_env(
            {"PATH": "/usr/bin", "HOME": "/Users/test"},
            {"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )

        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["HOME"], "/Users/test")
        self.assertEqual(env["LOG_LEVEL"], "info")

    def test_process_env_can_reference_user_env(self):
        service = make_service(
            {
                "PATH": "{user.PATH}:/opt/custom/bin",
                "TOKEN": "{user.CONTROL_TEST_TOKEN}",
            }
        )

        env = service.process_env(
            {"PATH": "/usr/bin:/bin"},
            {"PATH": "/usr/local/bin:/usr/bin:/bin"},
            {"PATH": "/user/bin", "CONTROL_TEST_TOKEN": "secret"},
        )

        self.assertEqual(env["PATH"], "/user/bin:/opt/custom/bin")
        self.assertEqual(env["TOKEN"], "secret")

    def test_process_env_can_reference_system_env(self):
        service = make_service({"PATH": "{sys.PATH}:/opt/custom/bin"})

        env = service.process_env(
            {"PATH": "/user/bin"},
            {"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )

        self.assertEqual(env["PATH"], "/usr/local/bin:/usr/bin:/bin:/opt/custom/bin")

    def test_process_env_leaves_unscoped_placeholders_literal(self):
        service = make_service({"PATH": "$PATH:{PATH}:${PATH:-fallback}:${}"})

        env = service.process_env(
            {"PATH": "/usr/bin"},
            {"PATH": "/usr/local/bin:/usr/bin:/bin"},
        )

        self.assertEqual(env["PATH"], "$PATH:{PATH}:${PATH:-fallback}:${}")

    def test_process_env_raises_when_user_env_is_missing(self):
        service = make_service({"TOKEN": "{user.CONTROL_TEST_TOKEN}"})

        with self.assertRaisesRegex(KeyError, "user.CONTROL_TEST_TOKEN"):
            service.process_env(
                {"PATH": "/usr/bin"},
                {"PATH": "/usr/local/bin:/usr/bin:/bin"},
                {},
            )

    def test_process_env_raises_on_unknown_source_namespace(self):
        service = make_service({"TOKEN": "{env.CONTROL_TEST_TOKEN}"})

        with self.assertRaisesRegex(KeyError, "env.CONTROL_TEST_TOKEN"):
            service.process_env(
                {"PATH": "/usr/bin"},
                {"PATH": "/usr/local/bin:/usr/bin:/bin"},
            )

    def test_process_env_raises_when_system_env_is_missing(self):
        service = make_service({"HOME": "{sys.HOME}"})

        with self.assertRaisesRegex(KeyError, "sys.HOME"):
            service.process_env(
                {"PATH": "/usr/bin"},
                {"PATH": "/usr/local/bin:/usr/bin:/bin"},
            )

    def test_config_env_substitution_leaves_process_env_refs_quietly(self):
        config = ConfigModel(
            name="test",
            version="https://github.com/mo22/control",
            services={
                "demo": ServiceModel(
                    shell="echo ok",
                    type="daemon",
                    env={"TOKEN": "{user.CONTROL_TEST_TOKEN}"},
                )
            },
        )
        output = StringIO()

        with redirect_stdout(output):
            config.apply_env_substitution()

        self.assertEqual(output.getvalue(), "")
        self.assertEqual(
            config.services["demo"].env["TOKEN"],
            "{user.CONTROL_TEST_TOKEN}",
        )

    def test_systemd_template_expands_user_path_reference(self):
        service = make_service({"PATH": "{user.PATH}:/opt/custom/bin"})
        backend = SystemD()
        backend.systemd_version = lambda: 245

        with patch.dict("os.environ", {"PATH": "/usr/bin:/bin"}):
            template = backend.service_template(service)

        self.assertIn("Environment=PATH=/usr/bin:/bin:/opt/custom/bin\n", template)
        self.assertNotIn("{user.PATH}", template)

    def test_launchd_plist_expands_system_path_reference(self):
        service = make_service({"PATH": "{sys.PATH}:/opt/custom/bin"})
        backend = object.__new__(LaunchD)
        backend._detect_path = lambda: "/usr/bin:/bin"

        def get_log_files(service: Service) -> tuple[Path, Path]:
            self.assertEqual(service.name, "demo")
            return Path("/tmp/stdout"), Path("/tmp/stderr")

        backend._get_log_files = get_log_files

        plist = backend._generate_plist(service)

        self.assertEqual(
            plist["EnvironmentVariables"]["PATH"],
            "/usr/local/bin:/usr/bin:/bin:/opt/custom/bin",
        )


class ExecutableArgsTests(unittest.TestCase):
    def test_explicit_symlink_path_stays_unresolved(self):
        target = shutil.which("true")
        self.assertIsNotNone(target)
        assert target is not None

        with TemporaryDirectory() as tmpdir:
            link = Path(tmpdir) / "truth"
            os.symlink(target, link)

            args = ServiceModel(cmd=str(link)).to_executable_args()
            self.assertEqual(args[0], str(link))
            self.assertNotEqual(args[0], os.path.realpath(args[0]))

    def test_bare_command_resolves_on_path_without_following_symlink(self):
        target = shutil.which("true")
        self.assertIsNotNone(target)
        assert target is not None

        with TemporaryDirectory() as tmpdir:
            link = Path(tmpdir) / "control-test-true"
            os.symlink(target, link)

            with patch.dict("os.environ", {"PATH": tmpdir}):
                args = ServiceModel(cmd=link.name).to_executable_args()

            self.assertEqual(args[0], str(link))

    def test_relative_run_path_keeps_venv_interpreter_symlink(self):
        """A ``run:`` command pointing into a virtualenv must stay in the venv.

        ``.venv/bin/python`` is a symlink to the base interpreter, and CPython
        finds ``pyvenv.cfg`` from the invocation path rather than the resolved
        one. Dereferencing the symlink therefore starts Python *outside* the
        virtualenv and every venv-installed import fails. The resolved target is
        also version-stamped, so it would break again on a patch upgrade.
        Regression test for control 0.4/0.5, which used ``os.path.realpath``
        here (fixed in 0.6).
        """
        target = shutil.which("true")
        self.assertIsNotNone(target)
        assert target is not None

        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            versioned_bin = base / "runtime" / "cpython-3.14.3" / "bin"
            versioned_bin.mkdir(parents=True)
            interpreter = versioned_bin / "python3.14"
            shutil.copy(target, interpreter)

            venv_bin = base / ".venv" / "bin"
            venv_bin.mkdir(parents=True)
            os.symlink(interpreter, venv_bin / "python")

            args = ServiceModel(
                run=".venv/bin/python scripts/git-pull.py"
            ).to_executable_args(str(base))

            self.assertEqual(args[0], str(venv_bin / "python"))
            self.assertEqual(args[1], "scripts/git-pull.py")
            self.assertNotIn("cpython-3.14.3", args[0])
            self.assertNotEqual(args[0], os.path.realpath(args[0]))


if __name__ == "__main__":
    unittest.main()
