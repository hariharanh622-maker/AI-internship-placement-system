from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database" / "placement.db"


def get_db():
    DATABASE_PATH.parent.mkdir(exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _add_columns(db, table, columns):
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db():
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('student', 'company', 'admin')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                department TEXT NOT NULL DEFAULT 'Not specified',
                cgpa REAL NOT NULL DEFAULT 0,
                skills TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS companies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                company_name TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT 'Not specified',
                package TEXT NOT NULL DEFAULT 'Not specified',
                eligibility_criteria TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS internships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                location TEXT NOT NULL,
                stipend TEXT NOT NULL DEFAULT 'Unpaid',
                deadline TEXT NOT NULL,
                role TEXT,
                duration TEXT,
                eligibility_criteria TEXT,
                technologies TEXT,
                package TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (company_id) REFERENCES users (id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                internship_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pending'
                    CHECK (status IN ('Pending', 'Shortlisted', 'Rejected', 'Selected')),
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (internship_id, student_id),
                FOREIGN KEY (internship_id) REFERENCES internships (id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES users (id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                interview_date TEXT NOT NULL,
                result TEXT NOT NULL DEFAULT 'Scheduled',
                FOREIGN KEY (application_id) REFERENCES applications (id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS placements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                company_id INTEGER NOT NULL,
                package TEXT NOT NULL,
                joining_date TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (company_id) REFERENCES users (id) ON DELETE CASCADE
            );
            """
        )
        _add_columns(
            db,
            "internships",
            {
                "role": "TEXT",
                "duration": "TEXT",
                "eligibility_criteria": "TEXT",
                "technologies": "TEXT",
                "package": "TEXT",
            },
        )
        application_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='applications'"
        ).fetchone()["sql"]
        if "Selected" not in application_sql:
            db.execute("ALTER TABLE applications RENAME TO applications_legacy")
            db.executescript(
                """
                CREATE TABLE applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    internship_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pending'
                        CHECK (status IN ('Pending', 'Shortlisted', 'Rejected', 'Selected')),
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (internship_id, student_id),
                    FOREIGN KEY (internship_id) REFERENCES internships (id) ON DELETE CASCADE,
                    FOREIGN KEY (student_id) REFERENCES users (id) ON DELETE CASCADE
                );
                INSERT INTO applications (id, internship_id, student_id, status, applied_at)
                    SELECT id, internship_id, student_id, status, applied_at
                    FROM applications_legacy;
                DROP TABLE applications_legacy;
                """
            )
        db.execute(
            """INSERT OR IGNORE INTO students (user_id)
               SELECT id FROM users WHERE role = 'student'"""
        )
        db.execute(
            """INSERT OR IGNORE INTO companies (user_id, company_name)
               SELECT id, name FROM users WHERE role = 'company'"""
        )
