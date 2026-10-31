from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
import sqlite3
import pandas as pd
import os
import csv
import io

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
    CREATE TABLE IF NOT EXISTS store_directory (
        store_code TEXT PRIMARY KEY,
        region TEXT,
        distributor TEXT,
        mall TEXT,
        store TEXT,
        dealer TEXT,
        store_type TEXT
    );
    """)
    
    # Safely preload Store List if available
    try:
        store_count = conn.execute("SELECT COUNT(*) FROM store_directory").fetchone()[0]
        excel_path = "Store List.xlsx"
        if store_count == 0 and os.path.exists(excel_path):
            df = pd.read_excel(excel_path, sheet_name=0)
            with conn:
                for idx, row in df.iterrows():
                    s_code = f"UGN-{idx+1:03d}"
                    conn.execute(
                        """INSERT OR IGNORE INTO store_directory (store_code, region, distributor, mall, store, dealer, store_type) 
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (s_code, str(row.get('Region', '')), str(row.get('Distributor', '')), 
                         str(row.get('Mall', '')), str(row.get('Store', '')), 
                         str(row.get('Dealer', '')), str(row.get('Store Type', '')))
                    )
            print("Successfully preloaded stores.")
    except Exception as e:
        print("Notice: Store List.xlsx not loaded on startup:", e)

    # Ensure admin account exists
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

# ---------------------------------------------------------
# BROWSER WEB INTERFACE & API ENDPOINTS
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def serve_browser_app():
    return "<h1>UGREEN PH TrackMaster Server Running Successfully</h1>"

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

@app.post("/api/change-password")
def change_password(data: dict):
    username = data.get("username")
    old_password = data.get("old_password")
    new_password = data.get("new_password")
    
    conn = get_db()
    if old_password:
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, old_password)).fetchone()
        if not user:
            conn.close()
            raise HTTPException(status_code=400, detail="Incorrect current password")
            
    conn.execute("UPDATE users SET password=? WHERE username=?", (new_password, username))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Password updated successfully"}

@app.get("/api/admin-overview")
def get_admin_overview():
    conn = get_db()
    total_sales = conn.execute("SELECT COALESCE(SUM(total),0) FROM sales").fetchone()[0]
    total_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_stock = conn.execute("SELECT COALESCE(SUM(stock),0) FROM products").fetchone()[0]
    
    store_sales = conn.execute(
        "SELECT store, COALESCE(SUM(total),0) as total_sales, COUNT(*) as tx_count FROM sales GROUP BY store"
    ).fetchall()
    
    all_sales = conn.execute(
        "SELECT sale_date, store, product_name, quantity, total, promoter FROM sales ORDER BY id DESC LIMIT 100"
    ).fetchall()
    
    conn.close()
    return {
        "total_sales": total_sales,
        "total_products": total_products,
        "total_stock": total_stock,
        "store_sales": [dict(row) for row in store_sales],
        "all_sales": [dict(row) for row in all_sales]
    }

@app.get("/api/dashboard-stats")
def get_dashboard_stats(role: str = "Promoter", store: str = ""):
    conn = get_db()
    prod_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    total_stock = conn.execute("SELECT COALESCE(SUM(stock),0) FROM products").fetchone()[0]
    
    if role == "Administrator":
        running_sales = conn.execute("SELECT COALESCE(SUM(total),0) FROM sales").fetchone()[0]
        conn.close()
        return {
            "role": "Administrator",
            "products_count": prod_count,
            "total_stock": total_stock,
            "running_sales": running_sales
        }
    else:
        running_sales = conn.execute("SELECT COALESCE(SUM(total),0) FROM sales WHERE store=?", (store,)).fetchone()[0]
        target_row = conn.execute("SELECT target_amount FROM targets WHERE store=? OR store LIKE ?", (store, f"%{store}%")).fetchone()
        
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
        raise HTTPException(status_code=403, detail="Unauthorized")
        
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
    return {"status": "success", "message": f"Target for {store} updated"}

@app.get("/api/stores")
def get_stores():
    conn = get_db()
    rows = conn.execute("SELECT * FROM store_directory ORDER BY store_code").fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/api/add-store")
def add_store(data: dict):
    role = data.get("role", "")
    if role != "Administrator":
        raise HTTPException(status_code=403, detail="Unauthorized: Admin only")
        
    conn = get_db()
    try:
        count = conn.execute("SELECT COUNT(*) FROM store_directory").fetchone()[0]
        store_code = data.get("store_code") or f"UGN-{count+1:03d}"
        
        with conn:
            conn.execute(
                """INSERT INTO store_directory (store_code, region, distributor, mall, store, dealer, store_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (store_code, data.get("region"), data.get("distributor"), data.get("mall"), 
                 data.get("store"), data.get("dealer"), data.get("store_type"))
            )
        return {"status": "success", "message": f"Store {store_code} added successfully."}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Store code or store already exists.")
    finally:
        conn.close()

@app.get("/api/export-sales-csv")
def export_sales_csv():
    conn = get_db()
    sales = conn.execute("SELECT sale_date, store, product_name, quantity, unit_price, total, promoter FROM sales ORDER BY id DESC").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sale Date", "Store", "Product Name", "Quantity", "Unit Price", "Total", "Promoter"])
    for s in sales:
        writer.writerow([s["sale_date"], s["store"], s["product_name"], s["quantity"], s["unit_price"], s["total"], s["promoter"]])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ugreen_sales_report.csv"}
    )

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
    return {"status": "success", "message": "Sale synced"}
