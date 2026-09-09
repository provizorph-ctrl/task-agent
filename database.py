import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

DB_PATH = "tasks.db"

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 3,
                subtasks TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                due_date TEXT,
                tags TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                remind_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent INTEGER DEFAULT 0
            )
        """)
        conn.commit()

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def add_task(title, description="", priority=3, due_date=None, tags="", subtasks=None):
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO tasks (title, description, priority, due_date, tags, subtasks) VALUES (?, ?, ?, ?, ?, ?)",
            (title, description, priority, due_date, tags, json.dumps(subtasks or []))
        )
        conn.commit()
        return cursor.lastrowid

def update_task(task_id, **kwargs):
    allowed = {"title", "description", "status", "priority", "subtasks", "due_date", "tags"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = datetime.now().isoformat()
    if "subtasks" in updates and isinstance(updates["subtasks"], list):
        updates["subtasks"] = json.dumps(updates["subtasks"])
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [task_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", values)
        conn.commit()

def get_task(task_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

def get_all_tasks(status=None):
    with get_conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM tasks WHERE status = ? ORDER BY priority, created_at", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tasks ORDER BY priority, created_at").fetchall()
        return [dict(r) for r in rows]

def delete_task(task_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()

def get_stats():
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'done'").fetchone()[0]
        in_progress = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'in_progress'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'pending'").fetchone()[0]
        return {"total": total, "done": done, "in_progress": in_progress, "pending": pending}

def add_reminder(text, remind_at):
    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO reminders (text, remind_at) VALUES (?, ?)",
            (text, remind_at)
        )
        conn.commit()
        return cursor.lastrowid

def get_pending_reminders():
    from datetime import timedelta, timezone
    local_tz = timezone(timedelta(hours=5))
    local_now = datetime.now(local_tz).replace(tzinfo=None)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE sent = 0 AND remind_at <= ?",
            (local_now.isoformat(),)
        ).fetchall()
        return [dict(r) for r in rows]

def mark_reminder_sent(reminder_id):
    with get_conn() as conn:
        conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
        conn.commit()

def get_all_reminders():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM reminders ORDER BY remind_at").fetchall()
        return [dict(r) for r in rows]
