"""
Evaluation history tracking.

Stores evaluation results over time for analysis and debugging.
Helps track improvement and identify patterns in response quality.
"""

import json
import os
from datetime import datetime
from typing import Optional

from agent.eval import EvaluationResult


HISTORY_FILE = os.path.join(os.path.dirname(__file__), "..", "eval_history.json")


def _load_history() -> list[dict]:
    """Load evaluation history from file."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_history(history: list[dict]):
    """Save evaluation history to file."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def record_evaluation(result: EvaluationResult):
    """Record an evaluation result to history."""
    history = _load_history()

    entry = {
        "timestamp": datetime.now().isoformat(),
        "query": result.query,
        "response_preview": result.response_preview,
        "scores": {
            "faithfulness": result.faithfulness,
            "relevance": result.relevance,
            "completeness": result.completeness,
            "groundedness": result.groundedness,
            "overall": result.overall_score,
        },
        "quality_level": result.quality_level,
        "feedback": result.feedback,
        "tools_used": result.tools_used,
    }

    history.append(entry)

    # Keep last 100 entries
    if len(history) > 100:
        history = history[-100:]

    _save_history(history)


def get_statistics() -> dict:
    """Get aggregate statistics from evaluation history."""
    history = _load_history()
    if not history:
        return {"total_evaluations": 0}

    scores = [entry["scores"]["overall"] for entry in history]
    quality_counts = {}
    for entry in history:
        level = entry.get("quality_level", "Unknown")
        quality_counts[level] = quality_counts.get(level, 0) + 1

    return {
        "total_evaluations": len(history),
        "average_score": sum(scores) / len(scores) if scores else 0,
        "min_score": min(scores) if scores else 0,
        "max_score": max(scores) if scores else 0,
        "quality_distribution": quality_counts,
        "recent_entries": history[-5:],  # Last 5 entries
    }


def format_statistics(stats: dict) -> str:
    """Format statistics for display."""
    if stats["total_evaluations"] == 0:
        return "No evaluation history yet."

    lines = [
        "",
        "=" * 50,
        "📈 Evaluation Statistics:",
        f"  Total Evaluations: {stats['total_evaluations']}",
        f"  Average Score:     {stats['average_score']:.2f}",
        f"  Min Score:         {stats['min_score']:.2f}",
        f"  Max Score:         {stats['max_score']:.2f}",
        f"",
        f"  Quality Distribution:",
    ]

    for level, count in stats.get("quality_distribution", {}).items():
        lines.append(f"    {level}: {count}")

    if stats.get("recent_entries"):
        lines.append(f"")
        lines.append(f"  Recent Evaluations:")
        for entry in stats["recent_entries"][-3:]:
            lines.append(f"    [{entry['timestamp'][:10]}] {entry['scores']['overall']:.2f} - {entry['query'][:50]}")

    lines.append("=" * 50)
    return "\n".join(lines)


def clear_history():
    """Clear all evaluation history."""
    _save_history([])
