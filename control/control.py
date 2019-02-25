#!/usr/bin/env python3
# pylama:ignore=E501,E303,E302,E305,E722,E201,E202,D100,D101,D102,D103,D105,D107,C901

from __future__ import print_function
import os
import sys
import subprocess
import re
import logging
import yaml
import jsonschema
import shlex
import time


class Executable:
    """Executable."""

    schema = {
        'type': 'object',
        'properties': {
            'cmd': { 'type': 'string' },
            'env': { 'type': 'object' },
            'args': { 'type': 'array' },
            'run': { 'type': 'string' },
            'shell': { 'type': 'string' },
            'cwd': { 'type': 'string' },
        },
        'oneOf': [
            { 'required': ['run'] },
            { 'required': ['cmd'] },
            { 'required': ['shell'] },
        ],
    }

    def __init__(self):
        self.args = None
        self.env = None
        self.cwd = None

    def to_dict(self):
        res = {}
        if self.args:
            res['args'] = self.args
        if self.env:
            res['env'] = self.env
        if self.cwd:
            res['cwd'] = self.cwd
        return res

    def __repr__(self):
        return repr(self.to_dict())

    def parse_dict(self, data):
        jsonschema.validate(data, self.schema)

        if 'run' in data:
            self.args = shlex.split(data.pop('run'))

        if 'shell' in data:
            assert self.args is None
            self.args = [ '/bin/sh', '-c', data.pop('shell') ]

        if 'cmd' in data:
            assert self.args is None
            self.args = [ data.pop('cmd') ] + data.pop('args', [])

        if 'cwd' in data:
            self.cwd = os.path.realpath(data.pop('cwd'))
            assert isinstance(self.cwd, str)

        if 'env' in data:
            self.env = data.pop('env')
            assert isinstance(self.env, dict)

        assert self.args and len(self.args) >= 1

        def resolve(path):
            return os.path.realpath(os.path.join(self.cwd if self.cwd else '.', path))

        if not os.access(resolve(self.args[0]), os.X_OK) and self.args[0].endswith('.js'):
            self.args = ['node'] + self.args
        if not os.access(resolve(self.args[0]), os.X_OK) and self.args[0].endswith('.py'):
            self.args = ['python'] + self.args

        if not os.path.isfile(resolve(self.args[0])) and '/' not in self.args[0]:
            try:
                tmp = subprocess.check_output(['which', self.args[0]]).strip()
                self.args[0] = tmp.decode('utf-8')
            except:
                pass

        self.args[0] = resolve(self.args[0])

        # @TODO: really?
        assert os.path.isfile(resolve(self.args[0])), 'does not exist: {}'.format(resolve(self.args[0]))
        assert os.access(resolve(self.args[0]), os.X_OK), 'not executable: {}'.format(resolve(self.args[0]))



class Service(Executable):
    schema = {
        'allOf': [
            Executable.schema,
            {
                'type': 'object',
                'properties': {
                    'user': { 'type': 'string' },
                    'type': { 'values': ['daemon', 'periodic', 'cron'] },
                    'systemd': { 'type': 'string' },
                    'systemd_timer': { 'type': 'string' },
                    'interval': { 'type': 'string' },
                    'first_interval': { 'type': 'string' },
                    'random_delay': { 'type': 'string' },
                    'cron': { 'type': 'string' },
                },
            },
        ],
    }

    def __init__(self, config, name):
        super().__init__()
        self.user = None
        self.type = None
        self.systemd = None
        self.systemd_timer = None
        self.interval = None
        self.first_interval = None
        self.random_delay = None
        self.cron = None
        self.name = name
        self.config = config

    def to_dict(self):
        res = super().to_dict()
        if self.user:
            res['user'] = self.user
        if self.type:
            res['type'] = self.type
        if self.systemd:
            res['systemd'] = self.systemd
        if self.systemd_timer:
            res['systemd_timer'] = self.systemd_timer
        if self.interval:
            res['interval'] = self.interval
        if self.first_interval:
            res['first_interval'] = self.first_interval
        if self.random_delay:
            res['random_delay'] = self.random_delay
        if self.cron:
            res['cron'] = self.cron
        return res

    def __repr__(self):
        return repr(self.to_dict())

    def parse_dict(self, data):
        jsonschema.validate(data, self.schema)
        super().parse_dict(data)
        self.user = data.pop('user', None)
        self.type = data.pop('type', None)
        self.systemd = data.pop('systemd', None)
        self.systemd_timer = data.pop('systemd_timer', None)
        self.interval = data.pop('interval', None)
        self.first_interval = data.pop('first_interval', None)
        self.random_delay = data.pop('random_delay', None)
        self.cron = data.pop('cron', None)



class Config:
    schema = {
        'type': 'object',
        'required': ['name', 'version'],
        'properties': {
            'name': { 'type': 'string' },
            'version': { 'type': 'string', 'enum': [ 'https://github.com/mo22/control' ] },
            'services': {
                'type': 'object',
                'additionalProperties': Service.schema,
            },
            'env': {
                'type': 'object',
                'additionalProperties': {
                    'type': 'string',
                },
            },
            'groups': {
                'type': 'object',
                'additionalProperties': {
                    'type': 'array',
                    'itemType': 'string',
                },
            },
        },
    }

    def __init__(self):
        self.version = None
        self.name = None
        self.path = None
        self.services = {}
        self.groups = {}
        self.env = {}

    def to_dict(self):
        res = {}
        res['version'] = self.version
        res['name'] = self.name
        res['path'] = self.path  # ?
        res['services'] = {}
        for k, v in self.services.items():
            res['services'][k] = v.to_dict()
        res['groups'] = self.groups
        res['env'] = self.env
        return res

    def __repr__(self):
        return repr(self.to_dict())
        # return repr(self.__dict__)

    def parse_dict(self, data):
        jsonschema.validate(data, self.schema)
        self.version = data.pop('version')
        self.name = data.pop('name')
        # res.path = os.path.realpath(path) if path else None
        for (key, value) in data.pop('services', {}).items():
            service = Service(self, key)
            service.parse_dict(value.copy())
            self.services[key] = service
        self.groups = data.pop('groups', {})
        self.env = data.pop('env', {})

    @classmethod
    def load(self, path):
        with open(path, 'r') as fp:
            data = yaml.load(fp)
        config = Config()
        config.parse_dict(data)
        config.path = os.path.realpath(path)
        return config

    def get_service(self, name):
        return self.services.get(name, None)

    def get_services(self, filter):
        if isinstance(filter, list):
            res = []
            for i in filter:
                res += self.get_services(i)
            return res

        if filter in self.services:
            return [self.services[filter]]

        if filter == 'all':
            return self.services.values()

        else:
            return []


class SystemD:
    unit_path = '/etc/systemd/system/'

    def file_write(self, path, content):
        try:
            if self.read_file(path) == content:
                return
        except:
            pass
        print('updating', path)
        if os.geteuid() == 0:
            with open(path, 'w') as fp:
                fp.write(content)
        else:
            proc = subprocess.Popen(['sudo', '-n', 'tee', path], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
            proc.communicate(content.encode('utf-8'))
            proc.wait()

    def file_read(self, path):
        with open(path, 'r') as fp:
            return fp.read()

    def file_delete(self, path):
        if os.geteuid() == 0:
            os.unlink(path)
        else:
            subprocess.call(['sudo', '-n', 'rm', path])

    def run(self, args, silent=False):
        if os.geteuid() != 0:
            args = ['sudo', '-n'] + args
        kwargs = {}
        if silent:
            kwargs['stdout'] = subprocess.DEVNULL
            kwargs['stderr'] = subprocess.DEVNULL
        subprocess.check_call(args, **kwargs)

    def quote(self, s):
        # escape for systemd
        if not re.search('[\x00-\x1f\x7f-\x9f]', s):
            return s
        # repr pretty much matches systemd escaping.. but verify this
        return repr(s)

    def service_template(self, service):
        if not service.args:
            raise Exception('args empty')
        if not service.name:
            raise Exception('name empty')
        if not service.config or not service.config.name:
            raise Exception('config empty')
        # https://www.freedesktop.org/software/systemd/man/systemd.unit.html
        # https://www.freedesktop.org/software/systemd/man/systemd.service.html
        tpl = '# created by control.py\n'
        tpl += '# control.yaml=%s\n' % (service.config.path, )
        tpl += '\n'

        tpl += '[Unit]\n'
        tpl += 'Description=%s\n' % (service.config.name + '-' + service.name, )
        tpl += 'After=syslog.target network.target\n'
        tpl += '\n'

        tpl += '[Service]\n'
        tpl += 'Type=simple\n'
        tpl += 'Restart=on-failure\n'  # config?
        tpl += 'SyslogIdentifier=%s\n' % (service.config.name + '-' + service.name, )
        tpl += 'User=%s\n' % (service.user or 'root', )
        tpl += 'ExecStart=%s\n' % (' '.join([ self.quote(i) for i in service.args ]), )
        tpl += 'WorkingDirectory=%s\n' % (os.path.realpath(service.cwd or os.path.dirname(service.config.path)), )
        if service.env:
            for (k, v) in service.env.items():
                tpl += 'Environment=%s=%s\n' % (k, v)
        if service.systemd:
            tpl += service.systemd
            if not service.systemd.endswith('\n'):
                tpl += '\n'

        if service.type == 'daemon':
            tpl += '\n'
            tpl += '[Install]\n'
            tpl += 'WantedBy=multi-user.target\n'

        return tpl

    def timer_template(self, service):
        # https://www.freedesktop.org/software/systemd/man/systemd.timer.html
        # https://www.freedesktop.org/software/systemd/man/systemd.time.html
        if service.type != 'periodic' and service.type != 'cron':
            return None
        if not service.config or not service.config.name:
            raise Exception('config empty')
        tpl = '# created by control.py\n'
        tpl += '# control.yaml=%s\n' % (service.config.path, )
        tpl += '\n'
        tpl += '[Unit]\n'
        tpl += 'Description=%s\n' % (service.config.name + '-' + service.name, )
        tpl += '\n'
        tpl += '[Timer]\n'
        if service.interval is not None and service.type == 'periodic':
            tpl += 'OnActiveSec=%s\n' % (service.first_interval or service.interval, )
            tpl += 'OnUnitActiveSec=%s\n' % (service.interval, )
        if service.cron is not None and service.type == 'cron':
            tpl += 'OnCalendar=%s\n' % (service.cron, )
            # Persistent=true
        if service.random_delay is not None:
            tpl += 'RandomizedDelaySec=%s\n' % (service.random_delay, )
        if service.systemd_timer:
            tpl += service.systemd_timer
            if not service.systemd_timer.endswith('\n'):
                tpl += '\n'
        tpl += '\n'
        tpl += '[Install]\n'
        tpl += 'WantedBy=timers.target\n'
        return tpl

    def install(self, service):
        tpl = self.service_template(service)
        if tpl:
            target = os.path.join(self.unit_path, service.config.name + '-' + service.name + '.service')
            self.file_write(target, tpl)

        tpl = self.timer_template(service)
        if tpl:
            target = os.path.join(self.unit_path, service.config.name + '-' + service.name + '.timer')
            self.file_write(target, tpl)

        self.run(['systemctl', 'daemon-reload'])
        self.enable(service)

    def uninstall(self, service):
        try:
            self.stop(service)
        except:
            pass
        try:
            self.disable(service)
        except:
            pass
        target = os.path.join(self.unit_path, service.config.name + '-' + service.name + '.service')
        self.file_delete(target)
        target = os.path.join(self.unit_path, service.config.name + '-' + service.name + '.timer')
        self.file_delete(target)

    def uninstall_all(self, config):
        for file in os.listdir(self.unit_path):
            if file.endswith('.timer'):
                try:
                    self.file_read(os.path.join(self.unit_path, file)).split('\n').index('# control.yaml=' + config.path)
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
        for file in os.listdir(self.unit_path):
            if file.endswith('.service'):
                try:
                    self.file_read(os.path.join(self.unit_path, file)).split('\n').index('# control.yaml=' + config.path)
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

    def start(self, service):
        print('start', service.name)
        try:
            self.run(['systemctl', 'start', service.config.name + '-' + service.name + '.service'])
            time.sleep(1)
            self.run(['systemctl', 'is-active', service.config.name + '-' + service.name + '.service'], silent=True)
        except subprocess.CalledProcessError:
            try:
                self.run(['systemctl', 'status', service.config.name + '-' + service.name + '.service'])
            except subprocess.CalledProcessError:
                pass

    def stop(self, service):
        print('stop', service.name)
        self.run(['systemctl', 'stop', service.config.name + '-' + service.name + '.service'])

    def restart(self, service):
        print('restart', service.name)
        self.run(['systemctl', 'restart', service.config.name + '-' + service.name + '.service'])

    def reload(self, service):
        print('reload', service.name)
        self.run(['systemctl', 'reload', service.config.name + '-' + service.name + '.service'])

    def is_started(self, service):
        try:
            self.run(['systemctl', 'is-active', service.config.name + '-' + service.name + '.service'], silent=True)
            return True
        except subprocess.CalledProcessError as e:
            if e.returncode == 3:
                return False
            raise e

    def enable(self, service):
        print('enable', service.name)
        if service.type == 'daemon':
            self.run(['systemctl', 'enable', service.config.name + '-' + service.name + '.service'])
        elif service.type == 'periodic' or service.type == 'cron':
            self.run(['systemctl', 'enable', service.config.name + '-' + service.name + '.timer'])
            self.run(['systemctl', 'start', service.config.name + '-' + service.name + '.timer'])

    def disable(self, service):
        print('disable', service.name)
        if service.type == 'daemon':
            self.run(['systemctl', 'disable', service.config.name + '-' + service.name + '.service'])
        elif service.type == 'periodic' or service.type == 'cron':
            self.run(['systemctl', 'stop', service.config.name + '-' + service.name + '.timer'])
            self.run(['systemctl', 'disable', service.config.name + '-' + service.name + '.timer'])

    def is_enabled(self, service):
        try:
            if service.type == 'daemon':
                self.run(['systemctl', 'is-enabled', service.config.name + '-' + service.name + '.service'], silent=True)
            elif service.type == 'periodic' or service.type == 'cron':
                self.run(['systemctl', 'is-enabled', service.config.name + '-' + service.name + '.timer'], silent=True)
            return True
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                return False
            raise e



class Commands:
    def __init__(self, config):
        self.config = config

    def dump(self):
        print(yaml.dump(self.config.to_dict()))

    def prefix(self):
        print(self.config.name)

    def run(self, name):
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
                proc.wait()  # no timeout?

    def install(self, names):
        backend = SystemD()
        for service in self.config.get_services(names):
            backend.install(service)

    def uninstall(self, names):
        backend = SystemD()
        if len(names) == 0:
            backend.uninstall_all(self.config)
        for service in self.config.get_services(names):
            backend.uninstall(service)

    def start(self, names):
        backend = SystemD()
        for service in self.config.get_services(names):
            backend.start(service)

    def stop(self, names):
        backend = SystemD()
        for service in self.config.get_services(names):
            backend.stop(service)

    def restart(self, names):
        backend = SystemD()
        for service in self.config.get_services(names):
            backend.restart(service)

    def reload(self, names):
        backend = SystemD()
        for service in self.config.get_services(names):
            backend.reload(service)

    def is_started(self, name):
        backend = SystemD()
        service = self.config.get_service(name)
        backend.is_started(service)

    def enable(self, names):
        backend = SystemD()
        for service in self.config.get_services(names):
            backend.enable(service)

    def disable(self, names):
        backend = SystemD()
        for service in self.config.get_services(names):
            backend.disable(service)

    def is_enabled(self, name):
        backend = SystemD()
        service = self.config.get_service(name)
        backend.is_enabled(service)

    def status(self, names, full=False):
        if len(names) == 0:
            names = 'all'
        backend = SystemD()
        for service in self.config.get_services(names):
            print('{:20s} {:10s} {:10s}'.format(
                service.name,
                'enabled' if backend.is_enabled(service) else 'disabled',
                'running' if backend.is_started(service) else 'stopped'
            ))
            if full:
                try:
                    backend.run(['systemctl', '--no-pager', '--no-ask-password', 'status', service.config.name + '-' + service.name])
                except subprocess.CalledProcessError:
                    pass

    def log(self, names, follow=False):
        backend = SystemD()
        if follow:
            procs = []
            for service in self.config.get_services(names):
                args = ['journalctl', '--no-pager', '-f', '-u', service.config.name + '-' + service.name]
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
            for service in self.config.get_services(names):
                backend.run(['journalctl', '--no-pager', '-u', service.config.name + '-' + service.name])



def main():
    import argparse

    # type=int
    # choices=[0, 1, 2]
    # default=
    # nargs='?',

    mainparser = argparse.ArgumentParser()
    mainparser.add_argument('--verbose', action='store_true', default=False, help='verbose mode')
    mainparser.add_argument('--config', default='control.yaml', help='path to config file')
    subparsers = mainparser.add_subparsers()

    config = None
    commands = None

    if True:
        parser = subparsers.add_parser('dump', help='dump parsed configuration')
        parser.set_defaults(func=lambda args: commands.dump())

    if True:
        parser = subparsers.add_parser('prefix', help='print prefix/name')
        parser.set_defaults(func=lambda args: commands.prefix())

    if True:
        parser = subparsers.add_parser('run', help='run service')
        parser.add_argument('name', help='name of service')
        parser.set_defaults(func=lambda args: commands.run(name=args.name))

    if True:
        parser = subparsers.add_parser('install', help='install service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=lambda args: commands.install(names=args.name))

    if True:
        parser = subparsers.add_parser('uninstall', help='uninstall service')
        parser.add_argument('name', nargs='*', help='name of service')
        parser.set_defaults(func=lambda args: commands.uninstall(names=args.name))

    if True:
        parser = subparsers.add_parser('start', help='start service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=lambda args: commands.start(names=args.name))

    if True:
        parser = subparsers.add_parser('stop', help='stop service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=lambda args: commands.stop(names=args.name))

    if True:
        parser = subparsers.add_parser('restart', help='restart service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=lambda args: commands.restart(names=args.name))

    if True:
        parser = subparsers.add_parser('reload', help='reload service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=lambda args: commands.reload(names=args.name))

    if True:
        parser = subparsers.add_parser('is-started', help='check if service is started')
        parser.add_argument('name', help='name of service')
        parser.set_defaults(func=lambda args: commands.is_started(name=args.name))

    if True:
        parser = subparsers.add_parser('enable', help='enable service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=lambda args: commands.enable(names=args.name))

    if True:
        parser = subparsers.add_parser('disable', help='disable service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=lambda args: commands.disable(names=args.name))

    if True:
        parser = subparsers.add_parser('is-enabled', help='check if service is enabled')
        parser.add_argument('name', help='name of service')
        parser.set_defaults(func=lambda args: commands.is_enabled(name=args.name))

    if True:
        parser = subparsers.add_parser('status', help='list services and status')
        parser.add_argument('name', nargs='*', help='name of service')
        parser.add_argument('--full', '-f', action='store_true', help='full status')
        parser.set_defaults(func=lambda args: commands.status(names=args.name, full=args.full))

    if True:
        parser = subparsers.add_parser('log', help='show logs')
        parser.add_argument('name', nargs='*', help='name of service')
        parser.add_argument('--follow', '-f', action='store_true', help='follow')
        parser.set_defaults(func=lambda args: commands.log(names=args.name, follow=args.follow))

    args = mainparser.parse_args()
    if 'func' not in args:
        mainparser.print_usage()
        sys.exit(1)

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    config = Config.load(args.config)
    commands = Commands(config)

    args.func(args)


if __name__ == '__main__':
    main()
