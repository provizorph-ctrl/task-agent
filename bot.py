import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from database import init_db, add_task, get_task, get_all_tasks, update_task, delete_task, get_stats
from llm import plan_task, analyze_progress, summarize_day

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
        "/done <id> — отметить выполненой\n"
        "/progress <id> — анализ прогресса\n"
        "/stats — статистика\n"
        "/report — отчёт за день\n"
        "/delete <id> — удалить задачу"
    )

async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("Аализирую прогресс...")
        analysis = analyze_progress(task["title"], task["subtasks"], [])
        await update.message.reply_text(f"Анализ задачи #{task_id}:\n\n{analysis}")
    except ValueError:
        await update.message.reply_text("Неверный ID.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("start_"):
        task_id = int(data.split("_")[1])
        update_task(task_id, status="in_progress")
        await query.edit_message_text(f"Задача #{task_id} начата!")

def run_bot():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("plan", plan))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("progress", progress))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("delete", delete_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.run_polling()

if __name__ == "__main__":
    run_bot()
