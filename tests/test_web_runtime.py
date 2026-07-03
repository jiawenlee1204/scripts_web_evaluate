from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from script_quality_evaluator.config import RuntimeConfig
from script_quality_evaluator.pipeline import safe_run_name
from script_quality_evaluator.web_utils import make_unique_run_name, mask_secret, sanitize_upload_filename

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import _preview_file  # noqa: E402


class WebRuntimeTest(unittest.TestCase):
    def test_runtime_config_uses_form_values_before_environment(self) -> None:
        env = {
            "SCRIPT_EVAL_API_KEY": "env-key",
            "SCRIPT_EVAL_BASE_URL": "https://env.example",
            "SCRIPT_EVAL_MODEL": "env-main",
            "SCRIPT_EVAL_JUDGE_MODEL": "env-judge",
        }

        config = RuntimeConfig.from_env(
            {
                "api_key": "form-key",
                "base_url": "https://form.example",
                "main_model": "form-main",
                "judge_model": "form-judge",
            },
            environ=env,
        )

        self.assertEqual(config.api_key, "form-key")
        self.assertEqual(config.base_url, "https://form.example")
        self.assertEqual(config.main_model, "form-main")
        self.assertEqual(config.judge_model, "form-judge")
        self.assertNotIn("form-key", repr(config))

    def test_runtime_config_keeps_cli_environment_defaults(self) -> None:
        config = RuntimeConfig.from_env({}, environ={"DEEPSEEK_API_KEY": "env-key"})

        self.assertEqual(config.api_key, "env-key")
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.main_model, "deepseek-v4-flash")
        self.assertEqual(config.judge_model, "deepseek-v4-flash")

    def test_safe_names_do_not_allow_path_injection_or_overwrite(self) -> None:
        self.assertEqual(safe_run_name("../坏 名字.md"), "坏_名字.md")
        self.assertEqual(sanitize_upload_filename("../../剧本.md"), "剧本.md")

        with tempfile.TemporaryDirectory() as temp_dir:
            output_base = Path(temp_dir)
            (output_base / "剧本").mkdir()
            unique = make_unique_run_name(output_base, "剧本")

        self.assertRegex(unique, r"^剧本_[0-9]{8}_[0-9]{6}_[a-f0-9]{6}$")

    def test_secret_masking_removes_api_key_from_errors(self) -> None:
        message = "HTTP 401 for key sk-test-secret"

        self.assertEqual(mask_secret(message, "sk-test-secret"), "HTTP 401 for key [已隐藏]")

    def test_json_preview_is_formatted_and_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "checkpoint.json"
            path.write_text('{"items": ["第一条", "第二条"]}', encoding="utf-8")

            preview = _preview_file(path, limit=20)

        self.assertIn('"items"', preview)
        self.assertIn("内容较长", preview)


if __name__ == "__main__":
    unittest.main()
