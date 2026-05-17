import os
import sqlite3
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "nag_bot.db"


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
            completed_at TIMESTAMP,
            assigned_to INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    _migrate_db(conn)
    conn.close()


def _migrate_db(conn):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "assigned_to" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN assigned_to INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE tasks ADD COLUMN created_by INTEGER NOT NULL DEFAULT 0")
        conn.commit()


def backfill_tasks(arushi_id: int, ankush_id: int):
    conn = get_connection()
    conn.execute(
        "UPDATE tasks SET assigned_to = ?, created_by = ? WHERE assigned_to = 0 AND created_by = 0",
        (ankush_id, arushi_id),
    )
    conn.commit()
    conn.close()


def add_task(description: str, deadline: datetime, assigned_to: int, created_by: int) -> dict:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO tasks (description, deadline, assigned_to, created_by) VALUES (?, ?, ?, ?)",
        (description, deadline, assigned_to, created_by),
    )
    task_id = cursor.lastrowid
    conn.commit()
    task = dict(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
    conn.close()
    return task


def get_open_tasks(assigned_to: int = None, created_by: int = None) -> list[dict]:
    conn = get_connection()
    query = "SELECT * FROM tasks WHERE completed = 0"
    params = []
    if assigned_to is not None:
        query += " AND assigned_to = ?"
        params.append(assigned_to)
    if created_by is not None:
        query += " AND created_by = ?"
        params.append(created_by)
    query += " ORDER BY deadline ASC"
    rows = conn.execute(query, params).fetchall()
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


def find_task_by_description(query: str, assigned_to: int = None) -> dict | None:
    conn = get_connection()
    sql = "SELECT * FROM tasks WHERE completed = 0"
    params = []
    if assigned_to is not None:
        sql += " AND assigned_to = ?"
        params.append(assigned_to)
    sql += " ORDER BY deadline ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    query_lower = query.lower().strip()
    for row in rows:
        if query_lower in row["description"].lower():
            return dict(row)
    return None
