"""Настройки и база данных SQLite (один файл, резервная копия — простым копированием)."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).parent


def load_env(path=HERE / ".env"):
    """Читает .env (строки КЛЮЧ=значение) в os.environ, не перезаписывая уже заданное."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DB_PATH = os.environ.get("DB_PATH", str(HERE / "app.db"))
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
FREE_LIMIT = int(os.environ.get("FREE_LIMIT", "10"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    org TEXT NOT NULL DEFAULT '',
    is_admin INTEGER NOT NULL DEFAULT 0,
    paid_until TEXT,                -- подписка до этой даты (ГГГГ-ММ-ДД), NULL — бесплатный тариф
    remind INTEGER NOT NULL DEFAULT 1,
    created TEXT NOT NULL DEFAULT (datetime('now')),
    last_login TEXT
);
CREATE TABLE IF NOT EXISTS login_codes (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS login_codes_email ON login_codes(email);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS equipment (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,              -- наименование, тип/модель
    kind TEXT NOT NULL DEFAULT 'СИ', -- СИ, ИО, ВО
    serial TEXT NOT NULL DEFAULT '', -- заводской номер
    inv_no TEXT NOT NULL DEFAULT '', -- инвентарный номер
    service TEXT NOT NULL DEFAULT 'поверка', -- поверка, калибровка, аттестация, ТО
    last_date TEXT,                  -- дата последней поверки/калибровки/аттестации
    interval_months INTEGER,         -- межповерочный (межкалибровочный) интервал
    next_date TEXT,                  -- срок следующей
    doc_no TEXT NOT NULL DEFAULT '', -- № свидетельства / записи во ФГИС «Аршин» / аттестата
    place TEXT NOT NULL DEFAULT '',  -- место установки, ответственный
    note TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0,
    updated TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS equipment_user ON equipment(user_id, archived);
"""


def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


@contextmanager
def db():
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init():
    with db() as con:
        con.executescript(SCHEMA)
