"""Configuration management for discoder."""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".discoder"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    """Load config from ~/.discoder/config.json."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save_config(config: dict) -> None:
    """Save config to ~/.discoder/config.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_token() -> str | None:
    """Get Discord bot token from config."""
    return load_config().get("discord_token")


def set_token(token: str) -> None:
    """Save Discord bot token to config."""
    config = load_config()
    config["discord_token"] = token
    save_config(config)
