"""Randomized user-agent strings to reduce fingerprinting.

Provides a pool of realistic, modern browser UA strings that rotate
per-request to avoid simple UA-based blocking.
"""

from __future__ import annotations

import random

# Realistic Chrome/Edge/Firefox UAs across Windows/Mac/Linux — updated regularly
_UA_POOL = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    # Chrome on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
    # Firefox on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    # Safari on Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]

# Matching Sec-CH-UA headers for Chrome UAs
_SEC_CH_UA = [
    '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    '"Google Chrome";v="130", "Chromium";v="130", "Not_A Brand";v="24"',
    '"Google Chrome";v="129", "Chromium";v="129", "Not_A Brand";v="24"',
    '"Microsoft Edge";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    '"Microsoft Edge";v="130", "Chromium";v="130", "Not_A Brand";v="24"',
]


class RandomUserAgent:
    """Provides randomized user-agent strings and matching headers."""

    def __init__(self, custom_uas: list[str] | None = None):
        self._pool = list(custom_uas) if custom_uas else list(_UA_POOL)

    def get(self) -> str:
        """Return a random user-agent string."""
        return random.choice(self._pool)

    def get_headers(self) -> dict[str, str]:
        """Return a full set of browser-like headers with a random UA.

        Includes Sec-CH-UA headers that match the selected UA family.
        """
        ua = self.get()
        headers: dict[str, str] = {
            "User-Agent": ua,
            "Accept-Language": random.choice([
                "en-US,en;q=0.9",
                "en-US,en;q=0.9,es;q=0.8",
                "en-US,en;q=0.8",
                "en-GB,en;q=0.9,en-US;q=0.8",
            ]),
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

        # Add Sec-CH-UA for Chrome/Edge UAs
        if "Chrome" in ua and "Firefox" not in ua and "Safari/605" not in ua:
            headers["Sec-CH-UA"] = random.choice(_SEC_CH_UA)
            headers["Sec-CH-UA-Mobile"] = "?0"

            if "Windows" in ua:
                headers["Sec-CH-UA-Platform"] = '"Windows"'
            elif "Macintosh" in ua:
                headers["Sec-CH-UA-Platform"] = '"macOS"'
            elif "Linux" in ua:
                headers["Sec-CH-UA-Platform"] = '"Linux"'

            headers["Upgrade-Insecure-Requests"] = "1"

        return headers
