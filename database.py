import os
import secrets
import sqlite3
import string
from datetime import datetime, timedelta
from pathlib import Path

from encryption import encrypt, decrypt

PAIRING_CODE_TTL = timedelta(minutes=15)
PAIRING_CODE_ALPHABET = string.ascii_uppercase + string.digits

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
        CREATE TABLE IF NOT EXISTS couples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nagger_chat_id INTEGER UNIQUE NOT NULL,
            naggee_chat_id INTEGER UNIQUE,
            nagger_name TEXT,
            naggee_name TEXT,
            tone TEXT NOT NULL DEFAULT 'default',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pairing_codes (
            code TEXT PRIMARY KEY,
            couple_id INTEGER NOT NULL REFERENCES couples(id) ON DELETE CASCADE,
            expires_at TIMESTAMP NOT NULL
        )
    """)
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
            created_by INTEGER NOT NULL DEFAULT 0,
            couple_id INTEGER NOT NULL DEFAULT 0 REFERENCES couples(id)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_couple_completed ON tasks(couple_id, completed)"
    )
    conn.commit()
    _migrate_db(conn)
    conn.close()


def _migrate_db(conn):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()]
    if "assigned_to" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN assigned_to INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE tasks ADD COLUMN created_by INTEGER NOT NULL DEFAULT 0")
    if "couple_id" not in columns:
        conn.execute(
            "ALTER TABLE tasks ADD COLUMN couple_id INTEGER NOT NULL DEFAULT 0 REFERENCES couples(id)"
        )
    conn.commit()


def _decrypt_task(row) -> dict:
    t = dict(row)
    t["description"] = decrypt(t["description"])
    return t


def _decrypt_couple(row) -> dict:
    d = dict(row)
    d["nagger_name"] = decrypt(d.get("nagger_name"))
    d["naggee_name"] = decrypt(d.get("naggee_name"))
    return d


def add_task(
    description: str,
    deadline: datetime,
    assigned_to: int,
    created_by: int,
    couple_id: int = 0,
) -> dict:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO tasks (description, deadline, assigned_to, created_by, couple_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (encrypt(description), deadline, assigned_to, created_by, couple_id),
    )
    task_id = cursor.lastrowid
    conn.commit()
    task = _decrypt_task(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
    conn.close()
    return task


def get_open_tasks(
    couple_id: int = None,
    assigned_to: int = None,
    created_by: int = None,
) -> list[dict]:
    conn = get_connection()
    query = "SELECT * FROM tasks WHERE completed = 0"
    params = []
    if couple_id is not None:
        query += " AND couple_id = ?"
        params.append(couple_id)
    if assigned_to is not None:
        query += " AND assigned_to = ?"
        params.append(assigned_to)
    if created_by is not None:
        query += " AND created_by = ?"
        params.append(created_by)
    query += " ORDER BY deadline ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_decrypt_task(r) for r in rows]


def get_tasks_needing_reminder(couple_id: int = None) -> list[dict]:
    conn = get_connection()
    query = "SELECT * FROM tasks WHERE completed = 0 AND reminders_sent < 3"
    params = []
    if couple_id is not None:
        query += " AND couple_id = ?"
        params.append(couple_id)
    query += " ORDER BY deadline ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_decrypt_task(r) for r in rows]


def mark_reminder_sent(task_id: int, couple_id: int = None):
    conn = get_connection()
    if couple_id is not None:
        conn.execute(
            "UPDATE tasks SET reminders_sent = reminders_sent + 1 WHERE id = ? AND couple_id = ?",
            (task_id, couple_id),
        )
    else:
        conn.execute(
            "UPDATE tasks SET reminders_sent = reminders_sent + 1 WHERE id = ?",
            (task_id,),
        )
    conn.commit()
    conn.close()


def complete_task(task_id: int, couple_id: int = None):
    conn = get_connection()
    if couple_id is not None:
        conn.execute(
            "UPDATE tasks SET completed = 1, completed_at = ? WHERE id = ? AND couple_id = ?",
            (datetime.now(), task_id, couple_id),
        )
    else:
        conn.execute(
            "UPDATE tasks SET completed = 1, completed_at = ? WHERE id = ?",
            (datetime.now(), task_id),
        )
    conn.commit()
    conn.close()


def create_couple(nagger_chat_id: int, nagger_name: str | None = None) -> int:
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO couples (nagger_chat_id, nagger_name) VALUES (?, ?)",
        (nagger_chat_id, encrypt(nagger_name)),
    )
    conn.commit()
    couple_id = cursor.lastrowid
    conn.close()
    return couple_id


def get_couple_for_chat(chat_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM couples WHERE nagger_chat_id = ? OR naggee_chat_id = ?",
        (chat_id, chat_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    row = _decrypt_couple(row)
    is_nagger = row["nagger_chat_id"] == chat_id
    return {
        "couple_id": row["id"],
        "role": "nagger" if is_nagger else "naggee",
        "self_chat_id": chat_id,
        "self_name": row["nagger_name"] if is_nagger else row["naggee_name"],
        "partner_chat_id": row["naggee_chat_id"] if is_nagger else row["nagger_chat_id"],
        "partner_name": row["naggee_name"] if is_nagger else row["nagger_name"],
        "tone": row["tone"],
        "paired": row["naggee_chat_id"] is not None,
    }


def _generate_pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(6))


def create_pairing_code(couple_id: int) -> str:
    conn = get_connection()
    conn.execute("DELETE FROM pairing_codes WHERE couple_id = ?", (couple_id,))
    expires_at = datetime.now() + PAIRING_CODE_TTL
    for _ in range(10):
        code = _generate_pairing_code()
        try:
            conn.execute(
                "INSERT INTO pairing_codes (code, couple_id, expires_at) VALUES (?, ?, ?)",
                (code, couple_id, expires_at),
            )
            conn.commit()
            conn.close()
            return code
        except sqlite3.IntegrityError:
            continue
    conn.close()
    raise RuntimeError("Could not generate a unique pairing code")


def consume_pairing_code(code: str, naggee_chat_id: int, naggee_name: str | None = None) -> int | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT couple_id, expires_at FROM pairing_codes WHERE code = ?",
        (code.upper(),),
    ).fetchone()
    if not row:
        conn.close()
        return None
    expires_at = row["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at < datetime.now():
        conn.execute("DELETE FROM pairing_codes WHERE code = ?", (code.upper(),))
        conn.commit()
        conn.close()
        return None
    couple_id = row["couple_id"]
    couple = conn.execute("SELECT * FROM couples WHERE id = ?", (couple_id,)).fetchone()
    if not couple or couple["nagger_chat_id"] == naggee_chat_id:
        conn.close()
        return None
    conn.execute(
        "UPDATE couples SET naggee_chat_id = ?, naggee_name = ? WHERE id = ?",
        (naggee_chat_id, encrypt(naggee_name), couple_id),
    )
    conn.execute("DELETE FROM pairing_codes WHERE couple_id = ?", (couple_id,))
    conn.commit()
    conn.close()
    return couple_id


def delete_couple(couple_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM tasks WHERE couple_id = ?", (couple_id,))
    conn.execute("DELETE FROM pairing_codes WHERE couple_id = ?", (couple_id,))
    conn.execute("DELETE FROM couples WHERE id = ?", (couple_id,))
    conn.commit()
    conn.close()


def set_tone(couple_id: int, tone: str):
    conn = get_connection()
    conn.execute("UPDATE couples SET tone = ? WHERE id = ?", (tone, couple_id))
    conn.commit()
    conn.close()


def get_task(task_id: int) -> dict | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return _decrypt_task(row) if row else None


def find_task_by_description(
    query: str,
    couple_id: int = None,
    assigned_to: int = None,
) -> dict | None:
    conn = get_connection()
    sql = "SELECT * FROM tasks WHERE completed = 0"
    params = []
    if couple_id is not None:
        sql += " AND couple_id = ?"
        params.append(couple_id)
    if assigned_to is not None:
        sql += " AND assigned_to = ?"
        params.append(assigned_to)
    sql += " ORDER BY deadline ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    query_lower = query.lower().strip()
    for row in rows:
        task = _decrypt_task(row)
        if query_lower in task["description"].lower():
            return task
    return None
