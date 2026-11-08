from html import escape
from pathlib import Path
from datetime import date
import uuid

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import db


db.init()
app = FastAPI(title="Lapka")
app.add_middleware(SessionMiddleware, secret_key="change-me-in-production")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

EMOJI = {"Корма": "🥣", "Іграшки": "🐥", "Лежанки": "🛏️", "Нашийники та повідки": "🦮", "Клітки та переноски": "🧳", "Догляд": "🧴"}
STATUSES = ["Нове", "В обробці", "Відправлено", "Доставлено", "Скасовано"]
PSEL = "SELECT p.*, c.name AS cat FROM Products p JOIN Categories c ON c.id = p.category_id"


def money(v):
    return f"{(v or 0):,.0f}".replace(",", " ") + " грн"


def d(s):
    return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if s else ""


def me(r):
    uid = r.session.get("uid")
    return db.q("SELECT * FROM Clients WHERE id=?", (uid,), one=True) if uid else None


def go(url, r=None, msg=None):
    if msg and r is not None:
        r.session["flash"] = msg
    return RedirectResponse(url, 303)


def cart_items(r):
    items, total = [], 0
    for pid, n in r.session.get("cart", {}).items():
        product = db.q(
            "SELECT p.*, c.name AS cat FROM Products p JOIN Categories c ON c.id = p.category_id WHERE p.id=?",
            (int(pid),),
            one=True,
        )
        if product:
            items.append({"p": product, "n": n, "sum": product["price"] * n})
            total += product["price"] * n
    return items, total


def _nav_html(user=None, cart_n=0, admin=False, section=None, new_n=0):
    if admin:
        nav = [
            ("home", "/admin", "Головна", "🏠"),
            ("products", "/admin/products", "Товари", "📦"),
            ("categories", "/admin/categories", "Категорії", "🏷"),
            ("suppliers", "/admin/suppliers", "Постачальники", "🚚"),
            ("orders", "/admin/orders", "Замовлення", "🛒"),
            ("clients", "/admin/clients", "Клієнти", "👥"),
            ("stats", "/admin/stats", "Статистика", "📊"),
        ]
        rows = []
        for key, href, label, icon in nav:
            active = " on" if section == key else ""
            badge = "<b class=\"badge\">%s</b>" % new_n if key == "orders" and new_n else ""
            rows.append(f'<a class="nav{active}" href="{href}"><span>{icon}</span>{label}{badge}</a>')
        rows.append('<a class="nav" href="/logout" style="margin-top:auto"><span>↩</span>Вихід</a>')
        return "".join(rows)

    nav = [
        ("/", "Головна", "🏠"),
        ("/catalog", "Каталог", "▦"),
        ("/cart", "Кошик", "🛒"),
        ("/orders", "Мої замовлення", "📋"),
        ("/profile", "Профіль", "👤"),
        ("/about", "Про магазин", "ℹ️"),
    ]
    rows = []
    for href, label, icon in nav:
        active = " on" if href == "/" and not section else ""
        if href != "/":
            active = " on" if section and href.startswith(section) else active
        badge = "<b class=\"badge\">%s</b>" % cart_n if href == "/cart" and cart_n else ""
        rows.append(f'<a class="nav{active}" href="{href}"><span>{icon}</span>{label}{badge}</a>')
    if user and user.get("role") == "seller":
        rows.append('<a class="nav" href="/admin"><span>🛠</span>Панель продавця</a>')
    return "".join(rows)


def _flash_html(flash):
    return f'<div class="flash">{escape(flash)}</div>' if flash else ""


def _icon_for(name):
    return EMOJI.get(name, "🐾")


def _product_card(product):
    image = product.get("image_url")
    picture = (
        f'<img class="product-photo" src="{escape(image)}" alt="{escape(product["name"])}">'
        if image
        else f'<div class="pimg">{_icon_for(product.get("cat", ""))}</div>'
    )
    return f"""
    <article class="card">
      <a class="product-link" href="/product/{product['id']}">
        {picture}
        <h4>{escape(product['name'])}</h4>
        <small>{escape(product.get('cat', ''))}</small>
        <span class="product-more">Детальніше →</span>
      </a>
      <div class="row">
        <b>{money(product['price'])}</b>
        <form method="post" action="/cart/add/{product['id']}"><button class="btn sq">+ в кошик</button></form>
      </div>
    </article>
    """


def _category_tile(category, index):
    return f'<a class="tile c{index % 6}" href="/catalog?cat={category["id"]}"><span class="e">{_icon_for(category["name"])}</span>{escape(category["name"])}</a>'


def _page_shell(title, body, *, user=None, cart_n=0, flash=None, admin=False, section=None, new_n=0):
    top_links = []
    if user:
        top_links.append(f'<a class="topl" href="/profile">👤 {escape(user["full_name"])}</a>')
        top_links.append('<a class="topl" href="/logout">Вийти</a>')
    else:
        top_links.append('<a class="topl" href="/login">👤 Вхід</a>')
    top_links.append(f'<a class="topl" href="/cart">🛒 Кошик{f" <b class=\"badge\">{cart_n}</b>" if cart_n else ""}</a>')
    if admin:
        top_bar = f'<div class="top"><h1 style="flex:1;margin:0">{escape(title)}</h1><span class="topl">👤 Продавець {escape(user["full_name"])}</span></div>'
    else:
        top_bar = f'''<header class="top"><form action="/catalog" class="search"><input name="q" placeholder="🔍 Пошук товарів..."></form>{''.join(top_links)}</header>'''
    nav = _nav_html(user=user, cart_n=cart_n, admin=admin, section=section, new_n=new_n)
    logo = '<a class="logo" href="/">🐾 PetShop</a>'
    return f'''<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><link rel="stylesheet" href="/static/style.css"></head><body><div class="app"><aside class="side">{logo}{nav}</aside><main>{top_bar}{_flash_html(flash)}{body}</main></div></body></html>'''


def render(r, name, **c):
    user = me(r)
    cart_n = sum(r.session.get("cart", {}).values())
    flash = r.session.pop("flash", None)
    section = c.get("section")
    if name == "home":
        cats = c.get("cats", [])
        pop = c.get("pop", [])
        body = f'''<div class="hero"><div><h1>Турбота про<br>ваших улюбленців</h1><p>Корма, іграшки, лежанки, аксесуари<br>та багато іншого</p><a class="btn" href="/catalog">Перейти до каталогу →</a></div><div class="big">🐶🐱</div></div><div class="tiles">{''.join(_category_tile(cat, idx) for idx, cat in enumerate(cats))}</div><div class="sec"><h2>Популярні товари</h2><a href="/catalog">Дивитися всі →</a></div><div class="grid">{''.join(_product_card(p) for p in pop)}</div>'''
        return HTMLResponse(_page_shell("Lapka – Інтернет зоомагазин", body, user=user, cart_n=cart_n, flash=flash, section="/"))
    if name == "catalog":
        prods = c.get("prods", [])
        cats = c.get("cats", [])
        qv = escape(c.get("q", ""))
        selected_cat = c.get("cat", 0)
        body = f'''<div class="sec"><h2>Каталог</h2></div><div class="pills">{''.join(f'<a class="pill{ " on" if cat_id == selected_cat else ""}" href="/catalog?cat={cat_id}">{escape(cat["name"])}</a>' for cat_id, cat in [(0, {"name": "Усі"})] + [(item["id"], item) for item in cats])}</div><form class="panel" method="get" action="/catalog"><div class="fg"><div><label>Пошук</label><input name="q" value="{qv}"></div><div><label>Категорія</label><select name="cat"><option value="0">Усі</option>{''.join(f'<option value="{item["id"]}" {"selected" if item["id"] == selected_cat else ""}>{escape(item["name"])}</option>' for item in cats)}</select></div><div><label>Ціна від</label><input name="pmin" value="{escape(c.get('pmin',''))}"></div><div><label>Ціна до</label><input name="pmax" value="{escape(c.get('pmax',''))}"></div></div><button class="btn" type="submit">Фільтрувати</button></form><div class="grid">{''.join(_product_card(p) for p in prods)}</div>'''
        return HTMLResponse(_page_shell("Каталог", body, user=user, cart_n=cart_n, flash=flash, section="/catalog"))
    if name == "product":
        product = c["product"]
        image = product.get("image_url")
        picture = (
            f'<img class="product-photo detail-photo" src="{escape(image)}" alt="{escape(product["name"])}">'
            if image
            else f'<div class="pimg detail-placeholder">{_icon_for(product.get("cat", ""))}</div>'
        )
        description = escape(product.get("description") or "Опис товару ще не додано.").replace("\n", "<br>")
        availability = "Є в наявності" if product["stock"] > 0 else "Немає в наявності"
        add_button = (
            f'<form method="post" action="/cart/add/{product["id"]}"><button class="btn" type="submit">Додати до кошика</button></form>'
            if product["stock"] > 0
            else '<button class="btn" type="button" disabled>Немає в наявності</button>'
        )
        body = f'''<p><a class="back-link" href="/catalog">← До каталогу</a></p><section class="product-detail"><div class="panel detail-picture">{picture}</div><div class="panel detail-info"><small>{escape(product.get("cat", ""))}</small><h2>{escape(product["name"])}</h2><div class="detail-price">{money(product["price"])}</div><p class="stock">{availability} · Кількість: {product["stock"]}</p><p class="detail-description">{description}</p>{add_button}</div></section>'''
        return HTMLResponse(_page_shell(product["name"], body, user=user, cart_n=cart_n, flash=flash, section="/catalog"))
    if name == "cart":
        items = c.get("items", [])
        total = c.get("total", 0)
        if not items:
            body = '<div class="panel"><h3>Кошик порожній</h3><a class="btn" href="/catalog">Повернутися до каталогу</a></div>'
        else:
            rows = []
            for item in items:
                p = item["p"]
                rows.append(f'''<div class="item"><div class="pimg">{_icon_for(p.get('cat',''))}</div><div class="nm"><b>{escape(p['name'])}</b><br><small>{escape(p.get('cat',''))}</small></div><div class="qty"><form method="post" action="/cart/set/{p['id']}" style="display:flex;align-items:center;gap:8px"><input type="hidden" name="delta" value="-1"><button type="submit">−</button></form><span>{item['n']}</span><form method="post" action="/cart/set/{p['id']}" style="display:flex;align-items:center;gap:8px"><input type="hidden" name="delta" value="1"><button type="submit">+</button></form></div><b>{money(item['sum'])}</b><form method="post" action="/cart/remove/{p['id']}" style="display:inline"><button class="xbtn" type="submit">🗑</button></form></div>''')
            form = '''<div class="panel"><h3>Оформлення</h3><form method="post" action="/checkout"><div class="fg"><div><label>ПІБ</label><input name="full_name" value="%s" required></div><div><label>Телефон</label><input name="phone" value="%s" required></div><div class="full"><label>Адреса</label><input name="address" value="%s" required></div><div><label>Відділення</label><input name="post_office" value="%s"></div><div><label>Оплата</label><select name="payment"><option>Післяплата</option><option>Оплата карткою</option></select></div></div><button class="btn" type="submit">Оформити замовлення</button></form></div>''' % (escape(user["full_name"]) if user else "", escape(user["phone"]) if user else "", escape(user["address"]) if user else "", escape(user["post_office"]) if user else "")
            body = f'''<div class="cat"><div class="panel"><h3>Товари в кошику</h3>{''.join(rows)}</div><div><div class="panel"><div class="row"><span>Разом</span><div class="total">{money(total)}</div></div>{form}</div></div></div>'''
        return HTMLResponse(_page_shell("Кошик", body, user=user, cart_n=cart_n, flash=flash, section="/cart"))
    if name == "orders":
        orders = c.get("orders", [])
        if not orders:
            body = '<div class="panel"><h3>Замовлень ще немає</h3></div>'
        else:
            lines = []
            for order in orders:
                items = "".join(f'<li>{escape(i["name"])} × {i["qty"]}</li>' for i in order["items"])
                lines.append(f'<div class="panel"><h3>Замовлення №{order["o"]["id"]}</h3><p>{d(order["o"]["order_date"])} · {escape(order["o"]["status"])}</p><ul>{items}</ul><b>{money(order["o"]["total"])}</b></div>')
            body = "".join(lines)
        return HTMLResponse(_page_shell("Мої замовлення", body, user=user, cart_n=cart_n, flash=flash, section="/orders"))
    if name == "profile":
        body = f'''<div class="auth"><div class="panel"><h3>Профіль</h3><form method="post" action="/profile"><label>ПІБ</label><input name="full_name" value="{escape(user['full_name'])}" required><label>Телефон</label><input name="phone" value="{escape(user.get('phone',''))}"><label>Адреса</label><input name="address" value="{escape(user.get('address',''))}"><label>Відділення</label><input name="post_office" value="{escape(user.get('post_office',''))}"><button class="btn" type="submit">Зберегти</button></form></div></div>'''
        return HTMLResponse(_page_shell("Профіль", body, user=user, cart_n=cart_n, flash=flash, section="/profile"))
    if name == "about":
        body = '<div class="panel"><h3>Про магазин</h3><p>Lapka — зоомагазин з кормами, іграшками, лежанками та аксесуарами для котів, собак та інших домашніх улюбленців.</p></div>'
        return HTMLResponse(_page_shell("Про магазин", body, user=user, cart_n=cart_n, flash=flash, section="/about"))
    if name == "login":
        mode = c.get("mode", "login")
        action = "/login" if mode == "login" else "/register"
        role_picker = (
            '<div class="tabs"><label style="margin:0"><input type="radio" name="role" value="buyer" checked><span>Покупець</span></label>'
            '<label style="margin:0"><input type="radio" name="role" value="seller"><span>Продавець</span></label></div>'
            if mode == "login"
            else ""
        )
        form = f'''<div class="auth"><div class="panel"><h3>{"Вхід" if mode == "login" else "Реєстрація"}</h3><form method="post" action="{action}">{role_picker}{"" if mode == "login" else '<label>ПІБ</label><input name="full_name" required>'}<label>Email</label><input name="email" type="email" required>{"" if mode == "login" else '<label>Телефон</label><input name="phone">'}<label>Пароль</label><input name="password" type="password" required>{"" if mode == "login" else ''}<button class="btn" type="submit">{ "Увійти" if mode == "login" else "Зареєструватися"}</button></form></div></div>'''
        return HTMLResponse(_page_shell("Вхід", form, user=user, cart_n=cart_n, flash=flash, section="/login"))

    return HTMLResponse("<h1>Page not found</h1>")


@app.get("/")
def home(r: Request):
    pop = db.q(PSEL + " ORDER BY (SELECT COALESCE(SUM(qty),0) FROM Order_Details WHERE product_id=p.id) DESC, p.id LIMIT 4")
    return render(r, "home", cats=db.q("SELECT * FROM Categories"), pop=pop)


@app.get("/catalog")
def catalog(r: Request, q: str = "", cat: int = 0, pmin: str = "", pmax: str = ""):
    sql, a = PSEL + " WHERE 1=1", []
    if q:
        sql += " AND p.name LIKE ?"
        a.append(f"%{q}%")
    if cat:
        sql += " AND p.category_id=?"
        a.append(cat)
    if pmin:
        sql += " AND p.price>=?"
        a.append(float(pmin))
    if pmax:
        sql += " AND p.price<=?"
        a.append(float(pmax))
    return render(r, "catalog", prods=db.q(sql + " ORDER BY p.id", a), cats=db.q("SELECT * FROM Categories"), cat=cat, q=q, pmin=pmin, pmax=pmax)


@app.get("/product/{pid}")
def product_page(r: Request, pid: int):
    product = db.q(PSEL + " WHERE p.id=?", (pid,), one=True)
    if not product:
        return HTMLResponse("Товар не знайдено", status_code=404)
    return render(r, "product", product=product)


@app.post("/cart/add/{pid}")
def cart_add(r: Request, pid: int):
    c = r.session.get("cart", {})
    c[str(pid)] = c.get(str(pid), 0) + 1
    r.session["cart"] = c
    return go(r.headers.get("referer", "/catalog"), r, "Товар додано до кошика")


@app.post("/cart/set/{pid}")
def cart_set(r: Request, pid: int, delta: int = Form(...)):
    c = r.session.get("cart", {})
    n = c.get(str(pid), 0) + delta
    if n > 0:
        c[str(pid)] = n
    else:
        c.pop(str(pid), None)
    r.session["cart"] = c
    return go("/cart")


@app.post("/cart/remove/{pid}")
def cart_rm(r: Request, pid: int):
    c = r.session.get("cart", {})
    c.pop(str(pid), None)
    r.session["cart"] = c
    return go("/cart")


@app.get("/cart")
def cart(r: Request):
    items, total = cart_items(r)
    return render(r, "cart", items=items, total=total)


@app.post("/checkout")
def checkout(r: Request, full_name: str = Form(...), phone: str = Form(...), email: str = Form(""), address: str = Form(...), post_office: str = Form(""), payment: str = Form("Післяплата")):
    u = me(r)
    if not u:
        return go("/login", r, "Увійдіть, щоб оформити замовлення")
    items, total = cart_items(r)
    if not items:
        return go("/cart", r, "Кошик порожній")
    for item in items:
        if item["n"] > item["p"]["stock"]:
            return go("/cart", r, f"Недостатньо на складі: {item['p']['name']}")
    db.ex("UPDATE Clients SET full_name=?,phone=?,address=?,post_office=? WHERE id=?", (full_name, phone, address, post_office, u["id"]))
    oid = db.ex("INSERT INTO Orders(client_id,order_date,status,payment,total) VALUES(?,?,?,?,?)", (u["id"], date.today().isoformat(), "Нове", payment, total))
    for item in items:
        db.ex("INSERT INTO Order_Details(order_id,product_id,qty,price_at_purchase) VALUES(?,?,?,?)", (oid, item["p"]["id"], item["n"], item["p"]["price"]))
        db.ex("UPDATE Products SET stock=stock-? WHERE id=?", (item["n"], item["p"]["id"]))
    r.session["cart"] = {}
    return go("/orders", r, f"Замовлення №{oid} оформлено!")


@app.get("/orders")
def orders(r: Request):
    u = me(r)
    if not u:
        return go("/login", r)
    rows = [
        {"o": o, "items": db.q("SELECT p.name, d.qty, d.price_at_purchase AS pr FROM Order_Details d JOIN Products p ON p.id = d.product_id WHERE d.order_id=?", (o["id"],))}
        for o in db.q("SELECT * FROM Orders WHERE client_id=? ORDER BY id DESC", (u["id"],))
    ]
    return render(r, "orders", orders=rows)


@app.get("/profile")
def profile(r: Request):
    return render(r, "profile") if me(r) else go("/login", r)


@app.post("/profile")
def profile_save(r: Request, full_name: str = Form(...), phone: str = Form(""), address: str = Form(""), post_office: str = Form("")):
    u = me(r)
    if u:
        db.ex("UPDATE Clients SET full_name=?,phone=?,address=?,post_office=? WHERE id=?", (full_name, phone, address, post_office, u["id"]))
    return go("/profile", r, "Профіль збережено")


@app.get("/about")
def about(r: Request):
    return render(r, "about")


@app.get("/login")
def login_page(r: Request):
    return render(r, "login", mode="login")


@app.post("/login")
def login(r: Request, email: str = Form(...), password: str = Form(...), role: str = Form("buyer")):
    u = db.q("SELECT * FROM Clients WHERE email=?", (email,), one=True)
    if not u or not u["password_hash"] or not db.chk(password, u["password_hash"]) or (role == "seller") != (u["role"] == "seller"):
        return go("/login", r, "Невірний e-mail, пароль або роль")
    r.session["uid"] = u["id"]
    return go("/admin" if u["role"] == "seller" else "/")


@app.get("/register")
def register_page(r: Request):
    return render(r, "login", mode="register")


@app.post("/register")
def register(r: Request, full_name: str = Form(...), email: str = Form(...), phone: str = Form(""), password: str = Form(...)):
    try:
        uid = db.ex("INSERT INTO Clients(full_name,email,phone,password_hash) VALUES(?,?,?,?)", (full_name, email, phone, db.hp(password)))
    except Exception:
        return go("/register", r, "Такий e-mail вже існує")
    r.session["uid"] = uid
    return go("/", r, "Ласкаво просимо!")


@app.get("/logout")
def logout(r: Request):
    r.session.clear()
    return go("/")


def _only_seller(r):
    u = me(r)
    return u if u and u.get("role") == "seller" else None


@app.get("/admin")
def a_home(r: Request):
    seller = _only_seller(r)
    if not seller:
        return go("/login")
    ym = date.today().isoformat()[:7]
    st = {
        "products": db.q("SELECT COUNT(*) AS value FROM Products", one=True)["value"],
        "orders": db.q("SELECT COUNT(*) AS value FROM Orders WHERE status='Нове'", one=True)["value"],
        "clients": db.q("SELECT COUNT(*) AS value FROM Clients WHERE role='buyer'", one=True)["value"],
        "income": db.q("SELECT COALESCE(SUM(total),0) AS value FROM Orders WHERE status!='Скасовано' AND substr(order_date,1,7)=?", (ym,), one=True)["value"],
    }
    last = db.q("SELECT o.*, c.full_name FROM Orders o JOIN Clients c ON c.id = o.client_id ORDER BY o.id DESC LIMIT 5")
    body = f'''<div class="stats"><div class="stat"><span>Товарів</span><b>{st['products']}</b></div><div class="stat"><span>Нових замовлень</span><b>{st['orders']}</b></div><div class="stat"><span>Клієнтів</span><b>{st['clients']}</b></div><div class="stat"><span>Дохід за місяць</span><b>{money(st['income'])}</b></div></div><div class="panel"><div class="sec"><h3>Останні замовлення</h3><a href="/admin/orders">Всі замовлення →</a></div><table><tr><th>№</th><th>Дата</th><th>Клієнт</th><th>Сума</th><th>Статус</th></tr>{''.join(f'<tr><td>{row["id"]}</td><td>{d(row["order_date"])}</td><td>{escape(row["full_name"])}</td><td>{money(row["total"])}</td><td><span class="st">{escape(row["status"])}</span></td></tr>' for row in last)}</table></div>'''
    return HTMLResponse(_page_shell("Панель продавця", body, user=seller, cart_n=sum(r.session.get("cart", {}).values()), flash=r.session.pop("flash", None), admin=True, section="home", new_n=st["orders"]))


@app.get("/admin/orders")
def a_orders(r: Request):
    seller = _only_seller(r)
    if not seller:
        return go("/login")
    rows = db.q("SELECT o.*, c.full_name, c.phone, c.address, c.post_office FROM Orders o JOIN Clients c ON c.id = o.client_id ORDER BY o.id DESC")
    order_rows = "".join(
        f'''<tr><td>{row['id']}</td><td>{d(row['order_date'])}</td><td>{escape(row['full_name'])}<br><small>{escape(row['phone'])}</small></td><td>{escape(row['address'])}<br><small>{escape(row['post_office'])}</small></td><td>{escape(row['payment'])}</td><td>{money(row['total'])}</td><td><form method="post" action="/admin/orders/{row['id']}/status"><select name="status" onchange="this.form.submit()">{''.join(f'<option value="{status}" {"selected" if row["status"] == status else ""}>{status}</option>' for status in STATUSES)}</select></form></td></tr>'''
        for row in rows
    )
    body = f'''<div class="panel"><table><tr><th>№</th><th>Дата</th><th>Клієнт</th><th>Доставка</th><th>Оплата</th><th>Сума</th><th>Статус</th></tr>{order_rows}</table></div>'''
    return HTMLResponse(_page_shell("Замовлення", body, user=seller, cart_n=sum(r.session.get("cart", {}).values()), flash=r.session.pop("flash", None), admin=True, section="orders", new_n=db.q("SELECT COUNT(*) AS value FROM Orders WHERE status='Нове'", one=True)["value"]))


@app.post("/admin/orders/{oid}/status")
def a_status(r: Request, oid: int, status: str = Form(...)):
    if _only_seller(r):
        db.ex("UPDATE Orders SET status=? WHERE id=?", (status, oid))
    return go("/admin/orders")


@app.get("/admin/clients")
def a_clients(r: Request):
    seller = _only_seller(r)
    if not seller:
        return go("/login")
    rows = db.q("SELECT c.*, COUNT(o.id) AS n, COALESCE(SUM(o.total),0) AS s FROM Clients c LEFT JOIN Orders o ON o.client_id = c.id WHERE c.role='buyer' GROUP BY c.id")
    table_rows = "".join(
        f'''<tr><td>{escape(row['full_name'])}</td><td>{escape(row['phone'])}</td><td>{escape(row['email'])}</td><td>{escape(row['address'])}</td><td>{escape(row['post_office'])}</td><td>{row['n']}</td><td>{money(row['s'])}</td></tr>'''
        for row in rows
    )
    body = f'''<div class="panel"><table><tr><th>ПІБ</th><th>Телефон</th><th>Email</th><th>Адреса</th><th>Відділення</th><th>Замовлень</th><th>Сума</th></tr>{table_rows}</table></div>'''
    return HTMLResponse(_page_shell("Клієнти", body, user=seller, cart_n=sum(r.session.get("cart", {}).values()), flash=r.session.pop("flash", None), admin=True, section="clients"))


@app.get("/admin/stats")
def a_stats(r: Request):
    seller = _only_seller(r)
    if not seller:
        return go("/login")
    months = db.q("SELECT substr(order_date,1,7) AS m, SUM(total) AS s, COUNT(*) AS n FROM Orders WHERE status!='Скасовано' GROUP BY m ORDER BY m DESC LIMIT 6")
    top = db.q("SELECT p.name, SUM(d.qty) AS q FROM Order_Details d JOIN Products p ON p.id = d.product_id GROUP BY p.id ORDER BY q DESC LIMIT 5")
    by_status = db.q("SELECT status, COUNT(*) AS n FROM Orders GROUP BY status")
    mx = max((item["s"] for item in months), default=1)
    mt = max((item["q"] for item in top), default=1)
    month_html = "".join(
        f'''<div class="brow"><span>{item['m']}</span><div class="bar" style="width:{max(6, int((item['s'] / mx) * 100))}%"></div><span>{money(item['s'])}</span></div>'''
        for item in months
    )
    top_html = "".join(
        f'''<div class="brow"><span>{escape(item['name'][:16])}</span><div class="bar" style="width:{max(6, int((item['q'] / mt) * 100))}%"></div><b>{item['q']}</b></div>'''
        for item in top
    )
    status_html = "".join(
        f'''<div class="brow"><span>{escape(item['status'])}</span><b>{item['n']}</b></div>'''
        for item in by_status
    )
    body = f'''<div class="two"><div class="panel"><h3>Дохід по місяцях</h3>{month_html}</div><div class="panel"><h3>Топ товарів (шт.)</h3>{top_html}<h3>Замовлення за статусом</h3>{status_html}</div></div>'''
    return HTMLResponse(_page_shell("Статистика", body, user=seller, cart_n=sum(r.session.get("cart", {}).values()), flash=r.session.pop("flash", None), admin=True, section="stats"))


PRODUCT_IMAGE_DIR = Path(__file__).parent / "static" / "product-images"
MAX_PRODUCT_IMAGE_SIZE = 5 * 1024 * 1024
PRODUCT_IMAGE_TYPES = {
    "image/jpeg": (".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/png": (".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (".webp", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
    "image/gif": (".gif", lambda data: data.startswith((b"GIF87a", b"GIF89a"))),
}


async def _store_product_image(image):
    if not image or not image.filename:
        return None
    image_type = PRODUCT_IMAGE_TYPES.get(image.content_type)
    if not image_type:
        raise ValueError("Оберіть зображення JPEG, PNG, WebP або GIF.")
    data = await image.read(MAX_PRODUCT_IMAGE_SIZE + 1)
    if len(data) > MAX_PRODUCT_IMAGE_SIZE:
        raise ValueError("Розмір зображення не повинен перевищувати 5 МБ.")
    extension, is_valid_image = image_type
    if not is_valid_image(data):
        raise ValueError("Файл не відповідає формату зображення.")
    PRODUCT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{extension}"
    (PRODUCT_IMAGE_DIR / filename).write_bytes(data)
    return f"/static/product-images/{filename}"


def _remove_product_image(image_url):
    prefix = "/static/product-images/"
    if image_url and image_url.startswith(prefix):
        path = PRODUCT_IMAGE_DIR / Path(image_url).name
        if path.parent == PRODUCT_IMAGE_DIR and path.exists():
            path.unlink()


def _admin_product_form(r, seller, product=None):
    categories = db.q("SELECT id, name FROM Categories ORDER BY name")
    suppliers = db.q("SELECT id, name FROM Suppliers ORDER BY name")
    selected_category = product["category_id"] if product else None
    supplier_ids = {supplier["id"] for supplier in suppliers}
    selected_supplier = product.get("supplier_id") if product and product.get("supplier_id") in supplier_ids else None
    category_options = "".join(
        f'<option value="{category["id"]}" {"selected" if category["id"] == selected_category else ""}>{escape(category["name"])}</option>'
        for category in categories
    )
    supplier_options = '<option value="">Не вказаний</option>' + "".join(
        f'<option value="{supplier["id"]}" {"selected" if supplier["id"] == selected_supplier else ""}>{escape(supplier["name"])}</option>'
        for supplier in suppliers
    )
    is_edit = product is not None
    action = f'/admin/products/{product["id"]}/edit' if is_edit else "/admin/products/new"
    image_preview = (
        f'<div class="current-image"><span>Поточне фото</span><img src="{escape(product["image_url"])}" alt="Фото товару"></div>'
        if is_edit and product.get("image_url")
        else ""
    )
    body = f'''<div class="panel product-form-panel"><p><a class="back-link" href="/admin/products">← До списку товарів</a></p><h2>{"Редагувати товар" if is_edit else "Новий товар"}</h2><form method="post" action="{action}" enctype="multipart/form-data"><div class="fg"><div class="full"><label>Назва товару</label><input name="name" value="{escape(product["name"]) if is_edit else ""}" required maxlength="200"></div><div><label>Категорія</label><select name="category_id" required>{category_options}</select></div><div><label>Постачальник</label><select name="supplier_id">{supplier_options}</select></div><div><label>Ціна, грн</label><input name="price" type="number" min="0" step="0.01" value="{product["price"] if is_edit else ""}" required></div><div><label>Кількість на складі</label><input name="stock" type="number" min="0" step="1" value="{product["stock"] if is_edit else 0}" required></div><div class="full"><label>Опис</label><textarea name="description" rows="5">{escape(product.get("description") or "") if is_edit else ""}</textarea></div><div class="full"><label>{"Замінити фото" if is_edit and product.get("image_url") else "Фото товару"}</label><input name="image" type="file" accept="image/jpeg,image/png,image/webp,image/gif"><small>JPEG, PNG, WebP або GIF, до 5 МБ. Якщо залишити поле порожнім, поточне фото збережеться.</small>{image_preview}</div></div><div class="form-actions"><button class="btn" type="submit">{"Зберегти зміни" if is_edit else "Додати товар"}</button><a class="btn out" href="/admin/products">Скасувати</a></div></form></div>'''
    return HTMLResponse(_page_shell("Редагування товару" if is_edit else "Новий товар", body, user=seller, cart_n=sum(r.session.get("cart", {}).values()), flash=r.session.pop("flash", None), admin=True, section="products"))


async def _save_admin_product(r, seller, name, category_id, supplier_id, price, stock, description, image, product_id=None):
    if not seller:
        return go("/login", r, "Увійдіть як продавець, щоб керувати товарами")
    product = db.q("SELECT * FROM Products WHERE id=?", (product_id,), one=True) if product_id else None
    if product_id and not product:
        return go("/admin/products", r, "Товар не знайдено")
    if not name.strip() or len(name.strip()) > 200:
        return go(f"/admin/products/{product_id}/edit" if product_id else "/admin/products/new", r, "Назва товару має містити від 1 до 200 символів")
    if price < 0 or stock < 0:
        return go(f"/admin/products/{product_id}/edit" if product_id else "/admin/products/new", r, "Ціна та кількість не можуть бути від'ємними")
    if not db.q("SELECT id FROM Categories WHERE id=?", (category_id,), one=True):
        return go(f"/admin/products/{product_id}/edit" if product_id else "/admin/products/new", r, "Оберіть наявну категорію")
    supplier = None
    if supplier_id:
        try:
            supplier_id = int(supplier_id)
        except ValueError:
            return go(f"/admin/products/{product_id}/edit" if product_id else "/admin/products/new", r, "Оберіть наявного постачальника")
        supplier = db.q("SELECT id FROM Suppliers WHERE id=?", (supplier_id,), one=True)
        if not supplier:
            return go(f"/admin/products/{product_id}/edit" if product_id else "/admin/products/new", r, "Оберіть наявного постачальника")
    else:
        supplier_id = None
    try:
        new_image_url = await _store_product_image(image)
    except ValueError as error:
        return go(f"/admin/products/{product_id}/edit" if product_id else "/admin/products/new", r, str(error))
    image_url = new_image_url or (product.get("image_url") if product else None)
    values = (name.strip(), category_id, supplier_id, price, stock, description.strip(), image_url)
    if product:
        db.ex("UPDATE Products SET name=?,category_id=?,supplier_id=?,price=?,stock=?,description=?,image_url=? WHERE id=?", (*values, product_id))
        if new_image_url:
            _remove_product_image(product.get("image_url"))
        message = "Товар оновлено"
    else:
        db.ex("INSERT INTO Products(name,category_id,supplier_id,price,stock,description,image_url) VALUES(?,?,?,?,?,?,?)", values)
        message = "Товар додано"
    return go("/admin/products", r, message)


@app.get("/admin/products")
def a_products(r: Request):
    seller = _only_seller(r)
    if not seller:
        return go("/login")
    rows = db.q("SELECT p.id, p.name, p.image_url, c.name AS category, p.price, p.stock FROM Products p JOIN Categories c ON c.id = p.category_id ORDER BY p.id DESC")
    table_rows = "".join(
        f'''<tr><td>{row["id"]}</td><td><div class="admin-product">{f'<img class="admin-thumb" src="{escape(row["image_url"])}" alt="">' if row.get("image_url") else '<span class="admin-thumb-placeholder">🐾</span>'}<a href="/product/{row["id"]}">{escape(row["name"])}</a></div></td><td>{escape(row["category"])}</td><td>{money(row["price"])}</td><td>{row["stock"]}</td><td><div class="admin-actions"><a class="btn sq out" href="/admin/products/{row["id"]}/edit">Редагувати</a><form method="post" action="/admin/products/{row["id"]}/delete" onsubmit="return confirm('Видалити цей товар?')"><button class="btn sq red" type="submit">Видалити</button></form></div></td></tr>'''
        for row in rows
    )
    body = f'''<div class="sec admin-page-title"><h2>Товари</h2><a class="btn" href="/admin/products/new">＋ Додати товар</a></div><div class="panel admin-table-wrap"><table><tr><th>ID</th><th>Товар</th><th>Категорія</th><th>Ціна</th><th>На складі</th><th>Дії</th></tr>{table_rows or '<tr><td colspan="6">Товарів ще немає</td></tr>'}</table></div>'''
    return HTMLResponse(_page_shell("Товари", body, user=seller, cart_n=sum(r.session.get("cart", {}).values()), flash=r.session.pop("flash", None), admin=True, section="products"))


@app.get("/admin/products/new")
def a_product_new(r: Request):
    seller = _only_seller(r)
    if not seller:
        return go("/login", r)
    return _admin_product_form(r, seller)


@app.get("/admin/products/{pid}/edit")
def a_product_edit(r: Request, pid: int):
    seller = _only_seller(r)
    if not seller:
        return go("/login", r)
    product = db.q("SELECT * FROM Products WHERE id=?", (pid,), one=True)
    if not product:
        return go("/admin/products", r, "Товар не знайдено")
    return _admin_product_form(r, seller, product)


@app.post("/admin/products/new")
async def a_product_create(
    r: Request,
    name: str = Form(...),
    category_id: int = Form(...),
    supplier_id: str = Form(""),
    price: float = Form(...),
    stock: int = Form(0),
    description: str = Form(""),
    image: UploadFile = File(None),
):
    return await _save_admin_product(r, _only_seller(r), name, category_id, supplier_id, price, stock, description, image)


@app.post("/admin/products/{pid}/edit")
async def a_product_update(
    r: Request,
    pid: int,
    name: str = Form(...),
    category_id: int = Form(...),
    supplier_id: str = Form(""),
    price: float = Form(...),
    stock: int = Form(0),
    description: str = Form(""),
    image: UploadFile = File(None),
):
    return await _save_admin_product(r, _only_seller(r), name, category_id, supplier_id, price, stock, description, image, pid)


@app.post("/admin/products/{pid}/delete")
def a_product_delete(r: Request, pid: int):
    seller = _only_seller(r)
    if not seller:
        return go("/login", r)
    product = db.q("SELECT id,image_url FROM Products WHERE id=?", (pid,), one=True)
    if not product:
        return go("/admin/products", r, "Товар не знайдено")
    if db.q("SELECT 1 FROM Order_Details WHERE product_id=? LIMIT 1", (pid,), one=True):
        return go("/admin/products", r, "Товар є у замовленнях і його не можна видалити")
    db.ex("DELETE FROM Products WHERE id=?", (pid,))
    _remove_product_image(product.get("image_url"))
    return go("/admin/products", r, "Товар видалено")


@app.get("/admin/categories")
def a_categories(r: Request):
    seller = _only_seller(r)
    if not seller:
        return go("/login")
    rows = db.q("SELECT * FROM Categories ORDER BY id")
    body = '<div class="panel"><table><tr><th>ID</th><th>Назва</th><th>Опис</th></tr>' + ''.join(f'<tr><td>{row["id"]}</td><td>{escape(row["name"])}</td><td>{escape(row["description"])}</td></tr>' for row in rows) + '</table></div>'
    return HTMLResponse(_page_shell("Категорії", body, user=seller, cart_n=sum(r.session.get("cart", {}).values()), flash=r.session.pop("flash", None), admin=True, section="categories"))


@app.get("/admin/suppliers")
def a_suppliers(r: Request):
    seller = _only_seller(r)
    if not seller:
        return go("/login")
    rows = db.q("SELECT * FROM Suppliers ORDER BY id")
    body = '<div class="panel"><table><tr><th>ID</th><th>Назва</th><th>Телефон</th><th>Email</th><th>Адреса</th></tr>' + ''.join(f'<tr><td>{row["id"]}</td><td>{escape(row["name"])}</td><td>{escape(row["phone"])}</td><td>{escape(row["email"])}</td><td>{escape(row["address"])}</td></tr>' for row in rows) + '</table></div>'
    return HTMLResponse(_page_shell("Постачальники", body, user=seller, cart_n=sum(r.session.get("cart", {}).values()), flash=r.session.pop("flash", None), admin=True, section="suppliers"))


@app.get("/admin/{ent}")
def a_list(r: Request, ent: str):
    seller = _only_seller(r)
    if not seller:
        return go("/login")
    if ent == "products":
        return a_products(r)
    if ent == "categories":
        return a_categories(r)
    if ent == "suppliers":
        return a_suppliers(r)
    if ent == "orders":
        return a_orders(r)
    if ent == "clients":
        return a_clients(r)
    if ent == "stats":
        return a_stats(r)
    return go("/admin")
