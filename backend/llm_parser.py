"""
llm_parser.py
Turns a natural-language voice/text command into a structured intent (JSON).
Runs server-side so the API key never touches the browser.
"""
import json
import os

SYSTEM_PROMPT = """You are the command parser for a voice-controlled task manager.
Convert the user's spoken command into ONE JSON object and output NOTHING else -
no markdown fences, no explanation.

Schema:
{
  "action": "add" | "list" | "complete" | "delete" | "update_priority" | "rename" | "unknown",
  "title": string or null,
  "match": string or null,
  "priority": "low" | "medium" | "high" | null,
  "filter_status": "all" | "pending" | "done",
  "filter_priority": "all" | "low" | "medium" | "high"
}

Examples:
"add buy milk to my list" -> {"action":"add","title":"buy milk","match":null,"priority":"medium","filter_status":"all","filter_priority":"all"}
"add call the dentist, high priority" -> {"action":"add","title":"call the dentist","match":null,"priority":"high","filter_status":"all","filter_priority":"all"}
"read out my tasks" -> {"action":"list","title":null,"match":null,"priority":null,"filter_status":"pending","filter_priority":"all"}
"read my high priority tasks" -> {"action":"list","title":null,"match":null,"priority":null,"filter_status":"pending","filter_priority":"high"}
"mark grocery run as done" -> {"action":"complete","title":null,"match":"grocery run","priority":null,"filter_status":"all","filter_priority":"all"}
"delete the dentist task" -> {"action":"delete","title":null,"match":"dentist","priority":null,"filter_status":"all","filter_priority":"all"}
"bump grocery run to high priority" -> {"action":"update_priority","title":null,"match":"grocery run","priority":"high","filter_status":"all","filter_priority":"all"}

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
        system=SYSTEM_PROMPT,
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
