import hashlib
import os
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .db import connect, initialize, password_hash, password_matches

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ('Vegetables', 'Fruits', 'Dairy', 'Bakery', 'Pantry', 'Other')


class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        value = value.strip().lower()
        if value.count('@') != 1 or '.' not in value.split('@')[1] or any(c.isspace() for c in value):
            raise ValueError('Enter a valid email address')
        return value


class Registration(Credentials):
    name: str = Field(min_length=2, max_length=80)
    role: str = 'customer'
    store_name: str = Field(default='', max_length=100)
    location: str = Field(default='', max_length=120)


class ProductInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    category: str
    unit: str = Field(min_length=1, max_length=40)
    price: int = Field(strict=True, gt=0, le=10_000_000)
    stock: int = Field(strict=True, ge=0, le=100_000)
    active: bool = True

    @field_validator('name', 'unit')
    @classmethod
    def trim(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value.strip()

    @field_validator('category')
    @classmethod
    def category_valid(cls, value):
        if value not in CATEGORIES:
            raise ValueError('Unknown category')
        return value


class CartItem(BaseModel):
    product_id: int = Field(strict=True, gt=0)
    quantity: int = Field(strict=True, gt=0, le=99)


class OrderInput(BaseModel):
    store_id: int = Field(gt=0)
    items: list[CartItem] = Field(min_length=1, max_length=100)
    pickup_at: datetime


class StatusInput(BaseModel):
    status: str


class FeedbackInput(BaseModel):
    rating: int = Field(strict=True, ge=1, le=5)
    message: str = Field(min_length=3, max_length=1000)

    @field_validator('message')
    @classmethod
    def trim(cls, value):
        if len(value.strip()) < 3:
            raise ValueError('Please write at least 3 characters')
        return value.strip()


def create_app(db_path=None):
    api = FastAPI(title='Quick Cart API', version='1.0.0', docs_url=None, redoc_url=None)
    api.state.db_path = str(db_path or os.environ.get('QUICKCART_DB', ROOT / 'data' / 'quickcart.db'))
    initialize(api.state.db_path)
    attempts = defaultdict(deque)

    @contextmanager
    def database():
        db = connect(api.state.db_path)
        try:
            with db:
                yield db
        finally:
            db.close()

    @api.middleware('http')
    async def security(request: Request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and urlsplit(origin).netloc != request.headers.get('host'):
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail': 'Cross-origin requests are not allowed'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    def current_user(request: Request):
        token = request.cookies.get('quickcart_session', '')
        with database() as db:
            row = db.execute('SELECT u.id,u.name,u.email,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',
                             (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
        if not row:
            raise HTTPException(401, 'Please sign in to continue')
        return dict(row)

    def role_required(user, *roles):
        if user['role'] not in roles:
            raise HTTPException(403, 'This action is not available for your account')

    def own_store(db, user):
        role_required(user, 'store')
        store = db.execute('SELECT * FROM stores WHERE owner_id=?', (user['id'],)).fetchone()
        if not store:
            raise HTTPException(404, 'Store not found')
        return store

    def start_session(db, user_id, response):
        token = secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
        db.execute('INSERT INTO sessions VALUES(?,?,?)',
                   (hashlib.sha256(token.encode()).hexdigest(), user_id, int(time.time()) + 86400))
        response.set_cookie('quickcart_session', token, httponly=True, samesite='strict', max_age=86400,
                            secure=os.environ.get('QUICKCART_SECURE_COOKIE') == '1')

    def throttle(request):
        key = request.client.host if request.client else 'local'
        now = time.monotonic()
        # Bounded, process-local rate limiting for this single-process MVP.
        for old_key in list(attempts):
            if not attempts[old_key] or attempts[old_key][-1] < now - 300:
                del attempts[old_key]
        history = attempts[key]
        while history and history[0] < now - 300:
            history.popleft()
        if len(history) >= 20:
            raise HTTPException(429, 'Too many attempts. Please try again in five minutes.')
        history.append(now)

    @api.get('/api/health')
    def health():
        return {'status': 'ok'}

    @api.post('/api/auth/register', status_code=201)
    def register(data: Registration, request: Request, response: Response):
        throttle(request)
        if data.role not in ('customer', 'store'):
            raise HTTPException(422, 'Choose a customer or store account')
        if len(data.name.strip()) < 2:
            raise HTTPException(422, 'Enter your name')
        if data.role == 'store' and (len(data.store_name.strip()) < 2 or len(data.location.strip()) < 2):
            raise HTTPException(422, 'Store name and location are required')
        with database() as db:
            try:
                uid = db.execute('INSERT INTO users(name,email,password_hash,role) VALUES(?,?,?,?)',
                                 (data.name.strip(), data.email, password_hash(data.password), data.role)).lastrowid
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'An account with this email already exists')
            if data.role == 'store':
                db.execute('INSERT INTO stores(owner_id,name,location) VALUES(?,?,?)',
                           (uid, data.store_name.strip(), data.location.strip()))
            start_session(db, uid, response)
        return {'id': uid, 'name': data.name.strip(), 'email': data.email, 'role': data.role}

    @api.post('/api/auth/login')
    def login(data: Credentials, request: Request, response: Response):
        throttle(request)
        with database() as db:
            row = db.execute('SELECT * FROM users WHERE email=?', (data.email,)).fetchone()
            if not row or not password_matches(data.password, row['password_hash']):
                raise HTTPException(401, 'Email or password is incorrect')
            start_session(db, row['id'], response)
        return {key: row[key] for key in ('id', 'name', 'email', 'role')}

    @api.post('/api/auth/logout')
    def logout(request: Request, response: Response):
        token = request.cookies.get('quickcart_session', '')
        with database() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))
        response.delete_cookie('quickcart_session')
        return {'ok': True}

    @api.get('/api/auth/me')
    def me(user=Depends(current_user)):
        return user

    @api.get('/api/stores')
    def stores():
        with database() as db:
            return [dict(r) for r in db.execute('SELECT id,name,location,description FROM stores WHERE approved=1 ORDER BY id')]

    @api.get('/api/stores/{store_id}/products')
    def products(store_id: int):
        with database() as db:
            if not db.execute('SELECT 1 FROM stores WHERE id=? AND approved=1', (store_id,)).fetchone():
                raise HTTPException(404, 'Store not found')
            return [dict(r) for r in db.execute('SELECT * FROM products WHERE store_id=? AND active=1 ORDER BY id', (store_id,))]

    @api.post('/api/orders', status_code=201)
    def place_order(data: OrderInput, user=Depends(current_user)):
        role_required(user, 'customer')
        now = datetime.now(timezone.utc)
        if data.pickup_at.tzinfo is None:
            raise HTTPException(422, 'Pickup time must include a timezone')
        if not now + timedelta(minutes=15) <= data.pickup_at <= now + timedelta(days=7):
            raise HTTPException(422, 'Choose a pickup time between 15 minutes and 7 days from now')
        ids = [i.product_id for i in data.items]
        if len(ids) != len(set(ids)):
            raise HTTPException(422, 'Combine duplicate products into one cart item')
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM stores WHERE id=? AND approved=1', (data.store_id,)).fetchone():
                raise HTTPException(404, 'Store is not available')
            total, lines = 0, []
            for item in data.items:
                product = db.execute('SELECT * FROM products WHERE id=? AND store_id=? AND active=1', (item.product_id, data.store_id)).fetchone()
                if not product:
                    raise HTTPException(409, 'A product in your bag is no longer available')
                if product['stock'] < item.quantity:
                    raise HTTPException(409, f"Only {product['stock']} of {product['name']} available. Update your bag.")
                total += product['price'] * item.quantity
                lines.append((product, item.quantity))
            oid = db.execute('INSERT INTO orders(customer_id,store_id,pickup_at,total,created_at) VALUES(?,?,?,?,?)',
                             (user['id'], data.store_id, data.pickup_at.astimezone(timezone.utc).isoformat(), total, now.isoformat())).lastrowid
            for p, quantity in lines:
                db.execute('UPDATE products SET stock=stock-? WHERE id=?', (quantity, p['id']))
                db.execute('INSERT INTO order_items(order_id,product_id,name,unit,price,quantity) VALUES(?,?,?,?,?,?)',
                           (oid, p['id'], p['name'], p['unit'], p['price'], quantity))
        return {'id': oid, 'total': total, 'status': 'placed'}

    @api.get('/api/orders')
    def orders(user=Depends(current_user)):
        with database() as db:
            if user['role'] == 'customer':
                condition, params = 'o.customer_id=?', (user['id'],)
            elif user['role'] == 'store':
                condition, params = 'o.store_id=?', (own_store(db, user)['id'],)
            else:
                condition, params = '1=1', ()
            rows = db.execute(f'SELECT o.*,s.name AS store_name,s.location,u.name AS customer_name FROM orders o JOIN stores s ON s.id=o.store_id JOIN users u ON u.id=o.customer_id WHERE {condition} ORDER BY o.id DESC', params).fetchall()
            result = []
            for row in rows:
                order = dict(row)
                order['items'] = [dict(r) for r in db.execute('SELECT product_id,name,unit,price,quantity FROM order_items WHERE order_id=?', (row['id'],))]
                f = db.execute('SELECT rating,message FROM feedback WHERE order_id=?', (row['id'],)).fetchone()
                order['feedback'] = dict(f) if f else None
                result.append(order)
            return result

    @api.patch('/api/orders/{order_id}/status')
    def order_status(order_id: int, data: StatusInput, user=Depends(current_user)):
        with database() as db:
            db.execute('BEGIN IMMEDIATE')
            order = db.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            if not order:
                raise HTTPException(404, 'Order not found')
            if user['role'] == 'customer':
                if order['customer_id'] != user['id']:
                    raise HTTPException(404, 'Order not found')
                allowed = {'placed': ('cancelled',)}
            elif user['role'] == 'store':
                if own_store(db, user)['id'] != order['store_id']:
                    raise HTTPException(404, 'Order not found')
                allowed = {'placed': ('preparing', 'cancelled'), 'preparing': ('ready', 'cancelled'), 'ready': ('collected', 'cancelled')}
            else:
                raise HTTPException(403, 'Only the customer or store can change this order')
            if data.status not in allowed.get(order['status'], ()):
                raise HTTPException(409, 'That status change is not available. Refresh the order.')
            db.execute('UPDATE orders SET status=? WHERE id=?', (data.status, order_id))
            if data.status == 'cancelled':
                for line in db.execute('SELECT product_id,quantity FROM order_items WHERE order_id=?', (order_id,)).fetchall():
                    db.execute('UPDATE products SET stock=stock+? WHERE id=?', (line['quantity'], line['product_id']))
        return {'ok': True}

    @api.post('/api/orders/{order_id}/feedback', status_code=201)
    def feedback(order_id: int, data: FeedbackInput, user=Depends(current_user)):
        role_required(user, 'customer')
        with database() as db:
            order = db.execute('SELECT * FROM orders WHERE id=? AND customer_id=?', (order_id, user['id'])).fetchone()
            if not order:
                raise HTTPException(404, 'Order not found')
            if order['status'] != 'collected':
                raise HTTPException(409, 'You can review an order after collection')
            try:
                db.execute('INSERT INTO feedback(order_id,customer_id,rating,message,created_at) VALUES(?,?,?,?,?)',
                           (order_id, user['id'], data.rating, data.message, datetime.now(timezone.utc).isoformat()))
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'You have already reviewed this order')
        return {'ok': True}

    @api.get('/api/manage/store')
    def manage_store(user=Depends(current_user)):
        with database() as db:
            store = own_store(db, user)
            return {**dict(store), 'products': [dict(r) for r in db.execute('SELECT * FROM products WHERE store_id=? ORDER BY id', (store['id'],))]}

    @api.post('/api/manage/products', status_code=201)
    def add_product(data: ProductInput, user=Depends(current_user)):
        with database() as db:
            store = own_store(db, user)
            pid = db.execute('INSERT INTO products(store_id,name,category,unit,price,stock,active) VALUES(?,?,?,?,?,?,?)',
                             (store['id'], data.name, data.category, data.unit, data.price, data.stock, data.active)).lastrowid
        return {'id': pid}

    @api.put('/api/manage/products/{product_id}')
    def update_product(product_id: int, data: ProductInput, user=Depends(current_user)):
        with database() as db:
            store = own_store(db, user)
            updated = db.execute('UPDATE products SET name=?,category=?,unit=?,price=?,stock=?,active=? WHERE id=? AND store_id=?',
                                 (data.name, data.category, data.unit, data.price, data.stock, data.active, product_id, store['id']))
            if updated.rowcount != 1:
                raise HTTPException(404, 'Product not found')
        return {'ok': True}

    @api.get('/api/admin/overview')
    def overview(user=Depends(current_user)):
        role_required(user, 'admin')
        with database() as db:
            return {
                'stores': [dict(r) for r in db.execute('SELECT s.*,u.email FROM stores s JOIN users u ON u.id=s.owner_id ORDER BY s.approved,s.id')],
                'users': [dict(r) for r in db.execute('SELECT id,name,email,role FROM users ORDER BY id')],
                'feedback': [dict(r) for r in db.execute('SELECT f.*,s.name AS store_name,u.name AS customer_name FROM feedback f JOIN orders o ON o.id=f.order_id JOIN stores s ON s.id=o.store_id JOIN users u ON u.id=f.customer_id ORDER BY f.id DESC')]
            }

    @api.patch('/api/admin/stores/{store_id}')
    def approve_store(store_id: int, data: dict[str, bool], user=Depends(current_user)):
        role_required(user, 'admin')
        if set(data) != {'approved'}:
            raise HTTPException(422, 'Provide approved: true or false')
        with database() as db:
            if db.execute('UPDATE stores SET approved=? WHERE id=?', (data['approved'], store_id)).rowcount != 1:
                raise HTTPException(404, 'Store not found')
        return {'ok': True}

    @api.get('/', include_in_schema=False)
    def index():
        return FileResponse(ROOT / 'static' / 'index.html')

    api.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
    return api


app = create_app()
