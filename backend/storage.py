"""
storage.py
Task storage using libsql — the same client library works against:
  - a local file (no env vars set) for development
  - a hosted Turso database (TURSO_DATABASE_URL + TURSO_AUTH_TOKEN set) in production

libsql's Python API mirrors sqlite3: connect(), execute(), commit(), fetchall().

Turso connections go over the network (Hrana protocol), which can hit
transient hiccups. _run() below reuses a cached connection and retries with
backoff if something goes wrong, instead of failing the whole request.

due_date is stored as a plain "YYYY-MM-DD" date (no time-of-day, for
simplicity). recurrence is one of: null, "daily", "weekly", "monthly".
When a recurring task is completed, the next occurrence is created
automatically with due_date advanced accordingly.
"""
import calendar
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import libsql

LOCAL_DB_PATH = Path(__file__).parent / "tasks.db"

COLUMNS = ["id", "title", "priority", "status", "created_at", "due_date", "recurrence", "starred", "my_day"]

_conn = None


def get_connection():
    url = os.environ.get("TURSO_DATABASE_URL")
    token = os.environ.get("TURSO_AUTH_TOKEN")
    if url:
        return libsql.connect(database=url, auth_token=token)
    return libsql.connect(database=str(LOCAL_DB_PATH))


def _get_conn():
    global _conn
    if _conn is None:
        _conn = get_connection()
    return _conn


def _reset_conn():
    global _conn
    _conn = None


def _run(fn, retries: int = 4, delay: float = 0.5):
    """Run fn(conn) reusing a cached connection, reconnecting and retrying
    with exponential backoff (0.5s, 1s, 2s, 4s) if something goes wrong."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            conn = _get_conn()
            return fn(conn)
        except Exception as e:
            last_err = e
            _reset_conn()  # force a fresh connection on the next attempt
            if attempt < retries:
                time.sleep(delay * (2 ** attempt))
                continue
            raise last_err


def _row_to_dict(row) -> dict:
    d = dict(zip(COLUMNS, row))
    if "starred" in d:
        d["starred"] = bool(d["starred"])
    if "my_day" in d:
        d["my_day"] = bool(d["my_day"])
    return d


def init_db():
    def _op(conn):
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                due_date TEXT,
                recurrence TEXT,
                starred INTEGER NOT NULL DEFAULT 0,
                my_day INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        # Migration for tables created before these columns existed.
        # SQLite/libsql has no "ADD COLUMN IF NOT EXISTS", so just ignore
        # the error if the column is already there.
        for stmt in (
            "ALTER TABLE tasks ADD COLUMN due_date TEXT",
            "ALTER TABLE tasks ADD COLUMN recurrence TEXT",
            "ALTER TABLE tasks ADD COLUMN starred INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN my_day INTEGER NOT NULL DEFAULT 0",
        ):
            try:
                conn.execute(stmt)
            except Exception:
                pass
        conn.commit()
    _run(_op)


def _next_due_date(due_date_str: str, recurrence: str) -> str:
    d = date.fromisoformat(due_date_str)
    if recurrence == "daily":
        d = d + timedelta(days=1)
    elif recurrence == "weekly":
        d = d + timedelta(days=7)
    elif recurrence == "monthly":
        month = d.month + 1
        year = d.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        day = min(d.day, calendar.monthrange(year, month)[1])
        d = date(year, month, day)
    return d.isoformat()


def add_task(title: str, priority: str = "medium", due_date: str = None, recurrence: str = None) -> int:
    def _op(conn):
        cur = conn.execute(
            """INSERT INTO tasks (title, priority, status, created_at, due_date, recurrence)
               VALUES (?, ?, 'pending', ?, ?, ?) RETURNING id""",
            (title, priority, datetime.now().isoformat(timespec="seconds"), due_date, recurrence),
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
        # Overdue/due-today first, then by priority, then soonest due date, then id.
        query += """
            ORDER BY
                CASE WHEN due_date IS NOT NULL AND date(due_date) <= date('now') AND status != 'done' THEN 0 ELSE 1 END,
                CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
                due_date,
                id
        """
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


def update_due_date(task_id: int, due_date: str) -> bool:
    def _op(conn):
        conn.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (due_date, task_id))
        conn.commit()
        return True
    return _run(_op)


def complete_task(task_id: int) -> bool:
    """Marks a task done. If it's recurring, also creates the next occurrence."""
    def _op(conn):
        row = conn.execute(
            f"SELECT {', '.join(COLUMNS)} FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return False
        task = _row_to_dict(row)

        conn.execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))

        if task["recurrence"] and task["due_date"]:
            next_due = _next_due_date(task["due_date"], task["recurrence"])
            conn.execute(
                """INSERT INTO tasks (title, priority, status, created_at, due_date, recurrence)
                   VALUES (?, ?, 'pending', ?, ?, ?)""",
                (task["title"], task["priority"], datetime.now().isoformat(timespec="seconds"),
                 next_due, task["recurrence"]),
            )

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


def set_starred(task_id: int, starred: bool) -> bool:
    def _op(conn):
        conn.execute("UPDATE tasks SET starred = ? WHERE id = ?", (1 if starred else 0, task_id))
        conn.commit()
        return True
    return _run(_op)


def set_my_day(task_id: int, my_day: bool) -> bool:
    def _op(conn):
        conn.execute("UPDATE tasks SET my_day = ? WHERE id = ?", (1 if my_day else 0, task_id))
        conn.commit()
        return True
    return _run(_op)


# ---------- chat message history ----------

def add_message(role: str, content: str) -> int:
    def _op(conn):
        cur = conn.execute(
            "INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?) RETURNING id",
            (role, content, datetime.now().isoformat(timespec="seconds")),
        )
        row = cur.fetchone()
        conn.commit()
        return row[0]
    return _run(_op)


def get_messages(limit: int = 40):
    def _op(conn):
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        rows = list(reversed(rows))
        return [dict(zip(["id", "role", "content", "created_at"], r)) for r in rows]
    return _run(_op)


def clear_messages() -> bool:
    def _op(conn):
        conn.execute("DELETE FROM messages")
        conn.commit()
        return True
    return _run(_op)
