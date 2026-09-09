import os
import json
import asyncio
import threading
import logging
from datetime import datetime, timedelta
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

telegram_app = None

async def send_message(text):
    if telegram_app:
        await telegram_app.bot.send_message(chat_id=CHAT_ID, text=text)

def send_message_sync(text):
    if telegram_app:
        asyncio.run_coroutine_threadsafe(
            telegram_app.bot.send_message(chat_id=CHAT_ID, text=text),
            telegram_app.bot_loop
        )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        await update.message.reply_text("Доступ запрещён.")
        return
    await update.message.reply_text(
        "Менеджер задач готов!\n\n"
        "Команды:\n"
        "/plan <задача> — спланировать задачу\n"
        "/list — список задач\n"
        "/done <id> — отметить выполненной\n"
        "/progress <id> — анализ прогресса\n"
        "/stats — статистика\n"
        "/report — отчёт за день\n"
        "/remind <часы> <текст> — напоминание\n"
        "/daily — включить/выключить ежедневный отчёт\n"
        "/delete <id> — удалить задачу"
    )

async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    task_text = " ".join(context.args) if context.args else None
    if not task_text:
        await update.message.reply_text("Укажи задачу: /plan написать отчёт")
        return
    await update.message.reply_text("Планирую задачу...")
    try:
        subtasks = plan_task(task_text)
        task_id = add_task(task_text, subtasks=subtasks)
        msg = f"Задача #{task_id}: {task_text}\n\nПодзадачи:\n"
        for i, st in enumerate(subtasks, 1):
            msg += f"  {i}. {st['title']} (приоритет: {st.get('priority', 3)})\n"
        keyboard = [[InlineKeyboardButton("Начать", callback_data=f"start_{task_id}")]]
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Plan error: {e}")
        await update.message.reply_text(f"Ошибка: {e}")

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    tasks = get_all_tasks()
    if not tasks:
        await update.message.reply_text("Нет задач.")
        return
    icons = {"pending": "⏳", "in_progress": "🔄", "done": "✅"}
    msg = "Все задачи:\n\n"
    for t in tasks:
        icon = icons.get(t["status"], "❓")
        msg += f"{icon} #{t['id']} — {t['title']}\n"
    await update.message.reply_text(msg)

async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("Укажи ID: /done 1")
        return
    try:
        task_id = int(context.args[0])
        task = get_task(task_id)
        if not task:
            await update.message.reply_text("Задача не найдена.")
            return
        update_task(task_id, status="done")
        await update.message.reply_text(f"Задача #{task_id} выполнена!")
    except ValueError:
        await update.message.reply_text("Неверный ID.")

async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("Укажи ID: /progress 1")
        return
    try:
        task_id = int(context.args[0])
        task = get_task(task_id)
        if not task:
            await update.message.reply_text("Задача не найдена.")
            return
        await update.message.reply_text("Анализирую прогресс...")
        analysis = analyze_progress(task["title"], task["subtasks"], [])
        await update.message.reply_text(f"Анализ задачи #{task_id}:\n\n{analysis}")
    except ValueError:
        await update.message.reply_text("Неверный ID.")

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    s = get_stats()
    await update.message.reply_text(
        f"Статистика:\n\n"
        f"Всего: {s['total']}\n"
        f"Выполнено: {s['done']}\n"
        f"В процессе: {s['in_progress']}\n"
        f"Ожидает: {s['pending']}"
    )

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    tasks = get_all_tasks()
    if not tasks:
        await update.message.reply_text("Нет задач для отчёта.")
        return
    await update.message.reply_text("Формирую отчёт...")
    try:
        summary = summarize_day(tasks)
        await update.message.reply_text(f"Отчёт за день:\n\n{summary}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    if len(context.args) < 2:
        await update.message.reply_text("Формат: /remind 2 Купить молоко\n(через 2 часа)")
        return
    try:
        hours = int(context.args[0])
        text = " ".join(context.args[1:])
        remind_time = datetime.now() + timedelta(hours=hours)

        async def do_remind():
            await asyncio.sleep(hours * 3600)
            await send_message(f"Напоминание!\n\n{text}")

        asyncio.create_task(do_remind())
        await update.message.reply_text(f"Напоминание через {hours}ч:\n{text}")
    except ValueError:
        await update.message.reply_text("Неверное число часов.")

daily_report_enabled = True

async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    global daily_report_enabled
    daily_report_enabled = not daily_report_enabled
    status = "включён" if daily_report_enabled else "выключен"
    await update.message.reply_text(f"Ежедневный отчёт {status}.")

async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != CHAT_ID:
        return
    if not context.args:
        await update.message.reply_text("Укажи ID: /delete 1")
        return
    try:
        task_id = int(context.args[0])
        delete_task(task_id)
        await update.message.reply_text(f"Задача #{task_id} удалена.")
    except ValueError:
        await update.message.reply_text("Неверный ID.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("start_"):
        task_id = int(data.split("_")[1])
        update_task(task_id, status="in_progress")
        await query.edit_message_text(f"Задача #{task_id} начата!")

def daily_report_job():
    if not daily_report_enabled:
        return
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
    msg = "Напоминание: у тебя есть задачи в процессе:\n\n"
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

    telegram_app.add_handler(CommandHandler("start", cmd_start))
    telegram_app.add_handler(CommandHandler("plan", cmd_plan))
    telegram_app.add_handler(CommandHandler("list", cmd_list))
    telegram_app.add_handler(CommandHandler("done", cmd_done))
    telegram_app.add_handler(CommandHandler("progress", cmd_progress))
    telegram_app.add_handler(CommandHandler("stats", cmd_stats))
    telegram_app.add_handler(CommandHandler("report", cmd_report))
    telegram_app.add_handler(CommandHandler("remind", cmd_remind))
    telegram_app.add_handler(CommandHandler("daily", cmd_daily))
    telegram_app.add_handler(CommandHandler("delete", cmd_delete))
    telegram_app.add_handler(CallbackQueryHandler(callback_handler))

    telegram_app.run_polling(drop_pending_updates=True)
