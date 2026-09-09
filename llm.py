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

def chat_with_agent(user_text, tasks_json, stats):
    from database import add_task, get_all_tasks, update_task, delete_task, add_reminder
    from datetime import datetime, timedelta, timezone

    local_tz = timezone(timedelta(hours=5))
    local_now = datetime.now(local_tz)

    system_prompt = f"""Ты — умный менеджер задач. Общаешься с человеком на русском языке.

Текущие задачи:
{tasks_json}

Статистика:
{json.dumps(stats, ensure_ascii=False)}

Правила:
1. Если человек хочет создать задачу — СОЗДАЙ её через add_task() и подтверди
2. Если хочет отметить задачу выполненной — отметь через update_task(id, status='done')
3. Если хочет удалить задачу — удали через delete_task(id)
4. Если спрашивает про задачи — покажи список
5. Если просит напоминание — СОЗДАЙ его через add_reminder() и подтверди
6. Если просто общается — поддерживай разговор, будь дружелюбным
7. Будь кратким, отвечай 1-3 предложения

Доступные функции:
- add_task(title, description, priority) — создать задачу
- update_task(id, status='done') — отметить выполненной
- delete_task(id) — удалить
- get_all_tasks() — получить список
- add_reminder(text, remind_at) — создать напоминание (remind_at в формате YYYY-MM-DD HH:MM:SS в UTC+3)

Если нужно создать задачу, верни JSON:
{{"action": "create", "title": "название", "description": "описание", "priority": 3}}

Если отметить выполненной:
{{"action": "done", "id": 1}}

Если удалить:
{{"action": "delete", "id": 1}}

Если создать напоминание:
{{"action": "remind", "text": "текст напоминания", "time": "YYYY-MM-DD HH:MM:SS"}}

Если просто общаешься — верни обычный текст без JSON.

Текущее время (Москва, UTC+3): {local_now.strftime('%Y-%m-%d %H:%M:%S')}"""

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        temperature=0.5,
        max_tokens=500
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
