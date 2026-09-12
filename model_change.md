# Model Change — Options & Limits (Sept 2026)

## Current Setup
- `agent/config.py:69-74` `DEFAULTS` + `.env:4` `MODEL_PROVIDER` switches provider per run.
- `agent/llm.py:26` `_get_gemini_model()` / `_get_groq_model()` dynamic via `get_config()`.
- Active: `GEMINI_MODEL=gemini-3.5-flash` (`agent/config.py:70`) primary (1M context), `GROQ_MODEL=openai/gpt-oss-20b` (`.env:6`) fallback.
- Throttle `agent/ratelimit.py:44` `LLM_RATE_RPM` + `LLM_MIN_INTERVAL` shared for both.
- `ENABLE_EVALUATION=false` (`.env:9`) saves 1 extra LLM call.

## Why Groq 429 Now
- Image error: `Groq API error 429 TPM Limit 8000 Used 4964 Requested 7666` (`agent/llm.py:59` urllib path, `webapp/server.py:180` `_agent_stream`).
- Root cause: `AGENT_WORKSPACE=.` (`agent/config.py:46`) -> prompt ~7.6k tokens (system + 10 `TOOL_SCHEMAS` in `agent/tools.py:42` + history) > Groq free `TPM 8000`. Earlier `./workspace` jail was ~2k so passed. `python -c Agent.run(groq) 2.55s` works for short history, fails when chat grows.
- Fix now: `MODEL_PROVIDER=gemini` for exploration (1M ctx), or keep Groq for fast 1-turn tasks only.

## Options Evaluated

### 1. Stay Gemini (Recommended, 0 days)
- Pros: 1M ctx, 5 RPM free but `agent/ratelimit.py` `rpm=5 min_interval=2s` safe. Works with current `AGENT_WORKSPACE=.`.
- Cons: Slower ~6-8s vs Groq 2-3s, still 5 RPM.
- Change: `.env:4 MODEL_PROVIDER=gemini`, `LLM_RATE_RPM=5`, `LLM_MIN_INTERVAL=2`.

### 2. Stay Groq + Reduce Context (1-2 hrs)
- Trim prompt: shorten `agent/core.py:43` SYSTEM_PROMPT, prune `TOOL_SCHEMAS` descriptions, lower `MAX_ITERATIONS=25` (`agent/core.py:61`), enable `should_summarize_groq` earlier (`agent/core.py:175`).
- Could drop to ~5k but still tight at 8k TPM. Needs `LLM_RATE_RPM=30` already.
- Risk: flaky under multi-turn.

### 3. HuggingFace Inference API (Half-day)
- Use `HF_TOKEN` + `huggingface_hub.InferenceClient` like RAG embeddings (`rag/indexer.py`).
- Models: `mistralai/Mistral-7B`, `Qwen/Qwen2.5-7B` via `https://api-inference.huggingface.co/models/<id>`.
- Pros: free tier, no Groq key.
- Cons: tool-calling support weak (need manual JSON parsing), rate limits similar, latency 3-5s, quality below Gemini. Need new provider in `agent/llm.py:188` + `agent/config.py`.

### 4. Ollama Local (Half-day, Best for Offline)
- Setup: `ollama serve`, `ollama pull llama3.1:8b` or `qwen2.5:7b-coder` (tool support).
- Code: add `agent/llm.py` `_call_ollama()` hitting `http://localhost:11434/api/chat`, `agent/config.py:73` `ollama.model = llama3.1:8b`, env `OLLAMA_MODEL` + `OLLAMA_HOST`.
- Pros: no quota, private, free forever, good for demo GIF.
- Cons: needs 8GB+ RAM/VRAM, 5-15s per call, tool-calling less reliable than Gemini, user must install Ollama.
- Env: `MODEL_PROVIDER=ollama`, `OLLAMA_MODEL=llama3.1:8b`.

### 5. OpenAI / Anthropic (Paid, future)
- Add `openai` provider to `agent/llm.py` OpenAI-compatible `/v1/chat/completions` (same as Groq path). Works with any `OPENAI_API_KEY`.
- Pros: best tool-calling, higher limits.
- Cons: paid, not free tier.

## Recommendation (Next)
- Short term: keep `.env:4=gemini` (exploration) + allow user toggle to `groq` for speed via `MODEL_PROVIDER` env (no code change).
- If offline needed: implement Ollama provider (option 4) behind feature flag `OLLAMA_HOST`. Add `pyproject.toml` optional dep none (just `httpx` already).
- Do not use HF for main chat; keep HF only for embeddings.

## Files to Touch if Implementing Ollama/HF
- `agent/llm.py:26,59,188` — add `_get_ollama_model()`, `_call_ollama()`, UA handling.
- `agent/config.py:69,192` — add `ollama` section + `ollama_model` prop.
- `.env.example:11` — add `OLLAMA_MODEL` / `HF_TOKEN` examples.
- `pyproject.toml:28` — no new dep needed (reuse `httpx`/`urllib`).
- `webapp/server.py:101` health to expose `model` per provider.
- `tests/test_llm.py` — mock ollama http.

## Quick Switch Commands
```bash
# Gemini (stable for project root)
# .env: MODEL_PROVIDER=gemini  LLM_RATE_RPM=5  LLM_MIN_INTERVAL=2

# Groq fast (small tasks)
# .env: MODEL_PROVIDER=groq   LLM_RATE_RPM=30 LLM_MIN_INTERVAL=0.5

# Ollama local (after code added)
# ollama pull llama3.1:8b
# .env: MODEL_PROVIDER=ollama  OLLAMA_MODEL=llama3.1:8b
```
