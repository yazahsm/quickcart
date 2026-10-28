"""Integration tests use the real API and isolated SQLite databases."""
import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import connect, seed_demo
from app.main import create_app


class Workflows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory()
        cls.template = Path(cls.fixtures.name) / 'template.db'
        seed_demo(cls.template)

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'test.db'
        self.path.write_bytes(self.template.read_bytes())
        self.app = create_app(self.path)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def login(self, account='customer', client=None):
        c = client or self.client
        response = c.post('/api/auth/login', json={'email':f'{account}@quickcart.demo','password':'QuickCart123!'})
        self.assertEqual(response.status_code, 200, response.text)
        return c

    def order(self, client=None, quantity=2, **overrides):
        body = {'store_id':1, 'items':[{'product_id':1,'quantity':quantity}],
                'pickup_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        body.update(overrides)
        return (client or self.client).post('/api/orders', json=body)

    def stock(self, product_id=1):
        with closing(connect(self.path)) as db:
            return db.execute('SELECT stock FROM products WHERE id=?', (product_id,)).fetchone()[0]

    def test_customer_to_store_to_review_lifecycle(self):
        self.login()
        placed = self.order()
        self.assertEqual(placed.status_code, 201, placed.text)
        oid = placed.json()['id']
        self.assertEqual(placed.json()['total'], 7000)
        self.assertEqual(self.stock(), 22)
        self.assertEqual(self.client.post(f'/api/orders/{oid}/feedback',json={'rating':5,'message':'Great pickup!'}).status_code,409)
        with TestClient(self.app) as store:
            self.login('store',store)
            self.assertEqual(store.get('/api/orders').json()[0]['id'], oid)
            self.assertEqual(store.patch(f'/api/orders/{oid}/status',json={'status':'collected'}).status_code,409)
            for status in ('preparing','ready','collected'):
                self.assertEqual(store.patch(f'/api/orders/{oid}/status',json={'status':status}).status_code,200)
        review = {'rating':5, 'message':'Great pickup!'}
        self.assertEqual(self.client.post(f'/api/orders/{oid}/feedback',json=review).status_code,201)
        self.assertEqual(self.client.post(f'/api/orders/{oid}/feedback',json=review).status_code,409)
        self.login('admin')
        overview = self.client.get('/api/admin/overview').json()
        self.assertEqual(overview['feedback'][0]['message'], 'Great pickup!')
        self.assertNotIn('password_hash', overview['users'][0])

    def test_registration_normalization_logout_and_session_storage(self):
        response = self.client.post('/api/auth/register',json={'name':' New Customer ','email':'NEW@EXAMPLE.COM','password':'long-password-123'})
        self.assertEqual(response.status_code,201)
        self.assertEqual(self.client.get('/api/auth/me').json()['email'],'new@example.com')
        cookie = self.client.cookies.get('quickcart_session')
        self.assertIn('HttpOnly',response.headers['set-cookie'])
        with closing(connect(self.path)) as db:
            stored = db.execute('SELECT token_hash FROM sessions').fetchone()[0]
            self.assertNotEqual(stored,cookie)
            self.assertEqual(stored, hashlib.sha256(cookie.encode()).hexdigest())
            self.assertNotIn('long-password-123',db.execute('SELECT password_hash FROM users WHERE email=?',('new@example.com',)).fetchone()[0])
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)
        self.client.cookies.set('quickcart_session',cookie)
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_pending_store_approval_and_product_management(self):
        r = self.client.post('/api/auth/register',json={'name':'New Owner','email':'owner@example.com','password':'owner-pass-123','role':'store','store_name':'New Local','location':'West Road'})
        self.assertEqual(r.status_code,201,r.text)
        store = self.client.get('/api/manage/store').json()
        self.assertFalse(store['approved'])
        sid = store['id']
        product = {'name':'Cucumbers','category':'Vegetables','unit':'1 kg','price':6500,'stock':6}
        p = self.client.post('/api/manage/products',json=product)
        self.assertEqual(p.status_code,201,p.text)
        self.assertEqual(self.client.get(f'/api/stores/{sid}/products').status_code,404)
        self.assertEqual(self.client.patch(f'/api/admin/stores/{sid}',json={'approved':True}).status_code,403)
        self.login('admin')
        self.assertEqual(self.client.patch(f'/api/admin/stores/{sid}',json={'approved':True}).status_code,200)
        self.assertEqual(self.client.get(f'/api/stores/{sid}/products').json()[0]['name'],'Cucumbers')
        self.assertEqual(len(self.client.get('/api/stores').json()),3)
        self.client.patch(f'/api/admin/stores/{sid}',json={'approved':False})
        self.login()
        self.assertEqual(self.order(store_id=sid,items=[{'product_id':p.json()['id'],'quantity':1}]).status_code,404)

    def test_roles_and_cross_account_ownership(self):
        self.assertEqual(self.client.post('/api/orders',json={}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/register',json={'name':'Intruder','email':'intruder@example.com','password':'long-password','role':'admin'}).status_code,422)
        self.login()
        oid = self.order().json()['id']
        self.assertEqual(self.client.get('/api/admin/overview').status_code,403)
        self.assertEqual(self.client.get('/api/manage/store').status_code,403)
        with TestClient(self.app) as other:
            other.post('/api/auth/register',json={'name':'Other Customer','email':'other@example.com','password':'long-password'})
            self.assertEqual(other.get('/api/orders').json(),[])
            self.assertEqual(other.patch(f'/api/orders/{oid}/status',json={'status':'cancelled'}).status_code,404)
            self.assertEqual(other.post(f'/api/orders/{oid}/feedback',json={'rating':5,'message':'Fake review'}).status_code,404)
            self.login('market',other)
            self.assertEqual(other.get('/api/orders').json(),[])
            self.assertEqual(other.patch(f'/api/orders/{oid}/status',json={'status':'preparing'}).status_code,404)
            self.assertEqual(other.put('/api/manage/products/1',json={'name':'Fake','category':'Other','unit':'1','price':1,'stock':1}).status_code,404)

    def test_invalid_and_mixed_carts_do_not_mutate_stock(self):
        self.login()
        for items in ([{'product_id':1,'quantity':0}], [{'product_id':1,'quantity':-1}],
                      [{'product_id':1,'quantity':1.5}], [{'product_id':1,'quantity':True}],
                      [{'product_id':1,'quantity':1},{'product_id':1,'quantity':1}], [],
                      [{'product_id':1,'quantity':2},{'product_id':9,'quantity':1}],
                      [{'product_id':1,'quantity':25}]):
            with self.subTest(items=items):
                self.assertIn(self.order(items=items).status_code,(409,422))
                self.assertEqual(self.stock(),24)
                self.assertEqual(self.client.get('/api/orders').json(),[])

    def test_rejected_pickup_times(self):
        self.login()
        now = datetime.now(timezone.utc)
        for dt in (now-timedelta(hours=1), now+timedelta(minutes=5), now+timedelta(days=8), datetime.now()):
            self.assertEqual(self.order(pickup_at=dt.isoformat()).status_code,422)
        self.assertEqual(self.stock(),24)

    def test_cancel_releases_stock_exactly_once(self):
        self.login()
        oid = self.order(quantity=3).json()['id']
        self.assertEqual(self.stock(),21)
        for expected in (200,409):
            self.assertEqual(self.client.patch(f'/api/orders/{oid}/status',json={'status':'cancelled'}).status_code,expected)
            self.assertEqual(self.stock(),24)
        self.login('store')
        self.assertEqual(self.client.patch(f'/api/orders/{oid}/status',json={'status':'cancelled'}).status_code,409)
        self.assertEqual(self.stock(),24)

    def test_customer_cannot_cancel_after_preparation(self):
        self.login()
        oid = self.order().json()['id']
        with TestClient(self.app) as store:
            self.login('store',store)
            store.patch(f'/api/orders/{oid}/status',json={'status':'preparing'})
        self.assertEqual(self.client.patch(f'/api/orders/{oid}/status',json={'status':'cancelled'}).status_code,409)

    def test_order_snapshot_survives_price_change_and_hide(self):
        self.login()
        self.order()
        with TestClient(self.app) as store:
            self.login('store',store)
            r = store.put('/api/manage/products/1',json={'name':'Updated tomatoes','category':'Vegetables','unit':'1 kg','price':9000,'stock':22,'active':False})
            self.assertEqual(r.status_code,200)
        order = self.client.get('/api/orders').json()[0]
        self.assertEqual(order['total'],7000)
        self.assertEqual(order['items'][0]['name'],'Farm fresh tomatoes')
        self.assertEqual(order['items'][0]['unit'],'500 g')
        self.assertEqual(self.order().status_code,409)

    def test_two_simultaneous_checkouts_cannot_oversell(self):
        with TestClient(self.app) as a, TestClient(self.app) as b:
            self.login(client=a)
            self.login(client=b)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda c:self.order(c,quantity=20),[a,b]))
            self.assertEqual(sorted(r.status_code for r in results),[201,409])
            self.assertEqual(self.stock(),4)

    def test_data_survives_new_app_instance(self):
        self.login()
        oid = self.order().json()['id']
        with TestClient(create_app(self.path)) as restarted:
            self.login(client=restarted)
            self.assertEqual(restarted.get('/api/orders').json()[0]['id'],oid)
            self.assertEqual(self.stock(),22)

    def test_validation_origin_security_and_login_rate_limit(self):
        self.assertEqual(self.client.post('/api/auth/login',json={'email':'bad','password':'short'}).status_code,422)
        self.assertEqual(self.client.post('/api/auth/login',json={'email':'customer@quickcart.demo','password':'QuickCart123!'},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertIn("script-src 'self'",self.client.get('/').headers['content-security-policy'])
        for _ in range(20):
            self.assertEqual(self.client.post('/api/auth/login',json={'email':'unknown@example.com','password':'wrong-password'}).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json={'email':'unknown@example.com','password':'wrong-password'}).status_code,429)

    def test_expired_session_is_rejected(self):
        self.login()
        with closing(connect(self.path)) as db, db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.client.get('/api/auth/me').status_code,401)

    def test_demo_seed_is_idempotent(self):
        self.assertFalse(seed_demo(self.path))
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM users').fetchone()[0],4)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM products').fetchone()[0],12)

    def test_checkout_ignores_client_supplied_prices(self):
        self.login()
        placed = self.order(total=1, items=[{'product_id':1,'quantity':2,'price':1}])
        self.assertEqual(placed.status_code,201)
        self.assertEqual(placed.json()['total'],7000)

    def test_product_values_and_hidden_catalog(self):
        self.login('store')
        valid = {'name':'Local item','category':'Other','unit':'1 pack','price':100,'stock':4}
        for overrides in ({'stock':-1},{'stock':1.5},{'price':0},{'price':1.5},
                          {'category':'Unknown'},{'name':'  '},{'unit':' '}):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.client.post('/api/manage/products',json={**valid,**overrides}).status_code,422)
        created = self.client.post('/api/manage/products',json={**valid,'active':False})
        self.assertEqual(created.status_code,201)
        pid = created.json()['id']
        self.assertNotIn(pid,[p['id'] for p in self.client.get('/api/stores/1/products').json()])
        self.assertIn(pid,[p['id'] for p in self.client.get('/api/manage/store').json()['products']])

    def test_unlisted_store_can_finish_existing_orders(self):
        self.login()
        oid = self.order().json()['id']
        self.login('admin')
        self.client.patch('/api/admin/stores/1',json={'approved':False})
        self.assertEqual(self.client.get('/api/stores/1/products').status_code,404)
        self.login('store')
        self.assertEqual(self.client.patch(f'/api/orders/{oid}/status',json={'status':'preparing'}).status_code,200)
        self.assertEqual(self.client.patch(f'/api/orders/{oid}/status',json={'status':'cancelled'}).status_code,200)
        self.assertEqual(self.stock(),24)


if __name__ == '__main__':
    unittest.main()
