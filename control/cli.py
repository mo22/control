"""Click-based CLI for control."""

import logging

import click

from .api import Commands, Config


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

    # Load config and store in context
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config.load(config)
    ctx.obj["commands"] = Commands(ctx.obj["config"])


@cli.command()
@click.pass_context
def dump(ctx):
    """Dump parsed configuration."""
    ctx.obj["commands"].dump()


@cli.command()
@click.pass_context
def prefix(ctx):
    """Print prefix/name."""
    ctx.obj["commands"].prefix()


@cli.command()
@click.argument("name")
@click.pass_context
def run(ctx, name):
    """Run service."""
    ctx.obj["commands"].run(name=name)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def install(ctx, names):
    """Install service."""
    ctx.obj["commands"].install(names=names)


@cli.command()
@click.argument("names", nargs=-1)
@click.pass_context
def uninstall(ctx, names):
    """Uninstall service."""
    ctx.obj["commands"].uninstall(names=names)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def start(ctx, names):
    """Start service."""
    ctx.obj["commands"].start(names=names)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def stop(ctx, names):
    """Stop service."""
    ctx.obj["commands"].stop(names=names)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def restart(ctx, names):
    """Restart service."""
    ctx.obj["commands"].restart(names=names)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def reload(ctx, names):
    """Reload service."""
    ctx.obj["commands"].reload(names=names)


@cli.command("is-started")
@click.argument("name")
@click.pass_context
def is_started(ctx, name):
    """Check if service is started."""
    ctx.obj["commands"].is_started(name=name)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def enable(ctx, names):
    """Enable service."""
    ctx.obj["commands"].enable(names=names)


@cli.command()
@click.argument("names", nargs=-1, required=True)
@click.pass_context
def disable(ctx, names):
    """Disable service."""
    ctx.obj["commands"].disable(names=names)


@cli.command("is-enabled")
@click.argument("name")
@click.pass_context
def is_enabled(ctx, name):
    """Check if service is enabled."""
    ctx.obj["commands"].is_enabled(name=name)


@cli.command()
@click.argument("names", nargs=-1)
@click.option("--full", "-f", is_flag=True, help="Full status")
@click.pass_context
def status(ctx, names, full):
    """List services and status."""
    ctx.obj["commands"].status(names=names, full=full)


@cli.command()
@click.argument("names", nargs=-1)
@click.pass_context
def json(ctx, names):
    """List services and status as JSON."""
    ctx.obj["commands"].status_json(names=names)


@cli.command()
@click.argument("names", nargs=-1)
@click.option("--follow", "-f", is_flag=True, help="Follow logs")
@click.pass_context
def log(ctx, names, follow):
    """Show logs."""
    ctx.obj["commands"].log(names=names, follow=follow)


def main():
    """Entry point for CLI."""
    cli(obj={})


if __name__ == "__main__":
    main()
