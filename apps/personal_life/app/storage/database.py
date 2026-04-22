import sqlite3
from pathlib import Path
from typing import Any

import pymysql

from ..config import get_settings


APP_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = APP_DIR / "data"
SQLITE_DB_PATH = DATA_DIR / "personal_life.db"

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS quick_captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    due_date TEXT,
    priority INTEGER NOT NULL DEFAULT 2,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    scheduled_for TEXT NOT NULL,
    start_time TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_name TEXT NOT NULL,
    category TEXT NOT NULL,
    current_value INTEGER NOT NULL DEFAULT 0,
    as_of_date TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS asset_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL,
    asset_name TEXT NOT NULL,
    category TEXT NOT NULL,
    current_value INTEGER NOT NULL DEFAULT 0,
    snapshot_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (asset_id) REFERENCES assets(id)
);

CREATE TABLE IF NOT EXISTS routines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    frequency TEXT NOT NULL DEFAULT 'daily',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS routine_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routine_id INTEGER NOT NULL,
    checkin_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (routine_id, checkin_date),
    FOREIGN KEY (routine_id) REFERENCES routines(id)
);

CREATE TABLE IF NOT EXISTS profile_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    memory_key TEXT NOT NULL,
    value_text TEXT NOT NULL,
    value_type TEXT NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'medium',
    memory_kind TEXT NOT NULL DEFAULT 'preference',
    source TEXT NOT NULL DEFAULT 'imported',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (category, memory_key)
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    remind_on TEXT NOT NULL,
    remind_time TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',
    origin_type TEXT NOT NULL DEFAULT 'manual',
    origin_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    notified_at TEXT
);

CREATE TABLE IF NOT EXISTS assistant_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    message TEXT NOT NULL,
    interpreted_as TEXT,
    created_type TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""

MARIADB_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS quick_captures (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        capture_type VARCHAR(50) NOT NULL,
        content TEXT NOT NULL,
        source VARCHAR(100) NOT NULL DEFAULT 'manual',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(200) NOT NULL,
        details TEXT NOT NULL,
        due_date VARCHAR(20) NULL,
        priority INT NOT NULL DEFAULT 2,
        status VARCHAR(20) NOT NULL DEFAULT 'open',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schedules (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(200) NOT NULL,
        details TEXT NOT NULL,
        scheduled_for VARCHAR(20) NOT NULL,
        start_time VARCHAR(10) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assets (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        asset_name VARCHAR(200) NOT NULL,
        category VARCHAR(100) NOT NULL,
        current_value BIGINT NOT NULL DEFAULT 0,
        as_of_date VARCHAR(20) NULL,
        notes TEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS asset_snapshots (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        asset_id BIGINT NOT NULL,
        asset_name VARCHAR(200) NOT NULL,
        category VARCHAR(100) NOT NULL,
        current_value BIGINT NOT NULL DEFAULT 0,
        snapshot_date VARCHAR(20) NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_asset_snapshots_asset
            FOREIGN KEY (asset_id) REFERENCES assets(id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS routines (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        name VARCHAR(200) NOT NULL,
        description TEXT NOT NULL,
        frequency VARCHAR(50) NOT NULL DEFAULT 'daily',
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS routine_checkins (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        routine_id BIGINT NOT NULL,
        checkin_date VARCHAR(20) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'done',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uniq_routine_day (routine_id, checkin_date),
        CONSTRAINT fk_routine_checkins_routine
            FOREIGN KEY (routine_id) REFERENCES routines(id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS profile_memories (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        category VARCHAR(100) NOT NULL,
        memory_key VARCHAR(255) NOT NULL,
        value_text TEXT NOT NULL,
        value_type VARCHAR(50) NOT NULL,
        confidence VARCHAR(20) NOT NULL DEFAULT 'medium',
        memory_kind VARCHAR(50) NOT NULL DEFAULT 'preference',
        source VARCHAR(50) NOT NULL DEFAULT 'imported',
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uniq_profile_memory (category, memory_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reminders (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        title VARCHAR(200) NOT NULL,
        details TEXT NOT NULL,
        remind_on VARCHAR(20) NOT NULL,
        remind_time VARCHAR(10) NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
        origin_type VARCHAR(50) NOT NULL DEFAULT 'manual',
        origin_id BIGINT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        notified_at DATETIME NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assistant_conversations (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        role VARCHAR(20) NOT NULL,
        message TEXT NOT NULL,
        interpreted_as VARCHAR(30) NULL,
        created_type VARCHAR(30) NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
]


def initialize_database() -> None:
    settings = get_settings()
    if settings.db_backend == "mariadb":
        initialize_mariadb()
    else:
        initialize_sqlite()


def initialize_sqlite() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(SQLITE_DB_PATH) as connection:
        connection.executescript(SQLITE_SCHEMA)
        connection.commit()


def initialize_mariadb() -> None:
    settings = get_settings()
    bootstrap = pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )
    with bootstrap.cursor() as cursor:
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{settings.db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    bootstrap.close()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            for statement in MARIADB_SCHEMA:
                cursor.execute(statement)
        connection.commit()


def get_connection() -> Any:
    settings = get_settings()
    if settings.db_backend == "mariadb":
        return pymysql.connect(
            host=settings.db_host,
            port=settings.db_port,
            user=settings.db_user,
            password=settings.db_password,
            database=settings.db_name,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(SQLITE_DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def _adapt_query(query: str) -> str:
    settings = get_settings()
    if settings.db_backend == "mariadb":
        return query.replace("?", "%s")
    return query


def execute(query: str, parameters: tuple[Any, ...] = ()) -> int:
    adapted = _adapt_query(query)
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(adapted, parameters)
        connection.commit()
        return int(cursor.lastrowid or 0)


def execute_many(query: str, parameter_rows: list[tuple[Any, ...]]) -> None:
    if not parameter_rows:
        return
    adapted = _adapt_query(query)
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.executemany(adapted, parameter_rows)
        connection.commit()


def fetch_one(query: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    adapted = _adapt_query(query)
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(adapted, parameters)
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row) if not isinstance(row, dict) else row


def fetch_all(query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    adapted = _adapt_query(query)
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(adapted, parameters)
        rows = cursor.fetchall()
        return [dict(row) if not isinstance(row, dict) else row for row in rows]
