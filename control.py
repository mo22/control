#!/usr/bin/env python3
from __future__ import print_function
import os
import sys
import subprocess
import re
import logging
import yaml
import jsonschema
import shlex
import pipes
import io



class Executable(object):
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
        res['args'] = self.args
        if self.env: res['env'] = self.env
        if self.cwd: res['cwd'] = self.cwd
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

        if not os.path.isfile(resolve(self.args[0])) and not '/' in self.args[0]:
            try:
                tmp = subprocess.check_output(['which', self.args[0]]).strip()
                self.args[0] = tmp.decode('utf-8')
            except:
                pass

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
                },
            },
        ],
    }

    def __init__(self, config, name):
        super().__init__()
        self.user = None
        self.type = None
        self.systemd = None
        self.name = name
        self.config = config

    def to_dict(self):
        res = super().to_dict()
        res['user'] = self.user
        res['type'] = self.type
        res['systemd'] = self.systemd
        return res

    def __repr__(self):
        return repr(self.to_dict())

    def parse_dict(self, data):
        jsonschema.validate(data, self.schema)
        super().parse_dict(data)
        self.user = data.pop('user', None)
        self.type = data.pop('type', None)
        self.systemd = data.pop('systemd', None)



class Config(object):
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
        },
    }

    def __init__(self):
        self.version = None
        self.name = None
        self.path = None
        self.services = {}

    def to_dict(self):
        res = {}
        res['version'] = self.version
        res['name'] = self.name
        res['path'] = self.path # ?
        res['services'] = {}
        for k, v in self.services.items():
            res['services'][k] = v.to_dict()
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
            return [ self.services[filter] ]

        if filter == 'all':
            return self.services.values()

        else:
            return []





class SystemD(object):
    unit_path = '/etc/systemd/system/'

    def file_write(self, path, content):
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
        # @TODO: in unit file $ needs to be escaped
        # @TODO: also bash stuff needs to be escaped.
        # https://www.freedesktop.org/software/systemd/man/systemd-escape.html
        if '\n' in s:
            return '\\$' + pipes.quote(s).replace('\n', '\\n')
        else:
            return pipes.quote(s)

    def template(self, service):
        # https://www.freedesktop.org/software/systemd/man/systemd.unit.html
        # https://www.freedesktop.org/software/systemd/man/systemd.timer.html
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
        tpl += 'Restart=on-failure\n' # config?
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

    def install(self, service):
        target = os.path.join(self.unit_path, service.config.name + '-' + service.name + '.service')
        tpl = self.template(service)
        try:
            if self.file_read(target) == tpl:
                return
        except:
            pass
        self.file_write(target, tpl)
        self.run(['systemctl', 'daemon-reload'])

    def uninstall(self, service):
        target = os.path.join(self.unit_path, service.config.name + '-' + service.name + '.service')
        self.file_delete(target)

    def uninstall_all(self, config):
        for file in os.listdir(self.unit_path):
            if not file.endswith('.service'):
                continue
            try:
                self.file_read(os.path.join(self.unit_path, file)).split('\n').index('# control.yaml=' + config.path)
            except:
                continue
            name = file[0:-len('.service')]
            try:
                self.run(['systemctl', 'disable', name])
            except subprocess.CalledProcessError:
                pass
            self.file_delete(os.path.join(self.unit_path, file))

    def start(self, service):
        self.run(['systemctl', 'start', service.config.name + '-' + service.name])

    def stop(self, service):
        self.run(['systemctl', 'stop', service.config.name + '-' + service.name])

    def restart(self, service):
        self.run(['systemctl', 'restart', service.config.name + '-' + service.name])

    def reload(self, service):
        self.run(['systemctl', 'reload', service.config.name + '-' + service.name])

    def is_started(self, service):
        try:
            self.run(['systemctl', 'is-active', service.config.name + '-' + service.name], silent=True)
            return True
        except subprocess.CalledProcessError as e:
            if e.returncode == 3:
                return False
            raise e

    def enable(self, service):
        self.run(['systemctl', 'enable', service.config.name + '-' + service.name])

    def disable(self, service):
        self.run(['systemctl', 'disable', service.config.name + '-' + service.name])

    def is_enabled(self, service):
        try:
            self.run(['systemctl', 'is-enabled', service.config.name + '-' + service.name], silent=True)
            return True
        except subprocess.CalledProcessError as e:
            if e.returncode == 1:
                return False
            raise e



class Commands(object):
    def __init__(self, config):
        self.config = config

    def dump(self):
        print(yaml.dump(self.config.to_dict()))

    def prefix(self):
        print(self.config.name)

    def run(self, name):
        service = self.config.get_service(name)
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
                proc.wait() # no timeout?

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
    if not 'func' in args:
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
