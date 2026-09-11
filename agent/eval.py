"""
Response evaluation module.

After the agent completes a task, this module evaluates the response quality
using an LLM-as-judge approach. This makes the system more than just
"API call → output" by adding quality assurance.

Evaluation Dimensions:
- Faithfulness: Does the response stick to the context?
- Relevance: Does it answer the actual question?
- Completeness: Is the answer complete?
- Groundedness: Are claims supported by context?
"""

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

from agent.llm import LLMClient
from agent.config import get_config

EVAL_MODEL = os.environ.get("EVAL_MODEL", get_config().gemini_model)

EVAL_PROMPT_TEMPLATE = """You are an evaluation assistant. Score the following response on multiple dimensions.

User Query:
{query}

Context Used (RAG chunks):
{context}

Agent Response:
{response}

Tools Called:
{tools}

Score each dimension from 0.0 to 1.0:
1. Faithfulness: Does the response only use information from the context? (1.0 = perfectly faithful, 0.0 = completely hallucinated)
2. Relevance: Does the response actually answer the user's question? (1.0 = perfectly relevant, 0.0 = completely off-topic)
3. Completeness: Does the response cover all aspects of the question? (1.0 = fully complete, 0.0 = missing major parts)
4. Groundedness: Are all claims in the response supported by the context? (1.0 = all claims supported, 0.0 = no support)

Return ONLY a JSON object with these exact keys:
{{"faithfulness": 0.0, "relevance": 0.0, "completeness": 0.0, "groundedness": 0.0, "feedback": "Brief explanation of scores"}}

Do not include any other text, just the JSON."""


@dataclass
class EvaluationResult:
    """Result of response evaluation."""
    faithfulness: float
    relevance: float
    completeness: float
    groundedness: float
    feedback: str
    query: str
    response_preview: str  # First 200 chars of response
    tools_used: list[str]

    @property
    def overall_score(self) -> float:
        """Average of all dimension scores."""
        return (self.faithfulness + self.relevance + self.completeness + self.groundedness) / 4

    @property
    def quality_level(self) -> str:
        """Human-readable quality level."""
        score = self.overall_score
        if score >= 0.9:
            return "Excellent"
        elif score >= 0.7:
            return "Good"
        elif score >= 0.5:
            return "Fair"
        else:
            return "Poor"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d["overall_score"] = self.overall_score
        d["quality_level"] = self.quality_level
        return d


class ResponseEvaluator:
    """Evaluates agent responses using LLM-as-judge."""

    def __init__(self):
        self.enabled = os.environ.get("ENABLE_EVALUATION", "true").lower() == "true"
        if self.enabled:
            self.llm = LLMClient()

    def evaluate(
        self,
        query: str,
        response: str,
        context_chunks: Optional[list[str]] = None,
        tools_called: Optional[list[dict]] = None,
    ) -> Optional[EvaluationResult]:
        """
        Evaluate an agent response.

        Args:
            query: The original user query
            response: The agent's final response
            context_chunks: RAG chunks used (if any)
            tools_called: List of tool calls made (name + args)

        Returns:
            EvaluationResult or None if evaluation disabled
        """
        if not self.enabled:
            return None

        # Format context
        if context_chunks:
            context_text = "\n\n".join(f"[Chunk {i+1}]\n{chunk}" for i, chunk in enumerate(context_chunks))
        else:
            context_text = "(No RAG context used)"

        # Format tools
        if tools_called:
            tools_text = "\n".join(
                f"- {t.get('name', 'unknown')}: {json.dumps(t.get('args', {}), ensure_ascii=False)[:100]}"
                for t in tools_called
            )
        else:
            tools_text = "(No tools called)"

        # Build prompt
        prompt = EVAL_PROMPT_TEMPLATE.format(
            query=query,
            context=context_text,
            response=response[:2000],  # Limit response length for evaluation
            tools=tools_text,
        )

        try:
            # Check env again dynamically - user may have disabled mid-session
            if os.environ.get("ENABLE_EVALUATION", "true").lower() == "false":
                return None

            # Make evaluation LLM call - support both Gemini and Groq
            from agent.ratelimit import with_retries

            # Groq provider has no self.llm.client, fallback to Gemini-style eval via Groq API
            if getattr(self.llm, "provider", "gemini") == "groq" or not hasattr(self.llm, "client"):
                # Use Groq for eval
                from agent.llm import _get_groq_model
                import json as _json
                import urllib.request
                from agent.config import get_config
                def _do_eval_groq():
                    import os as _os
                    import urllib.request as _req
                    import json as _js
                    payload = {
                        "model": _get_groq_model(),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                    }
                    req = _req.Request(
                        "https://api.groq.com/openai/v1/chat/completions",
                        data=_js.dumps(payload).encode(),
                        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_os.environ.get('GROQ_API_KEY')}", "User-Agent": "Mozilla/5.0"},
                        method="POST",
                    )
                    with _req.urlopen(req) as resp:
                        data = _js.loads(resp.read().decode())
                        # Wrap to mimic Gemini response
                        class _FakePart:
                            text = data["choices"][0]["message"]["content"]
                        class _FakeContent:
                            parts = [_FakePart()]
                        class _FakeCandidate:
                            content = _FakeContent()
                        class _FakeResp:
                            candidates = [_FakeCandidate()]
                        return _FakeResp()
                eval_response = with_retries(_do_eval_groq)
            else:
                from google.genai import types
                def _do_eval():
                    return self.llm.client.models.generate_content(
                        model=EVAL_MODEL,
                        contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
                        config=types.GenerateContentConfig(
                            temperature=0.1,
                        ),
                    )
                eval_response = with_retries(_do_eval)

            # Parse response
            response_text = eval_response.candidates[0].content.parts[0].text

            # Extract JSON from response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start == -1 or json_end == 0:
                raise ValueError("No JSON found in evaluation response")

            scores = json.loads(response_text[json_start:json_end])

            return EvaluationResult(
                faithfulness=float(scores.get("faithfulness", 0)),
                relevance=float(scores.get("relevance", 0)),
                completeness=float(scores.get("completeness", 0)),
                groundedness=float(scores.get("groundedness", 0)),
                feedback=scores.get("feedback", "No feedback provided"),
                query=query,
                response_preview=response[:200],
                tools_used=[t.get("name", "unknown") for t in (tools_called or [])],
            )

        except Exception as e:
            # Quota errors are expected on free tier - don't spam user
            msg = str(e)
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg or "quota" in msg.lower():
                print(f"  [Eval skipped: quota/RPM limit - main answer is fine]")
            else:
                print(f"  [Eval Error: {e}]")
            return None


def format_evaluation(result: EvaluationResult) -> str:
    """Format evaluation result for display."""
    lines = [
        "",
        "=" * 50,
        "📊 Evaluation Scores:",
        f"  Faithfulness:   {result.faithfulness:.2f} {_score_icon(result.faithfulness)}",
        f"  Relevance:      {result.relevance:.2f} {_score_icon(result.relevance)}",
        f"  Completeness:   {result.completeness:.2f} {_score_icon(result.completeness)}",
        f"  Groundedness:   {result.groundedness:.2f} {_score_icon(result.groundedness)}",
        f"  {'─' * 40}",
        f"  Overall:        {result.overall_score:.2f} ({result.quality_level})",
        f"",
        f"  Feedback: {result.feedback}",
        "=" * 50,
    ]
    return "\n".join(lines)


def _score_icon(score: float) -> str:
    """Return icon based on score."""
    if score >= 0.8:
        return "✅"
    elif score >= 0.6:
        return "⚠️"
    else:
        return "❌"
