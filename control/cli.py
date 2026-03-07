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


def main():
    """Entry point for CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
