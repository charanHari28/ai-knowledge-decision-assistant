"""SQLite access. A new connection per request keeps things simple and thread-safe."""
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from app.config import BASE_DIR, settings


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    schema = (BASE_DIR / "schema.sql").read_text()
    with get_conn() as conn:
        conn.executescript(schema)
