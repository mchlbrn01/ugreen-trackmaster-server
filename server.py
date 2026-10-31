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
    except Exception as e:
        print("Store list preload notice:", e)

    # 2. Preload SKU List if empty
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
    except Exception as e:
        print("SKU list preload notice:", e)

    # Ensure admin account exists
    admin_exists = conn.execute("SELECT COUNT(*) FROM users WHERE username='admin'").fetchone()[0]
    if admin_exists == 0:
        conn.execute(
            "INSERT INTO users (username, password, full_name, store_name, mall_name, role) VALUES (?, ?, ?, ?, ?, ?)",
            ("admin", "ugreen2026", "Administrator", "Ugreen Philippines", "PH HQ", "Administrator")
        )
    conn.commit()
    conn.close()

# ---------------------------------------------------------
# BROWSER WEB APPLICATION (WITH CAMERA SCANNER & AUTO-CLEAR)
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
        <!-- Include Html5Qrcode library for phone/web camera scanning -->
        <script src="https://unpkg.com/html5-qrcode" type="text/javascript"></script>
        <style>
            body { font-family: Arial, sans-serif; background: #121212; color: #e0e0e0; margin: 0; padding: 20px; }
            .container { max-width: 1000px; margin: auto; background: #1e1e1e; padding: 20px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.5); }
            h1, h2 { color: #00A859; text-align: center; }
            input, select, button { width: 100%; padding: 10px; margin: 8px 0; border: 1px solid #333; border-radius: 4px; background: #2c2c2c; color: #fff; box-sizing: border-box; }
            button { background: #00A859; color: white; font-weight: bold; cursor: pointer; border: none; }
            button:hover { background: #008f4c; }
            .hidden { display: none; }
            .card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 15px; }
            .card { background: #252525; padding: 15px; border-radius: 6px; text-align: center; border-left: 4px solid #00A859; }
            .nav-bar { display: flex; gap: 5px; margin-bottom: 20px; flex-wrap: wrap; }
            .nav-bar button { flex: 1; background: #2c2c2c; margin: 0; }
            .nav-bar button.active { background: #00A859; }
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { border: 1px solid #333; padding: 8px; text-align: left; font-size: 14px; }
            th { background: #252525; color: #00A859; }
            .logout-btn { background: #d9534f; width: auto; padding: 5px 15px; }
            .pass-btn { background: #205493; width: auto; padding: 5px 15px; margin-right: 5px; }
            .alt-btn { background: #333; }
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
                <button class="alt-btn" onclick="showSection('register-section')">Register New Account</button>
                <button class="alt-btn" onclick="showSection('forgot-section')" style="background: #444;">Forgot Password?</button>
                <p id="login-err" style="color: #ff6b6b; text-align: center;"></p>
            </div>

            <!-- REGISTER SECTION -->
            <div id="register-section" class="hidden">
                <h2>Register New Account</h2>
                <input type="text" id="reg-fullname" placeholder="Full Name">
                <input type="text" id="reg-user" placeholder="Choose Username">
                <input type="password" id="reg-pass" placeholder="Choose Password">
                <input type="text" id="reg-store" placeholder="Store Name (e.g. Ugreen Kiosk)">
                <input type="text" id="reg-mall" placeholder="Mall Name (e.g. SM Megamall)">
                <button onclick="registerUser()">Register Account</button>
                <button class="alt-btn" onclick="showSection('login-section')">Back to Login</button>
                <p id="reg-err" style="color: #ff6b6b; text-align: center;"></p>
            </div>

            <!-- FORGOT PASSWORD SECTION -->
            <div id="forgot-section" class="hidden">
                <h2>Reset Password</h2>
                <input type="text" id="fp-user" placeholder="Enter Username">
                <input type="password" id="fp-pass" placeholder="Enter New Password">
                <button onclick="resetPassword()">Update Password</button>
                <button class="alt-btn" onclick="showSection('login-section')">Back to Login</button>
                <p id="fp-err" style="color: #ff6b6b; text-align: center;"></p>
            </div>

            <!-- CHANGE PASSWORD SECTION -->
            <div id="change-pass-section" class="hidden" style="margin-bottom: 20px; background: #252525; padding: 15px; border-radius: 6px;">
                <h3>Change Password</h3>
                <input type="password" id="cp-old" placeholder="Current Password">
                <input type="password" id="cp-new" placeholder="New Password">
                <input type="password" id="cp-confirm" placeholder="Confirm New Password">
                <button onclick="changePassword()">Save New Password</button>
                <button class="alt-btn" onclick="toggleChangePass(false)">Cancel</button>
                <p id="cp-err" style="color: #ff6b6b; text-align: center;"></p>
            </div>

            <!-- MAIN APP SECTION -->
            <div id="app-section" class="hidden">
                <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #333; padding-bottom: 10px; margin-bottom: 15px;">
                    <div>
                        <h3 id="user-welcome" style="margin: 0; color: #00A859;">Welcome</h3>
                        <p id="user-meta" style="margin: 5px 0 0 0; color: #aaa; font-size: 13px;"></p>
                    </div>
                    <div>
                        <button class="pass-btn" onclick="toggleChangePass(true)">Change Password</button>
                        <button class="logout-btn" onclick="logout()">Logout</button>
                    </div>
                </div>

                <!-- DYNAMIC NAVIGATION TABS -->
                <div class="nav-bar" id="nav-tabs"></div>

                <!-- TAB: DASHBOARD -->
                <div id="pane-dashboard" class="pane hidden">
                    <h2 id="dash-title">Dashboard</h2>
                    <div class="card-grid" id="dash-cards"></div>
                    <div id="admin-extras" class="hidden" style="margin-top: 20px;">
                        <h3>Store Sales Breakdown</h3>
                        <div id="breakdown-list"></div>
                        <h3 style="margin-top: 15px;">Set Store Sales Target</h3>
                        <input type="text" id="target-store" placeholder="Store Name (e.g. Octagon)">
                        <input type="text" id="target-mall" placeholder="Mall Name (e.g. SM Megamall)">
                        <input type="number" id="target-amount" placeholder="New Target Amount">
                        <button onclick="setTarget()">Update Target</button>
                    </div>
                    <button onclick="loadDashboard()" style="margin-top: 15px;">Refresh Data</button>
                </div>

                <!-- TAB: STORE DIRECTORY (ADMIN) -->
                <div id="pane-stores" class="pane hidden">
                    <h2>Master Store Directory</h2>
                    <div style="max-height: 400px; overflow-y: auto;">
                        <table>
                            <thead>
                                <tr><th>Code</th><th>Store</th><th>Mall</th><th>Region</th><th>Type</th><th>Dealer</th></tr>
                            </thead>
                            <tbody id="stores-table-body"></tbody>
                        </table>
                    </div>
                    <button onclick="loadStores()" style="margin-top: 15px;">Refresh Store List</button>
                </div>

                <!-- TAB: SCAN SALES (PROMOTER) -->
                <div id="pane-sales" class="pane hidden">
                    <h2>Record & Scan Sale</h2>
                    <div id="reader" style="width: 100%; max-width: 400px; margin: 10px auto;"></div>
                    <button onclick="startScanner('sale-sku', 'sale-price')" style="background: #205493;">📷 Start Camera Scanner</button>
                    <input type="text" id="sale-sku" placeholder="SKU or Barcode">
                    <input type="number" id="sale-qty" placeholder="Quantity" value="1">
                    <input type="number" id="sale-price" placeholder="Unit Price (₱)" value="0.00">
                    <button onclick="submitSale()">Record Sale</button>
                    <p id="sale-msg" style="color: #00A859; text-align: center;"></p>
                </div>

                <!-- TAB: STOCK IN / OUT (PROMOTER) -->
                <div id="pane-stock" class="pane hidden">
                    <h2>Stock Adjustment (IN / OUT)</h2>
                    <div id="reader-stock" style="width: 100%; max-width: 400px; margin: 10px auto;"></div>
                    <button onclick="startScanner('stock-sku')" style="background: #205493;">📷 Start Camera Scanner</button>
                    <input type="text" id="stock-sku" placeholder="SKU or Barcode">
                    <input type="number" id="stock-qty" placeholder="Quantity" value="1">
                    <div style="display: flex; gap: 10px;">
                        <button onclick="submitStock('IN')" style="background: #00A859;">Save Stock IN (+)</button>
                        <button onclick="submitStock('OUT')" style="background: #d9534f;">Save Stock OUT (-)</button>
                    </div>
                    <p id="stock-msg" style="color: #00A859; text-align: center;"></p>
                </div>

                <!-- TAB: PRODUCTS & SKU -->
                <div id="pane-products" class="pane hidden">
                    <h2>Product Masterlist & SKU</h2>
                    <input type="text" id="product-search" placeholder="Search SKU, Model, or Description..." oninput="filterProducts()">
                    <div style="max-height: 400px; overflow-y: auto;">
                        <table>
                            <thead>
                                <tr><th>SKU</th><th>Model</th><th>Description</th><th>Price</th><th>Stock</th></tr>
                            </thead>
                            <tbody id="product-table-body"></tbody>
                        </table>
                    </div>
                </div>

                <!-- TAB: REPORTS -->
                <div id="pane-reports" class="pane hidden">
                    <h2 id="report-title">Sales Reports</h2>
                    <div id="admin-export-div" class="hidden">
                        <button onclick="downloadCSV()" style="background: #205493; margin-bottom: 10px;">📥 Export All Sales to CSV</button>
                    </div>
                    <div style="max-height: 400px; overflow-y: auto;">
                        <table>
                            <thead>
                                <tr><th>Date</th><th>Store</th><th>Product</th><th>Qty</th><th>Total</th><th>Promoter</th></tr>
                            </thead>
                            <tbody id="reports-table-body"></tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <script>
            let currentUser = null;
            let allProducts = [];
            let html5QrCode = null;

            function showSection(sectionId) {
                ['login-section', 'register-section', 'forgot-section'].forEach(id => {
                    document.getElementById(id).classList.add('hidden');
                });
                document.getElementById(sectionId).classList.remove('hidden');
                clearInputs(sectionId);
            }

            function clearInputs(containerId) {
                const container = document.getElementById(containerId);
                if(container) {
                    container.querySelectorAll('input').forEach(input => input.value = '');
                }
            }

            function toggleChangePass(show) {
                document.getElementById('change-pass-section').classList.toggle('hidden', !show);
                if(!show) clearInputs('change-pass-section');
            }

            function startScanner(targetFieldId, priceFieldId = null) {
                const scannerDiv = targetFieldId === 'sale-sku' ? 'reader' : 'reader-stock';
                if (html5QrCode) {
                    html5QrCode.stop().catch(() => {});
                }
                html5QrCode = new Html5Qrcode(scannerDiv);
                html5QrCode.start(
                    { facingMode: "environment" },
                    { fps: 10, qrbox: { width: 250, height: 100 } },
                    (decodedText, decodedResult) => {
                        document.getElementById(targetFieldId).value = decodedText;
                        if(priceFieldId) {
                            const p = allProducts.find(item => item.sku === decodedText || item.barcode === decodedText);
                            if(p) document.getElementById(priceFieldId).value = p.price;
                        }
                        html5QrCode.stop().catch(() => {});
                    },
                    (errorMessage) => {}
                ).catch(err => {
                    alert("Unable to access camera. Please check camera permissions.");
                });
            }

            async function registerUser() {
                const fullname = document.getElementById('reg-fullname').value.trim();
                const username = document.getElementById('reg-user').value.trim();
                const password = document.getElementById('reg-pass').value.trim();
                const store = document.getElementById('reg-store').value.trim();
                const mall = document.getElementById('reg-mall').value.trim();
                const err = document.getElementById('reg-err');

                if(!fullname || !username || !password || !store || !mall) {
                    err.innerText = "All fields are required.";
                    return;
                }

                const res = await fetch('/api/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, password, full_name: fullname, store_name: store, mall_name: mall })
                });

                if(res.ok) {
                    alert("Registration successful! Please log in.");
                    showSection('login-section');
                } else {
                    const data = await res.json();
                    err.innerText = data.detail || "Registration failed.";
                }
            }

            async function resetPassword() {
                const username = document.getElementById('fp-user').value.trim();
                const new_password = document.getElementById('fp-pass').value.trim();
                const err = document.getElementById('fp-err');

                if(!username || !new_password) { err.innerText = "Fill out all fields."; return; }

                const res = await fetch('/api/change-password', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, new_password })
                });

                if(res.ok) {
                    alert("Password updated successfully!");
                    showSection('login-section');
                } else {
                    err.innerText = "Failed to update password.";
                }
            }

            async function changePassword() {
                const old_password = document.getElementById('cp-old').value.trim();
                const new_password = document.getElementById('cp-new').value.trim();
                const confirm_pass = document.getElementById('cp-confirm').value.trim();
                const err = document.getElementById('cp-err');

                if(!old_password || !new_password || !confirm_pass) { err.innerText = "Fill out all fields."; return; }
                if(new_password !== confirm_pass) { err.innerText = "New passwords do not match."; return; }

                const res = await fetch('/api/change-password', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username: currentUser.username, old_password, new_password })
                });

                if(res.ok) {
                    alert("Password changed successfully!");
                    toggleChangePass(false);
                } else {
                    const data = await res.json();
                    err.innerText = data.detail || "Incorrect current password.";
                }
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
                    document.getElementById('app-section').classList.remove('hidden');
                    clearInputs('login-section');
                    
                    const isAdmin = currentUser.role === 'Administrator';
                    document.getElementById('user-welcome').innerText = `Welcome, ${currentUser.full_name}`;
                    document.getElementById('user-meta').innerText = isAdmin ? `Role: Administrator` : `Store: ${currentUser.store_name} | Mall: ${currentUser.mall_name}`;

                    buildTabs(isAdmin);
                    fetchProducts();
                } else {
                    err.innerText = "Invalid username or password.";
                }
            }

            function buildTabs(isAdmin) {
                let tabsHtml = '';
                if(isAdmin) {
                    tabsHtml = `
                        <button onclick="switchTab('dashboard')" id="tab-dashboard" class="active">Admin Overview</button>
                        <button onclick="switchTab('stores')" id="tab-stores">Store Directory</button>
                        <button onclick="switchTab('products')" id="tab-products">Products / SKU</button>
                        <button onclick="switchTab('reports')" id="tab-reports">All Store Sales Logs</button>
                    `;
                    document.getElementById('admin-extras').classList.remove('hidden');
                    document.getElementById('admin-export-div').classList.remove('hidden');
                } else {
                    tabsHtml = `
                        <button onclick="switchTab('dashboard')" id="tab-dashboard" class="active">Dashboard</button>
                        <button onclick="switchTab('sales')" id="tab-sales">Scan Sales</button>
                        <button onclick="switchTab('stock')" id="tab-stock">Stock In / Out</button>
                        <button onclick="switchTab('products')" id="tab-products">Products / SKU</button>
                        <button onclick="switchTab('reports')" id="tab-reports">Reports</button>
                    `;
                }
                document.getElementById('nav-tabs').innerHTML = tabsHtml;
                switchTab('dashboard');
            }

            function logout() {
                currentUser = null;
                if (html5QrCode) html5QrCode.stop().catch(() => {});
                document.getElementById('app-section').classList.add('hidden');
                showSection('login-section');
            }

            function switchTab(tabName) {
                if (html5QrCode) html5QrCode.stop().catch(() => {});
                const tabs = currentUser.role === 'Administrator' ? ['dashboard', 'stores', 'products', 'reports'] : ['dashboard', 'sales', 'stock', 'products', 'reports'];
                tabs.forEach(t => {
                    const pane = document.getElementById(`pane-${t}`);
                    const tabBtn = document.getElementById(`tab-${t}`);
                    if(pane) {
                        pane.classList.add('hidden');
                        clearInputs(`pane-${t}`);
                    }
                    if(tabBtn) tabBtn.classList.remove('active');
                });
                
                document.getElementById(`pane-${tabName}`).classList.remove('hidden');
                document.getElementById(`tab-${tabName}`).classList.add('active');

                if(tabName === 'dashboard') loadDashboard();
                if(tabName === 'stores') loadStores();
                if(tabName === 'reports') loadReports();
            }

            async function loadDashboard() {
                const isAdmin = currentUser.role === 'Administrator';
                document.getElementById('dash-title').innerText = isAdmin ? "Administrator Central Command" : "Store Performance Overview";
                
                const res = await fetch(`/api/dashboard-stats?role=${currentUser.role}&store=${encodeURIComponent(currentUser.store_name)}`);
                if(res.ok) {
                    const data = await res.json();
                    let cardsHtml = `
                        <div class="card"><h3>Total Products in Masterlist</h3><p style="font-size: 24px; font-weight: bold;">${data.products_count}</p></div>
                        <div class="card"><h3>${isAdmin ? 'Total Company-Wide Sales' : 'Current Running Sales'}</h3><p style="font-size: 24px; font-weight: bold;">₱${data.running_sales.toLocaleString('en-US', {minimumFractionDigits: 2})}</p></div>
                    `;
                    if(!isAdmin) {
                        cardsHtml += `
                            <div class="card"><h3>Target Sales Goal</h3><p style="font-size: 24px; font-weight: bold;">₱${data.target_amount.toLocaleString('en-US', {minimumFractionDigits: 2})}</p></div>
                            <div class="card"><h3>Achievement Percentage</h3><p style="font-size: 24px; font-weight: bold;">${data.percentage}%</p></div>
                        `;
                    }
                    document.getElementById('dash-cards').innerHTML = cardsHtml;

                    if(isAdmin) {
                        const ovRes = await fetch('/api/admin-overview');
                        if(ovRes.ok) {
                            const ovData = await ovRes.json();
                            let html = '<table><tr><th>Store</th><th>Sales</th><th>Transactions</th></tr>';
                            for(const s of (ovData.store_sales || [])) {
                                html += `<tr><td>${s.store}</td><td>₱${s.total_sales.toLocaleString('en-US', {minimumFractionDigits: 2})}</td><td>${s.tx_count}</td></tr>`;
                            }
                            html += '</table>';
                            document.getElementById('breakdown-list').innerHTML = html || "No store sales yet.";
                        }
                    }
                }
            }

            async function loadStores() {
                const res = await fetch('/api/stores');
                if(res.ok) {
                    const stores = await res.json();
                    let html = '';
                    for(const s of stores) {
                        html += `<tr><td>${s.store_code}</td><td>${s.store}</td><td>${s.mall}</td><td>${s.region}</td><td>${s.store_type}</td><td>${s.dealer}</td></tr>`;
                    }
                    document.getElementById('stores-table-body').innerHTML = html || '<tr><td colspan="6">No stores found.</td></tr>';
                }
            }

            async function setTarget() {
                if (currentUser.role !== 'Administrator') {
                    alert("Unauthorized: Only administrators can set targets.");
                    return;
                }
                const store = document.getElementById('target-store').value.trim();
                const mall = document.getElementById('target-mall').value.trim();
                const amount = parseFloat(document.getElementById('target-amount').value);
                if(!store || !mall || isNaN(amount)) { alert("Enter valid store, mall, and target."); return; }

                const res = await fetch('/api/set-target', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ store: `${store} (${mall})`, target_amount: amount, role: currentUser.role })
                });
                if(res.ok) { 
                    alert("Target updated!"); 
                    document.getElementById('target-store').value = '';
                    document.getElementById('target-mall').value = '';
                    document.getElementById('target-amount').value = '';
                    loadDashboard(); 
                } else {
                    alert("Unauthorized or failed to update target.");
                }
            }

            async function fetchProducts() {
                const res = await fetch('/api/products?limit=2000');
                if(res.ok) {
                    allProducts = await res.json();
                    renderProductTable(allProducts);
                }
            }

            function renderProductTable(products) {
                let html = '';
                for(const p of products) {
                    html += `<tr><td>${p.sku || ''}</td><td>${p.model_number || ''}</td><td>${p.name || ''}</td><td>₱${p.price.toLocaleString('en-US', {minimumFractionDigits: 2})}</td><td>${p.stock}</td></tr>`;
                }
                document.getElementById('product-table-body').innerHTML = html || '<tr><td colspan="5">No products found.</td></tr>';
            }

            function filterProducts() {
                const query = document.getElementById('product-search').value.toLowerCase();
                const filtered = allProducts.filter(p => 
                    (p.sku && p.sku.toLowerCase().includes(query)) ||
                    (p.model_number && p.model_number.toLowerCase().includes(query)) ||
                    (p.name && p.name.toLowerCase().includes(query))
                );
                renderProductTable(filtered);
            }

            async function submitSale() {
                const sku = document.getElementById('sale-sku').value.trim();
                const qty = parseInt(document.getElementById('sale-qty').value);
                const price = parseFloat(document.getElementById('sale-price').value);
                const msg = document.getElementById('sale-msg');

                if(!sku || isNaN(qty) || isNaN(price)) { msg.style.color="#ff6b6b"; msg.innerText = "Fill out all fields."; return; }
                const p = allProducts.find(item => item.sku === sku || item.barcode === sku);
                const prodName = p ? p.name : sku;

                const res = await fetch('/api/sales', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        sale_date: new Date().toISOString().slice(0, 19).replace('T', ' '),
                        sku: sku, product_name: prodName, quantity: qty, unit_price: price, total: qty * price,
                        branch: currentUser.mall_name, store: currentUser.store_name, promoter: currentUser.full_name
                    })
                });

                if(res.ok) {
                    msg.style.color="#00A859";
                    msg.innerText = "Sale recorded successfully!";
                    document.getElementById('sale-sku').value = '';
                    document.getElementById('sale-qty').value = '1';
                    document.getElementById('sale-price').value = '0.00';
                    fetchProducts();
                } else {
                    msg.style.color="#ff6b6b";
                    msg.innerText = "Failed to record sale.";
                }
            }

            async function submitStock(type) {
                const sku = document.getElementById('stock-sku').value.trim();
                const qty = parseInt(document.getElementById('stock-qty').value);
                const msg = document.getElementById('stock-msg');

                if(!sku || isNaN(qty)) { msg.style.color="#ff6b6b"; msg.innerText = "Fill out all fields."; return; }

                const res = await fetch('/api/stock-adjustment', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ sku: sku, quantity: qty, type: type, store: currentUser.store_name })
                });

                if(res.ok) {
                    msg.style.color="#00A859";
                    msg.innerText = `Stock ${type} updated successfully!`;
                    document.getElementById('stock-sku').value = '';
                    document.getElementById('stock-qty').value = '1';
                    fetchProducts();
                } else {
                    msg.style.color="#ff6b6b";
                    msg.innerText = "Product not found or update failed.";
                }
            }

            async function loadReports() {
                const isAdmin = currentUser.role === 'Administrator';
                if(isAdmin) {
                    const res = await fetch('/api/admin-overview');
                    if(res.ok) {
                        const data = await res.json();
                        let html = '';
                        for(const s of (data.all_sales || [])) {
                            html += `<tr><td>${s.sale_date}</td><td>${s.store}</td><td>${s.product_name}</td><td>${s.quantity}</td><td>₱${s.total.toLocaleString('en-US', {minimumFractionDigits: 2})}</td><td>${s.promoter}</td></tr>`;
                        }
                        document.getElementById('reports-table-body').innerHTML = html || '<tr><td colspan="6">No sales logs found.</td></tr>';
                    }
                } else {
                    document.getElementById('reports-table-body').innerHTML = '<tr><td colspan="6">Promoter reports view active.</td></tr>';
                }
            }

            function downloadCSV() {
                window.open('/api/export-sales-csv', '_blank');
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
        return {"status": "success"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Username already exists")
    finally:
        conn.close()

@app.post("/api/login")
def login_user(data: dict):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (data["username"], data["password"])).fetchone()
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

@app.get("/api/dashboard-stats")
def get_dashboard_stats(role: str = "Promoter", store: str = ""):
    conn = get_db()
    prod_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if role == "Administrator":
        running_sales = conn.execute("SELECT COALESCE(SUM(total),0) FROM sales").fetchone()[0]
        conn.close()
        return {"role": "Administrator", "products_count": prod_count, "running_sales": running_sales}
    else:
        running_sales = conn.execute("SELECT COALESCE(SUM(total),0) FROM sales WHERE store=?", (store,)).fetchone()[0]
        target_row = conn.execute("SELECT target_amount FROM targets WHERE store=? OR store LIKE ?", (store, f"%{store}%")).fetchone()
        target_amount = target_row["target_amount"] if target_row else 50000.0
        percentage = (running_sales / target_amount * 100) if target_amount > 0 else 0
        conn.close()
        return {"role": "Promoter", "products_count": prod_count, "running_sales": running_sales, "target_amount": target_amount, "percentage": round(percentage, 2)}

@app.get("/api/admin-overview")
def get_admin_overview():
    conn = get_db()
    store_sales = conn.execute("SELECT store, COALESCE(SUM(total),0) as total_sales, COUNT(*) as tx_count FROM sales GROUP BY store").fetchall()
    all_sales = conn.execute("SELECT sale_date, store, product_name, quantity, total, promoter FROM sales ORDER BY id DESC LIMIT 100").fetchall()
    conn.close()
    return {"store_sales": [dict(r) for r in store_sales], "all_sales": [dict(r) for r in all_sales]}

@app.get("/api/stores")
def get_stores():
    conn = get_db()
    rows = conn.execute("SELECT * FROM store_directory ORDER BY store_code").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/set-target")
def set_store_target(data: dict):
    if data.get("role") != "Administrator":
        raise HTTPException(status_code=403, detail="Unauthorized: Only administrators can set targets")
    conn = get_db()
    with conn:
        conn.execute("INSERT INTO targets (store, target_amount) VALUES (?, ?) ON CONFLICT(store) DO UPDATE SET target_amount = ?", 
                     (data["store"], float(data["target_amount"]), float(data["target_amount"])))
    conn.close()
    return {"status": "success"}

@app.get("/api/products")
def get_products(limit: int = 2000):
    conn = get_db()
    rows = conn.execute("SELECT sku, barcode, model_number, name, price, stock FROM products ORDER BY name LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/sales")
def post_sale(data: dict):
    conn = get_db()
    with conn:
        conn.execute(
            """INSERT INTO sales (sale_date, sku, product_name, quantity, unit_price, total, branch, store, promoter)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data["sale_date"], data["sku"], data["product_name"], data["quantity"], data["unit_price"], data["total"], data["branch"], data["store"], data["promoter"])
        )
        conn.execute("UPDATE products SET stock = stock - ? WHERE sku=? OR barcode=?", (data["quantity"], data["sku"], data["sku"]))
    conn.close()
    return {"status": "success"}

@app.post("/api/stock-adjustment")
def stock_adjustment(data: dict):
    conn = get_db()
    sku = data.get("sku")
    qty = int(data.get("quantity", 0))
    delta = qty if data.get("type") == "IN" else -qty
    with conn:
        cursor = conn.execute("UPDATE products SET stock = stock + ? WHERE sku=? OR barcode=?", (delta, sku, sku))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found")
    conn.close()
    return {"status": "success"}

@app.get("/api/export-sales-csv")
def export_sales_csv():
    conn = get_db()
    sales = conn.execute("SELECT sale_date, store, product_name, quantity, total, promoter FROM sales ORDER BY id DESC").fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Sale Date", "Store", "Product Name", "Quantity", "Total", "Promoter"])
    for s in sales:
        writer.writerow([s["sale_date"], s["store"], s["product_name"], s["quantity"], s["total"], s["promoter"]])
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=ugreen_sales_report.csv"})
