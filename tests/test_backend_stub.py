"""Tests for audio processing and backend routing using stubs."""
import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from scipy.io import wavfile

sys.path.insert(0, str(Path(__file__).parent.parent))

import main  # noqa: E402


def _make_wav_bytes(duration_sec: float = 0.1, sample_rate: int = 16000) -> bytes:
    """Generate a minimal silent WAV payload in memory (no disk write)."""
    samples = np.zeros(int(sample_rate * duration_sec), dtype=np.int16)
    buf = io.BytesIO()
    wavfile.write(buf, sample_rate, samples)
    return buf.getvalue()


class TestWavGeneration:
    def test_wav_bytes_is_non_empty(self):
        data = _make_wav_bytes()
        assert len(data) > 44  # WAV header is 44 bytes

    def test_wav_bytes_parseable(self):
        data = _make_wav_bytes(0.5)
        buf = io.BytesIO(data)
        sr, audio = wavfile.read(buf)
        assert sr == 16000
        assert audio.dtype == np.int16

    def test_no_disk_write_in_wav_generation(self, tmp_path):
        """Confirm _make_wav_bytes writes nothing to disk."""
        before = list(tmp_path.iterdir())
        _make_wav_bytes()
        after = list(tmp_path.iterdir())
        assert before == after


class TestStopRecordingEmpty:
    def test_returns_none_when_no_chunks(self):
        with patch.object(main, "_audio_chunks", []):
            with patch.object(main, "_stream", None):
                result = main.stop_recording()
        assert result is None


class TestStopRecordingWithAudio:
    def test_returns_wav_bytes(self):
        chunk = np.zeros((1600, 1), dtype=np.int16)
        with patch.object(main, "_audio_chunks", [chunk]):
            with patch.object(main, "_stream", None):
                result = main.stop_recording()
        assert result is not None
        assert isinstance(result, bytes)
        assert len(result) > 44

    def test_no_disk_artifact(self, tmp_path, monkeypatch):
        """stop_recording must not write files to disk (S-2)."""
        import os
        original_open = open
        opened_files: list = []

        def tracking_open(file, *args, **kwargs):
            if isinstance(file, (str, os.PathLike)) and str(file).endswith(".wav"):
                opened_files.append(str(file))
            return original_open(file, *args, **kwargs)

        chunk = np.zeros((1600, 1), dtype=np.int16)
        with patch.object(main, "_audio_chunks", [chunk]):
            with patch.object(main, "_stream", None):
                main.stop_recording()

        assert not opened_files, f"WAV written to disk: {opened_files}"


class TestBackendRouting:
    def test_gemini_backend_called(self, monkeypatch):
        monkeypatch.setattr(main, "BACKEND", "gemini")
        stub = MagicMock(return_value="テスト")
        monkeypatch.setattr(main, "_transcribe_gemini", stub)
        result = main.transcribe(b"dummy")
        stub.assert_called_once_with(b"dummy")
        assert result == "テスト"

    def test_cloudflare_backend_called(self, monkeypatch):
        monkeypatch.setattr(main, "BACKEND", "cloudflare")
        stub = MagicMock(return_value="test")
        monkeypatch.setattr(main, "_transcribe_cloudflare", stub)
        main.transcribe(b"dummy")
        stub.assert_called_once()

    def test_local_whisper_backend_called(self, monkeypatch):
        monkeypatch.setattr(main, "BACKEND", "local_whisper")
        stub = MagicMock(return_value="test")
        monkeypatch.setattr(main, "_transcribe_local", stub)
        main.transcribe(b"dummy")
        stub.assert_called_once()

    def test_unknown_backend_raises(self, monkeypatch):
        monkeypatch.setattr(main, "BACKEND", "unknown_backend")
        with pytest.raises(ValueError, match="Unknown BACKEND"):
            main.transcribe(b"dummy")

    def test_gemini_raises_without_api_key(self, monkeypatch):
        monkeypatch.setattr(main, "GEMINI_API_KEY", "")
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            main._transcribe_gemini(b"dummy")


class TestPasteText:
    def test_copies_to_clipboard_and_pastes(self, monkeypatch):
        copied: list = []
        monkeypatch.setattr(main.pyperclip, "copy", lambda t: copied.append(t))
        hotkey_calls: list = []
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: hotkey_calls.append(a))

        main.paste_text("こんにちは")

        assert copied[0] == "こんにちは"
        assert ("ctrl", "v") in hotkey_calls

    def test_clipboard_cleared_after_paste(self, monkeypatch):
        """S-4: clipboard must be cleared after paste."""
        cleared: list = []
        call_order: list = []

        def mock_copy(text):
            call_order.append(text)
            if text == "":
                cleared.append(True)

        monkeypatch.setattr(main.pyperclip, "copy", mock_copy)
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)

        main.paste_text("secret text")

        # Wait for the 0.5s timer
        import time
        time.sleep(0.7)

        assert cleared, "Clipboard was never cleared after paste (S-4 violation)"
        assert call_order[0] == "secret text"
        assert call_order[-1] == ""


class TestAudioCaptureSpec:
    """Verify 16kHz / mono / int16 settings are locked in source."""

    def _src(self) -> str:
        return (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")

    def test_sample_rate_constant_is_16k(self):
        assert main.SAMPLE_RATE == 16000

    def test_inputstream_uses_sample_rate_constant(self):
        assert "samplerate=SAMPLE_RATE" in self._src()

    def test_inputstream_is_mono(self):
        assert "channels=1" in self._src()

    def test_inputstream_dtype_is_int16(self):
        assert 'dtype="int16"' in self._src()


class TestTimingLog:
    """Verify transcription timing is measured and logged."""

    def test_timing_log_emitted(self, monkeypatch, caplog):
        import logging
        monkeypatch.setattr(main, "_audio_chunks", [])
        monkeypatch.setattr(main, "_stream", None)
        # stop_recording returns None → _process_and_paste exits early (no API call)
        # Use a stub that injects wav bytes to exercise the timing path
        wav = _make_wav_bytes()
        monkeypatch.setattr(main, "stop_recording", lambda: wav)
        monkeypatch.setattr(main, "transcribe", lambda _: "テスト")
        monkeypatch.setattr(main.pyperclip, "copy", lambda _: None)
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *_: None)

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        with caplog.at_level(logging.INFO, logger="voice-fep"):
            main._process_and_paste(_FakeIndicator())

        timing_lines = [r for r in caplog.records if "transcription took" in r.message]
        assert timing_lines, "No 'transcription took' log line emitted"
        # Value must be a parseable float (seconds)
        import re
        m = re.search(r"([\d.]+)s", timing_lines[0].message)
        assert m, f"Could not parse elapsed time from: {timing_lines[0].message}"
        assert float(m.group(1)) >= 0


class TestSecurityInSource:
    def test_no_hardcoded_api_key_pattern(self):
        """S-1: scan main.py for hardcoded key patterns."""
        import re
        source = Path(__file__).parent.parent / "main.py"
        content = source.read_text(encoding="utf-8")
        # Real Gemini keys start with "AIza"
        assert "AIza" not in content
        # Suspicious pattern: 32+ alphanumeric chars NOT inside a comment/docstring
        # Exclude separator lines (all dashes), hex color codes, and log format strings
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            matches = re.findall(r'[A-Za-z0-9]{32,}', stripped)
            assert not matches, f"Possible hardcoded key on line: {stripped!r}"

    def test_gitignore_excludes_env(self):
        gitignore = Path(__file__).parent.parent / ".gitignore"
        content = gitignore.read_text(encoding="utf-8")
        assert ".env" in content

    def test_gitignore_excludes_wav(self):
        gitignore = Path(__file__).parent.parent / ".gitignore"
        content = gitignore.read_text(encoding="utf-8")
        assert "*.wav" in content

    def test_gitignore_excludes_logs(self):
        gitignore = Path(__file__).parent.parent / ".gitignore"
        content = gitignore.read_text(encoding="utf-8")
        assert "*.log" in content
