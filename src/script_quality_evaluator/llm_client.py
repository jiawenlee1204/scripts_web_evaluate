from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import RuntimeConfig
from .io_utils import error_artifact


class UrlLibTransport:
    def post_json(self, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error: {exc.reason}") from exc


class LLMClient:
    """OpenAI-compatible JSON client for prompt-backed pipeline nodes."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float = 0,
        top_p: float = 0.1,
        timeout: int = 120,
        max_retries: int = 2,
        transport: Any | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("SCRIPT_EVAL_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("SCRIPT_EVAL_MODEL") or "deepseek-v4-flash"
        self.base_url = (base_url or os.getenv("SCRIPT_EVAL_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout
        self.max_retries = max_retries
        self.transport = transport or UrlLibTransport()

    @classmethod
    def from_env(cls) -> "LLMClient":
        return cls()

    @classmethod
    def from_config(cls, config: RuntimeConfig) -> "LLMClient":
        return cls(
            api_key=config.api_key,
            model=config.main_model,
            base_url=config.base_url,
            temperature=config.temperature,
            top_p=config.top_p,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )

    @classmethod
    def judge_from_env(cls, model: str | None = None) -> "LLMClient":
        return cls(
            api_key=os.getenv("SCRIPT_EVAL_JUDGE_API_KEY") or os.getenv("SCRIPT_EVAL_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"),
            model=model or os.getenv("SCRIPT_EVAL_JUDGE_MODEL") or os.getenv("SCRIPT_EVAL_MODEL") or "deepseek-v4-flash",
            base_url=os.getenv("SCRIPT_EVAL_JUDGE_BASE_URL") or os.getenv("SCRIPT_EVAL_BASE_URL") or "https://api.deepseek.com",
        )

    @classmethod
    def judge_from_config(cls, config: RuntimeConfig, model: str | None = None) -> "LLMClient":
        return cls(
            api_key=config.api_key,
            model=model or config.judge_model,
            base_url=config.base_url,
            temperature=config.temperature,
            top_p=config.top_p,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )

    def complete_json(self, node: str, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            return error_artifact(
                node,
                "缺少 API key。请设置 SCRIPT_EVAL_API_KEY、DEEPSEEK_API_KEY 或 OPENAI_API_KEY。",
                "填入 API key 后重新运行 --mode llm",
            )

        messages = self._json_messages(prompt, payload)
        last_content = ""
        for attempt in range(self.max_retries + 1):
            response = self._post(messages, response_format={"type": "json_object"})
            content = self._message_content(response)
            last_content = content
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                if attempt >= self.max_retries:
                    return error_artifact(node, "模型输出不是合法 JSON", "检查 prompt 或增加重试次数")
                messages = self._repair_messages(prompt, payload, content)
                continue
            return parsed
        return error_artifact(node, f"模型输出无法解析：{last_content[:120]}", "检查模型响应")

    def complete_text(self, node: str, prompt: str, payload: dict[str, Any]) -> str:
        if not self.api_key:
            return json.dumps(
                error_artifact(node, "缺少 API key。请设置 SCRIPT_EVAL_API_KEY、DEEPSEEK_API_KEY 或 OPENAI_API_KEY。", "填入 API key 后重新运行"),
                ensure_ascii=False,
                indent=2,
            )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ]
        response = self._post(messages, response_format=None)
        return self._message_content(response)

    def _post(self, messages: list[dict[str, str]], response_format: dict[str, str] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        if response_format:
            payload["response_format"] = response_format
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        return self.transport.post_json(f"{self.base_url}/chat/completions", headers, payload, self.timeout)

    def _json_messages(self, prompt: str, payload: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "请严格输出一个合法 JSON 对象，不要输出 Markdown。\n\n输入 payload:\n"
                + json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ]

    def _repair_messages(self, prompt: str, payload: dict[str, Any], invalid_content: str) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "请修复为合法 JSON，不要改变内容，不要输出 Markdown。\n\n原始 payload:\n"
                + json.dumps(payload, ensure_ascii=False, indent=2)
                + "\n\n待修复内容:\n"
                + invalid_content,
            },
        ]

    def _message_content(self, response: dict[str, Any]) -> str:
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected model response: {response}") from exc


class PromptNodeRunner:
    JUDGE_NODES = {
        "score_calibration",
        "low_score_diagnosis",
        "final_report",
    }

    def __init__(self, client: LLMClient, prompt_dir: str | Path | None = None, judge_client: LLMClient | None = None) -> None:
        self.client = client
        self.judge_client = judge_client or client
        self.prompt_dir = Path(prompt_dir) if prompt_dir else Path(__file__).resolve().parents[2] / "prompts"

    def run(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        prompt = self.load_prompt(node)
        return self._client_for(node).complete_json(node, prompt, payload)

    def run_text(self, node: str, payload: dict[str, Any]) -> str:
        prompt = self.load_prompt(node)
        return self._client_for(node).complete_text(node, prompt, payload)

    def load_prompt(self, node: str) -> str:
        path = self.prompt_dir / f"{node}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    def _client_for(self, node: str) -> LLMClient:
        if node.startswith("score_") or node in self.JUDGE_NODES:
            return self.judge_client
        return self.client
