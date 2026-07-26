"""
chat_agent.py
A conversational assistant for VoiceTask, built on Claude's tool use.

Unlike llm_parser.py (which maps one utterance to exactly one rigid action),
this lets Claude have an actual back-and-forth about your tasks: answering
analytical questions ("what are my top 3 upcoming tasks and why"), taking
multiple actions in one turn, and asking clarifying questions when unsure.

Conversation history is persisted in storage.messages, so it survives
across page loads and devices - that's the "read it back" behavior.
"""
import json
import os
from datetime import datetime

import storage

MAX_TOOL_ITERATIONS = 6
HISTORY_MESSAGES_FOR_CONTEXT = 20


def _system_prompt() -> str:
    now = datetime.now()
    return f"""You are the assistant inside VoiceTask, a personal voice-controlled
task manager. Today's date is {now.strftime('%A, %B %d, %Y')} ({now.strftime('%Y-%m-%d')}).

You can see and modify the user's task list using the tools provided. Be a
genuinely useful assistant, not just a command executor:
- For analytical questions ("what are my most important upcoming tasks",
  "how does my week look", "what's overdue") - call list_tasks, then reason
  over the results yourself and answer in plain, natural language. Never dump
  raw data or IDs at the user.
- For direct requests ("add X", "mark Y done", "star the dentist task",
  "add groceries to my day") - just do it using the tools, then briefly
  confirm what you did.
- You can have a real conversation - answer follow-ups, ask a clarifying
  question if a request is ambiguous (e.g. two tasks with similar names)
  instead of guessing.
- Keep responses SHORT and conversational - they're often read aloud via
  text-to-speech. A sentence or two is usually enough. Never use markdown
  formatting, bullet points, or asterisks in your reply text.
- due_date is a plain YYYY-MM-DD date, no time-of-day. Resolve relative
  dates ("tomorrow", "next Friday") using today's date above.
- recurrence is one of: daily, weekly, monthly, or null.
- When you need to act on a specific task, call list_tasks or search_tasks
  first to find its id, then use that id in the action tool. Don't guess ids.
"""


TOOLS = [
    {
        "name": "list_tasks",
        "description": "List tasks, optionally filtered by status or priority. Use this to see current tasks before answering questions or taking actions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["all", "pending", "done"], "description": "Default 'all' if omitted."},
                "priority": {"type": "string", "enum": ["all", "high", "medium", "low"]},
            },
        },
    },
    {
        "name": "search_tasks",
        "description": "Find a task by a fragment of its title. Returns the best match with its id.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "add_task",
        "description": "Create a new task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "due_date": {"type": "string", "description": "YYYY-MM-DD or omit if none"},
                "recurrence": {"type": "string", "enum": ["daily", "weekly", "monthly"], "description": "Omit if one-time."},
            },
            "required": ["title"],
        },
    },
    {
        "name": "complete_task",
        "description": "Mark a task done by its id. If it's recurring, the next occurrence is created automatically.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "delete_task",
        "description": "Permanently delete a task by its id.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "update_priority",
        "description": "Change a task's priority.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["task_id", "priority"],
        },
    },
    {
        "name": "update_due_date",
        "description": "Change or remove a task's due date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "due_date": {"type": "string", "description": "YYYY-MM-DD, or omit/empty to clear the due date"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "set_star",
        "description": "Star (favorite) or un-star a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "starred": {"type": "boolean"},
            },
            "required": ["task_id", "starred"],
        },
    },
    {
        "name": "set_my_day",
        "description": "Add or remove a task from 'My Day' (today's focus list).",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "my_day": {"type": "boolean"},
            },
            "required": ["task_id", "my_day"],
        },
    },
]


def _execute_tool(name: str, tool_input: dict) -> dict:
    try:
        if name == "list_tasks":
            tasks = storage.list_tasks(
                status=tool_input.get("status", "all"),
                priority=tool_input.get("priority", "all"),
            )
            return {"tasks": tasks}

        if name == "search_tasks":
            task = storage.find_task_by_title(tool_input["query"])
            return {"task": task} if task else {"error": "no matching task found"}

        if name == "add_task":
            task_id = storage.add_task(
                tool_input["title"],
                tool_input.get("priority", "medium"),
                tool_input.get("due_date"),
                tool_input.get("recurrence"),
            )
            return {"task": storage.get_task(task_id)}

        if name == "complete_task":
            storage.complete_task(tool_input["task_id"])
            return {"ok": True}

        if name == "delete_task":
            storage.delete_task(tool_input["task_id"])
            return {"ok": True}

        if name == "update_priority":
            storage.update_priority(tool_input["task_id"], tool_input["priority"])
            return {"ok": True}

        if name == "update_due_date":
            storage.update_due_date(tool_input["task_id"], tool_input.get("due_date") or None)
            return {"ok": True}

        if name == "set_star":
            storage.set_starred(tool_input["task_id"], tool_input["starred"])
            return {"ok": True}

        if name == "set_my_day":
            storage.set_my_day(tool_input["task_id"], tool_input["my_day"])
            return {"ok": True}

        return {"error": f"unknown tool {name}"}
    except Exception as e:
        return {"error": str(e)}


def handle_message(user_text: str) -> str:
    import anthropic

    client = anthropic.Anthropic()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    storage.add_message("user", user_text)

    history = storage.get_messages(limit=HISTORY_MESSAGES_FOR_CONTEXT)
    messages = [{"role": m["role"], "content": m["content"]} for m in history if m["role"] in ("user", "assistant")]

    final_text = "Sorry, I couldn't come up with a response."
    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=model,
            max_tokens=600,
            system=_system_prompt(),
            messages=messages,
            tools=TOOLS,
        )

        if response.stop_reason != "tool_use":
            final_text = "".join(b.text for b in response.content if b.type == "text").strip()
            if not final_text:
                final_text = "Done."
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = _execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
        messages.append({"role": "user", "content": tool_results})
    else:
        final_text = "That turned into a lot of steps - could you rephrase or simplify the request?"

    storage.add_message("assistant", final_text)
    return final_text
