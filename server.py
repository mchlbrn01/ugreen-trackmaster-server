from fastapi import FastAPI, HTTPException
import sqlite3

app = FastAPI(title="UGREEN PH TrackMaster Cloud API")
DB_PATH = "cloud_ugreen.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.on_event("startup")
def startup_event():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name TEXT NOT NULL,
        store_name TEXT NOT NULL,
        mall_name TEXT NOT NULL,
        role TEXT DEFAULT 'Promoter'
    );
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        barcode TEXT UNIQUE,
        sku TEXT UNIQUE,
        name TEXT NOT NULL,
        price REAL NOT NULL DEFAULT 0,
        stock INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_date TEXT NOT NULL,
        sku TEXT,
        product_name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL,
        total REAL NOT NULL,
        branch TEXT,
        store TEXT,
        promoter TEXT
    );
    CREATE TABLE IF NOT EXISTS targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store TEXT UNIQUE,
        target_amount REAL NOT NULL DEFAULT 50000.0
    );
    """)
    
    admin_exists = conn.execute("SELECT COUNT(*) FROM users WHERE username='admin'").fetchone()[0]
    if admin_exists == 0:
        conn.execute(
            "INSERT INTO users (username, password, full_name, store_name, mall_name, role) VALUES (?, ?, ?, ?, ?, ?)",
            ("admin", "ugreen2026", "Administrator", "Ugreen Philippines", "PH HQ", "Administrator")
        )
    else:
        conn.execute(
            "UPDATE users SET store_name=?, mall_name=?, role=? WHERE username='admin'",
            ("Ugreen Philippines", "PH HQ", "Administrator")
        )
    conn.commit()
    conn.close()

@app.post("/api/register")
def register_user(data: dict):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, password, full_name, store_name, mall_name, role) VALUES (?, ?, ?, ?, ?, ?)",
            (data["username"], data["password"], data["full_name"], data["store_name"], data["mall_name"], "Promoter")
        )
        conn.commit()
        return {"status": "success", "message": "User registered successfully"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already exists")
    finally:
        conn.close()

@app.post("/api/login")
def login_user(data: dict):
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE username=? AND password=?", 
        (data["username"], data["password"])
    ).fetchone()
    conn.close()
    if user:
        return dict(user)
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/dashboard-stats")
def get_dashboard_stats(role: str = "Promoter", store: str = ""):
    conn = get_db()
    prod_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_stock = conn.execute("SELECT COALESCE(SUM(stock),0) FROM products").fetchone()[0]
    
    if role == "Administrator":
        # Admin gets total company sales and per-store breakdown
        running_sales = conn.execute("SELECT COALESCE(SUM(total),0) FROM sales").fetchone()[0]
        store_sales_rows = conn.execute(
            "SELECT store, COALESCE(SUM(total),0) as total_sales FROM sales GROUP BY store"
        ).fetchall()
        store_breakdown = {row["store"]: row["total_sales"] for row in store_sales_rows}
        
        conn.close()
        return {
            "role": "Administrator",
            "products_count": prod_count,
            "total_stock": total_stock,
            "running_sales": running_sales,
            "store_breakdown": store_breakdown,
            "target_amount": 0.0,
            "percentage": 0.0
        }
    else:
        # Promoter gets only their specific store metrics
        running_sales = conn.execute("SELECT COALESCE(SUM(total),0) FROM sales WHERE store=?", (store,)).fetchone()[0]
        target_row = conn.execute("SELECT target_amount FROM targets WHERE store=?", (store,)).fetchone()
        target_amount = target_row["target_amount"] if target_row else 50000.0
        percentage = (running_sales / target_amount * 100) if target_amount > 0 else 0

        conn.close()
        return {
            "role": "Promoter",
            "products_count": prod_count,
            "total_stock": total_stock,
            "running_sales": running_sales,
            "target_amount": target_amount,
            "percentage": round(percentage, 2)
        }

@app.post("/api/set-target")
def set_store_target(data: dict):
    store = data.get("store")
    target_amount = data.get("target_amount")
    role = data.get("role", "")
    
    if role != "Administrator":
        raise HTTPException(status_code=403, detail="Unauthorized: Only administrators can set targets.")
        
    if not store or target_amount is None:
        raise HTTPException(status_code=400, detail="Store and target_amount are required")
        
    conn = get_db()
    with conn:
        conn.execute(
            """INSERT INTO targets (store, target_amount) VALUES (?, ?)
               ON CONFLICT(store) DO UPDATE SET target_amount = ?""",
            (store, float(target_amount), float(target_amount))
        )
    conn.close()
    return {"status": "success", "message": f"Target for {store} updated to ₱{target_amount:,.2f}"}

@app.post("/api/sales")
def post_sale(data: dict):
    conn = get_db()
    with conn:
        conn.execute(
            """INSERT INTO sales (sale_date, sku, product_name, quantity, unit_price, total, branch, store, promoter)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data["sale_date"], data["sku"], data["product_name"], data["quantity"], data["unit_price"], data["total"], data["branch"], data["store"], data["promoter"])
        )
    conn.close()
    return {"status": "success", "message": "Sale synced to central server"}
