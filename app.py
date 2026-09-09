import os
import json
from flask import Flask, render_template, request, jsonify, redirect, url_for
from database import init_db, add_task, get_task, get_all_tasks, update_task, delete_task, get_stats
from llm import plan_task

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")

@app.template_filter('fromjson')
def fromjson_filter(s):
    try:
        return json.loads(s) if isinstance(s, str) else s
    except:
        return []

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
