"""SQLite persistence; all money is stored in integer paise."""
import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('customer','store','admin'))
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS stores (
 id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
 name TEXT NOT NULL, location TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 approved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL REFERENCES stores(id),
 name TEXT NOT NULL, category TEXT NOT NULL, unit TEXT NOT NULL,
 price INTEGER NOT NULL CHECK(price > 0), stock INTEGER NOT NULL CHECK(stock >= 0),
 active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS orders (
 id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES users(id),
 store_id INTEGER NOT NULL REFERENCES stores(id), pickup_at TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'placed' CHECK(status IN ('placed','preparing','ready','collected','cancelled')),
 total INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_items (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
 product_id INTEGER NOT NULL REFERENCES products(id), name TEXT NOT NULL, unit TEXT NOT NULL,
 price INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0)
);
CREATE TABLE IF NOT EXISTS feedback (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
 customer_id INTEGER NOT NULL REFERENCES users(id), rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
 message TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS orders_store ON orders(store_id);
CREATE INDEX IF NOT EXISTS products_store ON products(store_id);
"""


def connect(path):
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def password_hash(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000).hex()
    return f'{salt}${digest}'


def password_matches(password, stored):
    salt, expected = stored.split('$')
    actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 600_000).hex()
    return hmac.compare_digest(actual, expected)


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as db, db:
        db.executescript(SCHEMA)


def seed_demo(path):
    """Opt-in local fixtures. Never overwrite existing accounts or store changes."""
    initialize(path)
    with closing(connect(path)) as db, db:
        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone():
            return False
        for name, email, role in [
            ('Alex Customer', 'customer@quickcart.demo', 'customer'),
            ('Maya Store', 'store@quickcart.demo', 'store'),
            ('Sam Store', 'market@quickcart.demo', 'store'),
            ('Demo Admin', 'admin@quickcart.demo', 'admin'),
        ]:
            db.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',
                       (name, email, password_hash('QuickCart123!'), role))
        db.execute("INSERT INTO stores(owner_id,name,location,description,approved) VALUES(2,'Green Basket','Town Centre','Fresh produce, everyday staples, and a friendlier grocery run.',1)")
        db.execute("INSERT INTO stores(owner_id,name,location,description,approved) VALUES(3,'The Daily Pantry','Riverside','Your neighbourhood stop for pantry essentials and little treats.',1)")
        products = [
            (1, 'Farm fresh tomatoes', 'Vegetables', '500 g', 3500, 24),
            (1, 'Sweet bananas', 'Fruits', '6 pieces', 4800, 18),
            (1, 'Fresh whole milk', 'Dairy', '1 litre', 6000, 20),
            (1, 'Whole wheat bread', 'Bakery', '400 g', 4500, 12),
            (1, 'Orange carrots', 'Vegetables', '500 g', 4200, 16),
            (1, 'Red apples', 'Fruits', '4 pieces', 12000, 14),
            (1, 'Free range eggs', 'Dairy', '6 pieces', 7800, 10),
            (1, 'Basmati rice', 'Pantry', '1 kg', 13500, 20),
            (2, 'Rolled oats', 'Pantry', '500 g', 9900, 15),
            (2, 'Fresh whole milk', 'Dairy', '1 litre', 6200, 14),
            (2, 'Sourdough loaf', 'Bakery', '400 g', 14000, 8),
            (2, 'Green apples', 'Fruits', '4 pieces', 13000, 12),
        ]
        db.executemany('INSERT INTO products(store_id,name,category,unit,price,stock) VALUES(?,?,?,?,?,?)', products)
    return True
