"""Proxy rotation for retailer requests.

Supports a list of HTTP/HTTPS/SOCKS proxies loaded from config or env.
Rotates through them round-robin, with automatic removal of dead proxies
and periodic re-checking.
"""

from __future__ import annotations

import logging
import os
import time
from threading import RLock

logger = logging.getLogger(__name__)


class ProxyRotator:
    """Round-robin proxy rotator with dead-proxy tracking.

    Usage:
        rotator = ProxyRotator.from_config(config)
        proxy = rotator.next()  # Returns proxy URL or None
    """

    # How long (seconds) to wait before retrying a dead proxy
    COOLDOWN_SECONDS = 300

    def __init__(self, proxies: list[str] | None = None):
        self._all_proxies: list[str] = list(proxies or [])
        self._dead: dict[str, float] = {}  # proxy -> time marked dead
        self._lock = RLock()
        self._index = 0

    @classmethod
    def from_config(cls, config: dict) -> ProxyRotator:
        """Build a ProxyRotator from config dict and/or environment.

        Config keys checked:
          - proxy_list: list of proxy URLs
          - proxy_file: path to a file with one proxy per line

        Environment variables:
          - POKEPING_PROXIES: comma-separated proxy URLs
          - POKEPING_PROXY_FILE: path to proxy list file
        """
        proxies: list[str] = []

        # From config
        proxies.extend(config.get("proxy_list", []))

        proxy_file = config.get("proxy_file") or os.environ.get("POKEPING_PROXY_FILE")
        if proxy_file:
            try:
                with open(proxy_file) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            proxies.append(line)
            except OSError as exc:
                logger.warning("Could not read proxy file %s: %s", proxy_file, exc)

        # From environment
        env_proxies = os.environ.get("POKEPING_PROXIES", "")
        if env_proxies:
            proxies.extend(p.strip() for p in env_proxies.split(",") if p.strip())

        if proxies:
            logger.info("Loaded %d proxies for rotation", len(proxies))
        else:
            logger.debug("No proxies configured — all requests will use direct connection")

        return cls(proxies)

    @property
    def has_proxies(self) -> bool:
        return len(self._all_proxies) > 0

    @property
    def active_count(self) -> int:
        now = time.time()
        with self._lock:
            return sum(
                1 for p in self._all_proxies
                if p not in self._dead or (now - self._dead[p]) > self.COOLDOWN_SECONDS
            )

    def next(self) -> str | None:
        """Get the next proxy URL, or None if no proxies are configured/available."""
        if not self._all_proxies:
            return None

        now = time.time()

        with self._lock:
            # Try each proxy in round-robin order
            for _ in range(len(self._all_proxies)):
                proxy = self._all_proxies[self._index % len(self._all_proxies)]
                self._index += 1

                # Skip dead proxies that are still in cooldown
                dead_time = self._dead.get(proxy)
                if dead_time and (now - dead_time) < self.COOLDOWN_SECONDS:
                    continue

                # Revive proxies past cooldown
                if proxy in self._dead:
                    del self._dead[proxy]
                    logger.debug("Reviving proxy after cooldown: %s", _mask_proxy(proxy))

                return proxy

        logger.warning("All %d proxies are in cooldown", len(self._all_proxies))
        return None

    def mark_dead(self, proxy: str) -> None:
        """Mark a proxy as dead (failed request). It will be retried after cooldown."""
        with self._lock:
            self._dead[proxy] = time.time()
            active = self.active_count
        logger.warning(
            "Proxy marked dead: %s (%d active remaining)",
            _mask_proxy(proxy),
            active,
        )

    def mark_alive(self, proxy: str) -> None:
        """Mark a proxy as alive (successful request)."""
        with self._lock:
            self._dead.pop(proxy, None)


def _mask_proxy(proxy: str) -> str:
    """Mask proxy credentials for logging."""
    if "@" in proxy:
        # http://user:pass@host:port -> http://***@host:port
        scheme_end = proxy.index("://") + 3 if "://" in proxy else 0
        at_pos = proxy.index("@")
        return proxy[:scheme_end] + "***" + proxy[at_pos:]
    return proxy
