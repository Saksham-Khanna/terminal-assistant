"""
Conversation summarization for context window management.

When the conversation history gets too long (especially on free-tier models
with limited context), this module compresses older messages into a concise
summary while preserving recent turns. This prevents the agent from hitting
context limits and keeps response times reasonable.

How it works:
  1. Estimate the total token count of the conversation (rough char-based).
  2. If it exceeds a threshold, take the oldest N messages.
  3. Ask the LLM to summarize them into a single "system summary" message.
  4. Replace those old messages with the summary.
  5. Keep recent messages intact so the agent has immediate context.
"""

import os
import json
import urllib.request
import urllib.error

from google.genai import types

from agent.config import get_config

# Rough estimate: ~4 chars per token for English text.
CHARS_PER_TOKEN = 4

# Default context budget — summarize when conversation exceeds this many tokens.
# Leaves room for the model's response. Tunable via config file or env var.
DEFAULT_CONTEXT_BUDGET = get_config().context_budget_tokens

# How many recent turns to always keep (never summarize these).
TAIL_TURNS = get_config().summarize_tail_turns

# Max tokens to request for the summary itself.
SUMMARY_MAX_TOKENS = 1024

SUMMARIZE_PROMPT = """You are a conversation summarizer. Condense the following conversation \
between a user and a coding agent into a concise summary.

Focus on:
- The original task/goal
- Key decisions made
- Files read, created, or modified (with brief descriptions)
- Errors encountered and how they were resolved
- Current progress and what remains to be done
- Any important context the agent needs to remember

Be factual and concise. Do not add information not present in the conversation. \
Use bullet points for clarity. Output ONLY the summary, no preamble."""


def estimate_tokens(text: str) -> int:
    """Rough token estimate based on character count."""
    return len(text) // CHARS_PER_TOKEN


def _estimate_gemini_tokens(contents: list[types.Content]) -> int:
    """Estimate total tokens across all Gemini Content objects."""
    total_chars = 0
    for content in contents:
        for part in content.parts:
            if getattr(part, "text", None):
                total_chars += len(part.text)
            elif getattr(part, "function_call", None):
                fc = part.function_call
                total_chars += len(fc.name) + len(json.dumps(dict(fc.args)))
            elif getattr(part, "function_response", None):
                fr = part.function_response
                resp = fr.response.get("result", "")
                total_chars += len(resp)
    return total_chars // CHARS_PER_TOKEN


def _estimate_groq_tokens(messages: list[dict]) -> int:
    """Estimate total tokens across all Groq message dicts."""
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total_chars += len(part["text"])
        # Tool calls
        if "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                total_chars += len(tc.get("function", {}).get("arguments", ""))
    return total_chars // CHARS_PER_TOKEN


def _summarize_via_gemini(
    client, contents: list[types.Content], system: str
) -> str | None:
    """Ask Gemini to summarize the conversation history."""
    # Build a prompt with the conversation to summarize
    conv_text = _gemini_to_text(contents)
    prompt = f"{SUMMARIZE_PROMPT}\n\n--- Conversation ---\n{conv_text}\n--- End ---"

    try:
        response = client.models.generate_content(
            model=get_config().gemini_model,
            contents=[
                types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=SUMMARY_MAX_TOKENS,
            ),
        )
        return response.candidates[0].content.parts[0].text.strip()
    except Exception as e:
        print(f"  [summarize] Gemini summarization failed: {e}")
        return None


def _summarize_via_groq(messages: list[dict], system: str) -> str | None:
    """Ask Groq to summarize the conversation history."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None

    conv_text = _groq_to_text(messages)
    prompt = f"{SUMMARIZE_PROMPT}\n\n--- Conversation ---\n{conv_text}\n--- End ---"

    payload = {
        "model": get_config().groq_model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": SUMMARY_MAX_TOKENS,
        "stream": False,
    }

    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": user_agent,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  [summarize] Groq summarization failed: {e}")
        return None


def _gemini_to_text(contents: list[types.Content]) -> str:
    """Convert Gemini contents to readable text for the summarizer prompt."""
    lines = []
    for content in contents:
        role = content.role.upper()
        for part in content.parts:
            if getattr(part, "text", None):
                lines.append(f"[{role}]: {part.text[:2000]}")
            elif getattr(part, "function_call", None):
                fc = part.function_call
                args_str = json.dumps(dict(fc.args), ensure_ascii=False)
                lines.append(f"[{role} TOOL_CALL]: {fc.name}({args_str[:500]})")
            elif getattr(part, "function_response", None):
                fr = part.function_response
                resp = fr.response.get("result", "")[:1000]
                lines.append(f"[{role} TOOL_RESULT]: {fr.name} -> {resp}")
    return "\n".join(lines)


def _groq_to_text(messages: list[dict]) -> str:
    """Convert Groq messages to readable text for the summarizer prompt."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "")
        if isinstance(content, str) and content:
            lines.append(f"[{role}]: {content[:2000]}")
        if "tool_calls" in msg:
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                lines.append(f"[{role} TOOL_CALL]: {fn.get('name')}({fn.get('arguments', '')[:500]})")
        if msg.get("role") == "tool":
            lines.append(f"[TOOL_RESULT]: {str(content)[:1000]}")
    return "\n".join(lines)


def should_summarize_gemini(contents: list[types.Content], budget: int | None = None) -> bool:
    """Check if Gemini conversation exceeds the context budget."""
    budget = budget or DEFAULT_CONTEXT_BUDGET
    return _estimate_gemini_tokens(contents) > budget


def should_summarize_groq(messages: list[dict], budget: int | None = None) -> bool:
    """Check if Groq conversation exceeds the context budget."""
    budget = budget or DEFAULT_CONTEXT_BUDGET
    return _estimate_groq_tokens(messages) > budget


def summarize_gemini(
    client, contents: list[types.Content], system: str
) -> list[types.Content]:
    """
    Summarize old Gemini messages, keeping recent turns intact.
    Returns a new contents list with the summary prepended.
    """
    if len(contents) <= TAIL_TURNS + 2:
        return contents

    # Split: old messages to summarize, recent messages to keep
    split_idx = len(contents) - TAIL_TURNS
    old_contents = contents[:split_idx]
    tail_contents = contents[split_idx:]

    print(f"  [summarize] Compressing {len(old_contents)} old messages...")

    summary = _summarize_via_gemini(client, old_contents, system)
    if not summary:
        return contents  # Fallback: keep everything

    print(f"  [summarize] Summary ({len(summary)} chars)")

    # Build new contents: summary + recent turns
    summary_content = types.Content(
        role="user",
        parts=[types.Part.from_text(
            text=f"[CONVERSATION SUMMARY — earlier messages compressed]\n\n{summary}"
        )],
    )
    model_ack = types.Content(
        role="model",
        parts=[types.Part.from_text(text="Understood. I have the context from the summary.")],
    )

    return [summary_content, model_ack] + tail_contents


def summarize_groq(
    client_ref, messages: list[dict], system: str
) -> list[dict]:
    """
    Summarize old Groq messages, keeping recent turns intact.
    Returns a new messages list with the summary prepended.
    """
    if len(messages) <= TAIL_TURNS + 2:
        return messages

    # Find a good split point — skip system message if present
    start = 0
    if messages and messages[0].get("role") == "system":
        start = 1

    split_idx = max(start + 1, len(messages) - TAIL_TURNS)
    old_messages = messages[start:split_idx]
    tail_messages = messages[split_idx:]

    # Keep system message if it was at the start
    prefix = messages[:start] if start > 0 else []

    print(f"  [summarize] Compressing {len(old_messages)} old messages...")

    summary = _summarize_via_groq(old_messages, system)
    if not summary:
        return messages  # Fallback: keep everything

    print(f"  [summarize] Summary ({len(summary)} chars)")

    summary_msg = {
        "role": "user",
        "content": f"[CONVERSATION SUMMARY — earlier messages compressed]\n\n{summary}",
    }
    ack_msg = {
        "role": "assistant",
        "content": "Understood. I have the context from the summary.",
    }

    return prefix + [summary_msg, ack_msg] + tail_messages
