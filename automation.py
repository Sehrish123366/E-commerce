"""Automation: order alerts, low-stock alerts and daily sales report.
Works with no setup (writes to logs/). Optional env vars add email and webhook alerts:
  SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASS NOTIFY_EMAIL   -> email alerts
  WEBHOOK_URL                                            -> JSON POST (Slack, Zapier, Make, n8n)
CLI:  python automation.py report   |   python automation.py stock
"""
import os, sys, json, sqlite3, smtplib, datetime, urllib.request
from email.message import EmailMessage

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DB_PATH", os.path.join(BASE, "noctyra.db"))
LOW_STOCK = int(os.environ.get("LOW_STOCK", "5"))

def log(name, text):
    os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
    with open(os.path.join(BASE, "logs", name), "a", encoding="utf-8") as f:
        f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")

def send(subject, body):
    """Send an alert through every channel that is configured."""
    log("alerts.log", f"{subject}\n{body}\n")
    host, to = os.environ.get("SMTP_HOST"), os.environ.get("NOTIFY_EMAIL")
    if host and to:
        try:
            m = EmailMessage(); m["Subject"] = subject; m["To"] = to
            m["From"] = os.environ.get("SMTP_USER", to); m.set_content(body)
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=15) as s:
                s.starttls(); s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"]); s.send_message(m)
        except Exception as e:
            log("errors.log", f"email failed: {e}")
    url = os.environ.get("WEBHOOK_URL")
    if url:
        try:
            req = urllib.request.Request(url, json.dumps({"text": f"{subject}\n{body}"}).encode(), {"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            log("errors.log", f"webhook failed: {e}")

def notify_order(order_id, text):
    send(f"New order {order_id}", text)
    low_stock()

def low_stock():
    c = sqlite3.connect(DB)
    rows = c.execute("SELECT name, stock FROM products WHERE stock <= ? ORDER BY stock", (LOW_STOCK,)).fetchall()
    c.close()
    if rows:
        send("Low stock alert", "\n".join(f"{n}: {s} left" for n, s in rows))
    return rows

def daily_report():
    c = sqlite3.connect(DB)
    since = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    n, rev = c.execute("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders WHERE created >= ? AND status != 'cancelled'", (since,)).fetchone()
    top = c.execute("""SELECT p.name, SUM(i.qty) q FROM order_items i JOIN orders o ON o.id=i.order_id
        JOIN products p ON p.id=i.product_id WHERE o.created >= ? AND o.status != 'cancelled'
        GROUP BY p.name ORDER BY q DESC""", (since,)).fetchall()
    pending = c.execute("SELECT COUNT(*) FROM orders WHERE status='new'").fetchone()[0]
    c.close()
    text = (f"Daily report {datetime.date.today()}\nOrders (24h): {n}\nRevenue (24h): Rs. {rev:,}\n"
            f"Orders waiting for confirmation: {pending}\nBest sellers: " + (", ".join(f"{a} x{b}" for a, b in top) or "none"))
    os.makedirs(os.path.join(BASE, "reports"), exist_ok=True)
    with open(os.path.join(BASE, "reports", f"report-{datetime.date.today()}.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    send("Daily sales report", text)
    return text

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "report": print(daily_report())
    elif cmd == "stock": print(low_stock() or "Stock levels are fine.")
    else: print(__doc__)
