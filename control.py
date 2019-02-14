#!/usr/bin/env python3
from __future__ import print_function



if False:
    import os
    import sys
    if os.geteuid() != 0:
        os.execvp('sudo', ['sudo', '-E', '-n'] + sys.argv)



import os
import sys
import subprocess
import re
import logging
import yaml
import jsonschema
import shlex
import pipes



DEVNULL = open(os.devnull, 'w')



def execute(
    args,
    stdin=None,
    stdout=None,
    stderr=None,
    cwd=None,
    env=None
):
    # @TODO: return status?
    # @TODO: devnull stdout, stderr etc.?
    # @TODO: sudo?
    # @TODO: pass string as stdin? get string from stdout?
    proc = subprocess.Popen(
        args,
        stdin=stdin, stdout=stdout, stderr=stderr,
        cwd=cwd,
        env=env,
    )
    proc.wait()
    # if retcode:
    #     cmd = kwargs.get("args")
    #     if cmd is None:
    #         cmd = popenargs[0]
    #     raise CalledProcessError(retcode, cmd)




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
            },
        ],
    }

    def __init__(self):
        super().__init__()

    def to_dict(self):
        res = super().to_dict()
        return res

    def __repr__(self):
        return repr(self.to_dict())
        # return repr(self.__dict__)

    def parse_dict(self, data):
        jsonschema.validate(data, self.schema)
        super().parse_dict(data)
        # super parse_dict



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
            service = Service()
            service.parse_dict(value.copy())
            self.services[key] = service



config_schema = {
    'type': 'object',
    'required': ['name'],
    'properties': {
        'name': { 'type': 'string' },
        'version': { 'type': 'string', 'enum': [ 'https://github.com/mo22/control' ] },
        'services': {
            'type': 'object',
            'additionalProperties': {
                'type': 'object',
                'properties': {
                    'cmd': { 'type': 'string' },
                    'env': { 'type': 'object' },
                    'args': { 'type': 'array' },
                    'run': { 'type': 'string' },
                    'shell': { 'type': 'string' },
                },
                'oneOf': [
                    { 'required': ['run'] },
                    { 'required': ['cmd'] },
                    { 'required': ['shell'] },
                ],
            },
        },
    },
}

def config_load(path):
    with open(path, 'r') as fp:
        config = yaml.load(fp)

    tmp = Config()
    tmp.parse_dict(config.copy())
    tmp.path = path
    print(yaml.safe_dump(tmp.to_dict()))

    jsonschema.validate(config, config_schema)
    config['path'] = path
    if not 'root' in config:
        config['root'] = os.path.realpath(os.path.dirname(path))
    if not 'services' in config:
        config['services'] = {}
    for name, service in config['services'].items():
        service['name'] = name
        if 'run' in service:
            tmp = shlex.split(service['run'])
            service['cmd'] = tmp[0]
            service['args'] = tmp[1:]
            del service['run']
        if 'shell' in service:
            service['cmd'] = '/bin/sh'
            service['args'] = [ '-c', service['shell'] ]
            del service['shell']
        if not 'cwd' in service:
            service['cwd'] = config['root']
        if service['cmd'].endswith('.js'):
            service['args'] = [service['cmd']] + service.get('args', [])
            service['cmd'] = 'node'
        if not service['cmd'].startswith('/'):
            tmp = os.path.join(config['root'], service['cmd'])
            if os.path.exists(tmp):
                # print('relative path in cmd', service['cmd'], tmp)
                service['cmd'] = tmp
        if not service['cmd'].startswith('/'):
            tmp = subprocess.check_output(['which', service['cmd']]).strip().decode('utf-8')
            if os.path.exists(tmp):
                # print('resolve path', service['cmd'], tmp)
                service['cmd'] = tmp
    return config

def config_get_service(config, name):
    return config['services'].get(name, None)

def config_get_services(config, filter):
    if isinstance(filter, list):
        res = []
        for i in filter:
            res += config_get_services(config, i)
        return res
    if filter in config['services']:
        return [ config['services'][filter] ]
    if filter == 'all':
        return config['services'].values()
    else:
        return []



def systemd_template(config, service):
    # https://www.freedesktop.org/software/systemd/man/systemd.unit.html
    # https://www.freedesktop.org/software/systemd/man/systemd.timer.html
    # https://www.freedesktop.org/software/systemd/man/systemd.service.html
    name = config['name'] + '-' + service['name']
    tpl = '# created by control.py\n'
    tpl += '# control.yaml=%s\n' % (config['path'], )
    tpl += '\n'
    tpl += '[Unit]\n'
    tpl += 'Description=%s\n' % (name, )
    tpl += 'After=syslog.target network.target\n'
    tpl += '\n'
    tpl += '[Service]\n'
    tpl += 'Type=simple\n'
    # tpl += 'KillMode=process\n'
    # @TODO: config
    tpl += 'Restart=on-failure\n'
    tpl += 'SyslogIdentifier=%s\n' % (name, )
    if 'nofile' in service:
        tpl += 'LimitNOFILE=%d\n' % (service['nofile'], )
    tpl += 'User=%s\n' % (service.get('user', 'root'), )
    cwd = os.path.realpath(service.get('cwd', '.'))
    tmp = [ service['cmd'] ] + service['args']
    execStart = ' '.join([ pipes.quote(i) for i in tmp ])
    tpl += 'ExecStart=%s\n' % (execStart, )
    tpl += 'WorkingDirectory=%s\n' % (cwd, )
    for (k, v) in service.get('env', {}).items():
        tpl += 'Environment=%s=%s\n' % (k, v)
    # @TODO: only if auto-start
    tpl += '\n'
    tpl += '[Install]\n'
    tpl += 'WantedBy=multi-user.target\n'
    return tpl

def systemd_install(config, service):
    name = config['name'] + '-' + service['name']
    target = '/etc/systemd/system/' + name + '.service'
    tpl = systemd_template(config, service)
    try:
        with open(target, 'r') as fp:
            if fp.read() == tpl:
                return
    except:
        pass
    # sudo?
    with open(target, 'w') as fp:
        fp.write(tpl)

def systemd_uninstall(config, service):
    name = config['name'] + '-' + service['name']
    subprocess.check_call(['systemctl', 'disable', name], stdout=DEVNULL)
    target = '/etc/systemd/system/' + name + '.service'
    if os.isfile(target):
        os.unlink(target)

def systemd_enable(config, service, enable):
    name = config['name'] + '-' + service['name']
    if enable:
        res = subprocess.call(['systemctl', 'enable', name], stdout=DEVNULL, stderr=DEVNULL)
        if res != 0 and res != 1: raise subprocess.CalledProcessError(res)
    else:
        res = subprocess.call(['systemctl', 'disable', name], stdout=DEVNULL, stderr=DEVNULL)
        if res != 0 and res != 1: raise subprocess.CalledProcessError(res)

def systemd_get_enabled(config, service):
    name = config['name'] + '-' + service['name']
    res = subprocess.call(['systemctl', 'is-enabled', name], stdout=DEVNULL, stderr=DEVNULL)
    return res == 0

def systemd_get_status(config, service):
    name = config['name'] + '-' + service['name']
    res = subprocess.call(['systemctl', 'is-active', name], stdout=DEVNULL)
    if res == 0:
        return 'running'
    elif res == 3:
        return 'stopped'
    else:
        return 'unknown ' + res






def do_run(args):
    config = config_load(args.config)
    services = config_get_services(config, args.name)
    assert len(services) == 1
    service = services[0]
    # @TODO: run multiple commands in parallel?
    cwd = os.path.realpath(service.get('cwd', '.'))
    cmd = service['cmd']
    args = service.get('args', [])
    env = service.get('env', {})
    proc = subprocess.Popen(
        [cmd] + args,
        cwd=cwd,
        env=env,
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
            # proc.send_signal(subprocess.CTRL_C_EVENT)





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


    if True:
        def handle(args):
            config = config_load(args.config)
            print(yaml.dump(config))
        parser = subparsers.add_parser('dump')
        parser.set_defaults(func=handle)


    if True:
        def handle(args):
            config = config_load(args.config)
            print(config['name'])
        parser = subparsers.add_parser('prefix')
        parser.set_defaults(func=handle)



    if True:
        parser = subparsers.add_parser('run', help='run service')
        parser.add_argument('name', help='name of service')
        parser.set_defaults(func=do_run)



    if True:
        def handle(args):
            config = config_load(args.config)
            services = config_get_services(config, args.name)
            for service in services:
                systemd_install(config, service)
        parser = subparsers.add_parser('install', help='install service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=handle)



    if True:
        def handle(args):
            config = config_load(args.config)
            services = config_get_services(config, args.name)
            for service in services:
                systemd_uninstall(config, service)
        parser = subparsers.add_parser('uninstall', help='uninstall service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=handle)



    if True:
        def handle(args):
            # @TODO: wait for result
            # @TODO: do not enable yet.
            config = config_load(args.config)
            services = config_get_services(config, args.name)
            for service in services:
                name = config['name'] + '-' + service['name']
                # systemd_install(config, service)
                subprocess.check_call(['systemctl', 'start', name])
        parser = subparsers.add_parser('start', help='start service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=handle)



    if True:
        def handle(args):
            # @TODO: wait for result
            config = config_load(args.config)
            services = config_get_services(config, args.name)
            for service in services:
                name = config['name'] + '-' + service['name']
                subprocess.check_call(['systemctl', 'stop', name])
        parser = subparsers.add_parser('stop', help='stop service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=handle)



    if True:
        def handle(args):
            config = config_load(args.config)
            services = config_get_services(config, args.name)
            for service in services:
                name = config['name'] + '-' + service['name']
                # also start if not running?
                subprocess.check_call(['systemctl', 'restart', name])
        parser = subparsers.add_parser('restart', help='restart service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=handle)



    if True:
        def handle(args):
            config = config_load(args.config)
            service = config_get_service(config, args.name)
            status = systemd_get_status(config, service)
            if status == 'running':
                sys.exit(0)
            else:
                sys.exit(1)
        parser = subparsers.add_parser('is-running', help='check if service is running')
        parser.add_argument('name', help='name of service')
        parser.set_defaults(func=handle)
        # @TODO: additional help?



    if True:
        def handle(args):
            config = config_load(args.config)
            service = config_get_service(config, args.name)
            status = systemd_get_enabled(config, service)
            if status:
                sys.exit(0)
            else:
                sys.exit(1)
        parser = subparsers.add_parser('is-enabled', help='check if service is enabled')
        parser.add_argument('name', help='name of service')
        parser.set_defaults(func=handle)



    if True:
        def handle(args):
            config = config_load(args.config)
            services = config_get_services(config, args.name)
            for service in services:
                systemd_enable(config, service, True)
        parser = subparsers.add_parser('enable', help='enable service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=handle)



    if True:
        def handle(args):
            config = config_load(args.config)
            services = config_get_services(config, args.name)
            for service in services:
                systemd_enable(config, service, False)
        parser = subparsers.add_parser('disable', help='disable service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.set_defaults(func=handle)



    if True:
        def handle(args):
            config = config_load(args.config)
            services = config_get_services(config, args.name or 'all')
            for service in services:
                status = systemd_get_status(config, service)
                print(service['name'], status)
                if args.full:
                    name = config['name'] + '-' + service['name']
                    subprocess.call(['systemctl', 'status', '--no-pager', name])
        parser = subparsers.add_parser('status', help='status service')
        parser.add_argument('name', nargs='*', help='name of service')
        parser.add_argument('--full', '-f', action='store_true')
        parser.set_defaults(func=handle)



    if True:
        def handle(args):
            config = config_load(args.config)
            for service in config['services'].values():
                status = systemd_get_status(config, service)
                enabled = systemd_get_enabled(config, service)
                print(service['name'], 'enabled' if enabled else 'disabled', status)
                if args.full:
                    try:
                        name = config['name'] + '-' + service['name']
                        subprocess.check_call(['systemctl', 'status', '--no-pager', name])
                    except subprocess.CalledProcessError as e:
                        pass
        parser = subparsers.add_parser('list', help='list service')
        parser.add_argument('--full', '-f', action='store_true')
        parser.set_defaults(func=handle)



    if True:
        def handle(args):
            config = config_load(args.config)
            procs = []
            services = config_get_services(config, args.name)
            for service in services:
                name = config['name'] + '-' + service['name']
                cmd = ['journalctl', '-u', name]
                if args.follow: cmd += ['-f']
                proc = subprocess.Popen(cmd) # really?
                procs.append(proc)
            for proc in procs:
                proc.wait()
        parser = subparsers.add_parser('log', help='log service')
        parser.add_argument('name', nargs='+', help='name of service')
        parser.add_argument('--follow', '-f', action='store_true', help='follow')
        parser.set_defaults(func=handle)



    args = mainparser.parse_args()
    if not 'func' in args:
        mainparser.print_usage()
        sys.exit(1)

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    args.func(args)



if __name__ == '__main__':
    main()
