"""
llm_parser.py
Turns a natural-language voice/text command into a structured intent (JSON).
Runs server-side so the API key never touches the browser.
"""
import json
import os
from datetime import datetime


def _build_system_prompt() -> str:
    now = datetime.now()
    today_iso = now.strftime("%Y-%m-%d")
    today_readable = now.strftime("%A, %B %d, %Y")

    return f"""You are the command parser for a voice-controlled task manager.
Convert the user's spoken command into ONE JSON object and output NOTHING else -
no markdown fences, no explanation.

Today's date is {today_readable} ({today_iso}). Use this to resolve relative
dates like "tomorrow", "next Friday", "in 3 days", etc.

Schema:
{{
  "action": "add" | "list" | "complete" | "delete" | "update_priority" | "update_due_date" | "rename" | "unknown",
  "title": string or null,
  "match": string or null,
  "priority": "low" | "medium" | "high" | null,
  "due_date": "YYYY-MM-DD" or null,
  "recurrence": "daily" | "weekly" | "monthly" | null,
  "filter_status": "all" | "pending" | "done",
  "filter_priority": "all" | "low" | "medium" | "high"
}}

Notes on due_date and recurrence:
- due_date is a single calendar date, no time-of-day. Resolve relative phrases
  ("tomorrow", "next Monday", "in two weeks") into an actual YYYY-MM-DD using
  today's date above.
- recurrence is only set when the user clearly wants something repeating
  ("every day", "every Monday" -> weekly, "every month" -> monthly). For
  "every Monday" etc., also set due_date to the NEXT occurrence of that weekday.
- If no date/recurrence is mentioned, leave both null.

Examples:
"add buy milk to my list" -> {{"action":"add","title":"buy milk","match":null,"priority":"medium","due_date":null,"recurrence":null,"filter_status":"all","filter_priority":"all"}}
"add call the dentist, high priority" -> {{"action":"add","title":"call the dentist","match":null,"priority":"high","due_date":null,"recurrence":null,"filter_status":"all","filter_priority":"all"}}
"remind me to call mom tomorrow" -> {{"action":"add","title":"call mom","match":null,"priority":"medium","due_date":"<tomorrow's date>","recurrence":null,"filter_status":"all","filter_priority":"all"}}
"add take out the trash every Monday" -> {{"action":"add","title":"take out the trash","match":null,"priority":"medium","due_date":"<next Monday's date>","recurrence":"weekly","filter_status":"all","filter_priority":"all"}}
"add take vitamins every day" -> {{"action":"add","title":"take vitamins","match":null,"priority":"medium","due_date":"<today's date>","recurrence":"daily","filter_status":"all","filter_priority":"all"}}
"read out my tasks" -> {{"action":"list","title":null,"match":null,"priority":null,"due_date":null,"recurrence":null,"filter_status":"pending","filter_priority":"all"}}
"read my high priority tasks" -> {{"action":"list","title":null,"match":null,"priority":null,"due_date":null,"recurrence":null,"filter_status":"pending","filter_priority":"high"}}
"mark grocery run as done" -> {{"action":"complete","title":null,"match":"grocery run","priority":null,"due_date":null,"recurrence":null,"filter_status":"all","filter_priority":"all"}}
"delete the dentist task" -> {{"action":"delete","title":null,"match":"dentist","priority":null,"due_date":null,"recurrence":null,"filter_status":"all","filter_priority":"all"}}
"bump grocery run to high priority" -> {{"action":"update_priority","title":null,"match":"grocery run","priority":"high","due_date":null,"recurrence":null,"filter_status":"all","filter_priority":"all"}}
"move the dentist appointment to Friday" -> {{"action":"update_due_date","title":null,"match":"dentist","priority":null,"due_date":"<this Friday's date>","recurrence":null,"filter_status":"all","filter_priority":"all"}}

If the command doesn't clearly match any action, return action "unknown".
Respond with ONLY the JSON object.
"""


def _parse_with_anthropic(text: str) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

    response = client.messages.create(
        model=model,
        max_tokens=300,
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": text}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text")
    return _safe_json(raw)


def _safe_json(raw: str) -> dict:
    cleaned = raw.strip().strip("`")
    if cleaned.startswith("json"):
        cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1:
            return json.loads(cleaned[start : end + 1])
        return {"action": "unknown"}


def parse_command(text: str) -> dict:
    return _parse_with_anthropic(text)
