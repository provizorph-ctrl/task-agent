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
        model="llama-3.1-8b-instant",
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
        model="llama-3.1-8b-instant",
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
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=500
    )
    return response.choices[0].message.content
