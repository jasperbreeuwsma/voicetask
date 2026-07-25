"""
storage.py
Task storage using libsql — the same client library works against:
  - a local file (no env vars set) for development
  - a hosted Turso database (TURSO_DATABASE_URL + TURSO_AUTH_TOKEN set) in production

libsql's Python API mirrors sqlite3: connect(), execute(), commit(), fetchall().
"""
import os
from datetime import datetime
from pathlib import Path

import libsql

LOCAL_DB_PATH = Path(__file__).parent / "tasks.db"

COLUMNS = ["id", "title", "priority", "status", "created_at"]


def get_connection():
    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")
    if url:
        return libsql.connect(database=url, auth_token=token)
    return libsql.connect(database=str(LOCAL_DB_PATH))


def _row_to_dict(row) -> dict:
    return dict(zip(COLUMNS, row))


def init_db():
    conn = get_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def add_task(title: str, priority: str = "medium") -> int:
    conn = get_connection()
    conn.execute(
        "INSERT INTO tasks (title, priority, status, created_at) VALUES (?, ?, 'pending', ?)",
        (title, priority, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM tasks ORDER BY id DESC LIMIT 1").fetchone()
    return row[0]


def list_tasks(status: str = "all", priority: str = "all"):
    conn = get_connection()
    query = f"SELECT {', '.join(COLUMNS)} FROM tasks WHERE 1=1"
    params = []
    if status != "all":
        query += " AND status = ?"
        params.append(status)
    if priority != "all":
        query += " AND priority = ?"
        params.append(priority)
    query += " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_task(task_id: int):
    conn = get_connection()
    row = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_dict(row) if row else None


def find_task_by_title(fragment: str):
    conn = get_connection()
    row = conn.execute(
        f"SELECT {', '.join(COLUMNS)} FROM tasks WHERE lower(title) LIKE ? ORDER BY id DESC LIMIT 1",
        (f"%{fragment.lower()}%",),
    ).fetchone()
    return _row_to_dict(row) if row else None


def update_priority(task_id: int, priority: str) -> bool:
    conn = get_connection()
    conn.execute("UPDATE tasks SET priority = ? WHERE id = ?", (priority, task_id))
    conn.commit()
    return True


def complete_task(task_id: int) -> bool:
    conn = get_connection()
    conn.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
    conn.commit()
    return True


def delete_task(task_id: int) -> bool:
    conn = get_connection()
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    return True


def rename_task(task_id: int, new_title: str) -> bool:
    conn = get_connection()
    conn.execute("UPDATE tasks SET title = ? WHERE id = ?", (new_title, task_id))
    conn.commit()
    return True
