import sqlite3
import os

import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.environ.get(
    "DB_PATH", os.path.join(BASE_DIR, "data", "mini_telegram_encrypted.db")
)

SCHEMA_PATH = os.environ.get("SCHEMA_PATH", os.path.join(BASE_DIR, "schema.sql"))


def get_db():
    """Open a database connection with row_factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Initialize the database from schema.sql."""
    conn = get_db()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print("Database initialized.")
