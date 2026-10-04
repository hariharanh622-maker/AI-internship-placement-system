from getpass import getpass

from werkzeug.security import generate_password_hash

from database import get_db, init_db

init_db()
name = input("Admin name: ").strip()
email = input("Admin email: ").strip()
password = getpass("Admin password (6+ characters): ")

if not name or not email or len(password) < 6:
    raise SystemExit("Name, email, and a password of at least 6 characters are required.")

with get_db() as db:
    db.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
        (name, email, generate_password_hash(password)),
    )

print("Admin account created. You can now log in from the website.")
