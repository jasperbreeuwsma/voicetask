"""
main.py
FastAPI backend for VoiceTask. Serves the JSON API used by the phone-friendly
frontend, and serves the frontend itself as static files so the whole app is
one deployable service.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import excel_io
import llm_parser
import storage

load_dotenv()

app = FastAPI(title="VoiceTask API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your own domain once deployed, if you want
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    storage.init_db()


# ---------- schemas ----------

class TaskCreate(BaseModel):
    title: str
    priority: str = "medium"


class PriorityUpdate(BaseModel):
    priority: str


class RenameUpdate(BaseModel):
    title: str


class CommandRequest(BaseModel):
    text: str


# ---------- task CRUD ----------

@app.get("/api/tasks")
def get_tasks(status: str = "all", priority: str = "all"):
    try:
        return storage.list_tasks(status=status, priority=priority)
    except Exception:
        return []


@app.post("/api/tasks")
def create_task(task: TaskCreate):
    task_id = storage.add_task(task.title, task.priority)
    return storage.get_task(task_id)


@app.patch("/api/tasks/{task_id}/priority")
def set_priority(task_id: int, body: PriorityUpdate):
    if not storage.get_task(task_id):
        raise HTTPException(404, "Task not found")
    storage.update_priority(task_id, body.priority)
    return storage.get_task(task_id)


@app.patch("/api/tasks/{task_id}/rename")
def rename(task_id: int, body: RenameUpdate):
    if not storage.get_task(task_id):
        raise HTTPException(404, "Task not found")
    storage.rename_task(task_id, body.title)
    return storage.get_task(task_id)


@app.post("/api/tasks/{task_id}/complete")
def complete(task_id: int):
    if not storage.get_task(task_id):
        raise HTTPException(404, "Task not found")
    storage.complete_task(task_id)
    return storage.get_task(task_id)


@app.delete("/api/tasks/{task_id}")
def delete(task_id: int):
    if not storage.get_task(task_id):
        raise HTTPException(404, "Task not found")
    storage.delete_task(task_id)
    return {"deleted": task_id}


# ---------- voice/text command ----------

def execute_intent(intent: dict) -> dict:
    action = intent.get("action", "unknown")

    if action == "add":
        title = intent.get("title")
        priority = intent.get("priority") or "medium"
        if not title:
            return {"message": "I didn't catch what the task should say.", "tasks": storage.list_tasks()}
        storage.add_task(title, priority)
        return {"message": f"Added '{title}' with {priority} priority.", "tasks": storage.list_tasks()}

    if action == "list":
        status = intent.get("filter_status") or "pending"
        priority = intent.get("filter_priority") or "all"
        tasks = storage.list_tasks(status=status, priority=priority)
        if not tasks:
            return {"message": "You have no matching tasks.", "tasks": tasks}
        lines = [f"{t['title']} ({t['priority']} priority)" for t in tasks]
        return {"message": f"You have {len(tasks)} tasks: " + "; ".join(lines), "tasks": tasks}

    if action == "complete":
        match = intent.get("match")
        task = storage.find_task_by_title(match) if match else None
        if not task:
            return {"message": f"I couldn't find a task matching '{match}'.", "tasks": storage.list_tasks()}
        storage.complete_task(task["id"])
        return {"message": f"Marked '{task['title']}' as done.", "tasks": storage.list_tasks()}

    if action == "delete":
        match = intent.get("match")
        task = storage.find_task_by_title(match) if match else None
        if not task:
            return {"message": f"I couldn't find a task matching '{match}'.", "tasks": storage.list_tasks()}
        storage.delete_task(task["id"])
        return {"message": f"Deleted '{task['title']}'.", "tasks": storage.list_tasks()}

    if action == "update_priority":
        match = intent.get("match")
        priority = intent.get("priority")
        task = storage.find_task_by_title(match) if match else None
        if not task:
            return {"message": f"I couldn't find a task matching '{match}'.", "tasks": storage.list_tasks()}
        storage.update_priority(task["id"], priority)
        return {"message": f"Set '{task['title']}' to {priority} priority.", "tasks": storage.list_tasks()}

    if action == "rename":
        match = intent.get("match")
        new_title = intent.get("title")
        task = storage.find_task_by_title(match) if match else None
        if not task or not new_title:
            return {"message": "I couldn't find that task to rename.", "tasks": storage.list_tasks()}
        storage.rename_task(task["id"], new_title)
        return {"message": f"Renamed to '{new_title}'.", "tasks": storage.list_tasks()}

    return {"message": "Sorry, I didn't understand that command.", "tasks": storage.list_tasks()}


@app.post("/api/command")
def run_command(body: CommandRequest):
    try:
        intent = llm_parser.parse_command(body.text)
        return execute_intent(intent)
    except Exception as e:
        # Surface the real error instead of letting it crash into a
        # non-JSON 500 page (which the frontend can't parse). Guard the
        # fallback task list too, in case the database itself is down.
        try:
            tasks = storage.list_tasks()
        except Exception:
            tasks = []
        return {"message": f"Error: {e}", "tasks": tasks}


# ---------- excel ----------

@app.get("/api/export")
def export_excel(status: str = "all"):
    data = excel_io.export_to_excel_bytes(status=status)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=tasks.xlsx"},
    )


@app.post("/api/import")
async def import_excel(file: UploadFile = File(...)):
    content = await file.read()
    try:
        imported, skipped = excel_io.import_from_excel_bytes(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"imported": imported, "skipped": skipped, "tasks": storage.list_tasks()}


# ---------- frontend (static files) ----------

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
