'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = n => new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR', maximumFractionDigits:2}).format(n / 100);
const when = s => new Date(s).toLocaleString('en-IN', {day:'numeric', month:'short', hour:'numeric', minute:'2-digit'});
const categories = ['All', 'Vegetables', 'Fruits', 'Dairy', 'Bakery', 'Pantry', 'Other'];
const state = {user:null, stores:[], storeId:null, products:[], category:'All', search:'', tab:'orders', orders:[], managed:null, overview:null};
let cart = {storeId:null, items:{}};
try {
  const saved = JSON.parse(localStorage.getItem('quickcart_bag'));
  if (saved && Number.isInteger(saved.storeId) && saved.items && typeof saved.items === 'object') {
    cart = {storeId:saved.storeId, items:Object.fromEntries(Object.entries(saved.items).filter(([id,q]) => /^\d+$/.test(id) && Number.isInteger(q) && q > 0 && q <= 99))};
  }
} catch { /* A malformed or unavailable local cache should not stop shopping. */ }
let toastTimer, renderVersion = 0, checkingOut = false;

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {credentials:'same-origin', ...options, headers:{'Content-Type':'application/json', ...options.headers}});
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    let detail = body.detail;
    if (Array.isArray(detail)) detail = detail.map(e => `${e.loc.slice(1).join(' ')}: ${e.msg}`).join('; ');
    throw new Error(detail || 'Something went wrong. Please try again.');
  }
  return body;
}
function toast(message) {
  $('#toast').textContent = message;
  $('#toast').classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 4200);
}
function saveCart() {
  try { localStorage.setItem('quickcart_bag', JSON.stringify(cart)); } catch { /* Bag still works in this tab. */ }
  renderHeader();
}
function bagCount() { return Object.values(cart.items).reduce((a,b) => a+b, 0); }
function emoji(p) {
  const name = p.name.toLowerCase();
  for (const [word, icon] of Object.entries({tomato:'🍅',banana:'🍌',milk:'🥛',bread:'🍞',carrot:'🥕',apple:'🍎',egg:'🥚',rice:'🍚',oat:'🌾',sourdough:'🥖'})) if (name.includes(word)) return icon;
  return ({Vegetables:'🥬', Fruits:'🍊', Dairy:'🧀', Bakery:'🥐', Pantry:'🫘'})[p.category] || '🛍️';
}
function route() { return location.hash.slice(1).split('?')[0] || 'shop'; }
function renderHeader() {
  const r = route();
  const links = [['shop','Shop local'], ['orders','My orders']];
  if (state.user?.role === 'store') links.push(['manage','Store dashboard']);
  if (state.user?.role === 'admin') links.push(['admin','Admin dashboard']);
  $('#nav').innerHTML = links.map(([key,label]) => `<a href="#${key}" class="${key === r ? 'active' : ''}" ${key === r ? 'aria-current="page"' : ''}>${label}</a>`).join('');
  $('#account').innerHTML = (state.user ? `<span class="signed-in" title="${esc(state.user.name)}">Hi, ${esc(state.user.name.split(' ')[0])}</span><button class="text-button" data-action="logout">Sign out</button>` : '<button class="text-button" data-action="login">Sign in</button>') + `<button class="secondary" data-action="bag" aria-label="Open bag, ${bagCount()} items">Bag <span class="bag-count">${bagCount()}</span></button>`;
}
function empty(title, message, action = '') {
  return `<div class="empty"><span aria-hidden="true">🧺</span><h2>${esc(title)}</h2><p>${esc(message)}</p>${action}</div>`;
}
function modalHeader(title, subtitle, id) {
  return `<div class="modal-head"><div><h2 id="${id}">${esc(title)}</h2><p>${esc(subtitle)}</p></div><button type="button" class="close" data-action="close" aria-label="Close dialog">×</button></div>`;
}
function showDialog(id, html) {
  const dialog = $(id);
  dialog.innerHTML = `<div class="modal-body">${html}</div>`;
  if (!dialog.open) dialog.showModal();
  return dialog;
}
async function render() {
  const version = ++renderVersion;
  const r = route();
  renderHeader();
  $('#main').innerHTML = '<div class="loading" role="status">Getting the good stuff ready…</div>';
  try {
    if (r === 'shop') {
      state.stores = await api('/stores');
      if (!state.stores.some(s => s.id === state.storeId)) state.storeId = state.stores.find(s => s.id === cart.storeId)?.id || state.stores[0]?.id || null;
      state.products = state.storeId ? await api(`/stores/${state.storeId}/products`) : [];
      if (version !== renderVersion) return;
      renderShop();
    } else if (r === 'orders') {
      if (!state.user) {
        $('#main').innerHTML = `<div class="page-heading"><h1>Your pickup orders</h1><p>From your first add to your last pickup.</p></div>${empty('Your orders live here', 'Sign in to track your groceries and see past pickups.', '<button class="primary" data-action="login">Sign in to continue</button>')}`;
        return;
      }
      state.orders = await api('/orders');
      if (version !== renderVersion) return;
      $('#main').innerHTML = `<div class="page-heading"><div class="eyebrow">Fresh plans</div><h1>Your pickup orders</h1><p>Status updates refresh every 20 seconds. Payment happens at the store.</p></div>${renderOrders(state.orders)}`;
    } else if (r === 'manage' && state.user?.role === 'store') {
      [state.managed, state.orders] = await Promise.all([api('/manage/store'), api('/orders')]);
      if (version !== renderVersion) return;
      renderManage();
    } else if (r === 'admin' && state.user?.role === 'admin') {
      [state.overview, state.orders] = await Promise.all([api('/admin/overview'), api('/orders')]);
      if (version !== renderVersion) return;
      renderAdmin();
    } else {
      $('#main').innerHTML = `<div class="page-heading"><h1>Let’s get you back to the good stuff.</h1></div>${empty('This page is not available', 'Choose a page above or sign in with the right account.', '<a class="primary" href="#shop">Browse groceries</a>')}`;
    }
  } catch (e) {
    if (version === renderVersion) $('#main').innerHTML = `<div class="view-error"><h2>We couldn’t load this page</h2><p>${esc(e.message)}</p><button class="secondary" data-action="refresh">Try again</button></div>`;
  }
}
function renderShop() {
  const selected = state.stores.find(s => s.id === state.storeId);
  $('#main').innerHTML = `
    <section class="hero" aria-label="Shop local, skip the queue">
      <div class="hero-copy"><div class="eyebrow">Your neighbourhood, in a bag</div><h1>Fresh picks.<br>Zero <em>queues.</em></h1><p>Your favourite local groceries, ready when you are. Fill your bag online. Swing by and pick it up.</p><a href="#catalog" class="primary" id="shop-cta">Explore the shelves <span aria-hidden="true">↗</span></a></div>
      <div class="hero-art" aria-hidden="true"><div class="halo"></div><span class="produce p1">🥬</span><span class="produce p2">🥖</span><span class="produce p3">🥕</span><div class="grocery-bag"><div class="bag-label"><b>qc.</b>GOOD & LOCAL</div></div><span class="produce p4">🍅</span><span class="produce p5">🍋</span><div class="art-note"><strong>Picked with care.</strong>Collected by you.</div><div class="hero-caption">A fresh way to shop your everyday.</div></div>
    </section>
    <div class="perks"><div class="perk"><span class="perk-icon" aria-hidden="true">⌂</span><div><strong>Love your local</strong><span>Good things, close to home</span></div></div><div class="perk"><span class="perk-icon" aria-hidden="true">◷</span><div><strong>Your time is yours</strong><span>Pick a time. Skip the line.</span></div></div><div class="perk"><span class="perk-icon" aria-hidden="true">♧</span><div><strong>Fresh, not rushed</strong><span>Reserved just for you</span></div></div></div>
    <section id="catalog" aria-labelledby="catalog-title"><div class="section-top"><div><h2 id="catalog-title">A little of everything good.</h2><p>Everyday essentials from around the corner.</p></div><label class="store-picker">Shopping at <select id="store-select" aria-label="Choose a supermarket">${state.stores.map(s => `<option value="${s.id}" ${s.id === state.storeId ? 'selected' : ''}>${esc(s.name)} · ${esc(s.location)}</option>`).join('')}</select></label></div>
    ${selected ? `<p class="store-description">${esc(selected.description || `Pickup at ${selected.location}`)}</p>` : ''}
    <div class="catalog-tools"><div class="categories" aria-label="Product categories">${categories.map(c => `<button class="chip ${c === state.category ? 'selected' : ''}" data-action="category" data-value="${c}" aria-pressed="${c === state.category}">${c}</button>`).join('')}</div><div class="search"><input type="search" id="search" placeholder="Find your everyday favourites…" value="${esc(state.search)}" aria-label="Search products"></div></div><div class="products" id="products"></div></section>
    <section class="how" aria-label="How Quick Cart works"><h2>Three steps.<br>More free time.</h2><div class="step"><span>01</span><strong>Find your favourites</strong><p>Browse your local store’s shelves.</p></div><div class="step"><span>02</span><strong>Make it your time</strong><p>Choose a pickup time that suits you.</p></div><div class="step"><span>03</span><strong>Grab it. Get going.</strong><p>Pay at the store and enjoy your day.</p></div></section>`;
  renderProducts();
  $('#shop-cta').onclick = e => { e.preventDefault(); $('#catalog').scrollIntoView({behavior:'smooth'}); };
  $('#store-select').onchange = e => { state.storeId = Number(e.target.value); state.category = 'All'; state.search = ''; render(); };
  $('#search').oninput = e => { state.search = e.target.value; renderProducts(); };
}
function productQuantity(id) { return cart.storeId === state.storeId ? cart.items[id] || 0 : 0; }
function quantityControl(id, q, inBag = false) {
  return `<div class="quantity"><button type="button" data-action="quantity" data-id="${id}" data-delta="-1" data-bag="${inBag}" aria-label="Remove one item">−</button><span aria-label="Quantity ${q}">${q}</span><button type="button" data-action="quantity" data-id="${id}" data-delta="1" data-bag="${inBag}" aria-label="Add one item">+</button></div>`;
}
function renderProducts() {
  const products = state.products.filter(p => (state.category === 'All' || p.category === state.category) && `${p.name} ${p.category}`.toLowerCase().includes(state.search.toLowerCase()));
  $('#products').innerHTML = products.length ? products.map(p => `<article class="product"><div class="product-picture"><span class="stock-label">${p.stock ? `${p.stock} available` : 'Sold out'}</span><span class="emoji" aria-hidden="true">${emoji(p)}</span></div><div class="product-info"><h3>${esc(p.name)}</h3><p>${esc(p.unit)} · ${esc(p.category)}</p><div class="price-row"><span class="price">${money(p.price)}</span>${productQuantity(p.id) ? quantityControl(p.id, productQuantity(p.id)) : `<button class="add-button" data-action="add" data-id="${p.id}" ${!p.stock ? 'disabled' : ''} aria-label="Add ${esc(p.name)} to bag">+ Add</button>`}</div></div></article>`).join('') : empty(state.stores.length ? 'Nothing on this shelf yet' : 'Your neighbourhood is on its way', state.stores.length ? 'Try another search, category, or store.' : 'An approved store will appear here once it joins Quick Cart.');
}
async function changeQuantity(id, delta, inBag) {
  let p = state.products.find(p => p.id === id);
  if (inBag && cart.storeId !== state.storeId) p = (await api(`/stores/${cart.storeId}/products`)).find(p => p.id === id);
  if (delta > 0 && (!p || p.stock <= (cart.storeId === p.store_id ? cart.items[id] || 0 : 0))) { toast('No more stock available for this item.'); return; }
  if (!inBag && cart.storeId && cart.storeId !== state.storeId && bagCount()) {
    if (!confirm('Your bag contains items from another store. Start a new bag at this store?')) return;
    cart = {storeId:state.storeId, items:{}};
  }
  if (!inBag) cart.storeId = state.storeId;
  const q = Math.max(0, Math.min(99, (cart.items[id] || 0) + delta));
  if (q) cart.items[id] = q; else delete cart.items[id];
  saveCart();
  if (route() === 'shop' && $('#products')) renderProducts();
  if ($('#bag-dialog').open) await openBag();
}
async function openBag() {
  if (checkingOut) return;
  if (!bagCount()) { showDialog('#bag-dialog', modalHeader('Your bag', 'Good things start with a few favourites.', 'bag-title') + empty('A little empty, for now', 'Add some groceries and make your next shop a quick one.', '<button class="primary" data-action="close">Keep shopping</button>')); return; }
  const [products, stores] = await Promise.all([api(`/stores/${cart.storeId}/products`), api('/stores')]);
  const store = stores.find(s => s.id === cart.storeId);
  let total = 0, invalid = false;
  const lines = Object.entries(cart.items).map(([id,q]) => {
    const p = products.find(p => p.id === Number(id));
    if (!p) { invalid = true; return `<div class="bag-line"><div class="bag-line-info"><strong>Unavailable product</strong><small>This item was removed by the store.</small></div><button class="text-button" data-action="remove" data-id="${id}">Remove</button></div>`; }
    total += p.price * q;
    if (q > p.stock) invalid = true;
    return `<div class="bag-line"><span aria-hidden="true">${emoji(p)}</span><div class="bag-line-info"><strong>${esc(p.name)}</strong><small>${esc(p.unit)} · ${money(p.price)} each${q > p.stock ? ` · Only ${p.stock} left` : ''}</small><div>${quantityControl(id,q,true)}</div></div><span class="price">${money(p.price*q)}</span></div>`;
  }).join('');
  const d = showDialog('#bag-dialog', modalHeader('Your good-stuff bag', `Pickup from ${store?.name || 'your store'}`, 'bag-title') + `<form id="checkout-form">${lines}<div class="bag-summary"><strong>Total</strong><strong class="price">${money(total)}</strong></div><p class="bag-note">Pay at pickup. No delivery or extra fees. Stock and prices are checked again when you reserve.</p>${invalid ? '<div class="notice">Some items are unavailable or exceed current stock. Update your bag before reserving.</div>' : ''}<label for="pickup">When would you like to pick up?</label><input id="pickup" name="pickup" type="datetime-local" required><p class="bag-note">At least 15 minutes from now, within the next 7 days. Confirm store opening hours directly.</p><div class="form-error" role="alert"></div><button class="primary full" type="submit" ${invalid ? 'disabled' : ''}>${state.user ? 'Reserve for pickup →' : 'Sign in to reserve →'}</button></form>`);
  const localValue = date => new Date(date.getTime() - date.getTimezoneOffset()*60000).toISOString().slice(0,16);
  $('#pickup').min = localValue(new Date(Date.now() + 16*60000));
  $('#pickup').max = localValue(new Date(Date.now() + 7*86400000 - 60000));
  $('#pickup').value = localValue(new Date(Date.now() + 60*60000));
  $('#checkout-form').onsubmit = async e => {
    e.preventDefault();
    if (!state.user) { d.close(); openAuth('login', true); return; }
    if (state.user.role !== 'customer') { $('.form-error',d).textContent = 'Sign in with a customer account to place an order.'; return; }
    checkingOut = true;
    const button = $('button[type=submit]',d);
    button.disabled = true;
    try {
      const order = await api('/orders', {method:'POST', body:JSON.stringify({store_id:cart.storeId, items:Object.entries(cart.items).map(([id,q]) => ({product_id:Number(id),quantity:q})), pickup_at:new Date($('#pickup').value).toISOString()})});
      cart = {storeId:null,items:{}}; saveCart(); d.close();
      toast(`Order #${String(order.id).padStart(4,'0')} reserved. Your store will prepare it for pickup.`);
      if (route() === 'orders') await render(); else location.hash = 'orders';
    } catch (err) { $('.form-error',d).textContent = err.message; button.disabled = false; }
    finally { checkingOut = false; }
  };
}
function openAuth(mode = 'login', returnToBag = false) {
  const register = mode === 'register';
  const d = showDialog('#auth-dialog', modalHeader(register ? 'Hello, neighbour.' : 'Welcome back.', register ? 'A quicker grocery run starts here.' : 'Your local favourites are waiting.', 'auth-title') + `<form id="auth-form">${register ? '<label for="name">Your name</label><input id="name" name="name" autocomplete="name" required minlength="2" maxlength="80">' : ''}<label for="email">Email address</label><input id="email" name="email" type="email" autocomplete="email" required maxlength="254"><label for="password">Password</label><input id="password" name="password" type="password" autocomplete="${register ? 'new-password' : 'current-password'}" required minlength="10" maxlength="128">${register ? '<p class="bag-note">Use at least 10 characters.</p><label for="role">I’m here to</label><select id="role" name="role"><option value="customer">Shop for groceries</option><option value="store">Run a supermarket</option></select><div id="store-fields" hidden><label for="store-name">Store name</label><input id="store-name" name="store_name" minlength="2" maxlength="100"><label for="location">Location / pickup address</label><input id="location" name="location" minlength="2" maxlength="120"><p class="bag-note">Your store needs admin approval before customers can see it.</p></div>' : ''}<div class="form-error" role="alert"></div><button class="primary full" type="submit">${register ? 'Create account' : 'Sign in'} →</button></form><div class="form-foot">${register ? 'Already a neighbour?' : 'New around here?'} <button type="button" id="auth-switch">${register ? 'Sign in' : 'Create an account'}</button></div>`);
  $('#auth-switch').onclick = () => openAuth(register ? 'login' : 'register', returnToBag);
  if (register) $('#role').onchange = e => {
    const store = e.target.value === 'store';
    $('#store-fields').hidden = !store;
    $('#store-name').required = store; $('#location').required = store;
  };
  $('#auth-form').onsubmit = async e => {
    e.preventDefault();
    const button = $('button[type=submit]',d); button.disabled = true;
    try {
      const data = Object.fromEntries(new FormData(e.target));
      state.user = await api(`/auth/${register ? 'register' : 'login'}`, {method:'POST',body:JSON.stringify(data)});
      d.close(); toast(`Good to see you, ${state.user.name.split(' ')[0]}.`);
      if (returnToBag && state.user.role === 'customer') { await render(); await openBag(); }
      else {
        const dest = state.user.role === 'store' ? 'manage' : state.user.role === 'admin' ? 'admin' : route();
        if (dest === route()) await render(); else location.hash = dest;
      }
    } catch (err) { $('.form-error',d).textContent = err.message; }
    finally { button.disabled = false; }
  };
}
function renderOrders(orders) {
  if (!orders.length) return empty('No pickups on the calendar', 'Your next grocery run could be a whole lot quicker.', '<a class="primary" href="#shop">Find your favourites →</a>');
  const labels = {placed:'Order placed',preparing:'Being prepared',ready:'Ready for pickup',collected:'Collected',cancelled:'Cancelled'};
  return orders.map(o => {
    const stages = ['placed','preparing','ready','collected'];
    const next = {placed:['preparing','Start preparing'],preparing:['ready','Mark ready for pickup'],ready:['collected','Confirm collection']}[o.status];
    const store = state.user.role === 'store';
    return `<article class="panel"><div class="order-header"><div><h3>Order #${String(o.id).padStart(4,'0')} · ${esc(o.store_name)}</h3><small>${esc(o.location)}${state.user.role !== 'customer' ? ` · ${esc(o.customer_name)}` : ''}</small></div><span class="badge ${o.status}">${labels[o.status]}</span></div>${o.status !== 'cancelled' ? `<div class="timeline" aria-label="Order progress">${stages.map((s,i) => `<div class="${i <= stages.indexOf(o.status) ? 'done' : ''}">${labels[s]}</div>`).join('')}</div>` : ''}<div class="order-details"><div>${o.items.map(i => `<p>${i.quantity} × ${esc(i.name)} <small>(${esc(i.unit)})</small> · ${money(i.price*i.quantity)}</p>`).join('')}</div><div><p><strong>Pickup ${esc(when(o.pickup_at))}</strong></p><p class="order-total">${money(o.total)}</p><small>${o.status === 'cancelled' ? 'Reservation cancelled · No payment due' : 'Pay at the store'}</small></div></div><div class="order-actions">${(state.user.role === 'customer' && o.status === 'placed') || (store && !['cancelled','collected'].includes(o.status)) ? `<button class="danger" data-action="status" data-id="${o.id}" data-status="cancelled">Cancel order</button>` : ''}${store && next ? `<button class="primary" data-action="status" data-id="${o.id}" data-status="${next[0]}">${next[1]}</button>` : ''}${state.user.role === 'customer' && o.status === 'collected' && !o.feedback ? `<button class="secondary" data-action="review" data-id="${o.id}">Leave a review</button>` : ''}</div>${o.feedback ? `<div class="order-review"><strong class="review-stars">${'★'.repeat(o.feedback.rating)}${'☆'.repeat(5-o.feedback.rating)}</strong> <span>${esc(o.feedback.message)}</span></div>` : ''}</article>`;
  }).join('');
}
function tabButtons(tabs) { return `<div class="tabs" aria-label="Dashboard views">${tabs.map(([key,label]) => `<button class="${state.tab === key ? 'selected' : ''}" aria-pressed="${state.tab === key}" data-action="tab" data-value="${key}">${label}</button>`).join('')}</div>`; }
function renderManage() {
  const s = state.managed;
  if (!['orders','products'].includes(state.tab)) state.tab = 'orders';
  const active = state.orders.filter(o => !['collected','cancelled'].includes(o.status));
  $('#main').innerHTML = `<div class="page-heading"><div class="eyebrow">Your local, behind the scenes</div><h1>${esc(s.name)}</h1><p>${esc(s.location)} · Manage the shelves. Make someone’s day.</p></div>${!s.approved ? '<div class="notice">Your store is awaiting admin approval. You can prepare your products here; customers will see them once approved.</div>' : ''}<div class="stats"><div class="stat"><strong>${active.length}</strong><span>Active pickups</span></div><div class="stat"><strong>${s.products.filter(p=>p.active).length}</strong><span>Listed products</span></div><div class="stat"><strong>${money(state.orders.filter(o=>o.status==='collected').reduce((a,o)=>a+o.total,0))}</strong><span>Collected order value</span></div></div>${tabButtons([['orders','Pickup orders'],['products','Products & stock']])}<div id="dashboard-content">${state.tab === 'orders' ? renderOrders(state.orders) : `<div class="section-top"><div><h2>Your shelves</h2><p>Stock means available units, excluding existing reservations.</p></div><button class="primary" data-action="product">+ Add product</button></div>${s.products.length ? `<div class="table-wrap"><table><thead><tr><th>Product</th><th>Price</th><th>Available</th><th>Status</th><th>Action</th></tr></thead><tbody>${s.products.map(p => `<tr><td>${esc(p.name)}<small>${esc(p.unit)} · ${esc(p.category)}</small></td><td>${money(p.price)}</td><td>${p.stock}</td><td><span class="badge ${p.active ? '' : 'cancelled'}">${p.active ? 'Listed' : 'Hidden'}</span></td><td><button class="secondary" data-action="product" data-id="${p.id}">Edit</button></td></tr>`).join('')}</tbody></table></div>` : empty('Ready for your first product', 'Add a product to start stocking your shelves.')}`}</div>`;
}
function renderAdmin() {
  const o = state.overview;
  if (!['stores','users','feedback','all-orders'].includes(state.tab)) state.tab = 'stores';
  let content;
  if (state.tab === 'stores') content = o.stores.length ? o.stores.map(s => `<article class="panel"><div class="order-header"><div><h3>${esc(s.name)}</h3><small>${esc(s.location)} · ${esc(s.email)}</small></div><span class="badge ${s.approved ? '' : 'pending'}">${s.approved ? 'Approved' : 'Awaiting approval'}</span></div><button class="${s.approved ? 'secondary' : 'primary'}" data-action="approve" data-id="${s.id}" data-approved="${s.approved ? 'false' : 'true'}">${s.approved ? 'Unlist store' : 'Approve store'}</button></article>`).join('') : empty('No stores yet', 'New store registrations will appear here for approval.');
  else if (state.tab === 'users') content = `<div class="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th></tr></thead><tbody>${o.users.map(u => `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td><span class="badge">${esc(u.role)}</span></td></tr>`).join('')}</tbody></table></div>`;
  else if (state.tab === 'feedback') content = o.feedback.length ? o.feedback.map(f => `<div class="panel"><div class="order-header"><h3>${esc(f.store_name)} · Order #${String(f.order_id).padStart(4,'0')}</h3><span class="review-stars">${'★'.repeat(f.rating)}</span></div><p>${esc(f.message)}</p><small>${esc(f.customer_name)} · ${esc(when(f.created_at))}</small></div>`).join('') : empty('A fresh start', 'Customer reviews appear here after a completed pickup.');
  else content = renderOrders(state.orders);
  $('#main').innerHTML = `<div class="page-heading"><div class="eyebrow">Neighbourhood headquarters</div><h1>A good local network.</h1><p>Approve stores, view accounts, and keep an eye on the experience.</p></div><div class="stats"><div class="stat"><strong>${o.stores.filter(s=>!s.approved).length}</strong><span>Stores awaiting approval</span></div><div class="stat"><strong>${o.users.length}</strong><span>Registered neighbours</span></div><div class="stat"><strong>${state.orders.length}</strong><span>Total orders</span></div></div>${tabButtons([['stores','Store approvals'],['users','Accounts'],['feedback','Feedback'],['all-orders','All orders']])}${content}`;
}
function openProduct(id) {
  const p = state.managed.products.find(p => p.id === id);
  const d = showDialog('#product-dialog', modalHeader(p ? 'Edit the essentials' : 'Something good to add', 'Prices are in rupees. Stock is available units.', 'product-title') + `<form id="product-form"><label for="product-name">Product name</label><input id="product-name" name="name" required minlength="2" maxlength="100" value="${esc(p?.name || '')}"><div class="field-pair"><div><label for="product-category">Category</label><select id="product-category" name="category">${categories.slice(1).map(c => `<option ${c === p?.category ? 'selected' : ''}>${c}</option>`).join('')}</select></div><div><label for="product-unit">Pack / unit</label><input id="product-unit" name="unit" required maxlength="40" placeholder="e.g. 500 g" value="${esc(p?.unit || '')}"></div></div><div class="field-pair"><div><label for="product-price">Price (₹)</label><input id="product-price" name="price" type="number" step="0.01" min="0.01" max="100000" required value="${p ? (p.price/100).toFixed(2) : ''}"></div><div><label for="product-stock">Available stock</label><input id="product-stock" name="stock" type="number" step="1" min="0" max="100000" required value="${p?.stock ?? 0}"></div></div><label><input name="active" type="checkbox" ${!p || p.active ? 'checked' : ''}> List this product for customers</label><p class="bag-note">Hide a product to stop new orders. Existing order details stay unchanged.</p><div class="form-error" role="alert"></div><button class="primary full" type="submit">Save product →</button></form>`);
  $('#product-form').onsubmit = async e => {
    e.preventDefault(); const button = $('button[type=submit]',d); button.disabled = true;
    const f = new FormData(e.target);
    try {
      await api(`/manage/products${p ? `/${p.id}` : ''}`, {method:p ? 'PUT' : 'POST', body:JSON.stringify({name:f.get('name'), category:f.get('category'), unit:f.get('unit'), price:Math.round(Number(f.get('price'))*100), stock:Number(f.get('stock')), active:f.has('active')})});
      d.close(); toast('Your shelves are up to date.'); await render();
    } catch (err) { $('.form-error',d).textContent = err.message; }
    finally { button.disabled = false; }
  };
}
function openReview(id) {
  const d = showDialog('#review-dialog', modalHeader('How was your pickup?', 'A little feedback goes a long way.', 'review-title') + `<form id="review-form"><label for="rating">Your rating</label><select id="rating" name="rating">${[5,4,3,2,1].map(n => `<option value="${n}">${n} ${n === 1 ? 'star' : 'stars'}</option>`).join('')}</select><label for="message">Tell us about it</label><textarea id="message" name="message" rows="4" minlength="3" maxlength="1000" required></textarea><div class="form-error" role="alert"></div><button class="primary full" type="submit">Share your review →</button></form>`);
  $('#review-form').onsubmit = async e => {
    e.preventDefault(); const button = $('button[type=submit]',d); button.disabled = true;
    try { await api(`/orders/${id}/feedback`, {method:'POST',body:JSON.stringify({rating:Number($('#rating').value),message:$('#message').value})}); d.close(); toast('Thanks for sharing a little local love.'); await render(); }
    catch (err) { $('.form-error',d).textContent = err.message; button.disabled = false; }
  };
}
document.addEventListener('click', async event => {
  const button = event.target.closest('[data-action]');
  if (!button || button.disabled) return;
  const a = button.dataset.action, id = Number(button.dataset.id);
  try {
    if (a === 'close') button.closest('dialog').close();
    else if (a === 'login') openAuth();
    else if (a === 'logout') { await api('/auth/logout',{method:'POST'}); state.user = null; toast('You’re signed out. See you around.'); location.hash = 'shop'; await render(); }
    else if (a === 'bag') {
      try { await openBag(); } catch (err) {
        showDialog('#bag-dialog', modalHeader('Your bag needs a fresh start', 'This store may no longer be available.', 'bag-title') + `<p>${esc(err.message)}</p><button class="danger" data-action="clear-bag">Clear bag</button>`);
      }
    }
    else if (a === 'clear-bag') { cart = {storeId:null,items:{}}; saveCart(); await openBag(); }
    else if (a === 'category') { state.category = button.dataset.value; document.querySelectorAll('.chip').forEach(b => { b.classList.toggle('selected', b === button); b.setAttribute('aria-pressed',String(b === button)); }); renderProducts(); }
    else if (a === 'add') await changeQuantity(id,1,false);
    else if (a === 'quantity') await changeQuantity(id,Number(button.dataset.delta),button.dataset.bag === 'true');
    else if (a === 'remove') { delete cart.items[id]; saveCart(); await openBag(); }
    else if (a === 'refresh') await render();
    else if (a === 'tab') { state.tab = button.dataset.value; route() === 'admin' ? renderAdmin() : renderManage(); }
    else if (a === 'product') openProduct(id);
    else if (a === 'review') openReview(id);
    else if (a === 'status') {
      if (button.dataset.status === 'cancelled' && !confirm('Cancel this order? Reserved stock will be returned to the shelves.')) return;
      button.disabled = true;
      await api(`/orders/${id}/status`, {method:'PATCH',body:JSON.stringify({status:button.dataset.status})});
      toast('Order updated.'); await render();
    } else if (a === 'approve') {
      button.disabled = true;
      await api(`/admin/stores/${id}`, {method:'PATCH',body:JSON.stringify({approved:button.dataset.approved === 'true'})});
      toast('Store visibility updated.'); await render();
    }
  } catch (e) { button.disabled = false; toast(e.message); }
});
window.addEventListener('hashchange', render);
setInterval(async () => {
  if (document.hidden || document.querySelector('dialog[open]') || !state.user || !['orders','manage','admin'].includes(route())) return;
  // Refresh only order views, preserving dashboard editing and tab selections.
  if (route() === 'orders' || (route() === 'manage' && state.tab === 'orders') || (route() === 'admin' && state.tab === 'all-orders')) {
    try {
      const orders = await api('/orders');
      if (JSON.stringify(orders) !== JSON.stringify(state.orders)) { state.orders = orders; await render(); }
    } catch { /* Keep the current view; manual refresh surfaces connection failures. */ }
  }
}, 20000);
(async () => { try { state.user = await api('/auth/me'); } catch { state.user = null; } await render(); })();
