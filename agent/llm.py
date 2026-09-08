"""
Thin wrapper around LLM APIs.

Supports two providers:
  1. Gemini (free tier, no credit card) via google.genai
  2. Groq (free API) via OpenAI-compatible chat completions

Swap providers by setting MODEL_PROVIDER in .env ("gemini" or "groq").
This is the only file that needs to change when swapping providers.
"""

import json
import os
import urllib.request
import urllib.error
from typing import Generator

import httpx

from google import genai
from google.genai import types

from agent.config import get_config

_config = get_config()
GEMINI_MODEL = _config.gemini_model
GROQ_MODEL = _config.groq_model
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


def _groq_request(messages: list, tools: list[dict], system: str, stream: bool = False) -> dict:
    """Low-level Groq call using urllib (no extra dependency needed)."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not set (if MODEL_PROVIDER=groq). Get free key at https://console.groq.com"
        )

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if system:
        payload["messages"] = [{"role": "system", "content": system}] + messages

    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            # urllib ka default Python-urllib User-Agent Cloudflare block karta hai.
            # Browser-like User-Agent lagane se request pass ho jaati hai.
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        if e.code == 403:
            raise RuntimeError(
                "Groq API key rejected (403). Check that GROQ_API_KEY is "
                "valid/active and not revoked. Create a new key at "
                "https://console.groq.com/keys"
            )
        raise RuntimeError(f"Groq API error {e.code}: {body}")


def _groq_stream(messages: list, tools: list[dict], system: str) -> Generator[dict, None, None]:
    """Yield SSE chunks from Groq streaming API."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    if system:
        payload["messages"] = [{"role": "system", "content": system}] + messages

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
    }

    with httpx.Client(timeout=60.0) as client:
        with client.stream("POST", GROQ_URL, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                if line == "data: [DONE]":
                    break
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        yield chunk
                    except json.JSONDecodeError:
                        continue


class LLMClient:

    def __init__(self, api_key: str | None = None):
        self.provider = get_config().provider

        if self.provider == "groq":
            self.groq_messages = []
            return

        # Default: Gemini
        api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY not set. Get a free key at "
                "https://aistudio.google.com/apikey and put it in your .env file. "
                "Or set MODEL_PROVIDER=groq and use GROQ_API_KEY instead."
            )
        self.client = genai.Client(api_key=api_key)

    def call(self, contents: list, system: str, tools: list[dict]) -> object:
        if self.provider == "groq":
            return self._call_groq(contents, system, tools)
        return self._call_gemini(contents, system, tools)

    def set_groq_messages(self, messages: list):
        self.groq_messages = messages

    # --- Gemini implementation (unchanged behavior) ---
    def _call_gemini(self, contents, system, tools):
        function_declarations = [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            }
            for t in tools
        ]

        response = self.client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[types.Tool(function_declarations=function_declarations)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )
        return response

    # --- Groq implementation ---
    def _call_groq(self, contents, system, tools):
        # If the caller has set messages directly (from Agent), use them.
        # Otherwise convert Gemini-style contents to OpenAI-style messages.
        if self.groq_messages:
            messages = self.groq_messages
        else:
            messages = []
            for content in contents:
                role = content.role
                text_parts = []
                for part in content.parts:
                    if getattr(part, "text", None):
                        text_parts.append(part.text)
                    elif getattr(part, "function_call", None):
                        fc = part.function_call
                        args = json.dumps(dict(fc.args), ensure_ascii=False)
                        text_parts.append(f"tool_call({fc.name}): {args}")
                    elif getattr(part, "function_response", None):
                        fr = part.function_response
                        resp = fr.response.get("result", "")
                        text_parts.append(f"tool_result({fr.name}): {resp}")
                if text_parts:
                    messages.append({"role": role, "content": "\n".join(text_parts)})

        # Convert tool schemas to OpenAI tools format
        groq_tools = []
        for t in tools:
            groq_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            })

        data = _groq_request(messages, groq_tools, system)
        return data

    def call_stream(self, contents, system, tools):
        if self.provider == "groq":
            return self._call_groq(contents, system, tools)
        return self._call_gemini(contents, system, tools)

    def stream(self, contents: list, system: str, tools: list[dict]) -> Generator[dict, None, None]:
        """Yield streaming chunks. Each chunk has 'type' ('text' or 'tool_call') and 'data'."""
        if self.provider == "groq":
            yield from self._stream_groq(contents, system, tools)
        else:
            yield from self._stream_gemini(contents, system, tools)

    def _stream_groq(self, contents, system, tools):
        """Stream from Groq, yielding text chunks and complete tool calls."""
        if self.groq_messages:
            messages = self.groq_messages
        else:
            messages = []
            for content in contents:
                role = content.role
                text_parts = []
                for part in content.parts:
                    if getattr(part, "text", None):
                        text_parts.append(part.text)
                    elif getattr(part, "function_call", None):
                        fc = part.function_call
                        args = json.dumps(dict(fc.args), ensure_ascii=False)
                        text_parts.append(f"tool_call({fc.name}): {args}")
                    elif getattr(part, "function_response", None):
                        fr = part.function_response
                        resp = fr.response.get("result", "")
                        text_parts.append(f"tool_result({fr.name}): {resp}")
                if text_parts:
                    messages.append({"role": role, "content": "\n".join(text_parts)})

        groq_tools = []
        for t in tools:
            groq_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            })

        accumulated_text = ""
        tool_calls_acc = {}

        for chunk in _groq_stream(messages, groq_tools, system):
            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})

            if delta.get("content"):
                text = delta["content"]
                accumulated_text += text
                yield {"type": "text", "data": text}

            if delta.get("tool_calls"):
                for tc in delta["tool_calls"]:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": tc.get("id", ""), "name": "", "arguments": ""}
                    if tc.get("id"):
                        tool_calls_acc[idx]["id"] = tc["id"]
                    func = tc.get("function", {})
                    if func.get("name"):
                        tool_calls_acc[idx]["name"] = func["name"]
                    if func.get("arguments"):
                        tool_calls_acc[idx]["arguments"] += func["arguments"]

        for idx in sorted(tool_calls_acc.keys()):
            tc = tool_calls_acc[idx]
            yield {"type": "tool_call", "data": tc}

    def _stream_gemini(self, contents, system, tools):
        """Stream from Gemini, yielding text chunks and complete tool calls."""
        function_declarations = [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            }
            for t in tools
        ]

        for chunk in self.client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[types.Tool(function_declarations=function_declarations)],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
            stream=True,
        ):
            if not chunk.candidates:
                continue
            candidate = chunk.candidates[0]
            if not candidate.content:
                continue

            for part in candidate.content.parts:
                if getattr(part, "text", None) and part.text:
                    yield {"type": "text", "data": part.text}
                elif getattr(part, "function_call", None):
                    fc = part.function_call
                    yield {
                        "type": "tool_call",
                        "data": {
                            "id": fc.name,
                            "name": fc.name,
                            "arguments": json.dumps(dict(fc.args), ensure_ascii=False),
                        },
                    }
