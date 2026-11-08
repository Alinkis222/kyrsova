"""БД Lapka.
Підключення до файлу Access .accdb, якщо він доступний. Інакше — SQLite fallback.
"""
import hashlib
import os
import re
import sqlite3
from datetime import date, timedelta

try:
    import pyodbc
except Exception:  # pragma: no cover - optional dependency on Windows
    pyodbc = None

ACCESS_DB = os.path.join(os.path.dirname(__file__), "KyrsovaFA1.accdb")
SQLITE_DB = os.path.join(os.path.dirname(__file__), "petshop.db")
USE_ACCESS = bool(pyodbc and os.path.exists(ACCESS_DB))


def _as_row_dict(row):
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    if hasattr(row, "cursor_description"):
        columns = [c[0] for c in row.cursor_description]
        return {key: value for key, value in zip(columns, row)}
    return row


def conn():
    global USE_ACCESS
    if USE_ACCESS:
        try:
            c = pyodbc.connect(
                r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + ACCESS_DB + ";UID=;PWD=;",
                autocommit=True,
            )
            return c
        except Exception:
            USE_ACCESS = False
    c = sqlite3.connect(SQLITE_DB)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _sql_for_db(sql):
    if not USE_ACCESS:
        return sql
    s = sql.strip()
    s = re.sub(r'(?is)\bCOALESCE\s*\(', 'NZ(', s)
    s = re.sub(r'(?is)\bsubstr\s*\(\s*([^,]+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)', r'Mid(\1,\2,\3)', s)
    m = re.search(r'(?is)\bLIMIT\s+(\d+)\b', s)
    if m:
        limit = m.group(1)
        s = re.sub(r'(?is)\s*LIMIT\s+\d+\s*$', '', s)
        s = re.sub(r'(?is)^SELECT\s+', f'SELECT TOP {limit} ', s, count=1)
    return s


def q(sql, a=(), one=False):
    c = conn()
    try:
        sql_exec = _sql_for_db(sql)
        rows = c.execute(sql_exec, a).fetchall()
        data = [_as_row_dict(r) for r in rows]
        return (data[0] if data else None) if one else data
    finally:
        c.close()


def ex(sql, a=()):
    c = conn()
    try:
        sql_exec = _sql_for_db(sql)
        if USE_ACCESS:
            cur = c.execute(sql_exec, a)
            c.commit()
            ident = c.execute("SELECT @@IDENTITY").fetchone()
            return ident[0] if ident and ident[0] is not None else 0
        cur = c.execute(sql_exec, a)
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _h(p, s):
    return hashlib.pbkdf2_hmac("sha256", p.encode(), s.encode(), 50000).hex()


def hp(p):
    s = os.urandom(8).hex()
    return s + "$" + _h(p, s)


def chk(p, h):
    s, x = h.split("$")
    return _h(p, s) == x


SCHEMA = """
CREATE TABLE IF NOT EXISTS Categories(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, description TEXT);
CREATE TABLE IF NOT EXISTS Suppliers(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, email TEXT, address TEXT);
CREATE TABLE IF NOT EXISTS Products(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES Categories(id), supplier_id INTEGER REFERENCES Suppliers(id),
  price REAL NOT NULL, stock INTEGER NOT NULL DEFAULT 0, description TEXT, image_url TEXT);
CREATE TABLE IF NOT EXISTS Clients(id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT NOT NULL, phone TEXT,
  email TEXT UNIQUE, address TEXT, post_office TEXT, password_hash TEXT, role TEXT DEFAULT 'buyer');
CREATE TABLE IF NOT EXISTS Orders(id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER NOT NULL REFERENCES Clients(id),
  order_date TEXT, status TEXT DEFAULT 'Нове', payment TEXT, total REAL);
CREATE TABLE IF NOT EXISTS Order_Details(id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES Orders(id),
  product_id INTEGER NOT NULL REFERENCES Products(id), qty INTEGER NOT NULL, price_at_purchase REAL NOT NULL);
"""


def _ensure_sqlite_schema():
    c = sqlite3.connect(SQLITE_DB)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    _migrate_sqlite_schema(c)
    c.commit()
    c.close()


def _migrate_sqlite_schema(c):
    product_columns = {row[1] for row in c.execute("PRAGMA table_info(Products)")}
    if "image_url" not in product_columns:
        c.execute("ALTER TABLE Products ADD COLUMN image_url TEXT")


def _ensure_access_schema():
    try:
        c = conn()
        c.execute("SELECT COUNT(*) FROM Categories")
        c.close()
        return
    except Exception:
        pass
    c = conn()
    for sql in [
        "CREATE TABLE Categories(id COUNTER CONSTRAINT PRIMARY KEY, name TEXT NOT NULL, description TEXT)",
        "CREATE TABLE Suppliers(id COUNTER CONSTRAINT PRIMARY KEY, name TEXT NOT NULL, phone TEXT, email TEXT, address TEXT)",
        "CREATE TABLE Products(id COUNTER CONSTRAINT PRIMARY KEY, name TEXT NOT NULL, category_id INTEGER NOT NULL, supplier_id INTEGER, price DOUBLE NOT NULL, stock INTEGER NOT NULL DEFAULT 0, description TEXT)",
        "CREATE TABLE Clients(id COUNTER CONSTRAINT PRIMARY KEY, full_name TEXT NOT NULL, phone TEXT, email TEXT UNIQUE, address TEXT, post_office TEXT, password_hash TEXT, role TEXT DEFAULT 'buyer')",
        "CREATE TABLE Orders(id COUNTER CONSTRAINT PRIMARY KEY, client_id INTEGER NOT NULL, order_date TEXT, status TEXT DEFAULT 'Нове', payment TEXT, total DOUBLE)",
        "CREATE TABLE Order_Details(id COUNTER CONSTRAINT PRIMARY KEY, order_id INTEGER NOT NULL, product_id INTEGER NOT NULL, qty INTEGER NOT NULL, price_at_purchase DOUBLE NOT NULL)",
    ]:
        try:
            c.execute(sql)
        except Exception:
            pass
    c.commit()
    c.close()


def _sync_access_to_sqlite():
    global USE_ACCESS
    access = pyodbc.connect(
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + ACCESS_DB + ";UID=;PWD=;",
        autocommit=True,
    )
    sqlite_c = sqlite3.connect(SQLITE_DB)
    sqlite_c.row_factory = sqlite3.Row
    sqlite_c.executescript(SCHEMA)
    _migrate_sqlite_schema(sqlite_c)
    if sqlite_c.execute("SELECT 1 FROM Products LIMIT 1").fetchone():
        sqlite_c.close()
        access.close()
        USE_ACCESS = False
        return
    for table in ["Order_Details", "Orders", "Products", "Suppliers", "Categories", "Clients"]:
        sqlite_c.execute(f"DELETE FROM {table}")

    def ins_clients(rows):
        for row in rows:
            row_id = int(row[0])
            full_name = str(row[1] or "")
            phone = str(row[2] or "")
            email = str(row[3] or "")
            address = str(row[4] or "")
            post = str(row[5] if len(row) > 5 else "")
            role = "seller" if "seller" in email.lower() else "buyer"
            password_hash = hp("seller123" if role == "seller" else "12345678")
            sqlite_c.execute(
                "INSERT INTO Clients(id, full_name, phone, email, address, post_office, password_hash, role) VALUES(?,?,?,?,?,?,?,?)",
                (row_id, full_name, phone, email, address, post, password_hash, role),
            )

    for table, key in [("Categories", "INSERT INTO Categories(id, name, description) VALUES(?,?,?)"), ("Suppliers", "INSERT INTO Suppliers(id, name, phone, email, address) VALUES(?,?,?,?,?)"), ("Products", "INSERT INTO Products(id, name, category_id, supplier_id, price, stock, description) VALUES(?,?,?,?,?,?,?)"), ("Orders", "INSERT INTO Orders(id, client_id, order_date, status, payment, total) VALUES(?,?,?,?,?,?)"), ("Order_Details", "INSERT INTO Order_Details(id, order_id, product_id, qty, price_at_purchase) VALUES(?,?,?,?,?)")]:
        rows = access.cursor().execute(f"SELECT * FROM {table}").fetchall()
        for row in rows:
            if table == "Categories":
                sqlite_c.execute(key, (int(row[0]), str(row[1] or ""), str(row[2] or "")))
            elif table == "Suppliers":
                sqlite_c.execute(key, (int(row[0]), str(row[1] or ""), str(row[2] or ""), str(row[3] or ""), str(row[4] or "")))
            elif table == "Products":
                sqlite_c.execute(key, (int(row[0]), str(row[1] or ""), int(row[2] or 0), int(row[3] or 0), float(row[4] or 0), int(row[5] or 0), str(row[6] or "")))
            elif table == "Orders":
                sqlite_c.execute(key, (int(row[0]), int(row[1] or 0), str(row[2])[:10] if row[2] else "", str(row[3] or "Нове"), str(row[4] or "Післяплата"), float(row[5] or 0)))
            elif table == "Order_Details":
                sqlite_c.execute(key, (int(row[0]), int(row[1] or 0), int(row[2] or 0), int(row[3] or 0), float(row[4] or 0)))

    access_clients = access.cursor().execute("SELECT * FROM Clients").fetchall()
    ins_clients(access_clients)

    sqlite_c.execute(
        "INSERT INTO Clients(full_name, phone, email, address, post_office, password_hash, role) VALUES(?,?,?,?,?,?,?)",
        ("Іваненко О.В.", "+380501112233", "seller@petshop.ua", "Київ", "", hp("seller123"), "seller")
    )
    sqlite_c.execute(
        "INSERT INTO Clients(full_name, phone, email, address, post_office, password_hash) VALUES(?,?,?,?,?,?)",
        ("Федорак Аліна", "+380981234567", "alina@mail.com", "м. Запоріжжя, вул. Перемоги, 20", "Відділення №5", hp("12345678"))
    )
    sqlite_c.commit()
    sqlite_c.close()
    access.close()
    USE_ACCESS = False


def init():
    if USE_ACCESS:
        _sync_access_to_sqlite()
        return

    if not USE_ACCESS:
        _ensure_sqlite_schema()

    if q("SELECT 1 FROM Categories LIMIT 1"):
        return

    for n in ["Корма", "Іграшки", "Лежанки", "Нашийники та повідки", "Клітки та переноски", "Догляд"]:
        ex("INSERT INTO Categories(name) VALUES(?)", (n,))
    for s in [("ТОВ ЗооОпт", "+380441112233", "opt@zoo.ua", "Київ"), ("Pet Supply", "+380322223344", "info@petsupply.ua", "Львів"),
              ("Trixie UA", "+380573334455", "sales@trixie.ua", "Харків")]:
        ex("INSERT INTO Suppliers(name,phone,email,address) VALUES(?,?,?,?)", s)
    P = [("Royal Canin для котів (1 кг)", 1, 1, 500, 40), ("Корм для собак Purina (2 кг)", 1, 1, 420, 25),
         ("Іграшка-качка", 2, 2, 90, 60), ("Іграшка для собак (канат)", 2, 2, 120, 50), ("М'яч гумовий", 2, 3, 70, 80),
         ("Лежанка Soft (50x40 см)", 3, 2, 750, 15), ("Лежанка Cozy (60x50 см)", 3, 2, 890, 10), ("Лежанка House (будиночок)", 3, 3, 1200, 6),
         ("Нашийник шкіряний", 4, 3, 250, 30), ("Повідець 2 м", 4, 3, 180, 35), ("Переноска для котів", 5, 3, 950, 12),
         ("Клітка для гризунів", 5, 2, 1100, 5), ("Щітка-пуходерка", 6, 2, 160, 40), ("Шампунь для собак", 6, 1, 210, 22)]
    for n, cat, sup, pr, st in P:
        ex("INSERT INTO Products(name,category_id,supplier_id,price,stock) VALUES(?,?,?,?,?)", (n, cat, sup, pr, st))
    ex("INSERT INTO Clients(full_name,phone,email,address,post_office,password_hash,role) VALUES(?,?,?,?,?,?,?)",
       ("Іваненко О.В.", "+380501112233", "seller@petshop.ua", "Київ", "", hp("seller123"), "seller"))
    ex("INSERT INTO Clients(full_name,phone,email,address,post_office,password_hash) VALUES(?,?,?,?,?,?)",
       ("Федорак Аліна", "+380981234567", "alina@mail.com", "м. Запоріжжя, вул. Перемоги, 20", "Відділення №5", hp("12345678")))
    for i, (st, items) in enumerate([("Доставлено", [(1, 1), (4, 2)]), ("В обробці", [(6, 1)]), ("Нове", [(11, 1), (9, 1)])]):
        d = (date.today() - timedelta(days=i * 9)).isoformat()
        oid = ex("INSERT INTO Orders(client_id,order_date,status,payment,total) VALUES(2,?,?,?,0)", (d, st, "Післяплата"))
        t = 0
        for pid, n in items:
            pr = q("SELECT price FROM Products WHERE id=?", (pid,), one=True)[0]
            t += pr * n
            ex("INSERT INTO Order_Details(order_id,product_id,qty,price_at_purchase) VALUES(?,?,?,?)", (oid, pid, n, pr))
        ex("UPDATE Orders SET total=? WHERE id=?", (t, oid))


if not USE_ACCESS:
    try:
        if not q("SELECT 1 FROM Categories LIMIT 1"):
            init()
    except Exception:
        init()
