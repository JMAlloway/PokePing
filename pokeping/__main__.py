"""PokePing CLI entry point.

Usage:
    python -m pokeping                     # Run with default config
    python -m pokeping --config my.yaml    # Run with custom config
    python -m pokeping --add-product       # Interactive product setup
    python -m pokeping --store-check --zip 90210  # Check in-store stock
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

import aiohttp

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
    parser.add_argument(
        "--store-check",
        action="store_true",
        help="Check in-store stock at nearby Target/Walmart stores",
    )
    parser.add_argument(
        "--zip",
        default=None,
        help="ZIP code for in-store stock check (use with --store-check)",
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
        "costco", "samsclub", "barnesnoble",
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


async def run_store_check(config: dict, zip_code: str):
    """Check in-store stock at nearby Target and Walmart stores."""
    import re
    from .store_check import (
        check_target_stores,
        check_walmart_stores,
        format_store_results,
    )
    from .retailers.target import extract_tcin
    from .retailers.walmart import extract_product_id

    products = config.get("products", [])
    if not products:
        print("No products configured. Add products to config.yaml first.")
        return

    async with aiohttp.ClientSession() as session:
        for product in products:
            name = product.get("name", "Unknown")
            urls = product.get("urls", {})
            print(f"\n{'='*60}")
            print(f"  {name}")
            print(f"  ZIP: {zip_code}")
            print(f"{'='*60}")

            # Check Target
            target_url = urls.get("target", "")
            tcin = extract_tcin(target_url) if target_url else None
            if tcin:
                print(f"\n  Target (TCIN {tcin}):")
                results = await check_target_stores(
                    session, tcin, zip_code
                )
                print(format_store_results("Target", results))
            else:
                print("\n  Target: No Target URL configured")

            # Check Walmart
            walmart_url = urls.get("walmart", "")
            product_id = extract_product_id(walmart_url) if walmart_url else None
            if product_id:
                print(f"\n  Walmart (ID {product_id}):")
                results = await check_walmart_stores(
                    session, product_id, zip_code
                )
                print(format_store_results("Walmart", results))
            else:
                print("\n  Walmart: No Walmart URL configured")

    print()


def main():
    args = parse_args()
    setup_logging(args.verbose)

    if args.add_product:
        add_product_interactive(args.config)
        return

    config = load_config(args.config)

    if args.store_check:
        zip_code = args.zip
        if not zip_code:
            zip_code = input("Enter ZIP code: ").strip()
        if not zip_code:
            print("ZIP code is required for store check.")
            sys.exit(1)
        asyncio.run(run_store_check(config, zip_code))
        return

    if not config.get("discord_webhook_url"):
        print(
            "WARNING: No Discord webhook URL configured.\n"
            "Set POKEPING_DISCORD_WEBHOOK env var or discord_webhook_url in config.yaml\n"
            "Alerts will be logged but not sent to Discord.\n"
        )

    asyncio.run(run(config))


if __name__ == "__main__":
    main()
