import sqlite3
import json
from config import DB_NAME

def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS stock (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_key TEXT NOT NULL,
        content TEXT NOT NULL,
        sold INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        product_key TEXT NOT NULL,
        qty INTEGER DEFAULT 1,
        amount REAL NOT NULL,
        status TEXT DEFAULT 'pending',
        order_ref TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        stock_id INTEGER,
        content TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        user_id INTEGER,
        amount REAL,
        screenshot_file_id TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        banned INTEGER DEFAULT 0,
        total_orders INTEGER DEFAULT 0,
        total_spent REAL DEFAULT 0,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    conn.commit()
    conn.close()

# ── STOCK ──────────────────────────────────────────────
def add_stock(product_key, items):
    conn = get_conn()
    c = conn.cursor()
    for item in items:
        c.execute("INSERT INTO stock (product_key, content) VALUES (?, ?)", (product_key, item.strip()))
    conn.commit()
    conn.close()
    return len(items)

def get_stock_count(product_key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM stock WHERE product_key=? AND sold=0", (product_key,))
    count = c.fetchone()[0]
    conn.close()
    return count

def pop_stock(product_key, qty=1):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, content FROM stock WHERE product_key=? AND sold=0 LIMIT ?", (product_key, qty))
    rows = c.fetchall()
    if len(rows) < qty:
        conn.close()
        return None
    ids = [r['id'] for r in rows]
    contents = [r['content'] for r in rows]
    c.execute(f"UPDATE stock SET sold=1 WHERE id IN ({','.join('?'*len(ids))})", ids)
    conn.commit()
    conn.close()
    return contents

def get_all_stock_counts():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT product_key, COUNT(*) as cnt FROM stock WHERE sold=0 GROUP BY product_key")
    rows = c.fetchall()
    conn.close()
    return {r['product_key']: r['cnt'] for r in rows}

# ── ORDERS ─────────────────────────────────────────────
def create_order(user_id, product_key, qty, amount, order_ref):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO orders (user_id, product_key, qty, amount, order_ref) VALUES (?,?,?,?,?)",
              (user_id, product_key, qty, amount, order_ref))
    oid = c.lastrowid
    conn.commit()
    conn.close()
    return oid

def save_order_items(order_id, contents):
    conn = get_conn()
    c = conn.cursor()
    for content in contents:
        c.execute("INSERT INTO order_items (order_id, content) VALUES (?,?)", (order_id, content))
    conn.commit()
    conn.close()

def complete_order(order_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE orders SET status='completed' WHERE id=?", (order_id,))
    conn.commit()
    conn.close()

def get_order(order_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_order_items(order_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT content FROM order_items WHERE order_id=?", (order_id,))
    rows = c.fetchall()
    conn.close()
    return [r['content'] for r in rows]

def get_user_orders(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_pending_orders():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT o.*, p.screenshot_file_id, p.id as payment_id FROM orders o JOIN payments p ON p.order_id=o.id WHERE o.status='pending' AND p.status='pending' ORDER BY o.created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── PAYMENTS ────────────────────────────────────────────
def create_payment(order_id, user_id, amount, screenshot_file_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO payments (order_id, user_id, amount, screenshot_file_id) VALUES (?,?,?,?)",
              (order_id, user_id, amount, screenshot_file_id))
    pid = c.lastrowid
    conn.commit()
    conn.close()
    return pid

def approve_payment(payment_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE payments SET status='approved' WHERE id=?", (payment_id,))
    conn.commit()
    conn.close()

def reject_payment(payment_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE payments SET status='rejected' WHERE id=?", (payment_id,))
    conn.commit()
    conn.close()

# ── USERS ───────────────────────────────────────────────
def upsert_user(user_id, username, first_name):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO users (user_id, username, first_name) VALUES (?,?,?)
                 ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, first_name=excluded.first_name''',
              (user_id, username, first_name))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def is_banned(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT banned FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row and row['banned'] == 1

def ban_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET banned=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET banned=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY joined_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_user_stats(user_id, amount):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET total_orders=total_orders+1, total_spent=total_spent+? WHERE user_id=?",
              (amount, user_id))
    conn.commit()
    conn.close()

# ── STATS ───────────────────────────────────────────────
def get_stats():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM orders WHERE status='completed'")
    total_orders = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(amount),0) FROM orders WHERE status='completed'")
    total_revenue = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM orders WHERE status='pending'")
    pending_orders = c.fetchone()[0]
    conn.close()
    return {
        'total_users': total_users,
        'total_orders': total_orders,
        'total_revenue': total_revenue,
        'pending_orders': pending_orders
    }

def store_admin_msg_map(admin_id, payment_id, user_id):
    # Simple stub — reply-to-caption approach doesn't need DB storage
    pass

def get_stock_items(product_key, limit=20, offset=0):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, content, created_at FROM stock WHERE product_key=? AND sold=0 ORDER BY id ASC LIMIT ? OFFSET ?",
              (product_key, limit, offset))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_stock_items_count(product_key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM stock WHERE product_key=? AND sold=0", (product_key,))
    count = c.fetchone()[0]
    conn.close()
    return count

def delete_stock_item(item_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM stock WHERE id=? AND sold=0", (item_id,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def delete_all_stock(product_key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM stock WHERE product_key=? AND sold=0", (product_key,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected

def add_product(key, name, emoji, price, description):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS custom_products (
        key TEXT PRIMARY KEY,
        name TEXT,
        emoji TEXT,
        price REAL,
        description TEXT,
        active INTEGER DEFAULT 1
    )""")
    c.execute("""INSERT INTO custom_products (key, name, emoji, price, description)
                 VALUES (?,?,?,?,?)
                 ON CONFLICT(key) DO UPDATE SET name=excluded.name,
                 emoji=excluded.emoji, price=excluded.price,
                 description=excluded.description, active=1""",
              (key, name, emoji, price, description))
    conn.commit()
    conn.close()

def remove_product(key):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE custom_products SET active=0 WHERE key=?", (key,))
    conn.commit()
    conn.close()

def get_custom_products():
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM custom_products WHERE active=1")
        rows = c.fetchall()
        conn.close()
        return {r['key']: {'name': r['name'], 'emoji': r['emoji'],
                            'price': r['price'], 'description': r['description']} for r in rows}
    except:
        conn.close()
        return {}
