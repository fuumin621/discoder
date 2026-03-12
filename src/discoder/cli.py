"""CLI entrypoint for discoder."""

import logging
import sys

import click

from .config import get_token, set_token


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
def start(dir):
    """Start the Discord bot."""
    token = get_token()
    if not token:
        click.echo("No token configured. Run 'discoder init' first.", err=True)
        sys.exit(1)

    from .bot import run_bot

    cwd = dir
    click.echo(f"Starting discoder bot (cwd: {cwd or 'current directory'})...")
    run_bot(token, default_cwd=cwd)


if __name__ == "__main__":
    main()
