# Quick Cart

**Fresh picks. Zero queues.**

A supermarket pickup app: browse a local store, reserve groceries, choose a pickup time, and collect your bag. Stores manage their products and orders; an administrator approves stores and reviews customer feedback.

This is a working **web MVP** inspired by the Quick Cart project brief. It uses a responsive HTML/CSS/JavaScript frontend, a FastAPI backend, and persistent SQLite storage. No paid services, API keys, Node build step, or external image/font requests are needed.

## Start in a few minutes

Requires **Python 3.11 or newer**. Run these commands from the project directory.

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py --demo
```

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py --demo
```

Open **http://127.0.0.1:8010**. Stop with `Ctrl+C`.

`--demo` creates four demo accounts, two approved supermarkets, and twelve products **only when the database has no users**. Running it again preserves existing data. Future starts can omit `--demo`.

The database is created at `data/quickcart.db`. Restarting the server keeps accounts, products, orders, and reviews. The shopping bag is saved in the browser on the same origin.

## Try the complete flow

All demo accounts use the password **`QuickCart123!`**. These are public demo credentials, for local use only.

| Account | Email | What to try |
| --- | --- | --- |
| Customer | `customer@quickcart.demo` | Browse, reserve, track, cancel, review |
| Store: Green Basket | `store@quickcart.demo` | Edit stock and fulfil orders |
| Store: The Daily Pantry | `market@quickcart.demo` | Try the second store and verify its separate orders |
| Administrator | `admin@quickcart.demo` | Approve stores, view accounts, orders, and feedback |

1. Browse **Green Basket**, search or filter products, and add items to your bag.
2. Open **Bag**, choose a pickup time, and sign in as the customer. Reserve the order.
3. Open **My orders** to see the reservation and total. Payment is due at the store.
4. Sign out and sign in as `store@quickcart.demo`. In **Store dashboard**, advance the order through **Start preparing → Mark ready for pickup → Confirm collection**.
5. Sign back in as the customer and leave a review on the collected order.
6. Sign in as the administrator and open **Feedback** to see the review.

Use separate browser profiles or a private window to view customer and store accounts simultaneously; tabs in the same browser profile share a session. Order views refresh every 20 seconds while visible.

To try store onboarding, create an account with **Run a supermarket**, add products in the store dashboard, then approve the store using the administrator account. Pending stores remain hidden from public browsing.

## What works

- Customer and store registration; sign-in and sign-out with role-based permissions.
- Approved supermarket browsing, product search, categories, prices, pack sizes, and available stock.
- One-store bags with quantity controls and a confirmation before switching a nonempty bag to another store.
- Pickup reservations between 15 minutes and 7 days ahead, stored in UTC and shown in the browser’s local timezone.
- Stock reservation in a SQLite write transaction, preventing simultaneous checkouts from overselling.
- Server-calculated totals in integer paise; completed order lines retain their original names, quantities, pack sizes, and prices.
- Order tracking and controlled status transitions.
- Customer cancellation before preparation; stores may cancel any uncollected order. Cancellation restores stock exactly once.
- Store-owned product creation/editing, stock updates, and hiding products from new shoppers.
- One review per collected order, visible to the customer, store, and administrator.
- Admin store approval/unlisting, account directory, all orders, and feedback review.
- Responsive layouts, native keyboard-accessible dialogs, form errors, and loading/empty states.

Order lifecycle:

```text
Placed → Preparing → Ready for pickup → Collected
   └─────────┴────────────┴────────────→ Cancelled (store)
   └─────────────────────────────────→ Cancelled (customer)
```

Unlisting a store stops new browsing and reservations. Its owner can still fulfil existing orders. Product stock represents **available units**, excluding units already reserved; updating stock sets the available count, rather than adding to it.

## Start without demo data

Set up the virtual environment and install requirements as above, then create an administrator locally:

```powershell
.\.venv\Scripts\python.exe manage.py admin@example.com --name "Store Administrator"
.\.venv\Scripts\python.exe run.py
```

On macOS/Linux, use `.venv/bin/python`. The command prompts for a password and confirmation; it never changes an existing account. Register store/customer accounts through the UI, then approve stores from the admin dashboard. Admin registration is not available through the public API.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `QUICKCART_DB` | `<project>/data/quickcart.db` | SQLite file path; use an absolute path for clarity |
| `QUICKCART_SECURE_COOKIE` | unset | Set to `1` only when serving through HTTPS |
| `run.py --port` | `8010` | Local server port |
| `run.py --host` | `127.0.0.1` | Bind address; defaults to this computer only |

Example for a different database and port in PowerShell:

```powershell
$env:QUICKCART_DB = Join-Path $PWD "data\another-demo.db"
.\.venv\Scripts\python.exe run.py --demo --port 8011
```

For a fresh demo, use a **new database filename** and `--demo`. Copy the existing SQLite file with the server stopped to back it up.

## Development and tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The integration suite uses temporary databases and the actual FastAPI routes. It covers onboarding and approval, order fulfilment and reviews, ownership/role boundaries, atomic cancellation, invalid carts and pickup times, price snapshots, restart persistence, expired/logout sessions, origin checks, login throttling, and concurrent stock reservations. It does not modify the demo database.

If Node is installed, also check frontend JavaScript syntax:

```bash
node --check static/app.js
```

GitHub Actions runs these checks on Windows and Linux with Python 3.11 and 3.13. UI layout and interactions should also be checked in a browser; the integration tests do not replace visual testing.

## Project structure

```text
QuickCart/
├── app/
│   ├── db.py                # Schema, password hashing, demo fixtures
│   └── main.py              # API, permissions, sessions, stock transactions
├── static/
│   ├── index.html           # App shell
│   ├── app.js               # Shopping and management interfaces
│   ├── styles.css           # Responsive theme
│   ├── base.css
│   └── icon.svg
├── tests/test_workflows.py  # API integration tests
├── .github/workflows/      # CI checks
├── manage.py               # Local administrator creation
├── run.py                  # Server entry point and optional demo seeding
├── requirements.txt
└── requirements-dev.txt
```

## API at a glance

All application endpoints begin with `/api`. Money values are **integer paise** (`6500` means ₹65). Requests and responses use JSON. Authenticated requests use the `quickcart_session` cookie. The OpenAPI schema is available at `/openapi.json`; `/api/health` is a simple health check.

| Method | Endpoint | Access |
| --- | --- | --- |
| `POST` | `/api/auth/register`, `/api/auth/login`, `/api/auth/logout` | Public |
| `GET` | `/api/auth/me` | Signed-in user |
| `GET` | `/api/stores`, `/api/stores/{id}/products` | Public approved stores |
| `POST` | `/api/orders` | Customer |
| `GET` | `/api/orders` | Own orders; admin sees all |
| `PATCH` | `/api/orders/{id}/status` | Owning customer/store, subject to lifecycle rules |
| `POST` | `/api/orders/{id}/feedback` | Owning customer, collected order |
| `GET` | `/api/manage/store` | Store owner |
| `POST` | `/api/manage/products` | Store owner |
| `PUT` | `/api/manage/products/{id}` | Owning store |
| `GET` | `/api/admin/overview` | Administrator |
| `PATCH` | `/api/admin/stores/{id}` | Administrator |

## MVP boundaries

This is a local demonstration, not a production commerce service. Payment is **pay at pickup**; there is no online payment, delivery, refund processing, tax/invoicing system, or integration with real supermarket inventory. Product illustrations are emoji, with appearance varying by platform.

Pickup times are requested timestamps, not capacity-controlled slots. Store opening hours, automatic reservation expiry, pickup verification codes, email/SMS/push notifications, password reset/email verification, account deletion/suspension, audit logs, and a native Flutter/Android app are future work. Administrators can view accounts but cannot edit/delete them in this MVP.

Passwords use PBKDF2-HMAC-SHA256 with a random salt and 600,000 iterations. Session tokens are random, stored hashed in the database, and expire after 24 hours. Cookies are HttpOnly and SameSite=Strict; writes reject mismatched browser Origins. Authentication attempts are throttled per client IP in memory, intended for one process. This limit resets on restart and is not a distributed protection mechanism.

Before hosting publicly: replace demo data, use HTTPS and secure cookies, add deployment-grade rate limiting, backups/migrations and operational monitoring, and review the application’s security and business rules. The included server setup is for local development.
