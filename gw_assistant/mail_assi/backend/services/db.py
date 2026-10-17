from __future__ import annotations

import os

import pymysql
from pymysql.connections import Connection
from pymysql.cursors import DictCursor


DB_HOST = os.getenv("MAIL_ASSI_DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("MAIL_ASSI_DB_PORT", "3306"))
DB_USER = os.getenv("MAIL_ASSI_DB_USER", "root")
DB_PASSWORD = os.getenv("MAIL_ASSI_DB_PASSWORD", "")
DB_NAME = os.getenv("MAIL_ASSI_DB_NAME", "mail_assi")


def connect(database: str | None = DB_NAME) -> Connection:
    kwargs = {
        "host": DB_HOST,
        "port": DB_PORT,
        "user": DB_USER,
        "password": DB_PASSWORD,
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": True,
    }
    if database is not None:
        kwargs["database"] = database
    return pymysql.connect(**kwargs)


def ensure_column(cursor: DictCursor, table_name: str, column_name: str, definition: str) -> None:
    cursor.execute(f"SHOW COLUMNS FROM `{table_name}` LIKE %s", (column_name,))
    if cursor.fetchone() is None:
        cursor.execute(f"ALTER TABLE `{table_name}` ADD COLUMN {definition}")


def ensure_database() -> None:
    with connect(database=None) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )

    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    sender VARCHAR(255) NOT NULL,
                    subject VARCHAR(255) NOT NULL,
                    body TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    action VARCHAR(20) NOT NULL,
                    reason TEXT NOT NULL,
                    draft_reply TEXT NOT NULL,
                    created_at VARCHAR(40) NOT NULL
                ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                """
            )

            ensure_column(cursor, "messages", "tone", "tone VARCHAR(20) NOT NULL DEFAULT 'balanced'")
            ensure_column(cursor, "messages", "draft_source", "draft_source VARCHAR(20) NOT NULL DEFAULT 'rule'")
