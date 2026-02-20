"""Configuration loader."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config.yaml")
LOCAL_CONFIG_PATH = Path("config.local.yaml")


def load_config(path: str | None = None) -> dict:
    """Load config from YAML file, with local overrides and env var support.

    Priority (highest to lowest):
      1. Environment variables (POKEPING_DISCORD_WEBHOOK, etc.)
      2. config.local.yaml
      3. config.yaml (or specified path)
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not config_path.exists():
        logger.warning("Config file not found: %s — using defaults", config_path)
        config = {}
    else:
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    # Apply local overrides
    if LOCAL_CONFIG_PATH.exists():
        with open(LOCAL_CONFIG_PATH, encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        config = _deep_merge(config, local)

    # Apply environment variable overrides
    env_overrides = {
        "POKEPING_DISCORD_WEBHOOK": "discord_webhook_url",
        "POKEPING_POLL_INTERVAL": ("poll_interval", int),
        "POKEPING_AMAZON_TAG": ("affiliate.amazon_tag", str),
        "POKEPING_TARGET_TAG": ("affiliate.target_tag", str),
        "POKEPING_WALMART_TAG": ("affiliate.walmart_tag", str),
    }

    for env_var, target in env_overrides.items():
        value = os.environ.get(env_var)
        if value is not None:
            if isinstance(target, tuple):
                key_path, cast = target
                value = cast(value)
            else:
                key_path = target
            _set_nested(config, key_path, value)

    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _set_nested(d: dict, key_path: str, value):
    """Set a nested dict value using dot notation (e.g., 'affiliate.amazon_tag')."""
    keys = key_path.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value
