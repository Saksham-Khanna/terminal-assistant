"""
Token and cost tracking for Agentic IDE.

Tracks the number of LLM calls, prompt/output tokens, and estimated
cost per session/task. Pricing is approximate and pulled from provider
rate cards; it's meant for awareness, not billing.

Gemini 2.0 Flash pricing (approx):
  - Input:  $0.10 / 1M tokens
  - Output: $0.40 / 1M tokens

Groq (varies by model; using gpt-oss-120b approx):
  - Input:  $0.15 / 1M tokens
  - Output: $0.60 / 1M tokens
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict

from agent.config import get_config


# Rough pricing per 1M tokens in USD
PRICING = {
    "gemini": {"input_per_m": 0.10, "output_per_m": 0.40},
    "groq": {"input_per_m": 0.15, "output_per_m": 0.60},
}


@dataclass
class CallRecord:
    """Record of a single LLM API call."""
    timestamp: float
    provider: str
    model: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    iter_count: int = 0
    cost: float = 0.0


@dataclass
class SessionUsage:
    """Aggregated usage for a task/session."""
    calls: list[CallRecord] = field(default_factory=list)
    tool_calls: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        return sum(c.cost for c in self.calls)

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def duration_sec(self) -> float:
        end = self.end_time or time.time()
        return max(0, end - self.start_time)

    def record_call(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        output_tokens: int,
        iteration: int,
    ):
        pricing = PRICING.get(provider, PRICING["gemini"])
        cost = (
            prompt_tokens / 1_000_000 * pricing["input_per_m"]
            + output_tokens / 1_000_000 * pricing["output_per_m"]
        )
        self.calls.append(CallRecord(
            timestamp=time.time(),
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            iter_count=iteration,
            cost=cost,
        ))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["prompt_tokens"] = self.prompt_tokens
        d["output_tokens"] = self.output_tokens
        d["total_tokens"] = self.total_tokens
        d["cost_usd"] = self.cost_usd
        d["total_calls"] = self.total_calls
        d["duration_sec"] = self.duration_sec
        return d


def estimate_gemini_tokens(response) -> tuple[int, int]:
    """Extract prompt/output token counts from a Gemini response."""
    try:
        usage = getattr(response, "usage_metadata", None)
        if usage:
            prompt = int(getattr(usage, "prompt_token_count", 0) or 0)
            output = int(getattr(usage, "candidates_token_count", 0) or 0)
            return prompt, output
    except Exception:
        pass
    return 0, 0


def estimate_groq_tokens(data: dict) -> tuple[int, int]:
    """Extract prompt/output token counts from a Groq response."""
    try:
        usage = data.get("usage", {})
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        output = int(usage.get("completion_tokens", 0) or 0)
        return prompt, output
    except Exception:
        return 0, 0


def format_usage(usage: SessionUsage) -> str:
    """Format usage data for display."""
    cost = usage.cost_usd
    lines = [
        "",
        "=" * 50,
        "📊 Usage Summary:",
        f"  LLM Calls:      {usage.total_calls}",
        f"  Tool Calls:     {usage.tool_calls}",
        f"  Prompt Tokens:  {usage.prompt_tokens:,}",
        f"  Output Tokens:  {usage.output_tokens:,}",
        f"  Total Tokens:   {usage.total_tokens:,}",
        f"  Est. Cost:      ${cost:.4f}",
        f"  Duration:       {usage.duration_sec:.1f}s",
        "=" * 50,
    ]
    if usage.calls:
        lines.insert(1, "  (per call breakdown available with --verbose)")
    return "\n".join(lines)


def estimate_tokens_char_fallback(text: str) -> int:
    """Rough token estimate when API doesn't return usage metadata."""
    return len(text) // 4