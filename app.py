import os, re, time, secrets, sqlite3, threading
from collections import defaultdict
from flask import Flask, jsonify, request, send_from_directory, abort
import automation

BASE = os.path.dirname(os.path.abspath(__file__))
DB = automation.DB
ADMIN_KEY = os.environ.get("ADMIN_PASSWORD", "change-me")
WA = os.environ.get("WHATSAPP_NUMBER", "920000000000")
SIZES = {50: 4500, 100: 7500}
FREE_OVER, SHIP_FEE = 8000, 250
STATUSES = ["new", "confirmed", "shipped", "delivered", "cancelled"]
PRODUCTS = [
    ("nebula", "Nebula", "Floral · Amber · Musk"), ("aurora", "Aurora", "Vanilla · Amber · Warm"),
    ("eclipse", "Eclipse", "Woody · Spicy · Leather"), ("stardust", "Stardust", "Citrus · Jasmine · Sandalwood")]

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

def db():
    c = sqlite3.connect(DB, timeout=10); c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON"); return c

def init():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY, name TEXT, notes TEXT, stock INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, created TEXT, name TEXT, phone TEXT, city TEXT, address TEXT,
        note TEXT, subtotal INTEGER, shipping INTEGER, total INTEGER, status TEXT DEFAULT 'new');
    CREATE TABLE IF NOT EXISTS order_items(order_id TEXT REFERENCES orders(id), product_id TEXT, ml INTEGER, qty INTEGER, price INTEGER);
    CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT, name TEXT, message TEXT);""")
    if not c.execute("SELECT 1 FROM products").fetchone():
        c.executemany("INSERT INTO products VALUES(?,?,?,25)", PRODUCTS)
    c.commit(); c.close()

HITS = defaultdict(list)
def limited(kind, n=20, window=3600):
    k = (kind, request.remote_addr); now = time.time()
    HITS[k] = [t for t in HITS[k] if now - t < window]
    if len(HITS[k]) >= n: return True
    HITS[k].append(now); return False

def clean(v, n): return re.sub(r"\s+", " ", str(v or "")).strip()[:n]
def err(msg, code=400): return jsonify(error=msg), code
def money(n): return f"Rs. {n:,}"
def need_admin():
    if not secrets.compare_digest(request.headers.get("X-Admin-Key", ""), ADMIN_KEY): abort(401)

@app.get("/")
def home(): return send_from_directory("static", "index.html")
@app.get("/admin")
def admin(): return send_from_directory("static", "admin.html")

@app.get("/api/products")
def products():
    c = db(); rows = [dict(r) for r in c.execute("SELECT id, name, notes, stock FROM products")]; c.close()
    return jsonify(products=rows, sizes=[{"ml": m, "price": p} for m, p in SIZES.items()], free=FREE_OVER, ship=SHIP_FEE, wa=WA)

@app.post("/api/orders")
def create_order():
    if limited("order", 10): return err("Too many orders from this connection. Please try again later.", 429)
    d = request.get_json(silent=True) or {}
    name, city, addr, note = clean(d.get("name"), 80), clean(d.get("city"), 60), clean(d.get("address"), 250), clean(d.get("note"), 200)
    phone = clean(d.get("phone"), 25)
    if not (name and city and addr): return err("Please fill in your name, city and address.")
    if len(re.sub(r"\D", "", phone)) < 10: return err("Please enter a valid phone number.")
    items = d.get("items")
    if not isinstance(items, list) or not items or len(items) > 20: return err("Your cart is empty.")
    c = db(); c.execute("BEGIN IMMEDIATE")
    try:
        lines, need = [], defaultdict(int)
        for it in items:
            try: pid, ml, qty = str(it["id"]), int(it["ml"]), int(it["qty"])
            except Exception: return err("Invalid cart.")
            row = c.execute("SELECT name, stock FROM products WHERE id=?", (pid,)).fetchone()
            if not row or ml not in SIZES or not 1 <= qty <= 10: return err("Invalid cart.")
            need[pid] += qty; lines.append((pid, row["name"], ml, qty, SIZES[ml]))
        for pid, q in need.items():
            have = c.execute("SELECT name, stock FROM products WHERE id=?", (pid,)).fetchone()
            if have["stock"] < q: return err(f"Sorry, only {have['stock']} of {have['name']} left.", 409)
        sub = sum(l[3] * l[4] for l in lines); ship = 0 if sub >= FREE_OVER else SHIP_FEE; total = sub + ship
        oid = "NX" + str(secrets.randbelow(900000) + 100000)
        c.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,'new')", (oid, time.strftime("%Y-%m-%d %H:%M:%S"), name, phone, city, addr, note, sub, ship, total))
        for pid, _, ml, qty, pr in lines:
            c.execute("INSERT INTO order_items VALUES(?,?,?,?,?)", (oid, pid, ml, qty, pr))
        for pid, q in need.items(): c.execute("UPDATE products SET stock = stock - ? WHERE id=?", (q, pid))
        c.commit()
    except Exception:
        c.rollback(); return err("Could not place the order. Please try again.", 500)
    finally: c.close()
    text = (f"New order {oid}\n\n" + "\n".join(f"{n} {ml}ml × {q} = {money(q*p)}" for _, n, ml, q, p in lines) +
            f"\n\nSubtotal: {money(sub)}\nDelivery: {money(ship) if ship else 'Free'}\nTotal: {money(total)} (cash on delivery)"
            f"\n\nName: {name}\nPhone: {phone}\nCity: {city}\nAddress: {addr}" + (f"\nNote: {note}" if note else ""))
    threading.Thread(target=automation.notify_order, args=(oid, text), daemon=True).start()
    return jsonify(id=oid, total=total, text=text), 201

@app.post("/api/contact")
def contact():
    if limited("contact", 10): return err("Too many messages. Please try again later.", 429)
    d = request.get_json(silent=True) or {}; msg = clean(d.get("message"), 1000)
    if not msg: return err("Please write a message.")
    c = db(); c.execute("INSERT INTO messages(created,name,message) VALUES(?,?,?)", (time.strftime("%Y-%m-%d %H:%M:%S"), clean(d.get("name"), 80), msg)); c.commit(); c.close()
    threading.Thread(target=automation.send, args=("New contact message", f"{clean(d.get('name'),80)}: {msg}"), daemon=True).start()
    return jsonify(ok=True), 201

@app.get("/api/admin/data")
def admin_data():
    need_admin(); c = db()
    orders = [dict(o) for o in c.execute("SELECT * FROM orders ORDER BY created DESC LIMIT 200")]
    for o in orders:
        o["items"] = [dict(i) for i in c.execute("SELECT p.name, i.ml, i.qty FROM order_items i JOIN products p ON p.id=i.product_id WHERE order_id=?", (o["id"],))]
    out = dict(orders=orders, products=[dict(r) for r in c.execute("SELECT id, name, stock FROM products")],
               messages=[dict(r) for r in c.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 100")], statuses=STATUSES)
    c.close(); return jsonify(out)

@app.patch("/api/admin/orders/<oid>")
def set_status(oid):
    need_admin(); st = (request.get_json(silent=True) or {}).get("status")
    if st not in STATUSES: return err("Unknown status.")
    c = db(); o = c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()
    if not o: c.close(); return err("Order not found.", 404)
    if st == "cancelled" and o["status"] != "cancelled":      # automation: put stock back
        for i in c.execute("SELECT product_id, qty FROM order_items WHERE order_id=?", (oid,)).fetchall():
            c.execute("UPDATE products SET stock = stock + ? WHERE id=?", (i["qty"], i["product_id"]))
    elif o["status"] == "cancelled" and st != "cancelled":
        for i in c.execute("SELECT product_id, qty FROM order_items WHERE order_id=?", (oid,)).fetchall():
            c.execute("UPDATE products SET stock = MAX(0, stock - ?) WHERE id=?", (i["qty"], i["product_id"]))
    c.execute("UPDATE orders SET status=? WHERE id=?", (st, oid)); c.commit(); c.close(); return jsonify(ok=True)

@app.patch("/api/admin/products/<pid>")
def set_stock(pid):
    need_admin()
    try: s = int((request.get_json(silent=True) or {}).get("stock"))
    except Exception: return err("Stock must be a number.")
    if s < 0 or s > 100000: return err("Stock out of range.")
    c = db(); c.execute("UPDATE products SET stock=? WHERE id=?", (s, pid)); c.commit(); c.close(); return jsonify(ok=True)

init()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
