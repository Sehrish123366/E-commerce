# Noctyra Fragrances – full store

**Frontend:** HTML, CSS, JavaScript (`static/`) – home, shop, product pages, cart, checkout, about, contact.
**Backend:** Python + Flask + SQLite (`app.py`) – products and stock, orders, contact messages, admin API.
**Automation (`automation.py`):** order alerts, low-stock alerts, daily sales report, automatic restock when an order is cancelled.

## Run it
```
pip install -r requirements.txt
ADMIN_PASSWORD=your-password WHATSAPP_NUMBER=923001234567 python app.py
```
Store: http://localhost:5000   Admin: http://localhost:5000/admin (asks for the password; refreshes every 30 s)

## What is automated
- Every order is validated on the server (prices and stock are never trusted from the browser), stock is reduced, and an alert is written to `logs/alerts.log`.
- Set the variables in `.env.example` to also get alerts by email (SMTP) or in Slack / Zapier / Make / n8n (`WEBHOOK_URL`).
- Stock at 5 or below triggers a low-stock alert. Cancelling an order in admin puts its stock back.
- Daily report (saved in `reports/`, also sent as an alert). Add to cron to run every night:
  `0 21 * * * cd /path/to/noctyra && python automation.py report`
- Order and contact forms are rate-limited per IP.

## Edit your details
- Prices, sizes, delivery fee: top of `app.py` (`SIZES`, `FREE_OVER`, `SHIP_FEE`).
- Perfumes: `PRODUCTS` in `app.py` and the matching list `P` in `static/app.js`.
- Photos: replace files in `static/img/`.
- Email and address on the Contact page: `CFG` in `static/app.js`.

## Go live
Use a host that runs Python (Railway, Render, a VPS): `gunicorn -w 2 app:app`. Set the env vars there and keep `noctyra.db` on a persistent disk. Put HTTPS in front (the host usually does this).
