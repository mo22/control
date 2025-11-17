"""Pydantic models for control.yaml configuration."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ExecutableModel(BaseModel):
    """Model for an executable configuration."""

    cmd: str | None = None
    args: list[str] = Field(default_factory=list)
    run: str | None = None
    shell: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None

    @model_validator(mode='after')
    def validate_executable(self) -> ExecutableModel:
        """Validate that exactly one of cmd, run, or shell is provided."""
        has_cmd = self.cmd is not None
        has_run = self.run is not None
        has_shell = self.shell is not None

        if sum([has_cmd, has_run, has_shell]) != 1:
            raise ValueError('Exactly one of cmd, run, or shell must be provided')

        return self

    def to_executable_args(self, base_cwd: str | None = None) -> list[str]:
        """Convert the model to executable arguments.

        Args:
            base_cwd: Base working directory for resolving paths

        Returns:
            List of arguments to execute
        """
        if self.run:
            exec_args = shlex.split(self.run)
        elif self.shell:
            exec_args = ['/bin/sh', '-c', self.shell]
        elif self.cmd:
            exec_args = [self.cmd] + self.args
        else:
            raise ValueError('No executable configuration provided')

        # Resolve the working directory
        cwd = os.path.realpath(self.cwd) if self.cwd else base_cwd or '.'

        def resolve(path: str) -> str:
            return os.path.realpath(os.path.join(cwd, path))

        # Auto-detect and add interpreters
        if not os.access(resolve(exec_args[0]), os.X_OK) and exec_args[0].endswith('.js'):
            exec_args = ['node'] + exec_args
        if not os.access(resolve(exec_args[0]), os.X_OK) and exec_args[0].endswith('.py'):
            exec_args = ['python'] + exec_args

        # Resolve command path
        if not os.path.isfile(resolve(exec_args[0])) and '/' not in exec_args[0]:
            try:
                result = subprocess.check_output(['which', exec_args[0]]).strip()
                exec_args[0] = result.decode('utf-8')
            except subprocess.CalledProcessError:
                pass

        exec_args[0] = resolve(exec_args[0])

        # Verify the executable exists
        if not os.path.isfile(exec_args[0]):
            raise ValueError(f'Executable does not exist: {exec_args[0]}')

        return exec_args

    def get_cwd(self) -> str | None:
        """Get the resolved working directory."""
        return os.path.realpath(self.cwd) if self.cwd else None


class ServiceModel(ExecutableModel):
    """Model for a service configuration."""

    user: str | None = None
    type: Literal['daemon', 'periodic', 'cron'] | None = None
    systemd: str | None = None
    systemd_timer: str | None = None
    interval: str | None = None
    first_interval: str | None = None
    random_delay: str | None = None
    cron: str | list[str] | None = None
    max_cpu: str | None = None
    max_memory: str | None = None
    max_time: str | None = None
    nofile: int | None = None
    syslog: bool = False


class ConfigModel(BaseModel):
    """Model for the control.yaml configuration."""

    name: str
    version: Literal['https://github.com/mo22/control']
    services: dict[str, ServiceModel] = Field(default_factory=dict)
    env: dict[str, str | int | bool] = Field(default_factory=dict)
    groups: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator('env', mode='before')
    @classmethod
    def normalize_env(cls, v: dict[str, Any]) -> dict[str, str]:
        """Convert all environment variables to strings."""
        return {k: str(val) for k, val in v.items()}

    def apply_env_substitution(self) -> None:
        """Apply environment variable substitution to all fields."""

        def env_subst(data: Any) -> Any:
            if isinstance(data, list):
                return [env_subst(i) for i in data]
            elif isinstance(data, dict):
                return {k: env_subst(v) for k, v in data.items()}
            elif isinstance(data, str):
                for match in re.findall(r'{[^}]+}', data):
                    var_name = match[1:-1]
                    if var_name in self.env:
                        data = data.replace(match, str(self.env[var_name]))
                    else:
                        print(f'WARNING: unknown variable {match}')
                return data
            else:
                return data

        # Apply substitution to services
        for service_name, service in self.services.items():
            service_dict = service.model_dump()
            substituted = env_subst(service_dict)
            self.services[service_name] = ServiceModel(**substituted)

        # Apply substitution to groups
        self.groups = env_subst(self.groups)

    @classmethod
    def load(cls, path: str) -> ConfigModel:
        """Load configuration from a YAML file.

        Args:
            path: Path to the control.yaml file

        Returns:
            Parsed and validated configuration
        """
        import yaml

        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        config = cls(**data)
        config.apply_env_substitution()
        return config
