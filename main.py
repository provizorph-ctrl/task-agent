import os
import json
import asyncio
import threading
import logging
from flask import Flask, render_template, request, jsonify
from database import init_db, add_task, get_task, get_all_tasks, update_task, delete_task, get_stats
from llm import plan_task, analyze_progress, summarize_day
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)
flask_app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")

@flask_app.template_filter('fromjson')
def fromjson_filter(s):
    try:
        return json.loads(s) if isinstance(s, str) else s
    except:
        return []

@flask_app.route("/")
def index():
    tasks = get_all_tasks()
    stats = get_stats()
    return render_template("index.html", tasks=tasks, stats=stats)

@flask_app.route("/api/tasks", methods=["GET"])
def api_tasks():
    status = request.args.get("status")
    return jsonify(get_all_tasks(status))

@flask_app.route("/api/tasks", methods=["POST"])
def api_create_task():
    data = request.json
    title = data.get("title", "")
    description = data.get("description", "")
    priority = data.get("priority", 3)
    subtasks = plan_task(title, description)
    task_id = add_task(title, description, priority, subtasks=subtasks)
    return jsonify({"id": task_id, "subtasks": subtasks})

@flask_app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def api_update_task(task_id):
    data = request.json
    update_task(task_id, **data)
    return jsonify({"ok": True})

@flask_app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_delete_task(task_id):
    delete_task(task_id)
    return jsonify({"ok": True})

@flask_app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        await update.message.reply_text("Access denied.")
        return
    await update.message.reply_text(
        "Task Manager ready!\n\n"
        "Commands:\n"
        "/plan <task> - plan a task\n"
        "/list - list tasks\n"
        "/done <id> - mark done\n"
        "/progress <id> - analyze progress\n"
        "/stats - statistics\n"
        "/report - daily report\n"
        "/delete <id> - delete task"
    )

async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    task_text = " ".join(context.args) if context.args else None
    if not task_text:
        await update.message.reply_text("Specify task: /plan write report")
        return
    await update.message.reply_text("Planning task...")
    try:
        subtasks = plan_task(task_text)
        task_id = add_task(task_text, subtasks=subtasks)
        msg = f"Task #{task_id}: {task_text}\n\nSubtasks:\n"
        for i, st in enumerate(subtasks, 1):
            msg += f"  {i}. {st['title']} (priority: {st.get('priority', 3)})\n"
        keyboard = [[InlineKeyboardButton("Start", callback_data=f"start_{task_id}")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Plan error: {e}")
        await update.message.reply_text(f"Error: {e}")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    tasks = get_all_tasks()
    if not tasks:
        await update.message.reply_text("No tasks.")
        return
    icons = {"pending": "⏳", "in_progress": "🔄", "done": "✅"}
    msg = "All tasks:\n\n"
    for t in tasks:
        icon = icons.get(t["status"], "❓")
        msg += f"{icon} #{t['id']} — {t['title']}\n"
    await update.message.reply_text(msg)

async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("Specify ID: /done 1")
        return
    try:
        task_id = int(context.args[0])
        task = get_task(task_id)
        if not task:
            await update.message.reply_text("Task not found.")
            return
        update_task(task_id, status="done")
        await update.message.reply_text(f"Task #{task_id} done!")
    except ValueError:
        await update.message.reply_text("Invalid ID.")

async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("Specify ID: /progress 1")
        return
    try:
        task_id = int(context.args[0])
        task = get_task(task_id)
        if not task:
            await update.message.reply_text("Task not found.")
            return
        await update.message.reply_text("Analyzing progress...")
        analysis = analyze_progress(task["title"], task["subtasks"], [])
        await update.message.reply_text(f"Analysis #{task_id}:\n\n{analysis}")
    except ValueError:
        await update.message.reply_text("Invalid ID.")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    s = get_stats()
    await update.message.reply_text(
        f"Stats:\n\n"
        f"Total: {s['total']}\n"
        f"Done: {s['done']}\n"
        f"In progress: {s['in_progress']}\n"
        f"Pending: {s['pending']}"
    )

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    tasks = get_all_tasks()
    if not tasks:
        await update.message.reply_text("No tasks for report.")
        return
    await update.message.reply_text("Generating report...")
    try:
        summary = summarize_day(tasks)
        await update.message.reply_text(f"Daily report:\n\n{summary}")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("Specify ID: /delete 1")
        return
    try:
        task_id = int(context.args[0])
        delete_task(task_id)
        await update.message.reply_text(f"Task #{task_id} deleted.")
    except ValueError:
        await update.message.reply_text("Invalid ID.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("start_"):
        task_id = int(data.split("_")[1])
        update_task(task_id, status="in_progress")
        await query.edit_message_text(f"Task #{task_id} started!")

def start_flask():
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Flask starting on port {port}")
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    init_db()

    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()
    logger.info("Flask thread started!")

    logger.info("Starting Telegram bot (main thread)...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("plan", cmd_plan))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("progress", cmd_progress))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.run_polling(drop_pending_updates=True)
