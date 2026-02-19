"""In-store stock checker for Target and Walmart.

Check local store inventory by ZIP code.

Usage via CLI:
    python -m pokeping --store-check --zip 10001
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)

# Target store search API
TARGET_STORE_API = "https://redsky.target.com/redsky_aggregations/v1/web/store_location_v1"
TARGET_STOCK_API = "https://redsky.target.com/redsky_aggregations/v1/web/product_summary_with_fulfillment_v1"
TARGET_API_KEY = "9f36aeafbe60771e321a7cc95a78140772ab3e96"

# Walmart store search
WALMART_STORE_API = "https://www.walmart.com/store/finder/electrode/api/stores"


async def check_target_stores(
    session: aiohttp.ClientSession,
    tcin: str,
    zip_code: str,
    radius: int = 50,
    limit: int = 10,
) -> list[dict]:
    """Check Target store inventory for a product near a ZIP code.

    Returns a list of dicts with store name, distance, and stock status.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    # Query the fulfillment API with the ZIP — it returns nearby store availability
    params = {
        "key": TARGET_API_KEY,
        "tcins": tcin,
        "zip": zip_code,
        "state": "",
        "latitude": "",
        "longitude": "",
    }

    url = f"{TARGET_STOCK_API}?{urlencode(params)}"
    results = []

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with session.get(url, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            data = await resp.json()

        summaries = data.get("data", {}).get("product_summaries", [])
        if not summaries:
            return results

        product = summaries[0]
        fulfillment = product.get("fulfillment", {})

        # Check store pickup options
        store_options = fulfillment.get("store_options", [])
        for store in store_options[:limit]:
            store_info = store.get("location_name", "Unknown Store")
            store_address = store.get("location_address", "")
            availability = store.get("order_pickup", {}).get(
                "availability_status", "UNAVAILABLE"
            )
            distance = store.get("distance", "?")

            in_stock = availability in ("IN_STOCK", "LIMITED_STOCK")

            results.append({
                "store": store_info,
                "address": store_address,
                "distance_miles": distance,
                "in_stock": in_stock,
                "status": availability,
            })

    except Exception as exc:
        logger.error("Target store check failed: %s", exc)

    return results


async def check_walmart_stores(
    session: aiohttp.ClientSession,
    product_id: str,
    zip_code: str,
    limit: int = 10,
) -> list[dict]:
    """Check Walmart store inventory for a product near a ZIP code.

    Returns a list of dicts with store name, distance, and stock status.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    # Get nearby Walmart stores
    store_url = f"{WALMART_STORE_API}?singleLineAddr={zip_code}&distance={50}"
    results = []

    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with session.get(store_url, headers=headers, timeout=timeout) as resp:
            resp.raise_for_status()
            data = await resp.json()

        stores = data.get("payload", {}).get("storesData", {}).get("stores", [])

        for store in stores[:limit]:
            store_name = store.get("displayName", "Unknown")
            store_address = store.get("address", {}).get("address", "")
            store_id = store.get("id")
            distance = store.get("distance", "?")

            # Check product availability at this store
            avail_url = (
                f"https://www.walmart.com/terra-firma/item/{product_id}"
                f"?storeId={store_id}"
            )
            try:
                async with session.get(
                    avail_url, headers=headers, timeout=timeout
                ) as avail_resp:
                    if avail_resp.status == 200:
                        avail_data = await avail_resp.json()
                        avail_status = avail_data.get(
                            "availabilityStatus", "NOT_AVAILABLE"
                        )
                        in_stock = avail_status == "IN_STOCK"
                    else:
                        in_stock = False
                        avail_status = "UNKNOWN"
            except Exception:
                in_stock = False
                avail_status = "UNKNOWN"

            results.append({
                "store": store_name,
                "address": store_address,
                "distance_miles": distance,
                "in_stock": in_stock,
                "status": avail_status,
            })

    except Exception as exc:
        logger.error("Walmart store check failed: %s", exc)

    return results


def format_store_results(retailer: str, results: list[dict]) -> str:
    """Format store results for display."""
    if not results:
        return f"  No {retailer} stores found or API unavailable."

    lines = []
    for r in results:
        icon = "🟢" if r["in_stock"] else "🔴"
        dist = f"{r['distance_miles']}mi" if r["distance_miles"] != "?" else ""
        lines.append(f"  {icon} {r['store']} ({dist}) — {r['status']}")

    in_stock_count = sum(1 for r in results if r["in_stock"])
    lines.insert(0, f"  {in_stock_count}/{len(results)} stores in stock:")
    return "\n".join(lines)
