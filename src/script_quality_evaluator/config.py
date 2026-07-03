from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class RuntimeConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str | None = field(default=None, repr=False)
    main_model: str = DEFAULT_MODEL
    judge_model: str = DEFAULT_MODEL
    timeout: int = 120
    temperature: float = 0
    top_p: float = 0.1
    max_retries: int = 2

    @classmethod
    def from_env(
        cls,
        overrides: Mapping[str, object] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "RuntimeConfig":
        env = environ if environ is not None else os.environ
        values = overrides or {}

        main_model = _first_value(values, "main_model") or _first_env(env, "SCRIPT_EVAL_MODEL", "MAIN_MODEL") or DEFAULT_MODEL
        return cls(
            base_url=_first_value(values, "base_url")
            or _first_env(env, "SCRIPT_EVAL_BASE_URL", "BASE_URL")
            or DEFAULT_BASE_URL,
            api_key=_first_value(values, "api_key")
            or _first_env(env, "SCRIPT_EVAL_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "API_KEY"),
            main_model=main_model,
            judge_model=_first_value(values, "judge_model")
            or _first_env(env, "SCRIPT_EVAL_JUDGE_MODEL", "JUDGE_MODEL", "SCRIPT_EVAL_MODEL", "MAIN_MODEL")
            or main_model,
            timeout=int(_first_value(values, "timeout") or _first_env(env, "SCRIPT_EVAL_TIMEOUT") or 120),
            temperature=float(_first_value(values, "temperature") or _first_env(env, "SCRIPT_EVAL_TEMPERATURE") or 0),
            top_p=float(_first_value(values, "top_p") or _first_env(env, "SCRIPT_EVAL_TOP_P") or 0.1),
            max_retries=int(_first_value(values, "max_retries") or _first_env(env, "SCRIPT_EVAL_MAX_RETRIES") or 2),
        )

    def has_api_credentials(self) -> bool:
        return bool(self.api_key and self.base_url)


def _first_value(values: Mapping[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_env(env: Mapping[str, str], *keys: str) -> str | None:
    for key in keys:
        value = env.get(key)
        if value and value.strip():
            return value.strip()
    return None
