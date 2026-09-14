import os
import json
import psycopg2
import psycopg2.extras
from datetime import datetime
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_conn():
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        return conn
    else:
        raise Exception("DATABASE_URL not set")

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id SERIAL PRIMARY KEY,
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id SERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    remind_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sent INTEGER DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    qty REAL DEFAULT 0
                )
            """)
            conn.commit()

def dict_from_row(row, cursor):
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))

def dict_list_from_rows(rows, cursor):
    if not rows:
        return []
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in rows]

def add_task(title, description="", priority=3, due_date=None, tags="", subtasks=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tasks (title, description, priority, due_date, tags, subtasks) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (title, description, priority, due_date, tags, json.dumps(subtasks or []))
            )
            task_id = cur.fetchone()[0]
            conn.commit()
            return task_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def update_task(task_id, **kwargs):
    allowed = {"title", "description", "status", "priority", "subtasks", "due_date", "tags"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = datetime.now().isoformat()
    if "subtasks" in updates and isinstance(updates["subtasks"], list):
        updates["subtasks"] = json.dumps(updates["subtasks"])
    set_clause = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [task_id]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE tasks SET {set_clause} WHERE id = %s", values)
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_task(task_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
            return dict_from_row(row, cur)
    finally:
        conn.close()

def get_all_tasks(status=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM tasks WHERE status = %s ORDER BY priority, created_at", (status,))
            else:
                cur.execute("SELECT * FROM tasks ORDER BY priority, created_at")
            rows = cur.fetchall()
            return dict_list_from_rows(rows, cur)
    finally:
        conn.close()

def delete_task(task_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_stats():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tasks")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tasks WHERE status = 'done'")
            done = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tasks WHERE status = 'in_progress'")
            in_progress = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tasks WHERE status = 'pending'")
            pending = cur.fetchone()[0]
            return {"total": total, "done": done, "in_progress": in_progress, "pending": pending}
    finally:
        conn.close()

def add_reminder(text, remind_at):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reminders (text, remind_at) VALUES (%s, %s) RETURNING id",
                (text, remind_at)
            )
            reminder_id = cur.fetchone()[0]
            conn.commit()
            return reminder_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_pending_reminders():
    from datetime import timedelta, timezone
    local_tz = timezone(timedelta(hours=5))
    local_now = datetime.now(local_tz).replace(tzinfo=None)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM reminders WHERE sent = 0 AND remind_at <= %s",
                (local_now.isoformat(),)
            )
            rows = cur.fetchall()
            return dict_list_from_rows(rows, cur)
    finally:
        conn.close()

def mark_reminder_sent(reminder_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE reminders SET sent = 1 WHERE id = %s", (reminder_id,))
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_all_reminders():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM reminders ORDER BY remind_at")
            rows = cur.fetchall()
            return dict_list_from_rows(rows, cur)
    finally:
        conn.close()

def add_product(name, qty):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, qty FROM products WHERE name = %s", (name,))
            row = cur.fetchone()
            if row:
                existing_id, existing_qty = row[0], row[1]
                new_qty = existing_qty + qty
                cur.execute("UPDATE products SET qty = %s WHERE id = %s", (new_qty, existing_id))
            else:
                cur.execute("INSERT INTO products (name, qty) VALUES (%s, %s)", (name, qty))
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_product(name):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE name = %s", (name,))
            row = cur.fetchone()
            return dict_from_row(row, cur)
    finally:
        conn.close()

def update_product_qty(name, delta):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, qty FROM products WHERE name = %s", (name,))
            row = cur.fetchone()
            if row:
                existing_id, existing_qty = row[0], row[1]
                new_qty = existing_qty + delta
                if new_qty < 0:
                    new_qty = 0
                cur.execute("UPDATE products SET qty = %s WHERE id = %s", (new_qty, existing_id))
                conn.commit()
                return new_qty
            return None
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def list_products():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM products ORDER BY name")
            rows = cur.fetchall()
            return dict_list_from_rows(rows, cur)
    finally:
        conn.close()

def get_all_products():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM products ORDER BY name")
            rows = cur.fetchall()
            return dict_list_from_rows(rows, cur)
    finally:
        conn.close()
