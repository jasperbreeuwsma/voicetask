"""
storage.py
Task storage using libsql — the same client library works against:
  - a local file (no env vars set) for development
  - a hosted Turso database (TURSO_DATABASE_URL + TURSO_AUTH_TOKEN set) in production

libsql's Python API mirrors sqlite3: connect(), execute(), commit(), fetchall().

Turso connections go over the network (Hrana protocol), which can hit
transient hiccups — especially right after a free-tier host wakes up from
being idle. _run() below retries once with a fresh connection if that happens,
instead of failing the whole request.
"""
import os
import time
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


def _run(fn, retries: int = 4, delay: float = 0.5):
    """Run fn(conn) against a fresh connection, retrying on transient network errors.
    Uses exponential backoff: 0.5s, 1s, 2s, 4s between attempts."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            conn = get_connection()
            return fn(conn)
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(delay * (2 ** attempt))
                continue
            raise last_err


def _row_to_dict(row) -> dict:
    return dict(zip(COLUMNS, row))


def init_db():
    def _op(conn):
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
    _run(_op)


def add_task(title: str, priority: str = "medium") -> int:
    def _op(conn):
        cur = conn.execute(
            "INSERT INTO tasks (title, priority, status, created_at) VALUES (?, ?, 'pending', ?) RETURNING id",
            (title, priority, datetime.now().isoformat(timespec="seconds")),
        )
        row = cur.fetchone()
        conn.commit()
        return row[0]
    return _run(_op)


def list_tasks(status: str = "all", priority: str = "all"):
    def _op(conn):
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
    return _run(_op)


def get_task(task_id: int):
    def _op(conn):
        row = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_dict(row) if row else None
    return _run(_op)


def find_task_by_title(fragment: str):
    def _op(conn):
        row = conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM tasks WHERE lower(title) LIKE ? ORDER BY id DESC LIMIT 1",
            (f"%{fragment.lower()}%",),
        ).fetchone()
        return _row_to_dict(row) if row else None
    return _run(_op)


def update_priority(task_id: int, priority: str) -> bool:
    def _op(conn):
        conn.execute("UPDATE tasks SET priority = ? WHERE id = ?", (priority, task_id))
        conn.commit()
        return True
    return _run(_op)


def complete_task(task_id: int) -> bool:
    def _op(conn):
        conn.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
        conn.commit()
        return True
    return _run(_op)


def delete_task(task_id: int) -> bool:
    def _op(conn):
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return True
    return _run(_op)


def rename_task(task_id: int, new_title: str) -> bool:
    def _op(conn):
        conn.execute("UPDATE tasks SET title = ? WHERE id = ?", (new_title, task_id))
        conn.commit()
        return True
    return _run(_op)
