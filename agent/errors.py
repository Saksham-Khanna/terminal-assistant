"""
User-friendly error handling for Agentic IDE.

Converts raw exceptions into friendly, actionable messages instead of
scary tracebacks. Used by the CLI entry point.
"""

import sys
import os
import traceback

# Map exception messages to friendly hints
HINTS = [
    (lambda e: "GEMINI_API_KEY not set" in str(e),
     "Missing Gemini API key. Get a free one at https://aistudio.google.com/apikey "
     "and add it to your .env file (or run `agentic setup`)."),
    (lambda e: "GROQ_API_KEY not set" in str(e),
     "Missing Groq API key. Get a free one at https://console.groq.com/keys "
     "and add it to your .env file (or run `agentic setup`)."),
    (lambda e: "GROQ_API_KEY rejected" in str(e) or "403" in str(e),
     "Groq API key was rejected (403). Check that your key is valid/active. "
     "Create a new key at https://console.groq.com/keys"),
    (lambda e: "No module named" in str(e),
     "Missing Python dependency. Run: pip install -r requirements.txt "
     "or pip install -e ."),
    (lambda e: "apikey" in str(e).lower() and "invalid" in str(e).lower(),
     "API key seems invalid. Double-check it in your .env file "
     "or run `agentic setup`."),
    (lambda e: isinstance(e, (ConnectionError, TimeoutError, OSError)) or
     "network" in str(e).lower() or "timed out" in str(e).lower(),
     "Network issue. Check your internet connection and try again."),
    (lambda e: "index out of range" in str(e) or "list index" in str(e),
     "Unexpected empty response from the model. The task may be too short "
     "or the API returned nothing. Try again."),
     (lambda e: "CUDNN" in str(e).upper() or "cuda" in str(e).lower(),
      "GPU/CUDA issue with sentence-transformers. Try reinstalling torch "
      "or run with CPU only."),
     (lambda e: "TPM" in str(e) or "tokens per minute" in str(e).lower() or "Limit 8000" in str(e),
       "Groq TPM limit hit (free tier 8000 tokens/min). Project prompt is ~7.5k tokens with AGENT_WORKSPACE=. "
       "Fix: switch to Gemini in .env (MODEL_PROVIDER=gemini, GEMINI_MODEL=gemini-3.5-flash, 1M context) "
       "or wait 20-30s and retry. Groq is fast but TPM is tight for full project context."),
     (lambda e: "Groq API error 429" in str(e) or ("Groq" in str(e) and "429" in str(e)),
       "Groq rate limit (429). Free tier is 30 RPM / 8000 TPM. Wait 20-30s then retry, "
       "or switch to MODEL_PROVIDER=gemini (1M context, more stable for project exploration)."),
     (lambda e: "RESOURCE_EXHAUSTED" in str(e) or "quota" in str(e).lower() or "429" in str(e),
       "Gemini quota exhausted (free tier 20 req/day for gemini-3.6-flash). "
       "Fix: switch model to 'gemini-3.5-flash' in agentic.toml/.env (GEMINI_MODEL=gemini-3.5-flash), "
       "or set MODEL_PROVIDER=groq with GROQ_API_KEY, or wait ~24h for quota reset. "
       "See https://ai.dev/rate-limit"),
      (lambda e: "503" in str(e) or "UNAVAILABLE" in str(e),
       "Model temporarily unavailable (high demand). Retry in few seconds or switch to "
       "GEMINI_MODEL=gemini-3.5-flash-lite / gemini-flash-lite-latest"),
]


def friendly_error(exc: Exception) -> str:
    """Convert an exception into a friendly, actionable message."""
    msg = str(exc)

    # First try known hints
    for matcher, hint in HINTS:
        try:
            if matcher(exc):
                return hint
        except Exception:
            continue

    # Unknown error - show a simplified version
    short = msg.strip().split("\n")[0]
    if len(short) > 200:
        short = short[:200] + "..."
    return (
        f"Something went wrong: {short}\n"
        f"Run with --debug for details, or report this issue."
    )


def format_traceback(exc: Exception) -> str:
    """Format a traceback for debug output."""
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return "".join(tb_lines)


def handle_error(exc: Exception, debug: bool = False):
    """Print a user-friendly error message."""
    if debug:
        print(format_traceback(exc))
    else:
        print(f"\n[Error] {friendly_error(exc)}")