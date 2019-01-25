#!/usr/bin/env python

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



config_schema = {
    'type': 'object',
    'required': ['name'],
    'properties': {
        'name': { 'type': 'string' },
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
    jsonschema.validate(config, config_schema)
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
            print('prefix node.js?')
        if not service['cmd'].startswith('/'):
            if os.path.exists(os.path.join(config['root'], service['cmd'])):
                print('relative path in cmd')
                service['cmd'] = os.path.join(config['root'], service['cmd'])
            else:
                print('check path?')
    return config

def config_service(args):
    config = config_load(args.config)
    service = config['services'].get(args.name, None)
    if not service:
        raise Exception('service %s not defined' % (args.name, ))
    return (config, service)



def systemd_template(config, service):
    name = config['name'] + '-' + service['name']
    tpl = '# created by control.py\n'
    tpl += '[Unit]\n'
    tpl += 'Description=%s\n' % (name, )
    tpl += 'After=syslog.target network.target\n'
    tpl += '[Service]\n'
    tpl += 'Type=simple\n'
    tpl += 'KillMode=process\n'
    tpl += 'Restart=on-failure\n'
    tpl += 'User=root\n'
    tpl += 'SyslogIdentifier=%s\n' % (name, )
    tpl += 'LimitNOFILE=32768\n'
    cwd = os.path.realpath(service.get('cwd', '.'))
    tmp = [ service['cmd'] ] + service['args']
    execStart = ' '.join([ pipes.quote(i) for i in tmp ])
    tpl += 'ExecStart=%s\n' % (execStart, )
    tpl += 'WorkingDirectory=%s\n' % (cwd, )
    for (k, v) in service.get('env', {}).items():
        tpl += 'Environment=%s=%s\n' % (k, v)
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
    with open(target, 'w') as fp:
        fp.write(tpl)
    subprocess.check_call(['systemctl', 'enable', name])


def do_dump(args):
    config = config_load(args.config)
    print(yaml.dumps(config))


def do_run(args):
    (config, service) = config_service(args)
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
    exitcode = proc.wait()
    sys.exit(exitcode)



def do_start(args):
    (config, service) = config_service(args)
    name = config['name'] + '-' + service['name']
    systemd_install(config, service)
    subprocess.check_call(['systemctl', 'start', name])



def do_stop(args):
    (config, service) = config_service(args)
    name = config['name'] + '-' + service['name']
    systemd_install(config, service)
    subprocess.check_call(['systemctl', 'stop', name])



def do_restart(args):
    (config, service) = config_service(args)
    name = config['name'] + '-' + service['name']
    systemd_install(config, service)
    subprocess.check_call(['systemctl', 'restart', name])


def do_status(args):
    (config, service) = config_service(args)
    name = config['name'] + '-' + service['name']
    # subprocess.check_call(['systemctl', 'status', '--no-pager', name])
    subprocess.check_call(['systemctl', 'is-active', name])
    # exit code?



def do_list(args):
    config = config_load(args.config)
    for service in config['services'].values():
        name = config['name'] + '-' + service['name']
        print(name)
        subprocess.check_call(['systemctl', 'status', '--no-pager', name])



def do_log(args):
    (config, service) = config_service(args)
    name = config['name'] + '-' + service['name']
    if args.follow:
        subprocess.check_call(['journalctl', '-f', '-u', name])
    else:
        subprocess.check_call(['journalctl', '-u', name])



def main():
    import argparse

    parser = argparse.ArgumentParser(description='control')
    parser.add_argument('--verbose', action='store_true', default=False, help='verbose mode')
    parser.add_argument('--config', default='control.yaml', help='path to config file')
    subparsers = parser.add_subparsers(help='sub-command help')

    parser_dump = subparsers.add_parser('dump')
    parser_dump.set_defaults(func=do_dump)


    parser_run = subparsers.add_parser('run', help='run service')
    parser_run.add_argument('name', help='name of service')
    parser_run.set_defaults(func=do_run)

    parser_start = subparsers.add_parser('start', help='start service')
    parser_start.add_argument('name', help='name of service')
    parser_start.set_defaults(func=do_start)

    parser_stop = subparsers.add_parser('stop', help='stop service')
    parser_stop.add_argument('name', help='name of service')
    parser_stop.set_defaults(func=do_stop)

    parser_restart = subparsers.add_parser('restart', help='restart service')
    parser_restart.add_argument('name', help='name of service')
    parser_restart.set_defaults(func=do_restart)

    parser_status = subparsers.add_parser('status', help='status service')
    parser_status.add_argument('name', help='name of service')
    parser_status.set_defaults(func=do_status)

    parser_list = subparsers.add_parser('list', help='list service')
    parser_list.set_defaults(func=do_list)

    parser_log = subparsers.add_parser('log', help='log service')
    parser_log.add_argument('name', help='name of service')
    parser_log.add_argument('--follow', '-f', action='store_true', help='follow')
    parser_log.set_defaults(func=do_log)

    # [ ] start all / stop all ?
    # [ ] start prefix* ?
    # [ ] status
    # [ ] log / logtail
    # [ ] list
    # [ ] crons?
    # [ ] trigger? manual / system-start / cron?
    # [ ] update to update systemd stuff?
    # [ ] restart

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    args.func(args)



if __name__ == '__main__':
    main()
