from database import get_connection, init_db
from werkzeug.security import generate_password_hash

def seed():
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    users = [
        ("admin", generate_password_hash("admin123"), "admin"),
        ("cashier", generate_password_hash("cashier123"), "cashier"),
    ]
    for u in users:
        cur.execute(
            "INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?,?,?)", u
        )

    products = [
        ("P001", "Ballpen (Black)", "15.00", 100, 10),
        ("P002", "Notebook 80 leaves", "25.50", 50, 10),
        ("P003", "Pencil No. 2", "8.00", 200, 20),
        ("P004", "Eraser", "5.00", 150, 20),
        ("P005", "Ruler 12in", "12.00", 80, 10),
        ("P006", "Correction Tape", "35.00", 30, 5),
        ("P007", "Highlighters (Set)", "60.00", 25, 5),
        ("P008", "Glue Stick", "18.00", 40, 8),
        ("P009", "Scissors", "45.00", 15, 5),
        ("P010", "Calculator", "350.00", 8, 3),
    ]
    for p in products:
        cur.execute(
            """INSERT OR IGNORE INTO products
               (product_code, name, price, stock_quantity, reorder_level)
               VALUES (?,?,?,?,?)""", p
        )

    conn.commit()
    conn.close()
    print("Seeded. Login: admin/admin123 or cashier/cashier123")

if __name__ == "__main__":
    seed()