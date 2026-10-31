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
        model_number TEXT,
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
    
    # 1. Preload Store List if empty
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

    # 2. Preload SKU / Product List with Model Number, Description, and 0 default stock
    try:
        prod_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        sku_file_xlsx = "SKU List.xlsx"
        sku_file_csv = "SKU List.csv"
        target_sku_file = sku_file_xlsx if os.path.exists(sku_file_xlsx) else (sku_file_csv if os.path.exists(sku_file_csv) else None)
        
        if prod_count == 0 and target_sku_file:
            df_prods = pd.read_excel(target_sku_file) if target_sku_file.endswith('.xlsx') else pd.read_csv(target_sku_file)
            with conn:
                for _, row in df_prods.iterrows():
                    conn.execute(
                        """INSERT OR IGNORE INTO products (sku, barcode, model_number, name, price, stock) 
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            str(row.get('SKU', '')), 
                            str(row.get('Barcode', row.get('SKU', ''))),
                            str(row.get('Model', row.get('Model Number', ''))), 
                            str(row.get('Description', row.get('Name', ''))), 
                            float(row.get('Price', 0.0)), 
                            int(row.get('Stock', 0))
                        )
                    )
            print("Successfully preloaded product SKU list with Model & Description.")
    except Exception as e:
        print("Notice: SKU list file not loaded on startup:", e)

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
# BROWSER WEB INTERFACE (HTML / JS)
# ---------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def serve_browser_app():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>UGREEN PH TrackMaster Cloud</title>
        <style>
            body { font-family: Arial, sans-serif; background: #121212; color: #e0e0e0; margin: 0; padding: 20px; }
            .container { max-width: 900px; margin: auto; background: #1e1e1e; padding: 20px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
            h1, h2 { color: #00A859; text-align: center; }
            input, select, button { width: 100%; padding: 10px; margin: 8px 0; border: 1px solid #333; border-radius: 4px; background: #2c2c2c; color: #fff; box-sizing: border-box; }
            button { background: #00A859; color: white; font-weight: bold; cursor: pointer; border: none; }
            button:hover { background: #008f4c; }
            .hidden { display: none; }
            .card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px; }
            .card { background: #252525; padding: 15px; border-radius: 6px; text-align: center; border-left: 4px solid #00A859; }
            .logout-btn { background: #d9534f; width: auto; padding: 5px 15px; float: right; margin-left: 5px; }
            .alt-btn { background: #333; margin-top: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>UGREEN PH TrackMaster</h1>
            
            <!-- LOGIN SECTION -->
            <div id="login-section">
                <h2>Cloud Login</h2>
                <input type="text" id="login-user" placeholder="Username / ID">
                <input type="password" id="login-pass" placeholder="Password">
                <button onclick="login()">Login</button>
                <button class="alt-btn" onclick="toggleForgot(true)">Forgot Password?</button>
                <p id="login-err" style="color: #ff6b6b; text-align: center;"></p>
            </div>

            <!-- FORGOT PASSWORD SECTION -->
            <div id="forgot-section" class="hidden">
                <h2>Reset Password</h2>
                <input type="text" id="fp-user" placeholder="Enter Username">
                <input type="password" id="fp-pass" placeholder="Enter New Password">
                <button onclick="resetPassword()">Update Password</button>
                <button class="alt-btn" onclick="toggleForgot(false)">Back to Login</button>
                <p id="fp-err" style="color: #ff6b6b; text-align: center;"></p>
            </div>

            <!-- DASHBOARD SECTION -->
            <div id="dashboard-section" class="hidden">
                <button class="logout-btn" onclick="logout()">Logout</button>
                <button class="logout-btn" style="background: #205493;" onclick="toggleChangePass(true)">Change Password</button>
                <h2 id="welcome-title">Dashboard</h2>
                <p id="user-meta" style="color: #aaa; text-align: center;"></p>
                
                <div class="card-grid">
                    <div class="card">
                        <h3>Products in Masterlist</h3>
                        <p id="stat-products" style="font-size: 24px; font-weight: bold;">0</p>
                    </div>
                    <div class="card">
                        <h3 id="sales-card-title">Running Sales</h3>
                        <p id="stat-sales" style="font-size: 24px; font-weight: bold;">₱0.00</p>
                    </div>
                    <div id="promoter-cards" style="display: contents;">
                        <div class="card">
                            <h3>Target Sales Goal</h3>
                            <p id="stat-target" style="font-size: 24px; font-weight: bold;">₱0.00</p>
                        </div>
                        <div class="card">
                            <h3>Achievement Percentage</h3>
                            <p id="stat-percentage" style="font-size: 24px; font-weight: bold;">0%</p>
                        </div>
                    </div>
                </div>

                <div id="admin-panel" class="hidden" style="margin-top: 20px; background: #222; padding: 15px; border-radius: 6px;">
                    <h3>Store Sales Breakdown</h3>
                    <div id="breakdown-list"></div>
                    
                    <h3 style="margin-top: 20px;">Set Store Sales Target</h3>
                    <input type="text" id="target-store-name" placeholder="Store Name (e.g. Octagon)">
                    <input type="text" id="target-mall-name" placeholder="Mall Name (e.g. SM Megamall)">
                    <input type="number" id="target-new-amount" placeholder="New Target Amount">
                    <button onclick="setTarget()">Update Target</button>
                </div>

                <!-- CHANGE PASSWORD PANEL -->
                <div id="change-pass-panel" class="hidden" style="margin-top: 20px; background: #222; padding: 15px; border-radius: 6px;">
                    <h3>Change Password</h3>
                    <input type="password" id="cp-old" placeholder="Current Password">
                    <input type="password" id="cp-new" placeholder="New Password">
                    <input type="password" id="cp-confirm" placeholder="Confirm New Password">
                    <button onclick="changePasswordNet()">Save New Password</button>
                    <button class="alt-btn" onclick="toggleChangePass(false)">Cancel</button>
                    <p id="cp-err" style="color: #ff6b6b; text-align: center;"></p>
                </div>

                <button onclick="loadDashboard()" style="margin-top: 20px;">Refresh Data</button>
            </div>
        </div>

        <script>
            let currentUser = null;

            function toggleForgot(show) {
                document.getElementById('login-section').classList.toggle('hidden', show);
                document.getElementById('forgot-section').classList.toggle('hidden', !show);
            }

            function toggleChangePass(show) {
                document.getElementById('change-pass-panel').classList.toggle('hidden', !show);
            }

            async function login() {
                const u = document.getElementById('login-user').value.trim();
                const p = document.getElementById('login-pass').value.trim();
                const err = document.getElementById('login-err');

                if(!u || !p) { err.innerText = "Please enter credentials."; return; }

                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username: u, password: p})
                });

                if(res.ok) {
                    currentUser = await res.json();
                    document.getElementById('login-section').classList.add('hidden');
                    document.getElementById('dashboard-section').classList.remove('hidden');
                    loadDashboard();
                } else {
                    err.innerText = "Invalid username or password.";
                }
            }

            async function resetPassword() {
                const u = document.getElementById('fp-user').value.trim();
                const p = document.getElementById('fp-pass').value.trim();
                const err = document.getElementById('fp-err');

                if(!u || !p) { err.innerText = "Fill out all fields."; return; }

                const res = await fetch('/api/change-password', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username: u, new_password: p})
                });

                if(res.ok) {
                    alert("Password updated successfully!");
                    toggleForgot(false);
                } else {
                    err.innerText = "Failed to update password.";
                }
            }

            async function changePasswordNet() {
                const oldPass = document.getElementById('cp-old').value.trim();
                const newPass = document.getElementById('cp-new').value.trim();
                const confirmPass = document.getElementById('cp-confirm').value.trim();
                const err = document.getElementById('cp-err');

                if(!oldPass || !newPass || !confirmPass) { err.innerText = "Fill out all fields."; return; }
                if(newPass !== confirmPass) { err.innerText = "New passwords do not match."; return; }

                const res = await fetch('/api/change-password', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username: currentUser.username, old_password: oldPass, new_password: newPass})
                });

                if(res.ok) {
                    alert("Password changed successfully!");
                    toggleChangePass(false);
                } else {
                    const data = await res.json();
                    err.innerText = data.detail || "Failed to change password.";
                }
            }

            async function loadDashboard() {
                const isAdmin = currentUser.role === 'Administrator';
                document.getElementById('welcome-title').innerText = isAdmin ? "Administrator Command Center" : "Store Performance Overview";
                document.getElementById('user-meta').innerText = `User: ${currentUser.full_name} | Role: ${currentUser.role} | Store: ${currentUser.store_name}`;

                const res = await fetch(`/api/dashboard-stats?role=${currentUser.role}&store=${encodeURIComponent(currentUser.store_name)}`);
                if(res.ok) {
                    const data = await res.json();
                    document.getElementById('stat-products').innerText = data.products_count;
                    document.getElementById('stat-sales').innerText = `₱${data.running_sales.toLocaleString('en-US', {minimumFractionDigits: 2})}`;

                    if(isAdmin) {
                        document.getElementById('promoter-cards').style.display = 'none';
                        document.getElementById('admin-panel').classList.remove('hidden');
                        
                        const ovRes = await fetch('/api/admin-overview');
                        if(ovRes.ok) {
                            const ovData = await ovRes.json();
                            let html = '';
                            const storeSales = ovData.store_sales || [];
                            for(const s of storeSales) {
                                html += `<p>• ${s.store}: ₱${s.total_sales.toLocaleString('en-US', {minimumFractionDigits: 2})} (${s.tx_count} tx)</p>`;
                            }
                            document.getElementById('breakdown-list').innerHTML = html || "No store sales yet.";
                        }
                    } else {
                        document.getElementById('stat-target').innerText = `₱${data.target_amount.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
                        document.getElementById('stat-percentage').innerText = `${data.percentage}%`;
                    }
                }
            }

            async function setTarget() {
                const store = document.getElementById('target-store-name').value.trim();
                const mall = document.getElementById('target-mall-name').value.trim();
                const amount = parseFloat(document.getElementById('target-new-amount').value);

                if(!store || !mall || isNaN(amount)) { alert("Enter valid store name, mall name, and target."); return; }

                const fullStoreId = `${store} (${mall})`;
                const res = await fetch('/api/set-target', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({store: fullStoreId, target_amount: amount, role: currentUser.role})
                });

                if(res.ok) {
                    alert("Target updated successfully!");
                    loadDashboard();
                } else {
                    alert("Failed to update target.");
                }
            }

            function logout() {
                currentUser = null;
                document.getElementById('dashboard-section').classList.add('hidden');
                document.getElementById('login-section').classList.remove('hidden');
            }
        </script>
    </body>
    </html>
    """

# ---------------------------------------------------------
# API ENDPOINTS
# ---------------------------------------------------------
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

@app.get("/api/products")
def get_products(limit: int = 1500, offset: int = 0):
    conn = get_db()
    rows = conn.execute("SELECT sku, barcode, model_number, name, price, stock FROM products ORDER BY name LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    conn.close()
    return [dict(row) for row in rows]

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
