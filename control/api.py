"""API layer for control - business logic and command implementations."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from typing import Sequence

import yaml

from .models import ConfigModel, ServiceModel


class Service:
    """Service wrapper that combines model and config reference."""

    def __init__(self, config: Config, name: str, model: ServiceModel):
        self.config = config
        self.name = name
        self.model = model

    @property
    def args(self) -> list[str]:
        """Get executable arguments."""
        base_cwd = os.path.dirname(self.config.path) if self.config.path else None
        return self.model.to_executable_args(base_cwd)

    @property
    def cwd(self) -> str | None:
        """Get working directory."""
        return self.model.get_cwd()

    @property
    def env(self) -> dict[str, str]:
        """Get environment variables."""
        return self.model.env

    @property
    def user(self) -> str | None:
        """Get service user."""
        return self.model.user

    @property
    def type(self) -> str | None:
        """Get service type."""
        return self.model.type

    @property
    def systemd(self) -> str | None:
        """Get systemd configuration."""
        return self.model.systemd

    @property
    def systemd_timer(self) -> str | None:
        """Get systemd timer configuration."""
        return self.model.systemd_timer

    @property
    def interval(self) -> str | None:
        """Get interval for periodic services."""
        return self.model.interval

    @property
    def first_interval(self) -> str | None:
        """Get first interval for periodic services."""
        return self.model.first_interval

    @property
    def random_delay(self) -> str | None:
        """Get random delay."""
        return self.model.random_delay

    @property
    def cron(self) -> str | list[str] | None:
        """Get cron schedule."""
        return self.model.cron

    @property
    def max_cpu(self) -> str | None:
        """Get CPU limit."""
        return self.model.max_cpu

    @property
    def max_memory(self) -> str | None:
        """Get memory limit."""
        return self.model.max_memory

    @property
    def max_time(self) -> str | None:
        """Get time limit."""
        return self.model.max_time

    @property
    def nofile(self) -> int | None:
        """Get file descriptor limit."""
        return self.model.nofile

    @property
    def syslog(self) -> bool:
        """Get syslog flag."""
        return self.model.syslog


class Config:
    """Configuration wrapper that combines model and path."""

    def __init__(self, model: ConfigModel, path: str | None = None):
        self.model = model
        self.path = os.path.realpath(path) if path else None
        self._services: dict[str, Service] = {}

        # Create Service wrappers
        for name, service_model in model.services.items():
            self._services[name] = Service(self, name, service_model)

    @property
    def name(self) -> str:
        """Get configuration name."""
        return self.model.name

    @property
    def version(self) -> str:
        """Get configuration version."""
        return self.model.version

    @property
    def services(self) -> dict[str, Service]:
        """Get services."""
        return self._services

    @property
    def groups(self) -> dict[str, list[str]]:
        """Get service groups."""
        return self.model.groups

    @property
    def env(self) -> dict[str, str]:
        """Get environment variables."""
        return self.model.env

    def get_service(self, name: str) -> Service | None:
        """Get a single service by name.

        Args:
            name: Service name

        Returns:
            Service instance or None if not found
        """
        return self._services.get(name)

    def get_services(self, filter: str | list[str]) -> list[Service]:
        """Get services by filter.

        Args:
            filter: Service name, group name, 'all', or list of names

        Returns:
            List of matching services
        """
        if isinstance(filter, list):
            result = []
            for item in filter:
                result += self.get_services(item)
            return result

        if filter == 'all':
            return list(self._services.values())

        if filter in self._services:
            return [self._services[filter]]

        if filter in self.groups:
            return self.get_services(self.groups[filter])

        return []

    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return {
            'name': self.name,
            'version': self.version,
            'path': self.path,
            'services': {name: svc.model.model_dump() for name, svc in self._services.items()},
            'groups': self.groups,
            'env': self.env,
        }

    @classmethod
    def load(cls, path: str) -> Config:
        """Load configuration from a YAML file.

        Args:
            path: Path to the control.yaml file

        Returns:
            Config instance
        """
        model = ConfigModel.load(path)
        return cls(model, path)


class SystemD:
    """SystemD backend for managing services."""

    unit_path = '/etc/systemd/system/'

    def file_write(self, path: str, content: str) -> None:
        """Write file with sudo if needed."""
        try:
            if self.file_read(path) == content:
                return
        except:
            pass
        print('updating', path)
        if os.geteuid() == 0:
            with open(path, 'w') as fp:
                fp.write(content)
        else:
            proc = subprocess.Popen(
                ['sudo', '-n', 'tee', path],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL
            )
            proc.communicate(content.encode('utf-8'))
            proc.wait()

    def file_read(self, path: str) -> str:
        """Read file."""
        with open(path, 'r') as fp:
            return fp.read()

    def file_delete(self, path: str) -> None:
        """Delete file with sudo if needed."""
        if not os.path.exists(path):
            return
        if os.geteuid() == 0:
            os.unlink(path)
        else:
            subprocess.call(['sudo', '-n', 'rm', path])

    def run(self, args: list[str], silent: bool = False) -> None:
        """Run command with sudo if needed."""
        if os.geteuid() != 0:
            args = ['sudo', '-n'] + args
        kwargs = {}
        if silent:
            kwargs['stdout'] = subprocess.DEVNULL
            kwargs['stderr'] = subprocess.DEVNULL
        subprocess.check_call(args, **kwargs)

    def systemd_version(self) -> int:
        """Get systemd version."""
        tmp = subprocess.check_output(['systemd', '--version'])
        return int(tmp.decode('utf-8').split('\n')[0].split(' ')[1])

    def service_template(self, service: Service) -> str:
        """Generate systemd service template."""
        if not service.args:
            raise Exception('args empty')
        if not service.name:
            raise Exception('name empty')
        if not service.config or not service.config.name:
            raise Exception('config empty')

        version = self.systemd_version()
        tpl = '# created by control.py\n'
        tpl += f'# control.yaml={service.config.path}\n'
        tpl += '\n'

        tpl += '[Unit]\n'
        tpl += f'Description={service.config.name}-{service.name}\n'
        tpl += 'After=syslog.target network.target\n'
        if version > 244:
            tpl += 'StartLimitIntervalSec=0\n'
        else:
            tpl += 'StartLimitInterval=0\n'
        tpl += '\n'

        tpl += '[Service]\n'
        tpl += 'Type=simple\n'
        if service.type == 'daemon':
            tpl += 'Restart=on-failure\n'
            tpl += 'RestartSec=10\n'
        else:
            tpl += 'Restart=no\n'
        tpl += 'StandardOutput=journal\n'
        tpl += 'StandardError=journal\n'
        if service.syslog:
            tpl += f'SyslogIdentifier={service.syslog}\n'
        else:
            tpl += f'SyslogIdentifier={service.config.name}-{service.name}\n'
        tpl += f'User={service.user or "root"}\n'
        tpl += f'ExecStart={" ".join([shlex.quote(i) for i in service.args])}\n'

        cwd = service.cwd or (os.path.dirname(service.config.path) if service.config.path else '.')
        tpl += f'WorkingDirectory={os.path.realpath(cwd)}\n'

        if service.env:
            for k, v in service.env.items():
                tpl += f'Environment={k}={v}\n'
        if service.max_cpu is not None:
            tpl += f'CPUQuota={service.max_cpu}\n'
        if service.max_memory is not None:
            tpl += f'MemoryMax={service.max_memory}\n'
        if service.max_time is not None:
            tpl += f'RuntimeMaxSec={service.max_time}\n'
        if service.nofile is not None:
            tpl += f'LimitNOFILE={service.nofile}\n'
        if service.systemd:
            tpl += service.systemd
            if not service.systemd.endswith('\n'):
                tpl += '\n'

        if service.type == 'daemon':
            tpl += '\n'
            tpl += '[Install]\n'
            tpl += 'WantedBy=multi-user.target\n'

        return tpl

    def timer_template(self, service: Service) -> str | None:
        """Generate systemd timer template."""
        if service.type not in ('periodic', 'cron'):
            return None
        if not service.config or not service.config.name:
            raise Exception('config empty')

        tpl = '# created by control.py\n'
        tpl += f'# control.yaml={service.config.path}\n'
        tpl += '\n'
        tpl += '[Unit]\n'
        tpl += f'Description={service.config.name}-{service.name}\n'
        tpl += '\n'
        tpl += '[Timer]\n'

        if service.interval is not None and service.type == 'periodic':
            tpl += f'OnActiveSec={service.first_interval or service.interval}\n'
            tpl += f'OnUnitActiveSec={service.interval}\n'

        if service.cron is not None and service.type == 'cron':
            crons = service.cron if isinstance(service.cron, list) else [service.cron]
            for cron in crons:
                subprocess.check_output(['systemd-analyze', 'calendar', cron])
                tpl += f'OnCalendar={cron}\n'

        if service.random_delay is not None:
            tpl += f'RandomizedDelaySec={service.random_delay}\n'
        if service.systemd_timer:
            tpl += service.systemd_timer
            if not service.systemd_timer.endswith('\n'):
                tpl += '\n'
        tpl += '\n'
        tpl += '[Install]\n'
        tpl += 'WantedBy=timers.target\n'
        return tpl

    def install(self, service: Service) -> None:
        """Install service."""
        tpl = self.service_template(service)
        if tpl:
            target = os.path.join(
                self.unit_path,
                f'{service.config.name}-{service.name}.service'
            )
            self.file_write(target, tpl)

        tpl = self.timer_template(service)
        if tpl:
            target = os.path.join(
                self.unit_path,
                f'{service.config.name}-{service.name}.timer'
            )
            self.file_write(target, tpl)

        self.run(['systemctl', 'daemon-reload'])
        self.enable(service)

    def uninstall(self, service: Service) -> None:
        """Uninstall service."""
        try:
            self.stop(service)
        except:
            pass
        try:
            self.disable(service)
        except:
            pass

        target = os.path.join(
            self.unit_path,
            f'{service.config.name}-{service.name}.service'
        )
        self.file_delete(target)

        target = os.path.join(
            self.unit_path,
            f'{service.config.name}-{service.name}.timer'
        )
        self.file_delete(target)

    def uninstall_all(self, config: Config) -> None:
        """Uninstall all services from config."""
        for file in os.listdir(self.unit_path):
            if not (file.endswith('.timer') or file.endswith('.service')):
                continue

            try:
                content = self.file_read(os.path.join(self.unit_path, file))
                if f'# control.yaml={config.path}' not in content:
                    continue
            except:
                continue

            try:
                self.run(['systemctl', 'stop', file])
            except subprocess.CalledProcessError:
                pass
            try:
                self.run(['systemctl', 'disable', file])
            except subprocess.CalledProcessError:
                pass
            self.file_delete(os.path.join(self.unit_path, file))

    def start(self, service: Service) -> None:
        """Start service."""
        if self.is_started(service):
            return
        print('start', service.name)
        try:
            self.run(['systemctl', 'start', f'{service.config.name}-{service.name}.service'])
            time.sleep(1)
            self.run(['systemctl', 'is-active', f'{service.config.name}-{service.name}.service'], silent=True)
        except subprocess.CalledProcessError:
            try:
                self.run(['systemctl', 'status', f'{service.config.name}-{service.name}.service'])
            except subprocess.CalledProcessError:
                pass

    def stop(self, service: Service) -> None:
        """Stop service."""
        if not self.is_started(service):
            return
        print('stop', service.name)
        self.run(['systemctl', 'stop', f'{service.config.name}-{service.name}.service'])

    def restart(self, service: Service) -> None:
        """Restart service."""
        print('restart', service.name)
        self.run(['systemctl', 'restart', f'{service.config.name}-{service.name}.service'])

    def reload(self, service: Service) -> None:
        """Reload service."""
        print('reload', service.name)
        self.run(['systemctl', 'reload', f'{service.config.name}-{service.name}.service'])

    def is_started(self, service: Service) -> bool:
        """Check if service is started."""
        try:
            self.run(['systemctl', 'is-active', f'{service.config.name}-{service.name}.service'], silent=True)
            return True
        except subprocess.CalledProcessError as e:
            if e.returncode in (3, 4):
                return False
            raise e

    def enable(self, service: Service) -> None:
        """Enable service."""
        if self.is_enabled(service):
            return
        print('enable', service.name)
        if service.type == 'daemon':
            self.run(['systemctl', 'enable', f'{service.config.name}-{service.name}.service'])
        elif service.type in ('periodic', 'cron'):
            self.run(['systemctl', 'enable', f'{service.config.name}-{service.name}.timer'])
            self.run(['systemctl', 'start', f'{service.config.name}-{service.name}.timer'])

    def disable(self, service: Service) -> None:
        """Disable service."""
        if not self.is_enabled(service):
            return
        print('disable', service.name)
        if service.type == 'daemon':
            self.run(['systemctl', 'disable', f'{service.config.name}-{service.name}.service'])
        elif service.type in ('periodic', 'cron'):
            self.run(['systemctl', 'stop', f'{service.config.name}-{service.name}.timer'])
            self.run(['systemctl', 'disable', f'{service.config.name}-{service.name}.timer'])

    def is_enabled(self, service: Service) -> bool:
        """Check if service is enabled."""
        try:
            if service.type == 'daemon':
                self.run(['systemctl', 'is-enabled', f'{service.config.name}-{service.name}.service'], silent=True)
            elif service.type in ('periodic', 'cron'):
                self.run(['systemctl', 'is-enabled', f'{service.config.name}-{service.name}.timer'], silent=True)
            return True
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                return False
            raise e


class Commands:
    """Command implementations."""

    def __init__(self, config: Config):
        self.config = config

    def dump(self) -> None:
        """Dump configuration."""
        print(yaml.dump(self.config.to_dict()))

    def prefix(self) -> None:
        """Print configuration name."""
        print(self.config.name)

    def run(self, name: str) -> None:
        """Run a service."""
        service = self.config.get_service(name)
        if not service:
            return
        if not service.args:
            return
        proc = subprocess.Popen(
            service.args,
            cwd=service.cwd,
            env=service.env,
            stdout=sys.stdout,
            stderr=sys.stderr,
            stdin=sys.stdin,
        )
        while True:
            try:
                exitcode = proc.wait()
                sys.exit(exitcode)
            except KeyboardInterrupt:
                proc.terminate()
                proc.wait()

    def install(self, names: Sequence[str]) -> None:
        """Install services."""
        backend = SystemD()
        for service in self.config.get_services(list(names)):
            backend.install(service)

    def uninstall(self, names: Sequence[str]) -> None:
        """Uninstall services."""
        backend = SystemD()
        if len(names) == 0:
            backend.uninstall_all(self.config)
        for service in self.config.get_services(list(names)):
            backend.uninstall(service)

    def start(self, names: Sequence[str]) -> None:
        """Start services."""
        backend = SystemD()
        for service in self.config.get_services(list(names)):
            backend.start(service)

    def stop(self, names: Sequence[str]) -> None:
        """Stop services."""
        backend = SystemD()
        for service in self.config.get_services(list(names)):
            backend.stop(service)

    def restart(self, names: Sequence[str]) -> None:
        """Restart services."""
        backend = SystemD()
        for service in self.config.get_services(list(names)):
            backend.restart(service)

    def reload(self, names: Sequence[str]) -> None:
        """Reload services."""
        backend = SystemD()
        for service in self.config.get_services(list(names)):
            backend.reload(service)

    def is_started(self, name: str) -> None:
        """Check if service is started."""
        backend = SystemD()
        service = self.config.get_service(name)
        if service:
            backend.is_started(service)

    def enable(self, names: Sequence[str]) -> None:
        """Enable services."""
        backend = SystemD()
        for service in self.config.get_services(list(names)):
            backend.enable(service)

    def disable(self, names: Sequence[str]) -> None:
        """Disable services."""
        backend = SystemD()
        for service in self.config.get_services(list(names)):
            backend.disable(service)

    def is_enabled(self, name: str) -> None:
        """Check if service is enabled."""
        backend = SystemD()
        service = self.config.get_service(name)
        if service:
            backend.is_enabled(service)

    def status(self, names: Sequence[str], full: bool = False) -> None:
        """Show status of services."""
        service_names = list(names) if names else 'all'
        backend = SystemD()
        for service in sorted(self.config.get_services(service_names), key=lambda i: i.name):
            print('{:30s} {:10s} {:10s}'.format(
                service.name,
                'enabled' if backend.is_enabled(service) else 'disabled',
                'running' if backend.is_started(service) else 'stopped'
            ))
            if full:
                try:
                    backend.run([
                        'systemctl', '--no-pager', '--no-ask-password',
                        'status', f'{service.config.name}-{service.name}'
                    ])
                except subprocess.CalledProcessError:
                    pass

    def status_json(self, names: Sequence[str]) -> None:
        """Show status of services as JSON."""
        service_names = list(names) if names else 'all'
        backend = SystemD()
        res_services = {}
        for service in sorted(self.config.get_services(service_names), key=lambda i: i.name):
            res_service = {
                'name': service.name,
                'enabled': backend.is_enabled(service),
                'started': backend.is_started(service),
            }
            res_services[service.name] = res_service
        print(json.dumps(res_services))

    def log(self, names: Sequence[str], follow: bool = False) -> None:
        """Show logs of services."""
        backend = SystemD()
        if follow:
            procs = []
            for service in self.config.get_services(list(names)):
                args = ['journalctl', '--no-pager', '-f', '-u',
                        f'{service.config.name}-{service.name}']
                if os.getuid() != 0:
                    args = ['sudo', '-n'] + args
                procs.append(subprocess.Popen(args))
            if len(procs) > 0:
                procs[0].wait()
            for proc in procs:
                proc.terminate()
            for proc in procs:
                proc.wait()
        else:
            for service in self.config.get_services(list(names)):
                backend.run(['journalctl', '--no-pager', '-u',
                             f'{service.config.name}-{service.name}'])
