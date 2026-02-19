"""PokePing CLI entry point.

Usage:
    python -m pokeping                     # Run with default config
    python -m pokeping --config my.yaml    # Run with custom config
    python -m pokeping --add-product       # Interactive product setup
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from .config import load_config
from .engine import MonitorEngine


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args():
    parser = argparse.ArgumentParser(
        prog="pokeping",
        description="PokePing — Free Pokemon TCG Restock & Drop Alerts",
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to config YAML file (default: config.yaml)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--add-product",
        action="store_true",
        help="Interactive mode: add a product to monitor",
    )
    return parser.parse_args()


def add_product_interactive(config_path: str | None):
    """Simple interactive product addition."""
    import yaml
    from pathlib import Path

    path = Path(config_path) if config_path else Path("config.yaml")
    if not path.exists():
        print(f"Config file not found: {path}")
        sys.exit(1)

    with open(path) as f:
        config = yaml.safe_load(f) or {}

    print("\n=== Add Product to PokePing ===\n")
    name = input("Product name: ").strip()
    if not name:
        print("Product name is required.")
        sys.exit(1)

    print("\nEnter retailer URLs (leave blank to skip):")
    retailers = [
        "target", "walmart", "amazon", "bestbuy",
        "pokemoncenter", "gamestop", "tcgplayer",
    ]

    urls = {}
    for retailer in retailers:
        url = input(f"  {retailer}: ").strip()
        if url:
            urls[retailer] = url

    if not urls:
        print("At least one retailer URL is required.")
        sys.exit(1)

    if "products" not in config or config["products"] is None:
        config["products"] = []

    config["products"].append({"name": name, "urls": urls})

    with open(path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"\nAdded '{name}' with {len(urls)} retailer(s) to {path}")
    print("Run `python -m pokeping` to start monitoring.")


async def run(config: dict):
    engine = MonitorEngine(config)

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()

    def shutdown_handler():
        print("\nShutting down PokePing...")
        asyncio.ensure_future(engine.stop())

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown_handler)

    try:
        await engine.start()
    except KeyboardInterrupt:
        pass
    finally:
        await engine.stop()


def main():
    args = parse_args()
    setup_logging(args.verbose)

    if args.add_product:
        add_product_interactive(args.config)
        return

    config = load_config(args.config)

    if not config.get("discord_webhook_url"):
        print(
            "WARNING: No Discord webhook URL configured.\n"
            "Set POKEPING_DISCORD_WEBHOOK env var or discord_webhook_url in config.yaml\n"
            "Alerts will be logged but not sent to Discord.\n"
        )

    asyncio.run(run(config))


if __name__ == "__main__":
    main()
