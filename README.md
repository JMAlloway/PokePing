# PokePing

Free Pokemon TCG Restock & Drop Alerts. Monitors major retailers for stock changes and sends instant notifications to Discord.

## How It Works

PokePing polls retailer APIs and product pages on a configurable interval, detects when stock status changes (out of stock → in stock), and pushes alerts to a Discord channel via webhook.

**API-first, scraper-fallback** — each retailer monitor tries a fast API call first. If the retailer doesn't have a usable API (or it fails), PokePing falls back to HTML scraping.

## Supported Retailers

| Retailer | Method | Notes |
|---|---|---|
| Target | API (Redsky) | Fulfillment availability endpoint |
| Walmart | API + Scrape | GraphQL API with __NEXT_DATA__ fallback |
| Amazon | Scrape | No public stock API |
| Best Buy | API | Fulfillment availability endpoint |
| Pokemon Center | API + Scrape | Heavy Cloudflare protection |
| GameStop | Scrape | JSON-LD structured data |
| TCGplayer | API + Scrape | Marketplace listings |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set your Discord webhook
export POKEPING_DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."

# Add a product to monitor
python -m pokeping --add-product

# Start monitoring
python -m pokeping
```

## Configuration

Edit `config.yaml` or create `config.local.yaml` for local overrides. Environment variables take highest priority:

| Env Variable | Config Key | Description |
|---|---|---|
| `POKEPING_DISCORD_WEBHOOK` | `discord_webhook_url` | Discord webhook URL |
| `POKEPING_POLL_INTERVAL` | `poll_interval` | Check interval in seconds |
| `POKEPING_AMAZON_TAG` | `affiliate.amazon_tag` | Amazon Associates tag |
| `POKEPING_TARGET_TAG` | `affiliate.target_tag` | Target affiliate ID |
| `POKEPING_WALMART_TAG` | `affiliate.walmart_tag` | Walmart affiliate ID |

### Adding Products

Interactive:
```bash
python -m pokeping --add-product
```

Or edit `config.yaml` directly:
```yaml
products:
  - name: "Prismatic Evolutions Elite Trainer Box"
    urls:
      target: "https://www.target.com/p/-/A-91728364"
      walmart: "https://www.walmart.com/ip/123456789"
      amazon: "B0DEXAMPLE"
      bestbuy: "6590001"
      pokemoncenter: "https://www.pokemoncenter.com/product/100-10001/product-name"
```

## Revenue / Monetization

PokePing is free for users. Revenue options:

1. **Affiliate links** — Every alert includes a product link. Configure Amazon Associates, Target, and Walmart affiliate tags to earn commission on purchases driven by your alerts.
2. **Freemium tier** (future) — Free users get standard alerts. Paid tier gets faster polling, price drop alerts, wish lists, and priority notifications.
3. **Sponsored deals** — Local card shops can pay for featured placement in alerts.

## Architecture

```
pokeping/
├── __main__.py          # CLI entry point
├── config.py            # Config loader (YAML + env vars)
├── db.py                # SQLite state tracking
├── discord.py           # Discord webhook alerter
├── engine.py            # Core monitoring loop
└── retailers/
    ├── base.py          # Abstract base (API-first, scrape-fallback)
    ├── target.py        # Target (Redsky API)
    ├── walmart.py       # Walmart (GraphQL + scrape)
    ├── amazon.py        # Amazon (scrape only)
    ├── bestbuy.py       # Best Buy (fulfillment API)
    ├── pokemoncenter.py # Pokemon Center (API + scrape)
    ├── gamestop.py      # GameStop (scrape)
    └── tcgplayer.py     # TCGplayer (API + scrape)
```

## Deployment

Runs on any Python 3.10+ environment. For always-on monitoring:

- **Fly.io** (free tier) — `fly launch` and `fly deploy`
- **Railway** — connect repo, set env vars
- **VPS** — run with `systemd` or `supervisor`
- **Docker** — Dockerfile coming soon

## Limitations

- Retailers may rate-limit or block requests. Consider proxy rotation for production.
- Pokemon Center has aggressive Cloudflare protection; a headless browser may be needed for reliable scraping.
- This is a prototype. API endpoints and page structures change; monitors will need periodic updates.
