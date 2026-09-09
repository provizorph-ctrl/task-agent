import os
import json
import asyncio
import threading
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from database import init_db, add_task, get_task, get_all_tasks, update_task, delete_task, get_stats
from llm import plan_task, analyze_progress, summarize_day, chat_with_agent
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

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

telegram_app = None

async def send_message(text):
    if telegram_app:
        await telegram_app.bot.send_message(chat_id=CHAT_ID, text=text)

def send_message_sync(text):
    if telegram_app:
        try:
            loop = telegram_app.bot_loop
            if loop and loop.is_running():
                asyncio.run_coroutine_threadsafe(send_message(text), loop)
        except Exception as e:
            logger.error(f"Send message error: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return

    user_text = update.message.text
    if not user_text:
        return

    tasks = get_all_tasks()
    stats = get_stats()
    tasks_json = json.dumps(tasks, ensure_ascii=False, default=str)

    try:
        response = chat_with_agent(user_text, tasks_json, stats)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Chat error: {e}")
        await update.message.reply_text("Произошла ошибка, попробуй ещё раз.")

def daily_report_job():
    tasks = get_all_tasks()
    if not tasks:
        return
    try:
        summary = summarize_day(tasks)
        send_message_sync(f"Ежедневный отчёт:\n\n{summary}")
    except Exception as e:
        logger.error(f"Daily report error: {e}")

def check_pending_tasks():
    tasks = get_all_tasks(status="in_progress")
    if not tasks:
        return
    msg = "Напоминание: у тебя задачи в процессе:\n\n"
    for t in tasks:
        msg += f"🔄 #{t['id']} — {t['title']}\n"
    send_message_sync(msg)

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
    telegram_app = Application.builder().token(TOKEN).build()
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    telegram_app.run_polling(drop_pending_updates=True)
