import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "nag_bot.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            deadline TIMESTAMP NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reminders_sent INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            completed_at TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def add_task(description: str, deadline: datetime) -> dict:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO tasks (description, deadline) VALUES (?, ?)",
        (description, deadline),
    )
    task_id = cursor.lastrowid
    conn.commit()
    task = dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
    conn.close()
    return task


def get_open_tasks() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE completed = 0 ORDER BY deadline ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tasks_needing_reminder() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE completed = 0 AND reminders_sent < 3 ORDER BY deadline ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_reminder_sent(task_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE tasks SET reminders_sent = reminders_sent + 1 WHERE id = ?",
        (task_id,),
    )
    conn.commit()
    conn.close()


def complete_task(task_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE tasks SET completed = 1, completed_at = ? WHERE id = ?",
        (datetime.now(), task_id),
    )
    conn.commit()
    conn.close()


def find_task_by_description(query: str) -> dict | None:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE completed = 0 ORDER BY deadline ASC"
    ).fetchall()
    conn.close()
    query_lower = query.lower().strip()
    for row in rows:
        if query_lower in row["description"].lower():
            return dict(row)
    return None
