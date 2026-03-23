"""CLI entrypoint for discoder."""

import logging
import sys

import click

from .config import get_token, set_token, get_backend, set_backend


@click.group()
def main():
    """Control AI coding agents from your phone via Discord."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )


@main.command()
def init():
    """Set up Discord bot token."""
    token = click.prompt("Discord bot token")
    set_token(token)
    click.echo("Token saved to ~/.discoder/config.json")
    click.echo("Run 'discoder start' to launch the bot.")


@main.command()
@click.option("--dir", "-d", default=None, help="Default working directory")
@click.option(
    "--backend", "-b", default=None,
    type=click.Choice(["claude", "codex"]),
    help="AI agent backend (default: from config or claude)",
)
def start(dir, backend):
    """Start the Discord bot."""
    token = get_token()
    if not token:
        click.echo("No token configured. Run 'discoder init' first.", err=True)
        sys.exit(1)

    # Resolve backend: CLI flag > config > default
    backend_name = backend or get_backend()

    from .claude import set_backend as set_active_backend
    set_active_backend(backend_name)

    from .bot import run_bot

    cwd = dir
    click.echo(f"Starting discoder bot (backend: {backend_name}, cwd: {cwd or 'current directory'})...")
    run_bot(token, default_cwd=cwd)


@main.command("set-backend")
@click.argument("backend", type=click.Choice(["claude", "codex"]))
def cmd_set_backend(backend):
    """Set the default AI agent backend."""
    set_backend(backend)
    click.echo(f"Default backend set to: {backend}")


if __name__ == "__main__":
    main()
