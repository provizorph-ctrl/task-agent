import os
import json
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def plan_task(task_title, task_description=""):
    prompt = f"""Ты — менеджер по планированию задач. Разбей задачу на конкретные подзадачи.

Задача: {task_title}
Описание: {task_description if task_description else 'Без описания'}

Верни ТОЛЬКО JSON массив подзадач в формате:
[
  {{"title": "Название подзадачи", "description": "Описание", "priority": 1-5}}
]

Приоритет: 1 - критический, 2 - высокий, 3 - средний, 4 - низкий, 5 - можно подождать.
Создай от 3 до 7 подзадач. Отвечай ТОЛЬКО JSON, без текста."""

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1000
    )

    content = response.choices[0].message.content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        subtasks = json.loads(content)
        return subtasks
    except json.JSONDecodeError:
        return [{"title": task_title, "description": task_description, "priority": 3}]

def analyze_progress(task_title, subtasks, completed):
    prompt = f"""Проанализируй прогресс выполнения задачи.

Задача: {task_title}
Подзадачи: {json.dumps(subtasks, ensure_ascii=False)}
Выполнено: {json.dumps(completed, ensure_ascii=False)}

Дай краткий анализ:
1. Процент выполнения
2. Какие подзадачи в процессе
3. Есть ли блокеры
4. Рекомендации

Отвечай кратко на русском."""

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=500
    )
    return response.choices[0].message.content

def summarize_day(tasks):
    prompt = f"""Составь краткий отчёт за день по задачам.

Задачи:
{json.dumps(tasks, ensure_ascii=False, indent=2)}

Включи:
1. Сколько задач выполнено
2. Что в процессе
3. Что запланировано на завтра
4. Общую оценку продуктивности

Отвечай кратко и структурированно."""

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=500
    )
    return response.choices[0].message.content

def chat_with_agent(user_text, tasks_json, stats, get_logs=None, get_status=None, get_code=None, get_diagnostics=None):
    from database import add_task, get_all_tasks, update_task, delete_task, add_reminder, get_all_reminders
    from datetime import datetime, timedelta, timezone

    local_tz = timezone(timedelta(hours=5))
    local_now = datetime.now(local_tz)

    reminders = get_all_reminders()
    reminders_json = json.dumps(reminders, ensure_ascii=False, default=str)

    logs_data = []
    if get_logs:
        try:
            logs_data = get_logs()
        except:
            logs_data = ["Логи недоступны"]
    logs_str = "\n".join(logs_data) if logs_data else "Логи пусты"

    status_data = {}
    if get_status:
        try:
            status_data = get_status()
        except:
            status_data = {"error": "status unavailable"}
    status_str = str(status_data)

    code_str = ""
    if get_code:
        try:
            code_str = get_code()
        except:
            code_str = "Код недоступен"

    diag_str = ""
    if get_diagnostics:
        try:
            diag_str = str(get_diagnostics())
        except:
            diag_str = "Диагностика недоступна"

    system_prompt = f"""Ты — автономный AI-разработчик, DevOps-инженер и технический администратор Telegram-бота. Общаешься с человеком на русском языке.

Архитектура системы:
Владелец → Telegram → AI Agent → OpenCode → GitHub → Render → Telegram Bot

ТЕКУЩЕЕ СОСТОЯНИЕ СИСТЕМЫ:

Текущие задачи:
{tasks_json}

Напоминания:
{reminders_json}

Статистика:
{json.dumps(stats, ensure_ascii=False)}

Логи сервера:
{logs_str}

Статус сервера:
{status_str}

Исходный код main.py:
{code_str}

Диагностика сервера:
{diag_str}

Текущее время (UTC+5): {local_now.strftime('%Y-%m-%d %H:%M:%S')}

РОЛЬ И ОБЯЗАННОСТИ:
Ты — действующий AI-разработчик. Твоя задача — самостоятельно выполнять технические задачи владельца через Telegram. Не давай абстрактных советов — делай сам.

ЦИКЛ ВЫПОЛНЕНИЯ ЗАДАЧ:
1. ПОНЯТЬ цель
2. ИССЛЕДОВАТЬ проект (прочитай код и логи выше)
3. ВНЕСТИ изменение
4. СООБЩИ владельцу что сделано

ПРАВИЛА РАБОТЫ:
- НИКОГДА не говори "сделай сам" или "у меня нет доступа" — ты имеешь доступ ко всему
- Используй данные из блоков логов, статуса, кода и диагностики выше
- Если спрашивают про логи — проанализируй и ответь
- Если спрашивают про статус — покажи из блока статуса
- Если спрашивают про код — покажи из блока кода
- Если спрашивают про диагностику — покажи из блока диагностики
- Если просят исправить ошибку — проанализируй код выше и предложи конкретное исправление
- Если просят добавить функцию — предложи конкретную реализацию
- Если спрашивают про архитектуру — объясни на основе кода выше
- Будь кратким, отвечай 1-5 предложений
- НЕ засоряй Telegram лишней информацией

ДОСТУПНЫЕ ФУНКЦИИ:
- add_task(title, description, priority) — создать задачу
- update_task(id, status='done') — отметить выполненной
- delete_task(id) — удалить задачу
- get_all_tasks() — получить список задач
- add_reminder(text, remind_at) — создать напоминание (YYYY-MM-DD HH:MM:SS в UTC+5)
- get_all_reminders() — получить список напоминаний

ФОРМАТЫ ОТВЕТОВ:

Создание задачи:
{{"action": "create", "title": "название", "description": "описание", "priority": 3}}

Выполнение задачи:
{{"action": "done", "id": 1}}

Удаление задачи:
{{"action": "delete", "id": 1}}

Создание напоминания:
{{"action": "remind", "text": "текст напоминания", "time": "YYYY-MM-DD HH:MM:SS"}}

Просто общение — верни обычный текст без JSON."""

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        temperature=0.5,
        max_tokens=1500
    )

    content = response.choices[0].message.content.strip()

    try:
        if content.startswith("{"):
            action = json.loads(content)
            if action.get("action") == "create":
                task_id = add_task(
                    action.get("title", ""),
                    action.get("description", ""),
                    action.get("priority", 3)
                )
                return f"Задача #{task_id} создана: {action.get('title', '')}"
            elif action.get("action") == "done":
                update_task(action["id"], status="done")
                return f"Задача #{action['id']} выполнена!"
            elif action.get("action") == "delete":
                delete_task(action["id"])
                return f"Задача #{action['id']} удалена."
            elif action.get("action") == "remind":
                remind_time = action.get("time", "")
                text = action.get("text", "")
                add_reminder(text, remind_time)
                return f"Напоминание установлено на {remind_time}: {text}"
    except (json.JSONDecodeError, KeyError):
        pass

    return content
