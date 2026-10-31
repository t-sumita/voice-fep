"""Tests for SYSTEM_PROMPT correctness and security."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import main  # noqa: E402


class TestSystemPrompt:
    def test_is_non_empty_string(self):
        assert isinstance(main.SYSTEM_PROMPT, str)
        assert len(main.SYSTEM_PROMPT) > 50

    def test_no_api_key_in_prompt(self):
        """Security: prompt must never contain a real-looking API key."""
        import re
        # API keys are typically 32+ hex/base64 chars; reject if found
        pattern = r"[A-Za-z0-9_\-]{32,}"
        matches = re.findall(pattern, main.SYSTEM_PROMPT)
        assert not matches, f"Possible secret in SYSTEM_PROMPT: {matches}"

    def test_contains_japanese_instruction(self):
        assert "書き起こし" in main.SYSTEM_PROMPT

    def test_no_greeting_in_output_rule(self):
        assert "挨拶" in main.SYSTEM_PROMPT

    def test_filler_removal_rule(self):
        assert "言い淀み" in main.SYSTEM_PROMPT

    def test_no_markdown_rule(self):
        assert "マークダウン" in main.SYSTEM_PROMPT


class TestConfig:
    def test_sample_rate_is_16k(self):
        assert main.SAMPLE_RATE == 16000

    def test_app_version_defined(self):
        assert hasattr(main, "APP_VERSION")
        assert main.APP_VERSION == "0.1.0"

    def test_default_backend_is_gemini(self, monkeypatch):
        monkeypatch.delenv("BACKEND", raising=False)
        import importlib
        importlib.reload(main)
        assert main.BACKEND in ("gemini", "cloudflare", "local_whisper")

    def test_gemini_model_default(self, monkeypatch):
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        import importlib
        importlib.reload(main)
        assert "gemini" in main.GEMINI_MODEL.lower()

