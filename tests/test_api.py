from pathlib import Path
import unittest
from unittest.mock import patch

from control.api import Config, LaunchD, SystemD
from control.models import ConfigModel, ServiceModel


def make_service(env: dict[str, str] | None = None):
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
    return config.get_service("demo")


class ServiceEnvTests(unittest.TestCase):
    def test_process_env_uses_default_path_when_service_has_no_path(self):
        service = make_service({"LOG_LEVEL": "info"})

        env = service.process_env({"PATH": "/usr/bin", "HOME": "/Users/test"})

        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["HOME"], "/Users/test")
        self.assertEqual(env["LOG_LEVEL"], "info")

    def test_process_env_can_extend_default_path(self):
        service = make_service({"PATH": "${PATH}:/opt/custom/bin"})

        env = service.process_env({"PATH": "/usr/bin:/bin"})

        self.assertEqual(env["PATH"], "/usr/bin:/bin:/opt/custom/bin")

    def test_process_env_leaves_other_placeholders_literal(self):
        service = make_service({"PATH": "${PATH}:${OTHER}:${PATH:-fallback}:${}"})

        env = service.process_env({"PATH": "/usr/bin"})

        self.assertEqual(env["PATH"], "/usr/bin:${OTHER}:${PATH:-fallback}:${}")

    def test_process_env_raises_when_path_placeholder_has_no_default(self):
        service = make_service({"PATH": "${PATH}:/opt/custom/bin"})

        with self.assertRaisesRegex(KeyError, "PATH"):
            service.process_env({})

    def test_systemd_template_expands_path_placeholder(self):
        service = make_service({"PATH": "${PATH}:/opt/custom/bin"})
        backend = SystemD()
        backend.systemd_version = lambda: 245

        with patch.dict("os.environ", {"PATH": "/usr/bin:/bin"}):
            template = backend.service_template(service)

        self.assertIn("Environment=PATH=/usr/bin:/bin:/opt/custom/bin\n", template)
        self.assertNotIn("${PATH}", template)

    def test_launchd_plist_expands_path_placeholder(self):
        service = make_service({"PATH": "${PATH}:/opt/custom/bin"})
        backend = object.__new__(LaunchD)
        backend._detect_path = lambda: "/usr/bin:/bin"
        backend._get_log_files = lambda service: (
            Path("/tmp/stdout"),
            Path("/tmp/stderr"),
        )

        plist = backend._generate_plist(service)

        self.assertEqual(
            plist["EnvironmentVariables"]["PATH"],
            "/usr/bin:/bin:/opt/custom/bin",
        )


if __name__ == "__main__":
    unittest.main()
