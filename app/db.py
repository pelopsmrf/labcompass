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
LEADS_TO = os.environ.get("LEADS_TO") or "info@labcompass.ru"  # куда присылать заявки
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
    mit_number TEXT NOT NULL DEFAULT '', -- № в госреестре утверждённых типов СИ (25405-03)
    arshin_bad INTEGER NOT NULL DEFAULT 0, -- по последней записи «Аршина» — непригоден
    place TEXT NOT NULL DEFAULT '',  -- место установки, ответственный
    note TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0,
    updated TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS equipment_user ON equipment(user_id, archived);
CREATE TABLE IF NOT EXISTS vlk_indicators (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,               -- показатель (что определяем)
    method TEXT NOT NULL DEFAULT '',  -- методика (НД)
    range_text TEXT NOT NULL DEFAULT '', -- диапазон измерений
    units TEXT NOT NULL DEFAULT '',
    sigma_r REAL,                     -- σr, %
    sigma_rl REAL,                     -- σRл, %
    delta REAL,                       -- Δ методики, %
    delta_lab REAL,                   -- Δл лаборатории, %
    use_lab INTEGER NOT NULL DEFAULT 0, -- 1 — задан Δл, 0 — Δл = 0,84·Δ
    period TEXT NOT NULL DEFAULT '',  -- периодичность контроля (ключ vlk.PERIODS)
    note TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL DEFAULT (datetime('now')),
    updated TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS vlk_indicators_user ON vlk_indicators(user_id, archived);
CREATE TABLE IF NOT EXISTS vlk_results (
    id INTEGER PRIMARY KEY,
    indicator_id INTEGER NOT NULL REFERENCES vlk_indicators(id),
    run_date TEXT,                    -- дата контроля (ГГГГ-ММ-ДД)
    kind TEXT NOT NULL,               -- повт, прец, ок, доб
    x1 REAL, x2 REAL, c REAL, xd1 REAL, xd2 REAL,
    performer TEXT NOT NULL DEFAULT '', -- исполнитель
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS vlk_results_ind ON vlk_results(indicator_id);
CREATE TABLE IF NOT EXISTS stock (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL DEFAULT 'реактив', -- реактив, СО, другое
    name TEXT NOT NULL,
    grade TEXT NOT NULL DEFAULT '',     -- квалификация: хч, чда, осч
    standard TEXT NOT NULL DEFAULT '',  -- ГОСТ / ТУ / № ГСО по реестру
    maker TEXT NOT NULL DEFAULT '',     -- изготовитель
    lot TEXT NOT NULL DEFAULT '',       -- № партии (экземпляра)
    cert_value TEXT NOT NULL DEFAULT '', -- аттестованное значение ± погрешность (для СО)
    made_date TEXT,                     -- дата изготовления
    shelf_months INTEGER,               -- срок годности от изготовления, мес
    expiry_date TEXT,                   -- годен до
    received_date TEXT,                 -- дата получения
    opened_date TEXT,                   -- дата вскрытия
    qty TEXT NOT NULL DEFAULT '',       -- количество (текстом)
    place TEXT NOT NULL DEFAULT '',     -- место хранения
    ext_until TEXT,                     -- срок продлён до (по проверке пригодности)
    ext_doc TEXT NOT NULL DEFAULT '',   -- основание продления: № протокола
    note TEXT NOT NULL DEFAULT '',
    archived INTEGER NOT NULL DEFAULT 0, -- израсходован / списан
    updated TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS stock_user ON stock(user_id, archived);
CREATE TABLE IF NOT EXISTS solutions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,                 -- что приготовлено
    conc TEXT NOT NULL DEFAULT '',      -- концентрация
    volume TEXT NOT NULL DEFAULT '',    -- объём
    source_id INTEGER REFERENCES stock(id), -- из чего (запись склада)
    source_text TEXT NOT NULL DEFAULT '', -- из чего (текстом, если нет на складе)
    method TEXT NOT NULL DEFAULT '',    -- методика (НД)
    prep_date TEXT NOT NULL,            -- дата приготовления
    shelf_days INTEGER,                 -- срок хранения, сут
    expiry_date TEXT,                   -- годен до
    performer TEXT NOT NULL DEFAULT '', -- приготовил
    note TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS solutions_user ON solutions(user_id, prep_date);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    created TEXT NOT NULL DEFAULT (datetime('now')),
    source TEXT NOT NULL,            -- check (самопроверка), contact (форма на главной)
    email TEXT NOT NULL,
    org TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    score INTEGER,                   -- процент готовности (для самопроверки)
    details TEXT NOT NULL DEFAULT '', -- текст разбора, как в письме
    ip_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'новая'
);
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


# Столбцы, добавленные после запуска: в старой базе их дописываем
MIGRATIONS = {
    "equipment": [("mit_number", "TEXT NOT NULL DEFAULT ''"), ("arshin_bad", "INTEGER NOT NULL DEFAULT 0")],
}


def init():
    with db() as con:
        con.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            for name, decl in cols:
                if name not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
