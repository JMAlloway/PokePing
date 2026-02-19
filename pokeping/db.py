"""SQLite state tracking for stock status changes."""

from __future__ import annotations

import logging
import time

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS product_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer TEXT NOT NULL,
    product_url TEXT NOT NULL,
    product_name TEXT NOT NULL,
    last_status TEXT NOT NULL DEFAULT 'unknown',
    last_price REAL,
    last_checked REAL NOT NULL,
    last_alerted REAL,
    UNIQUE(retailer, product_url)
);

CREATE TABLE IF NOT EXISTS alert_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    retailer TEXT NOT NULL,
    product_url TEXT NOT NULL,
    product_name TEXT NOT NULL,
    old_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    price REAL,
    alerted_at REAL NOT NULL
);
"""


class StateDB:
    """Tracks product stock state to detect changes."""

    def __init__(self, db_path: str = "pokeping.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self):
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("Database connected: %s", self.db_path)

    async def close(self):
        if self._db:
            await self._db.close()

    async def get_last_status(self, retailer: str, product_url: str) -> str | None:
        """Get the last known stock status for a product."""
        async with self._db.execute(
            "SELECT last_status FROM product_state WHERE retailer = ? AND product_url = ?",
            (retailer, product_url),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_last_price(self, retailer: str, product_url: str) -> float | None:
        """Get the last known price for a product."""
        async with self._db.execute(
            "SELECT last_price FROM product_state WHERE retailer = ? AND product_url = ?",
            (retailer, product_url),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def update_status(
        self,
        retailer: str,
        product_url: str,
        product_name: str,
        status: str,
        price: float | None,
    ):
        """Update the stored status for a product."""
        now = time.time()
        await self._db.execute(
            """INSERT INTO product_state (retailer, product_url, product_name, last_status, last_price, last_checked)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(retailer, product_url) DO UPDATE SET
                 last_status = excluded.last_status,
                 last_price = excluded.last_price,
                 last_checked = excluded.last_checked,
                 product_name = excluded.product_name""",
            (retailer, product_url, product_name, status, price, now),
        )
        await self._db.commit()

    async def log_alert(
        self,
        retailer: str,
        product_url: str,
        product_name: str,
        old_status: str,
        new_status: str,
        price: float | None,
    ):
        """Log that an alert was sent."""
        now = time.time()
        await self._db.execute(
            """INSERT INTO alert_log (retailer, product_url, product_name, old_status, new_status, price, alerted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (retailer, product_url, product_name, old_status, new_status, price, now),
        )
        # Also update last_alerted in product_state
        await self._db.execute(
            "UPDATE product_state SET last_alerted = ? WHERE retailer = ? AND product_url = ?",
            (now, retailer, product_url),
        )
        await self._db.commit()
