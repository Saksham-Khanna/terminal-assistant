"""
Configuration management for Agentic IDE.

Loads settings from (in order of precedence):
  1. Environment variables (.env file)
  2. Agentic config file (agentic.toml / ~/.config/agentic/config.toml)

Config file example:
    [provider]
    model = "gemini"               # "gemini" or "groq"

    [gemini]
    model = "gemini-2.0-flash"

    [groq]
    model = "openai/gpt-oss-120b"

    [workspace]
    root = "./workspace"

    [context]
    budget_tokens = 50000
    summarize_tail_turns = 6

    [session]
    dir = "./.sessions"
"""

import os
from typing import Any

import tomllib
from dotenv import load_dotenv

# Load .env first (doesn't override existing env vars)
load_dotenv()

CONFIG_DIR = os.path.abspath(
    os.environ.get("AGENTIC_CONFIG_DIR", os.path.expanduser("~/.config/agentic"))
)
PROJECT_CONFIG = "agentic.toml"

DEFAULTS: dict[str, Any] = {
    "provider": "gemini",
    "workspace": {
        "root": "./workspace",
    },
    "session": {
        "dir": "./.sessions",
    },
    "context": {
        "budget_tokens": 50000,
        "summarize_tail_turns": 6,
    },
    "llm": {
        "rpm": 15,
        "min_interval": 0.5,
        "max_retries": 3,
        "backoff_base": 1.0,
    },
    "sandbox": {
        "enabled": True,
        "image": "python:3.12-slim",
        "memory": "512m",
        "cpus": "2",
        "network": "none",
        "timeout": 60,
    },
    "web": {
        "require_auth": False,
        "token": "",
        "allow_origins": [],
    },
    "gemini": {
        "model": "gemini-3.6-flash",
    },
    "groq": {
        "model": "openai/gpt-oss-120b",
    },
}


def _load_toml(path: str) -> dict[str, Any]:
    """Load a TOML file, returning {} on any error."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """Agentic IDE configuration with layered loading."""

    def __init__(self, config_path: str | None = None):
        # Load config file(s)
        loaded: dict[str, Any] = _deep_merge({}, DEFAULTS)

        # Project-level config
        if os.path.exists(PROJECT_CONFIG):
            loaded = _deep_merge(loaded, _load_toml(PROJECT_CONFIG))

        # User-level config overrides project config
        user_config = os.path.join(CONFIG_DIR, "config.toml")
        if os.path.exists(user_config):
            loaded = _deep_merge(loaded, _load_toml(user_config))

        # Explicit config path overrides everything
        if config_path:
            loaded = _deep_merge(loaded, _load_toml(config_path))

        self._config = loaded

    # --- Accessors ---
    def get(self, key: str, default: Any = None) -> Any:
        """Get a top-level config value."""
        return self._config.get(key, default)

    def section(self, name: str) -> dict[str, Any]:
        """Get a config section as dict."""
        return self._config.get(name, {}) or {}

    # --- Convenience properties ---
    @property
    def provider(self) -> str:
        """Resolve provider from config or env var."""
        return (os.environ.get("MODEL_PROVIDER") or
                self._config.get("provider") or "gemini").lower()

    @property
    def workspace_root(self) -> str:
        """Workspace root directory."""
        return os.environ.get(
            "AGENT_WORKSPACE",
            self.section("workspace").get("root", "./workspace"),
        )

    @property
    def session_dir(self) -> str:
        """Sessions directory."""
        return os.environ.get(
            "AGENT_SESSIONS_DIR",
            self.section("session").get("dir", "./.sessions"),
        )

    @property
    def context_budget_tokens(self) -> int:
        """Context window budget in tokens."""
        return int(os.environ.get(
            "CONTEXT_BUDGET_TOKENS",
            self.section("context").get("budget_tokens", 50000),
        ))

    @property
    def summarize_tail_turns(self) -> int:
        """Number of recent turns to always keep."""
        return int(os.environ.get(
            "SUMMARIZE_TAIL_TURNS",
            self.section("context").get("summarize_tail_turns", 6),
        ))

    @property
    def gemini_model(self) -> str:
        """Gemini model name."""
        return os.environ.get(
            "GEMINI_MODEL",
            self.section("gemini").get("model", "gemini-3.6-flash"),
        )

    @property
    def groq_model(self) -> str:
        """Groq model name."""
        return os.environ.get(
            "GROQ_MODEL",
            self.section("groq").get("model", "openai/gpt-oss-120b"),
        )

    @property
    def has_gemini_key(self) -> bool:
        """True if GEMINI_API_KEY is set."""
        return bool(os.environ.get("GEMINI_API_KEY"))

    @property
    def has_groq_key(self) -> bool:
        """True if GROQ_API_KEY is set."""
        return bool(os.environ.get("GROQ_API_KEY"))

    @property
    def web_require_auth(self) -> bool:
        """Whether the web UI requires an API token."""
        env = os.environ.get("AGENTIC_WEB_AUTH")
        if env is not None:
            return env.strip().lower() in ("1", "true", "yes", "on")
        return bool(self.section("web").get("require_auth", False))

    @property
    def web_token(self) -> str:
        """Web UI API token (env AGENTIC_WEB_TOKEN or [web].token)."""
        return os.environ.get(
            "AGENTIC_WEB_TOKEN",
            self.section("web").get("token", ""),
        ).strip()

    @property
    def web_allow_origins(self) -> list[str]:
        """Allowed browser origins for CORS (empty = same-origin only)."""
        origins = self.section("web").get("allow_origins", []) or []
        return [str(o) for o in origins if str(o).strip()]

    def validate(self) -> list[str]:
        """Return list of missing critical config warnings."""
        warnings = []
        if not self.has_gemini_key and not self.has_groq_key:
            warnings.append(
                "No API key found. Set GEMINI_API_KEY or GROQ_API_KEY in .env, "
                "or run `agentic setup` to configure."
            )
        elif self.provider == "gemini" and not self.has_gemini_key:
            warnings.append(
                "MODEL_PROVIDER is 'gemini' but GEMINI_API_KEY is not set. "
                "Add it to .env or switch provider with MODEL_PROVIDER=groq."
            )
        elif self.provider == "groq" and not self.has_groq_key:
            warnings.append(
                "MODEL_PROVIDER is 'groq' but GROQ_API_KEY is not set. "
                "Add it to .env or switch provider with MODEL_PROVIDER=gemini."
            )
        return warnings


_config: Config | None = None


def get_config() -> Config:
    """Singleton config accessor."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def create_default_config() -> str:
    """Write a default agentic.toml to the project root. Returns path."""
    content = """# Agentic IDE Configuration
# All values are optional - defaults shown below.

[provider]
# "gemini" or "groq"
model = "gemini"

[gemini]
model = "gemini-2.0-flash"

[groq]
model = "openai/gpt-oss-120b"

[workspace]
root = "./workspace"

[context]
budget_tokens = 50000
summarize_tail_turns = 6

[llm]
rpm = 15
min_interval = 0.5
max_retries = 3
backoff_base = 1.0

[sandbox]
enabled = true
image = "python:3.12-slim"
memory = "512m"
cpus = "2"
network = "none"
timeout = 60

[web]
require_auth = false
# token = "change-me"        # or set AGENTIC_WEB_TOKEN in .env
# allow_origins = ["http://localhost:3000"]

[session]
dir = "./.sessions"
"""
    if not os.path.exists(PROJECT_CONFIG):
        with open(PROJECT_CONFIG, "w", encoding="utf-8") as f:
            f.write(content)
    return os.path.abspath(PROJECT_CONFIG)
