# SGAbode API Reference

Base URL (production): `https://sgabode-production.up.railway.app`
Base URL (local):       `http://localhost:8000`
Swagger UI:             `https://sgabode-production.up.railway.app/docs`

Admin routes require the header: `X-Admin-Key: <your key from .env>`

---

## Health

### GET /health
Check if the server is running.
```powershell
Invoke-WebRequest https://sgabode-production.up.railway.app/health
```
Response: `{"status": "ok", "service": "SGAbode API"}`

---

## Listings

### GET /listings
List active listings (20 per page by default).

Query params:
- `intent`          — `buy` or `rent`
- `property_type`   — `hdb`, `condo`, `landed`, `commercial`
- `district`        — integer 1–28
- `listing_status`  — `active` (default), `inactive`, `sold`, `rented`
- `skip`            — offset for pagination (default 0)
- `limit`           — results per page (default 20, max any)

```powershell
# All active listings
Invoke-WebRequest "https://sgabode-production.up.railway.app/listings"

# HDB listings for rent
Invoke-WebRequest "https://sgabode-production.up.railway.app/listings?intent=rent&property_type=hdb"

# Condos in District 9, first 50
Invoke-WebRequest "https://sgabode-production.up.railway.app/listings?property_type=condo&district=9&limit=50"

# Page 2 (skip first 20)
Invoke-WebRequest "https://sgabode-production.up.railway.app/listings?skip=20&limit=20"
```

### GET /listings/{listing_id}
Get a single listing with all media.
```powershell
Invoke-WebRequest "https://sgabode-production.up.railway.app/listings/42"
```

### POST /listings
Create a new listing manually.
```powershell
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/listings" `
  -ContentType "application/json" `
  -Body '{
    "title": "4 Room HDB at Bishan St 22",
    "property_type": "hdb",
    "intent": "buy",
    "address": "Blk 123 Bishan St 22, Singapore 570123",
    "postal_code": "570123",
    "district": 20,
    "asking_price": 680000,
    "floor_size": 1001,
    "bedrooms": 4,
    "bathrooms": 2,
    "tenure": "99-year",
    "build_year": 1995
  }'
```

### PATCH /listings/{listing_id}/status
Update a listing's status.

Valid statuses: `active`, `under_offer`, `sold`, `rented`, `inactive`
```powershell
Invoke-WebRequest -Method PATCH `
  "https://sgabode-production.up.railway.app/listings/42/status?new_status=sold"
```

### POST /listings/{listing_id}/media
Upload an image/floor plan for a listing.
```powershell
# Requires multipart form — use Swagger UI at /docs for this one
```

### POST /listings/{listing_id}/trigger-match
Manually re-run matching for a specific listing (sends notifications to matching buyers).
```powershell
Invoke-WebRequest -Method POST `
  "https://sgabode-production.up.railway.app/listings/42/trigger-match"
```

---

## Buyers

### POST /buyers
Register a new buyer (or update existing by telegram_id).
```powershell
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/buyers" `
  -ContentType "application/json" `
  -Body '{"telegram_id": 123456789, "name": "John", "whatsapp_number": "+6591234567"}'
```

### GET /buyers/{buyer_id}
Get buyer profile.
```powershell
Invoke-WebRequest "https://sgabode-production.up.railway.app/buyers/1"
```

### POST /buyers/{buyer_id}/preferences
Replace all preferences for a buyer (creates new, deactivates old).
```powershell
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/buyers/1/preferences" `
  -ContentType "application/json" `
  -Body '{
    "intent": "buy",
    "property_types": ["hdb", "condo"],
    "price_min": 400000,
    "price_max": 800000,
    "bedrooms": [3, 4],
    "districts": [20, 19, 12]
  }'
```

### PATCH /buyers/{buyer_id}/preferences
Update specific preference fields only (keeps others unchanged).
```powershell
Invoke-WebRequest -Method PATCH "https://sgabode-production.up.railway.app/buyers/1/preferences" `
  -ContentType "application/json" `
  -Body '{"price_max": 900000, "bedrooms": [4, 5]}'
```

### GET /buyers/{buyer_id}/preferences
Get active preferences for a buyer.
```powershell
Invoke-WebRequest "https://sgabode-production.up.railway.app/buyers/1/preferences"
```

### GET /buyers/{buyer_id}/matches
Get recent matches for a buyer (last 50).
```powershell
Invoke-WebRequest "https://sgabode-production.up.railway.app/buyers/1/matches"
```

---

## Viewing Requests

### POST /viewing-requests
Create a viewing request manually.
```powershell
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/viewing-requests" `
  -ContentType "application/json" `
  -Body '{"match_id": 7, "buyer_id": 1, "listing_id": 42}'
```

### GET /viewing-requests/{request_id}
Get a viewing request.
```powershell
Invoke-WebRequest "https://sgabode-production.up.railway.app/viewing-requests/3"
```

### PATCH /viewing-requests/{request_id}
Update viewing request status.

Valid statuses: `pending`, `confirmed`, `cancelled`, `completed`
```powershell
Invoke-WebRequest -Method PATCH "https://sgabode-production.up.railway.app/viewing-requests/3" `
  -ContentType "application/json" `
  -Body '{"status": "confirmed"}'
```

---

## Scrapers  ⚠️ Requires X-Admin-Key header

### POST /scraper/run
Trigger ALL scrapers in the background (returns immediately, runs async).
```powershell
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/scraper/run" `
  -Headers @{"X-Admin-Key"="YOUR_ADMIN_KEY"}
```

### POST /scraper/run/{source}
Trigger one scraper in the background.

Available sources: `srx`, `99co`, `hdb_trend`, `hdb_rental`, `ura`, `propertyguru`
```powershell
# SRX (active HDB + condo for sale/rent)
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/scraper/run/srx" `
  -Headers @{"X-Admin-Key"="YOUR_ADMIN_KEY"}

# 99.co (active listings)
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/scraper/run/99co" `
  -Headers @{"X-Admin-Key"="YOUR_ADMIN_KEY"}

# HDB price trends (historical transaction data → price benchmarks)
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/scraper/run/hdb_trend" `
  -Headers @{"X-Admin-Key"="YOUR_ADMIN_KEY"}

# HDB rental transactions
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/scraper/run/hdb_rental" `
  -Headers @{"X-Admin-Key"="YOUR_ADMIN_KEY"}

# PropertyGuru (requires Playwright, slower)
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/scraper/run/propertyguru" `
  -Headers @{"X-Admin-Key"="YOUR_ADMIN_KEY"}
```

### POST /scraper/run/{source}/now
Run one scraper INLINE — waits for completion and returns results immediately.
Good for testing; use the background version for production.
```powershell
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/scraper/run/srx/now" `
  -Headers @{"X-Admin-Key"="YOUR_ADMIN_KEY"} `
  -TimeoutSec 120
```
Response example:
```json
{"status": "completed", "result": {"source": "srx", "new": 45, "updated": 12, "deactivated": 3, "errors": 0}}
```

### GET /scraper/schedule
View the automatic scrape schedule (runs every 6 hours).
```powershell
Invoke-WebRequest "https://sgabode-production.up.railway.app/scraper/schedule" `
  -Headers @{"X-Admin-Key"="YOUR_ADMIN_KEY"}
```

### GET /scraper/sources
List all registered scrapers.
```powershell
Invoke-WebRequest "https://sgabode-production.up.railway.app/scraper/sources" `
  -Headers @{"X-Admin-Key"="YOUR_ADMIN_KEY"}
```

---

## Payments (Stripe — optional)

### POST /payments/create-intent
Create a Stripe payment intent for a boosted listing (SGD 49.00).
```powershell
Invoke-WebRequest -Method POST "https://sgabode-production.up.railway.app/payments/create-intent" `
  -ContentType "application/json" `
  -Body '{"listing_id": 42, "agent_id": 1}'
```

### POST /payments/webhook
Stripe webhook endpoint — called automatically by Stripe, not by you.

---

## Telegram Bot Commands

These are typed directly in the Telegram chat:

| Command | Description |
|---------|-------------|
| `/start` | Reset and start fresh onboarding |
| `/preferences` | View your saved search preferences |
| `/update` | Update preferences in plain English |
| `/recommend` | Get your top ranked matching listings |
| `/liked` | View listings you've liked |
| `/like_N` | Like match number N (e.g. `/like_42`) |
| `/skip_N` | Skip match number N |
| `/view_N` | Request a viewing for match N |
| `/help` | Show all commands |

You can also just **chat freely** — the AI handles:
- Finding listings ("show me 3-bed condos in D9 under $2M")
- Nearby amenities ("is there a coffee shop near listing 5?")
- Price trends ("what do 4-room HDBs cost in Bishan?")
- Updating preferences ("change my budget to $900k")

---

## Admin Key

Your admin key (required for `/scraper/*` routes):
```
fd1e520ebf1dc1d734c804ca438c077c653e6c53b25a64fdca3785c7015f7d72
```
Store this in `.env` as `ADMIN_API_KEY` and in Railway environment variables.

Replace `YOUR_ADMIN_KEY` in all commands above with this value.
