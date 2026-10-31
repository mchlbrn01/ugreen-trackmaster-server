from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
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
            .container { max-width: 800px; margin: auto; background: #1e1e1e; padding: 20px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
            h1, h2 { color: #00A859; text-align: center; }
            input, select, button { width: 100%; padding: 10px; margin: 8px 0; border: 1px solid #333; border-radius: 4px; background: #2c2c2c; color: #fff; box-sizing: border-box; }
            button { background: #00A859; color: white; font-weight: bold; cursor: pointer; border: none; }
            button:hover { background: #008f4c; }
            .hidden { display: none; }
            .card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px; }
            .card { background: #252525; padding: 15px; border-radius: 6px; text-align: center; border-left: 4px solid #00A859; }
            .logout-btn { background: #d9534f; width: auto; padding: 5px 15px; float: right; }
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
                <p id="login-err" style="color: #ff6b6b; text-align: center;"></p>
            </div>

            <!-- DASHBOARD SECTION -->
            <div id="dashboard-section" class="hidden">
                <button class="logout-btn" onclick="logout()">Logout</button>
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

                <button onclick="loadDashboard()" style="margin-top: 20px;">Refresh Data</button>
            </div>
        </div>

        <script>
            let currentUser = null;

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
        
        # Matches exact store name or partial name inside targets table
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
