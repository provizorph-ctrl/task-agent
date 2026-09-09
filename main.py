import os
import asyncio
import threading
import logging
from flask import Flask, render_template, request, jsonify
from database import init_db, add_task, get_task, get_all_tasks, update_task, delete_task, get_stats
from llm import plan_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")

@app.template_filter('fromjson')
def fromjson_filter(s):
    try:
        return json.loads(s) if isinstance(s, str) else s
    except:
        return []

import json

@app.before_request
def setup():
    init_db()

@app.route("/")
def index():
    tasks = get_all_tasks()
    stats = get_stats()
    return render_template("index.html", tasks=tasks, stats=stats)

@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    status = request.args.get("status")
    return jsonify(get_all_tasks(status))

@app.route("/api/tasks", methods=["POST"])
def api_create_task():
    data = request.json
    title = data.get("title", "")
    description = data.get("description", "")
    priority = data.get("priority", 3)
    subtasks = plan_task(title, description)
    task_id = add_task(title, description, priority, subtasks=subtasks)
    return jsonify({"id": task_id, "subtasks": subtasks})

@app.route("/api/tasks/<int:task_id>", methods=["PUT"])
def api_update_task(task_id):
    data = request.json
    update_task(task_id, **data)
    return jsonify({"ok": True})

@app.route("/api/tasks/<int:task_id>", methods=["DELETE"])
def api_delete_task(task_id):
    delete_task(task_id)
    return jsonify({"ok": True})

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

def run_bot_thread():
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

    CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
    TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "/delete <id> — удалить задачу"
        )

    async def plan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != CHAT_ID:
            return
        tasks = get_all_tasks()
        if not tasks:
            await update.message.reply_text("Нет задач.")
            return
        status_icons = {"pending": "⏳", "in_progress": "🔄", "done": "✅"}
        msg = "Все задачи:\n\n"
        for t in tasks:
            icon = status_icons.get(t["status"], "❓")
            msg += f"{icon} #{t['id']} — {t['title']}\n"
        await update.message.reply_text(msg)

    async def done_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def progress_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            from llm import analyze_progress
            analysis = analyze_progress(task["title"], task["subtasks"], [])
            await update.message.reply_text(f"Анализ задачи #{task_id}:\n\n{analysis}")
        except ValueError:
            await update.message.reply_text("Неверный ID.")

    async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id != CHAT_ID:
            return
        tasks = get_all_tasks()
        if not tasks:
            await update.message.reply_text("Нет задач для отчёта.")
            return
        await update.message.reply_text("Формирую отчёт...")
        try:
            from llm import summarize_day
            summary = summarize_day(tasks)
            await update.message.reply_text(f"Отчёт за день:\n\n{summary}")
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")

    async def delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("plan", plan_cmd))
        application.add_handler(CommandHandler("list", list_cmd))
        application.add_handler(CommandHandler("done", done_cmd))
        application.add_handler(CommandHandler("progress", progress_cmd))
        application.add_handler(CommandHandler("stats", stats_cmd))
        application.add_handler(CommandHandler("report", report_cmd))
        application.add_handler(CommandHandler("delete", delete_cmd))
        application.add_handler(CallbackQueryHandler(callback_handler))
        application.run_polling(drop_pending_updates=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    logger.info("Telegram bot thread started!")

if __name__ == "__main__":
    init_db()
    run_bot_thread()
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting web server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
