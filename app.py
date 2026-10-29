from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import check_password_hash
from decimal import Decimal, InvalidOperation
from datetime import datetime
from database import get_connection
import functools

app = Flask(__name__)
app.secret_key = "change-this-secret-key-in-production"

# ---------- Helpers ----------
def login_required(role=None):
    def wrapper(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                flash("Unauthorized access.", "error")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return inner
    return wrapper

def validate_product(name, code, price, stock):
    errors = []
    name = (name or "").strip()
    code = (code or "").strip()
    if not name:
        errors.append("Product name is required.")
    if not code:
        errors.append("Product code is required.")

    price_value = None
    try:
        price_value = Decimal(str(price))
        if not price_value.is_finite() or price_value <= 0:
            errors.append("Price must be greater than zero.")
        elif price_value.as_tuple().exponent < -2:
            errors.append("Price cannot have more than 2 decimals.")
    except (InvalidOperation, ValueError, TypeError):
        errors.append("Price must be a valid number.")

    stock_value = None
    try:
        if isinstance(stock, bool):
            raise ValueError
        stock_value = int(stock)
        if str(stock).strip() != str(stock_value):
            raise ValueError
        if stock_value < 0:
            errors.append("Stock must be a non-negative whole number.")
    except (ValueError, TypeError):
        errors.append("Stock must be a non-negative whole number.")

    if errors:
        return errors, None
    return [], {"name": name, "code": code, "price": price_value, "stock": stock_value}

# ---------- Auth ----------
@app.route("/", methods=["GET"])
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if not username or not password:
            flash("Enter both username and password.", "error")
            return render_template("login.html")
        conn = get_connection()
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()
        if not row or not check_password_hash(row["password_hash"], password):
            flash("Invalid username or password.", "error")
            return render_template("login.html")
        if not row["is_active"]:
            flash("Account is deactivated.", "error")
            return render_template("login.html")
        session["user_id"] = row["user_id"]
        session["username"] = row["username"]
        session["role"] = row["role"]
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- Dashboard ----------
@app.route("/dashboard")
@login_required()
def dashboard():
    conn = get_connection()
    stats = {}
    stats["product_count"] = conn.execute(
        "SELECT COUNT(*) c FROM products WHERE is_active=1"
    ).fetchone()["c"]
    stats["low_stock"] = conn.execute(
        "SELECT COUNT(*) c FROM products WHERE is_active=1 AND stock_quantity <= reorder_level"
    ).fetchone()["c"]
    stats["today_sales"] = conn.execute(
        "SELECT COALESCE(SUM(CAST(total_amount AS REAL)),0) t FROM sales "
        "WHERE date(sale_date) = date('now','localtime')"
    ).fetchone()["t"]
    stats["today_txn"] = conn.execute(
        "SELECT COUNT(*) c FROM sales WHERE date(sale_date) = date('now','localtime')"
    ).fetchone()["c"]

    low = conn.execute(
        """SELECT product_code, name, stock_quantity, reorder_level
           FROM products WHERE is_active=1 AND stock_quantity <= reorder_level
           ORDER BY stock_quantity ASC LIMIT 8"""
    ).fetchall()
    recent = conn.execute(
        """SELECT s.sale_id, s.sale_date, s.total_amount, u.username
           FROM sales s JOIN users u ON u.user_id = s.user_id
           ORDER BY s.sale_id DESC LIMIT 6"""
    ).fetchall()
    conn.close()
    return render_template("dashboard.html", stats=stats, low=low, recent=recent)

# ---------- Inventory ----------
@app.route("/inventory")
@login_required(role="admin")
def inventory():
    q = (request.args.get("q") or "").strip()
    conn = get_connection()
    if q:
        rows = conn.execute(
            """SELECT * FROM products WHERE is_active=1
               AND (name LIKE ? OR product_code LIKE ?) ORDER BY name""",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM products WHERE is_active=1 ORDER BY name"
        ).fetchall()
    conn.close()
    # Convert sqlite3.Row objects to plain dicts so Jinja's |tojson works
    products = [dict(r) for r in rows]
    return render_template("inventory.html", products=products, q=q)

@app.route("/inventory/add", methods=["POST"])
@login_required(role="admin")
def add_product():
    name = request.form.get("name", "")
    code = request.form.get("product_code", "")
    price = request.form.get("price", "")
    stock = request.form.get("stock", "0")
    reorder = request.form.get("reorder_level", "5")

    errors, data = validate_product(name, code, price, stock)
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("inventory"))

    conn = get_connection()
    exists = conn.execute(
        "SELECT 1 FROM products WHERE product_code = ?", (data["code"],)
    ).fetchone()
    if exists:
        conn.close()
        flash("Product code already exists.", "error")
        return redirect(url_for("inventory"))

    try:
        conn.execute(
            """INSERT INTO products
               (product_code, name, price, stock_quantity, reorder_level)
               VALUES (?,?,?,?,?)""",
            (data["code"], data["name"], str(data["price"]), data["stock"], int(reorder))
        )
        conn.commit()
        flash("Product added successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Database error: {e}", "error")
    conn.close()
    return redirect(url_for("inventory"))

@app.route("/inventory/edit/<int:pid>", methods=["POST"])
@login_required(role="admin")
def edit_product(pid):
    name = request.form.get("name", "")
    price = request.form.get("price", "")
    stock = request.form.get("stock", "0")
    reorder = request.form.get("reorder_level", "5")

    errors, data = validate_product(name, "TEMP", price, stock)
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("inventory"))

    conn = get_connection()
    old = conn.execute("SELECT * FROM products WHERE product_id=?", (pid,)).fetchone()
    if not old:
        conn.close()
        flash("Product not found.", "error")
        return redirect(url_for("inventory"))

    try:
        conn.execute(
            """UPDATE products SET name=?, price=?, stock_quantity=?, reorder_level=?
               WHERE product_id=?""",
            (data["name"], str(data["price"]), data["stock"], int(reorder), pid)
        )
        # Record stock movement if changed
        diff = data["stock"] - old["stock_quantity"]
        if diff != 0:
            conn.execute(
                """INSERT INTO stock_movements
                   (product_id, user_id, movement_type, quantity, movement_date, reference)
                   VALUES (?,?,?,?,?,?)""",
                (pid, session["user_id"], "adjustment", diff,
                 datetime.now().isoformat(timespec="seconds"), "Manual edit")
            )
        conn.commit()
        flash("Product updated.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Database error: {e}", "error")
    conn.close()
    return redirect(url_for("inventory"))

@app.route("/inventory/restock/<int:pid>", methods=["POST"])
@login_required(role="admin")
def restock(pid):
    try:
        qty = int(request.form.get("quantity", "0"))
        if qty <= 0:
            raise ValueError
    except ValueError:
        flash("Restock quantity must be a positive whole number.", "error")
        return redirect(url_for("inventory"))

    conn = get_connection()
    try:
        prod = conn.execute("SELECT * FROM products WHERE product_id=?", (pid,)).fetchone()
        if not prod:
            flash("Product not found.", "error")
            conn.close()
            return redirect(url_for("inventory"))
        conn.execute(
            "UPDATE products SET stock_quantity = stock_quantity + ? WHERE product_id=?",
            (qty, pid)
        )
        conn.execute(
            """INSERT INTO stock_movements
               (product_id, user_id, movement_type, quantity, movement_date, reference)
               VALUES (?,?,?,?,?,?)""",
            (pid, session["user_id"], "restock", qty,
             datetime.now().isoformat(timespec="seconds"), "Restock")
        )
        conn.commit()
        flash(f"Restocked {qty} unit(s).", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    conn.close()
    return redirect(url_for("inventory"))

@app.route("/inventory/deactivate/<int:pid>", methods=["POST"])
@login_required(role="admin")
def deactivate(pid):
    conn = get_connection()
    conn.execute("UPDATE products SET is_active=0 WHERE product_id=?", (pid,))
    conn.commit()
    conn.close()
    flash("Product deactivated.", "success")
    return redirect(url_for("inventory"))

# ---------- POS ----------
@app.route("/pos")
@login_required()
def pos():
    conn = get_connection()
    products = conn.execute(
        "SELECT * FROM products WHERE is_active=1 AND stock_quantity > 0 ORDER BY name"
    ).fetchall()
    conn.close()
    return render_template("pos.html", products=products)

@app.route("/api/products")
@login_required()
def api_products():
    q = (request.args.get("q") or "").strip()
    conn = get_connection()
    if q:
        rows = conn.execute(
            """SELECT product_id, product_code, name, price, stock_quantity
               FROM products WHERE is_active=1 AND stock_quantity>0
               AND (name LIKE ? OR product_code LIKE ?)
               ORDER BY name LIMIT 20""",
            (f"%{q}%", f"%{q}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT product_id, product_code, name, price, stock_quantity
               FROM products WHERE is_active=1 AND stock_quantity>0
               ORDER BY name LIMIT 20"""
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/checkout", methods=["POST"])
@login_required()
def checkout():
    data = request.get_json(force=True)
    cart = data.get("cart", [])
    payment_raw = data.get("payment")

    if not cart:
        return jsonify({"ok": False, "error": "Cart is empty."}), 400

    try:
        payment = Decimal(str(payment_raw))
        if payment <= 0:
            return jsonify({"ok": False, "error": "Payment must be greater than zero."}), 400
    except (InvalidOperation, TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid payment amount."}), 400

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN")
        items = []
        total = Decimal("0.00")
        for c in cart:
            pid = int(c["product_id"])
            qty = int(c["quantity"])
            if qty <= 0:
                raise ValueError("Quantity must be at least 1.")
            row = cur.execute(
                "SELECT * FROM products WHERE product_id=? AND is_active=1", (pid,)
            ).fetchone()
            if not row:
                raise ValueError(f"Product ID {pid} not found or inactive.")
            if qty > row["stock_quantity"]:
                raise ValueError(f"Insufficient stock for {row['name']}.")
            unit_price = Decimal(row["price"])
            line_total = (unit_price * qty).quantize(Decimal("0.01"))
            total += line_total
            items.append({
                "product_id": pid,
                "name": row["name"],
                "quantity": qty,
                "unit_price": unit_price,
                "line_total": line_total,
            })

        if payment < total:
            raise ValueError("Payment is less than the total amount.")

        change = (payment - total).quantize(Decimal("0.01"))
        now = datetime.now().isoformat(timespec="seconds")

        cur.execute(
            """INSERT INTO sales
               (user_id, sale_date, total_amount, amount_paid, change_amount, status)
               VALUES (?,?,?,?,?,?)""",
            (session["user_id"], now, str(total), str(payment), str(change), "completed")
        )
        sale_id = cur.lastrowid

        for it in items:
            cur.execute(
                """INSERT INTO sale_items
                   (sale_id, product_id, quantity, unit_price, line_total)
                   VALUES (?,?,?,?,?)""",
                (sale_id, it["product_id"], it["quantity"],
                 str(it["unit_price"]), str(it["line_total"]))
            )
            cur.execute(
                "UPDATE products SET stock_quantity = stock_quantity - ? WHERE product_id=?",
                (it["quantity"], it["product_id"])
            )
            cur.execute(
                """INSERT INTO stock_movements
                   (product_id, user_id, movement_type, quantity, movement_date, reference)
                   VALUES (?,?,?,?,?,?)""",
                (it["product_id"], session["user_id"], "sale",
                 -it["quantity"], now, f"Sale #{sale_id}")
            )

        conn.commit()
        return jsonify({
            "ok": True,
            "sale_id": sale_id,
            "sale_date": now,
            "cashier": session["username"],
            "items": [{
                "name": it["name"],
                "quantity": it["quantity"],
                "unit_price": str(it["unit_price"]),
                "line_total": str(it["line_total"]),
            } for it in items],
            "total": str(total),
            "payment": str(payment),
            "change": str(change),
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "error": str(e)}), 400
    finally:
        conn.close()

# ---------- Reports ----------
@app.route("/reports")
@login_required(role="admin")
def reports():
    start = request.args.get("start") or datetime.now().strftime("%Y-%m-%d")
    end = request.args.get("end") or datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    rows = conn.execute(
        """SELECT s.sale_id, s.sale_date, s.total_amount, s.amount_paid,
                  s.change_amount, u.username
           FROM sales s JOIN users u ON u.user_id=s.user_id
           WHERE date(s.sale_date) BETWEEN date(?) AND date(?)
           ORDER BY s.sale_id DESC""",
        (start, end)
    ).fetchall()
    totals = conn.execute(
        """SELECT COALESCE(SUM(CAST(total_amount AS REAL)),0) t, COUNT(*) c
           FROM sales WHERE date(sale_date) BETWEEN date(?) AND date(?)""",
        (start, end)
    ).fetchone()
    low = conn.execute(
        """SELECT * FROM products WHERE is_active=1 AND stock_quantity <= reorder_level
           ORDER BY stock_quantity ASC"""
    ).fetchall()
    conn.close()
    return render_template(
        "reports.html", rows=rows, totals=totals,
        low=low, start=start, end=end
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)