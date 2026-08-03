#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0", "pydantic>=2.0", "click>=8.1.8"]
# ///
"""Click-based CLI for control."""

import logging

import click

try:
    from .api import Commands, Config
    from .models import ConfigModel
except ImportError:
    from control.api import Commands, Config
    from control.models import ConfigModel


@click.group()
@click.option("--verbose", is_flag=True, help="Verbose mode")
@click.option("--config", default="control.yaml", help="Path to config file")
@click.pass_context
def cli(ctx, verbose, config):
    """Manage processes with systemd."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    # Store config path in context (load lazily)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["_config"] = None
    ctx.obj["_commands"] = None


def get_config(ctx) -> Config:
    """Get or load the config."""
    if ctx.obj["_config"] is None:
        ctx.obj["_config"] = Config.load(ctx.obj["config_path"])
    return ctx.obj["_config"]


def get_commands(ctx) -> Commands:
    """Get or create the commands object."""
    if ctx.obj["_commands"] is None:
        ctx.obj["_commands"] = Commands(get_config(ctx))
    return ctx.obj["_commands"]


@cli.command()
@click.pass_context
def dump(ctx):
    """Dump parsed configuration."""
    get_commands(ctx).dump()


@cli.command()
@click.pass_context
def prefix(ctx):
    """Print prefix/name."""
    get_commands(ctx).prefix()


@cli.command()
@click.argument("name")
@click.pass_context
def run(ctx, name):
    """Run service."""
    get_commands(ctx).run(name=name)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def install(ctx, names):
    """Install service."""
    get_commands(ctx).install(names=names)


@cli.command()
@click.argument("names", nargs=-1)
@click.pass_context
def uninstall(ctx, names):
    """Uninstall service."""
    get_commands(ctx).uninstall(names=names)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def start(ctx, names):
    """Start service."""
    get_commands(ctx).start(names=names)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def stop(ctx, names):
    """Stop service."""
    get_commands(ctx).stop(names=names)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def restart(ctx, names):
    """Restart service."""
    get_commands(ctx).restart(names=names)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def reload(ctx, names):
    """Reload service."""
    get_commands(ctx).reload(names=names)


@cli.command("is-started")
@click.argument("name")
@click.pass_context
def is_started(ctx, name):
    """Check if service is started."""
    get_commands(ctx).is_started(name=name)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def enable(ctx, names):
    """Enable service."""
    get_commands(ctx).enable(names=names)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def disable(ctx, names):
    """Disable service."""
    get_commands(ctx).disable(names=names)


@cli.command("is-enabled")
@click.argument("name")
@click.pass_context
def is_enabled(ctx, name):
    """Check if service is enabled."""
    get_commands(ctx).is_enabled(name=name)


@cli.command()
@click.argument("names", nargs=-1)
@click.option("--full", "-f", is_flag=True, help="Full status")
@click.pass_context
def status(ctx, names, full):
    """List services and status."""
    get_commands(ctx).status(names=names, full=full)


@cli.command()
@click.argument("names", nargs=-1)
@click.pass_context
def json(ctx, names):
    """List services and status as JSON."""
    get_commands(ctx).status_json(names=names)


@cli.command()
@click.argument("names", nargs=-1)
@click.option("--follow", "-f", is_flag=True, help="Follow logs")
@click.option("--since", "-s", default=None, help="Show logs since (e.g. '1 hour', '2026-01-01')")
@click.option("--last", "-n", default=None, type=int, help="Show last N lines")
@click.pass_context
def log(ctx, names, follow, since, last):
    """Show logs."""
    get_commands(ctx).log(names=names, follow=follow, since=since, last=last)


@cli.command("log-rotation")
@click.option(
    "--max-bytes",
    default=None,
    help="Rotate logs larger than this (bytes, or 50M / 1G)",
)
@click.option("--keep", default=None, type=int, help="Compressed generations to keep")
@click.option("--dry-run", is_flag=True, help="Report what would be rotated")
def log_rotation(max_bytes, keep, dry_run):
    """Rotate oversized launchd log files (macOS)."""
    _run_log_rotation(max_bytes=max_bytes, keep=keep, dry_run=dry_run)


@cli.command("install-log-rotation")
@click.option(
    "--max-bytes",
    default=None,
    help="Rotate logs larger than this (bytes, or 50M / 1G)",
)
@click.option("--interval", default=None, help="How often to sweep (e.g. 15m, 1h)")
@click.option("--keep", default=None, type=int, help="Compressed generations to keep")
def install_log_rotation(max_bytes, interval, keep):
    """Install the launchd agent that rotates service logs (macOS)."""
    _install_log_rotation(max_bytes=max_bytes, interval=interval, keep=keep)


@cli.command("uninstall-log-rotation")
def uninstall_log_rotation():
    """Remove the log rotation agent (macOS)."""
    _uninstall_log_rotation()


@cli.command()
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.pass_context
def schema(ctx, output):
    """Generate JSON schema for config file."""
    import json

    schema_json = ConfigModel.model_json_schema()
    schema_str = json.dumps(schema_json, indent=2)

    if output:
        with open(output, "w") as f:
            f.write(schema_str)
        click.echo(f"Schema written to {output}")
    else:
        click.echo(schema_str)


def _logrotate():
    """Import the rotation module, failing loudly on the systemd backend."""
    try:
        from . import logrotate
    except ImportError:
        from control import logrotate

    if not logrotate.is_supported():
        raise click.ClickException(
            "log rotation is macOS-only: systemd services log to journald, "
            "which bounds itself"
        )
    return logrotate


def _run_log_rotation(max_bytes=None, keep=None, dry_run=False):
    lr = _logrotate()
    limit = lr.parse_size(max_bytes) if max_bytes else lr.DEFAULT_MAX_BYTES
    generations = keep if keep is not None else lr.DEFAULT_KEEP
    directory = lr.log_dir()

    with lr.rotation_lock(directory) as acquired:
        if not acquired:
            click.echo("another rotation run is in progress; skipping")
            return
        results = lr.rotate_log_dir(
            directory, max_bytes=limit, keep=generations, dry_run=dry_run
        )

    failed = False
    for result in results:
        if result.error:
            failed = True
            click.echo(f"{result.path.name}: {result.error}", err=True)
        elif result.planned:
            click.echo(f"would rotate {result.path.name} ({lr.human(result.size)})")
        else:
            assert result.archive is not None
            click.echo(
                f"rotated {result.path.name} ({lr.human(result.size)}"
                f" -> {result.archive.name},"
                f" {lr.human(result.archive.stat().st_size)})"
            )
    if dry_run and not results:
        click.echo(f"nothing over {lr.human(limit)} in {directory}")
    if failed:
        raise SystemExit(1)


def _install_log_rotation(max_bytes=None, interval=None, keep=None):
    lr = _logrotate()
    limit = lr.parse_size(max_bytes) if max_bytes else lr.DEFAULT_MAX_BYTES
    seconds = lr.parse_interval(interval) if interval else lr.DEFAULT_INTERVAL
    generations = keep if keep is not None else lr.DEFAULT_KEEP
    if generations < 1:
        raise click.ClickException("--keep must be at least 1")

    existed = lr.install_agent(max_bytes=limit, interval=seconds, keep=generations)
    verb = "reinstalled" if existed else "installed"
    click.echo(
        f"{verb} {lr.LABEL}: sweeping {lr.log_dir()} every {seconds}s,"
        f" rotating logs over {lr.human(limit)},"
        f" keeping {generations} gzipped generation{'s' if generations != 1 else ''}"
    )


def _uninstall_log_rotation():
    lr = _logrotate()
    if lr.uninstall_agent():
        click.echo(f"uninstalled {lr.LABEL}")
    else:
        click.echo(f"{lr.LABEL}: not installed")


def main():
    """Entry point for CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
