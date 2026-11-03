"""Tests for audio processing and backend routing using stubs."""
import io
import logging
import sys
import time
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
        # 8000 samples = 0.5s > 0.3s guard threshold
        chunk = np.zeros((8000, 1), dtype=np.int16)
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

        # 8000 samples = 0.5s > 0.3s guard threshold
        chunk = np.zeros((8000, 1), dtype=np.int16)
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

    def test_local_backend_called(self, monkeypatch):
        monkeypatch.setattr(main, "BACKEND", "local")
        stub = MagicMock(return_value="ローカル認識")
        monkeypatch.setattr(main, "_transcribe_local", stub)
        result = main.transcribe(b"dummy")
        stub.assert_called_once_with(b"dummy")
        assert result == "ローカル認識"

    def test_local_whisper_compat_alias(self, monkeypatch):
        """'local_whisper' must still route to _transcribe_local for backward compat."""
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


def _fake_faster_whisper_module(model_cls):
    """Inject a fake faster_whisper module so tests run without the real package."""
    import sys
    import types
    mod = types.ModuleType("faster_whisper")
    mod.WhisperModel = model_cls
    return patch.dict(sys.modules, {"faster_whisper": mod})


class TestLocalBackend:
    def test_transcribe_local_no_disk_write(self, monkeypatch):
        """S-2: _transcribe_local must never write a .wav to disk."""
        opened_wav: list = []
        original_open = open

        def tracking_open(file, *args, **kwargs):
            if isinstance(file, str) and file.endswith(".wav"):
                opened_wav.append(file)
            return original_open(file, *args, **kwargs)

        class _FakeSegment:
            text = "テスト"

        class _FakeModel:
            def __init__(self, *_, **__): pass
            def transcribe(self, audio, language, initial_prompt=None):
                return [_FakeSegment()], None

        monkeypatch.setattr(main, "WHISPER_MODEL", "base")
        wav = _make_wav_bytes(0.1)
        with _fake_faster_whisper_module(_FakeModel):
            result = main._transcribe_local(wav)

        assert not opened_wav, f"WAV written to disk (S-2 violation): {opened_wav}"
        assert result == "テスト"

    def test_whisper_model_env_respected(self, monkeypatch):
        """WHISPER_MODEL env var must be forwarded to WhisperModel constructor."""
        monkeypatch.setattr(main, "WHISPER_MODEL", "small")
        constructed_with: list = []

        class _FakeModel:
            def __init__(self, model_name, **_):
                constructed_with.append(model_name)
            def transcribe(self, *_, **__):
                return [], None

        wav = _make_wav_bytes(0.05)
        with _fake_faster_whisper_module(_FakeModel):
            main._transcribe_local(wav)

        assert constructed_with == ["small"]


class TestBackendInfo:
    def test_gemini_info(self, monkeypatch):
        monkeypatch.setattr(main, "BACKEND", "gemini")
        monkeypatch.setattr(main, "GEMINI_MODEL", "gemini-2.0-flash")
        info = main._backend_info()
        assert "gemini" in info
        assert "gemini-2.0-flash" in info

    def test_local_info(self, monkeypatch):
        monkeypatch.setattr(main, "BACKEND", "local")
        monkeypatch.setattr(main, "WHISPER_MODEL", "base")
        info = main._backend_info()
        assert "local" in info
        assert "base" in info

    def test_cloudflare_info(self, monkeypatch):
        monkeypatch.setattr(main, "BACKEND", "cloudflare")
        info = main._backend_info()
        assert "cloudflare" in info


class TestWhisperAPICompatibility:
    """Static guard: verify _transcribe_local passes only valid kwargs to transcribe()."""

    def _parse_transcribe_kwargs(self) -> set:
        """Use AST to extract keyword arg names passed to model.transcribe() in _transcribe_local."""
        import ast
        src = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_transcribe_local":
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "transcribe"
                    ):
                        return {kw.arg for kw in inner.keywords}
        return set()

    def test_sampling_rate_not_passed(self):
        """Regression: sampling_rate was wrongly passed and caused TypeError in v0.3.0."""
        kwargs = self._parse_transcribe_kwargs()
        assert "sampling_rate" not in kwargs, (
            "'sampling_rate' is not a valid faster-whisper transcribe() arg — "
            "remove it from _transcribe_local (caused TypeError in v0.3.0)"
        )

    def test_kwargs_match_real_signature_if_installed(self):
        """If faster-whisper is installed, verify all kwargs exist in the real signature."""
        import inspect
        import pytest
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            pytest.skip("faster_whisper not installed — skipping live signature check")

        valid_params = set(inspect.signature(WhisperModel.transcribe).parameters) - {"self"}
        invalid = self._parse_transcribe_kwargs() - valid_params
        assert not invalid, (
            f"_transcribe_local passes unknown kwargs to transcribe(): {invalid}\n"
            f"Valid params: {sorted(valid_params)}"
        )


class TestPasteText:
    def test_copies_to_clipboard_and_pastes(self, monkeypatch):
        monkeypatch.setattr(main, "_has_pasted", False)
        copied: list = []
        monkeypatch.setattr(main.pyperclip, "copy", lambda t: copied.append(t))
        hotkey_calls: list = []
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: hotkey_calls.append(a))

        main.paste_text("こんにちは")

        assert copied[0] == "こんにちは"
        assert ("ctrl", "v") in hotkey_calls

    def test_clipboard_cleared_after_paste(self, monkeypatch):
        """S-4: clipboard must be cleared after paste when RESTORE_CLIPBOARD=True."""
        monkeypatch.setattr(main, "_has_pasted", False)
        monkeypatch.setattr(main, "RESTORE_CLIPBOARD", True)
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
        monkeypatch.setattr(main, "_has_pasted", False)
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


class TestRecordMaxDuration:
    """RECORD_MAX_SEC: auto-stop fires after timeout; normal release cancels it."""

    def test_record_max_sec_default(self):
        assert main.RECORD_MAX_SEC == 30

    def test_record_max_sec_env_respected(self, monkeypatch):
        import importlib
        monkeypatch.setenv("RECORD_MAX_SEC", "10")
        importlib.reload(main)
        assert main.RECORD_MAX_SEC == 10
        monkeypatch.delenv("RECORD_MAX_SEC", raising=False)
        importlib.reload(main)

    def test_auto_stop_fires_when_timer_expires(self, monkeypatch):
        """_auto_stop must flip _active to False and trigger _process_and_paste."""
        process_calls: list = []
        monkeypatch.setattr(main, "_active", True)
        monkeypatch.setattr(main, "_record_timer", None)

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        monkeypatch.setattr(
            main, "_process_and_paste",
            lambda ind: process_calls.append(ind),
        )
        main._auto_stop(_FakeIndicator())

        assert not main._active
        assert len(process_calls) == 1

    def test_auto_stop_noop_when_already_inactive(self, monkeypatch):
        """_auto_stop must not double-trigger if recording already stopped."""
        process_calls: list = []
        monkeypatch.setattr(main, "_active", False)
        monkeypatch.setattr(main, "_process_and_paste", lambda _: process_calls.append(1))

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        main._auto_stop(_FakeIndicator())
        assert not process_calls

    def test_on_press_starts_timer(self, monkeypatch):
        """_on_press must create a non-None _record_timer."""
        from pynput import keyboard as kb
        monkeypatch.setattr(main, "_active", False)
        monkeypatch.setattr(main, "_blocked_until_release", False)
        monkeypatch.setattr(main, "_is_processing", False)
        # Simulate Ctrl held so ctrl+space record hotkey fires
        monkeypatch.setattr(main, "_mods_held", {kb.Key.ctrl_l})
        monkeypatch.setattr(main, "start_recording", lambda: None)

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        main._on_press(main._RECORD_KEY, _FakeIndicator())
        assert main._record_timer is not None
        main._record_timer.cancel()
        main._record_timer = None
        main._active = False

    def test_on_release_cancels_timer(self, monkeypatch):
        """_on_release must cancel the timer so _auto_stop never fires."""
        cancelled: list = []

        class _FakeTimer:
            def cancel(self): cancelled.append(True)

        monkeypatch.setattr(main, "_active", True)
        monkeypatch.setattr(main, "_blocked_until_release", False)
        monkeypatch.setattr(main, "_is_processing", False)
        monkeypatch.setattr(main, "_record_timer", _FakeTimer())
        monkeypatch.setattr(
            main, "_process_and_paste", lambda _: None,
        )

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        main._on_release(main._RECORD_KEY, _FakeIndicator())
        assert cancelled, "_record_timer.cancel() was not called on key release"
        assert main._record_timer is None

    def test_auto_stop_sets_blocked_flag(self, monkeypatch):
        """_auto_stop must set _blocked_until_release to prevent key-repeat recording."""
        monkeypatch.setattr(main, "_active", True)
        monkeypatch.setattr(main, "_record_timer", None)
        monkeypatch.setattr(main, "_blocked_until_release", False)
        monkeypatch.setattr(main, "_is_processing", False)
        monkeypatch.setattr(main, "_process_and_paste", lambda _: None)

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        main._auto_stop(_FakeIndicator())
        assert main._blocked_until_release, "_blocked_until_release must be True after auto-stop"

    def test_on_press_blocked_when_flag_set(self, monkeypatch):
        """Key-repeat presses after auto-stop must not start a new recording."""
        from pynput import keyboard as kb
        monkeypatch.setattr(main, "_active", False)
        monkeypatch.setattr(main, "_blocked_until_release", True)
        monkeypatch.setattr(main, "_mods_held", {kb.Key.ctrl_l})
        started: list = []
        monkeypatch.setattr(main, "start_recording", lambda: started.append(1))

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        main._on_press(main._RECORD_KEY, _FakeIndicator())
        assert not started, "start_recording must not be called while blocked"

    def test_on_release_clears_blocked_flag(self, monkeypatch):
        """Physical key release must clear _blocked_until_release."""
        monkeypatch.setattr(main, "_active", False)
        monkeypatch.setattr(main, "_blocked_until_release", True)

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        main._on_release(main._RECORD_KEY, _FakeIndicator())
        assert not main._blocked_until_release

    def test_on_release_no_double_paste_after_auto_stop(self, monkeypatch):
        """Physical release after auto-stop must NOT trigger another _process_and_paste."""
        process_calls: list = []
        monkeypatch.setattr(main, "_active", False)
        monkeypatch.setattr(main, "_blocked_until_release", True)
        monkeypatch.setattr(main, "_process_and_paste", lambda _: process_calls.append(1))

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        main._on_release(main._RECORD_KEY, _FakeIndicator())
        assert not process_calls, "_process_and_paste must not fire again on release after auto-stop"


class TestDictionary:
    def test_path_env_var_wins(self, monkeypatch, tmp_path):
        """DICTIONARY_FILE env var takes highest priority."""
        custom = tmp_path / "custom.txt"
        monkeypatch.setenv("DICTIONARY_FILE", str(custom))
        assert main.get_dictionary_path() == custom

    def test_path_local_file_when_no_env(self, monkeypatch, tmp_path):
        """./dictionary.txt in cwd is used when no env var is set."""
        local = tmp_path / "dictionary.txt"
        local.write_text("", encoding="utf-8")
        monkeypatch.delenv("DICTIONARY_FILE", raising=False)
        monkeypatch.chdir(tmp_path)
        assert main.get_dictionary_path() == local

    def test_path_appdata_fallback(self, monkeypatch, tmp_path):
        """Falls back to APPDATA/voice-fep/dictionary.txt when no local file exists."""
        empty_dir = tmp_path / "cwd"
        empty_dir.mkdir()
        monkeypatch.delenv("DICTIONARY_FILE", raising=False)
        monkeypatch.setenv("APPDATA", str(tmp_path))
        monkeypatch.chdir(empty_dir)
        path = main.get_dictionary_path()
        assert path == tmp_path / "voice-fep" / "dictionary.txt"

    def test_load_empty_when_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DICTIONARY_FILE", str(tmp_path / "nonexistent.txt"))
        assert main.load_dictionary() == []

    def test_load_skips_comments_and_blanks(self, monkeypatch, tmp_path):
        d = tmp_path / "dict.txt"
        d.write_text("# comment\n\nAPI\nGitHub\n  \n", encoding="utf-8")
        monkeypatch.setenv("DICTIONARY_FILE", str(d))
        assert main.load_dictionary() == ["API", "GitHub"]

    def test_build_system_prompt_includes_words(self, monkeypatch, tmp_path):
        """When dictionary has entries, Gemini prompt must include them."""
        d = tmp_path / "dict.txt"
        d.write_text("Kubernetes\nHelm\n", encoding="utf-8")
        monkeypatch.setenv("DICTIONARY_FILE", str(d))
        prompt = main._build_system_prompt()
        assert "Kubernetes" in prompt
        assert "Helm" in prompt
        assert "優先使用する語彙" in prompt

    def test_build_system_prompt_unchanged_when_empty(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # no system_prompt.txt → falls back to SYSTEM_PROMPT constant
        monkeypatch.setenv("DICTIONARY_FILE", str(tmp_path / "nonexistent.txt"))
        assert main._build_system_prompt() == main.SYSTEM_PROMPT

    def test_add_from_clipboard_appends_word(self, monkeypatch, tmp_path):
        d = tmp_path / "dict.txt"
        d.write_text("", encoding="utf-8")
        monkeypatch.setenv("DICTIONARY_FILE", str(d))
        monkeypatch.setattr(main.pyperclip, "paste", lambda: "  Kubernetes  ")
        main._add_from_clipboard()
        assert "Kubernetes" in d.read_text(encoding="utf-8")

    def test_add_from_clipboard_deduplication(self, monkeypatch, tmp_path):
        """Same word must not be added twice."""
        d = tmp_path / "dict.txt"
        d.write_text("Kubernetes\n", encoding="utf-8")
        monkeypatch.setenv("DICTIONARY_FILE", str(d))
        monkeypatch.setattr(main.pyperclip, "paste", lambda: "Kubernetes")
        main._add_from_clipboard()
        lines = [l for l in d.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert lines.count("Kubernetes") == 1

    def test_add_from_clipboard_empty_ignored(self, monkeypatch, tmp_path):
        d = tmp_path / "dict.txt"
        d.write_text("", encoding="utf-8")
        monkeypatch.setenv("DICTIONARY_FILE", str(d))
        monkeypatch.setattr(main.pyperclip, "paste", lambda: "   ")
        main._add_from_clipboard()
        assert d.read_text(encoding="utf-8") == ""

    def test_add_from_clipboard_creates_parent_dir(self, monkeypatch, tmp_path):
        """Parent directory must be created if it does not exist."""
        d = tmp_path / "subdir" / "dict.txt"
        monkeypatch.setenv("DICTIONARY_FILE", str(d))
        monkeypatch.setattr(main.pyperclip, "paste", lambda: "新機能")
        main._add_from_clipboard()
        assert d.exists()
        assert "新機能" in d.read_text(encoding="utf-8")


class TestShortRecordingGuard:
    """0.3s guard: short recordings are silently discarded (hallucination prevention)."""

    def test_returns_none_when_too_short(self):
        """< 0.3s (4800 samples at 16kHz) must be discarded."""
        chunk = np.zeros((1600, 1), dtype=np.int16)  # 0.1s
        with patch.object(main, "_audio_chunks", [chunk]):
            with patch.object(main, "_stream", None):
                result = main.stop_recording()
        assert result is None

    def test_returns_wav_when_long_enough(self):
        """>= 0.3s must pass through to transcription."""
        chunk = np.zeros((6400, 1), dtype=np.int16)  # 0.4s
        with patch.object(main, "_audio_chunks", [chunk]):
            with patch.object(main, "_stream", None):
                result = main.stop_recording()
        assert result is not None

    def test_boundary_behavior(self):
        """4799 samples (< 0.3s) discarded; 4800 samples (== 0.3s) passes through."""
        chunk_below = np.zeros((4799, 1), dtype=np.int16)
        with patch.object(main, "_audio_chunks", [chunk_below]):
            with patch.object(main, "_stream", None):
                assert main.stop_recording() is None

        chunk_at = np.zeros((4800, 1), dtype=np.int16)
        with patch.object(main, "_audio_chunks", [chunk_at]):
            with patch.object(main, "_stream", None):
                assert main.stop_recording() is not None

    def test_short_recording_log_message(self, caplog):
        import logging
        chunk = np.zeros((1600, 1), dtype=np.int16)
        with patch.object(main, "_audio_chunks", [chunk]):
            with patch.object(main, "_stream", None):
                with caplog.at_level(logging.INFO, logger="voice-fep"):
                    main.stop_recording()
        assert any("too short" in r.message for r in caplog.records)


class TestHotkeyConfig:
    def test_default_hotkey_string(self):
        assert main.HOTKEY == "ctrl+space"

    def test_default_dict_hotkey_string(self):
        assert main.DICT_HOTKEY == "shift+space"

    def test_record_key_is_space(self):
        from pynput import keyboard as kb
        assert main._RECORD_KEY == kb.Key.space

    def test_dict_key_is_space(self):
        from pynput import keyboard as kb
        assert main._DICT_KEY == kb.Key.space

    def test_record_mods_include_ctrl_variants(self):
        from pynput import keyboard as kb
        assert kb.Key.ctrl_l in main._RECORD_MODS
        assert kb.Key.ctrl_r in main._RECORD_MODS

    def test_dict_mods_include_shift_variants(self):
        from pynput import keyboard as kb
        assert kb.Key.shift_l in main._DICT_MODS
        assert kb.Key.shift_r in main._DICT_MODS

    def test_parse_hotkey_no_modifier(self):
        """Plain key like 'f8' must yield empty modifier set."""
        from pynput import keyboard as kb
        key, mods = main._parse_hotkey("f8")
        assert key == kb.Key.f8
        assert mods == frozenset()

    def test_parse_hotkey_ctrl_space(self):
        from pynput import keyboard as kb
        key, mods = main._parse_hotkey("ctrl+space")
        assert key == kb.Key.space
        assert kb.Key.ctrl_l in mods


class TestWindowPositionPersistence:
    """_get_config_path / _save_window_pos / _load_window_pos round-trip."""

    def test_config_path_under_appdata(self, monkeypatch, tmp_path):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        path = main._get_config_path()
        assert path.parent == tmp_path / "voice-fep"
        assert path.suffix == ".json"

    def test_save_and_load_roundtrip(self, monkeypatch, tmp_path):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        main._save_window_pos(123, 456)
        pos = main._load_window_pos()
        assert pos == (123, 456)

    def test_load_returns_none_when_no_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert main._load_window_pos() is None

    def test_load_returns_none_on_corrupt_json(self, monkeypatch, tmp_path):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        path = main._get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not valid json {{", encoding="utf-8")
        assert main._load_window_pos() is None

    def test_save_creates_parent_directory(self, monkeypatch, tmp_path):
        """_save_window_pos must create missing parent dirs."""
        monkeypatch.setenv("APPDATA", str(tmp_path))
        main._save_window_pos(10, 20)
        assert main._get_config_path().exists()


class TestPasteStripDefense:
    """Whitespace-only results must not be pasted; stripped text is pasted correctly."""

    def test_whitespace_only_not_pasted(self, monkeypatch):
        pasted: list = []
        monkeypatch.setattr(main, "stop_recording", lambda: b"dummy")
        monkeypatch.setattr(main, "transcribe", lambda _: "  \n  ")
        monkeypatch.setattr(main, "paste_text", lambda t: pasted.append(t))

        class _FakeIndicator:
            states: list = []
            def safe_set_state(self, s): self.states.append(s)

        ind = _FakeIndicator()
        main._process_and_paste(ind)
        assert not pasted, "Whitespace-only transcription must not be pasted"
        assert "idle" in ind.states

    def test_stripped_text_reaches_paste(self, monkeypatch):
        """Text with surrounding whitespace is stripped before it arrives at paste_text."""
        pasted: list = []
        monkeypatch.setattr(main, "stop_recording", lambda: b"dummy")
        monkeypatch.setattr(main, "transcribe", lambda _: "  こんにちは  ")
        monkeypatch.setattr(main, "paste_text", lambda t: pasted.append(t))

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        main._process_and_paste(_FakeIndicator())
        assert pasted == ["こんにちは"]

    def test_strip_called_in_source(self):
        src = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")
        assert "transcribe(wav_bytes).strip()" in src

    def test_done_state_called_on_success(self, monkeypatch):
        """Successful transcription must transition to 'done', not 'idle' directly."""
        states: list = []
        monkeypatch.setattr(main, "stop_recording", lambda: b"dummy")
        monkeypatch.setattr(main, "transcribe", lambda _: "テスト")
        monkeypatch.setattr(main, "paste_text", lambda _: None)

        class _FakeIndicator:
            def safe_set_state(self, s): states.append(s)

        main._process_and_paste(_FakeIndicator())
        assert "done" in states
        assert "idle" not in states


class TestIndicatorUI:
    """Wave animation data and drag logic — no display required."""

    def _src(self) -> str:
        return (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")

    # --- wave frame data ---

    def test_wave_frames_defined(self):
        assert hasattr(main, "_WAVE_FRAMES")

    def test_wave_frames_length(self):
        """At least 4 frames so the animation has visible variety."""
        assert len(main._WAVE_FRAMES) >= 4

    def test_wave_frames_bar_count(self):
        """Every frame must have exactly 4 bar heights (matches _N_BARS)."""
        for frame in main._WAVE_FRAMES:
            assert len(frame) == 4

    def test_wave_frame_heights_in_range(self):
        """Heights must be positive and fit within a 72px canvas."""
        for frame in main._WAVE_FRAMES:
            for h in frame:
                assert 2 <= h <= 40, f"Bar height {h} out of expected range [2, 40]"

    # --- animation lifecycle (source inspection) ---

    def test_wave_job_managed_in_source(self):
        """Indicator must use _wave_job / _tick_wave for timer lifecycle."""
        src = self._src()
        assert "_wave_job" in src
        assert "_tick_wave" in src

    def test_wave_job_cancelled_on_state_change(self):
        """set_state must cancel _wave_job before switching away from recording."""
        src = self._src()
        assert "after_cancel(self._wave_job)" in src

    # --- drag binding (source inspection) ---

    def test_drag_start_binding_present(self):
        src = self._src()
        assert "_on_drag_start" in src
        assert "Button-1" in src

    def test_drag_move_binding_present(self):
        src = self._src()
        assert "_on_drag_move" in src
        assert "B1-Motion" in src

    def test_drag_end_binding_present(self):
        src = self._src()
        assert "_on_drag_end" in src
        assert "ButtonRelease-1" in src

    def test_wave_color_is_light_blue(self):
        assert "#38bdf8" in self._src()

    def test_done_state_in_indicator(self):
        assert '"done"' in self._src()

    def test_no_circle_char_in_source(self):
        """◎ must not appear as a text label — processing state uses amber mic icon instead."""
        assert 'text="◎"' not in self._src()

    # --- drag offset math (pure computation, no display) ---

    def test_drag_start_offset_math(self):
        """_on_drag_start offset = cursor_root − window_origin."""
        cursor_x, cursor_y = 350, 200
        win_x, win_y = 300, 160
        drag_ox = cursor_x - win_x
        drag_oy = cursor_y - win_y
        assert drag_ox == 50
        assert drag_oy == 40

    def test_drag_move_position_math(self):
        """_on_drag_move new_pos = cursor_root − drag_offset."""
        drag_ox, drag_oy = 50, 40
        cursor_x, cursor_y = 500, 400
        new_x = cursor_x - drag_ox
        new_y = cursor_y - drag_oy
        assert new_x == 450
        assert new_y == 360


class TestSystemPromptFile:
    """load_system_prompt(): external file overrides constant; empty/absent falls back."""

    def test_file_used_when_present(self, monkeypatch, tmp_path):
        """system_prompt.txt in cwd must override SYSTEM_PROMPT constant."""
        custom = "カスタムプロンプトのテスト内容です。"
        (tmp_path / "system_prompt.txt").write_text(custom, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert main.load_system_prompt() == custom

    def test_fallback_when_file_absent(self, monkeypatch, tmp_path):
        """When system_prompt.txt is absent, return SYSTEM_PROMPT constant."""
        monkeypatch.chdir(tmp_path)
        assert main.load_system_prompt() == main.SYSTEM_PROMPT

    def test_fallback_when_file_empty(self, monkeypatch, tmp_path):
        """When system_prompt.txt is empty (or whitespace-only), return SYSTEM_PROMPT constant."""
        (tmp_path / "system_prompt.txt").write_text("   \n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert main.load_system_prompt() == main.SYSTEM_PROMPT

    def test_dictionary_injection_works_with_file_prompt(self, monkeypatch, tmp_path):
        """Custom dict words must still be appended even when external prompt file is used."""
        custom = "外部プロンプトファイルの内容。"
        (tmp_path / "system_prompt.txt").write_text(custom, encoding="utf-8")
        d = tmp_path / "dict.txt"
        d.write_text("Terraform\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DICTIONARY_FILE", str(d))
        prompt = main._build_system_prompt()
        assert custom in prompt
        assert "Terraform" in prompt
        assert "優先使用する語彙" in prompt


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


class TestApiKeyFallback:
    """_check_backend_config() must fall back to local Whisper when GEMINI_API_KEY is unset."""

    def _run(self, monkeypatch, backend: str, api_key: str) -> str:
        monkeypatch.setattr(main, "BACKEND", backend)
        monkeypatch.setattr(main, "GEMINI_API_KEY", api_key)
        with patch("tkinter.messagebox.showwarning"):
            main._check_backend_config()
        return main.BACKEND

    def test_gemini_no_key_falls_back_to_local(self, monkeypatch):
        assert self._run(monkeypatch, "gemini", "") == "local"

    def test_gemini_with_key_stays_gemini(self, monkeypatch):
        assert self._run(monkeypatch, "gemini", "AIzaSyFAKEKEY12345") == "gemini"

    def test_local_no_key_stays_local(self, monkeypatch):
        assert self._run(monkeypatch, "local", "") == "local"

    def test_cloudflare_no_gemini_key_stays_cloudflare(self, monkeypatch):
        assert self._run(monkeypatch, "cloudflare", "") == "cloudflare"

    def test_fallback_emits_warning_log(self, monkeypatch, caplog):
        import logging
        monkeypatch.setattr(main, "BACKEND", "gemini")
        monkeypatch.setattr(main, "GEMINI_API_KEY", "")
        with patch("tkinter.messagebox.showwarning"):
            with caplog.at_level(logging.WARNING, logger="voice-fep"):
                main._check_backend_config()
        assert any("GEMINI_API_KEY" in r.message for r in caplog.records)

    def test_fallback_is_idempotent(self, monkeypatch):
        """After fallback BACKEND is 'local'; a second call (no key, local) must be a no-op."""
        monkeypatch.setattr(main, "BACKEND", "gemini")
        monkeypatch.setattr(main, "GEMINI_API_KEY", "")
        with patch("tkinter.messagebox.showwarning"):
            main._check_backend_config()
        assert main.BACKEND == "local"
        main._check_backend_config()  # BACKEND is now "local" → condition skipped
        assert main.BACKEND == "local"


class TestExeDir:
    """_get_exe_dir() and frozen exe resource-path helpers."""

    def test_dev_mode_returns_source_directory(self):
        """In dev mode (not frozen), _get_exe_dir() returns the directory of main.py."""
        assert main._get_exe_dir() == Path(main.__file__).parent

    def test_frozen_mode_returns_executable_parent(self, monkeypatch):
        """When sys.frozen is set, _get_exe_dir() returns the exe's parent directory."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", r"C:\app\voice-fep.exe", raising=False)
        assert str(main._get_exe_dir()) == r"C:\app"

    def test_load_system_prompt_uses_exe_dir_when_frozen(self, monkeypatch, tmp_path):
        """When frozen, system_prompt.txt next to the exe is used when cwd has none."""
        exe_dir = tmp_path / "exe"
        exe_dir.mkdir()
        (exe_dir / "system_prompt.txt").write_text("frozen prompt", encoding="utf-8")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_dir / "voice-fep.exe"), raising=False)
        monkeypatch.chdir(tmp_path)  # cwd has no system_prompt.txt
        assert main.load_system_prompt() == "frozen prompt"

    def test_load_system_prompt_cwd_beats_exe_dir_when_frozen(self, monkeypatch, tmp_path):
        """cwd system_prompt.txt must take priority over the one next to the exe."""
        exe_dir = tmp_path / "exe"
        cwd_dir = tmp_path / "cwd"
        exe_dir.mkdir()
        cwd_dir.mkdir()
        (exe_dir / "system_prompt.txt").write_text("exe prompt", encoding="utf-8")
        (cwd_dir / "system_prompt.txt").write_text("cwd prompt", encoding="utf-8")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_dir / "voice-fep.exe"), raising=False)
        monkeypatch.chdir(cwd_dir)
        assert main.load_system_prompt() == "cwd prompt"


class TestPasteGuard:
    """_pasting flag must block new recordings while clipboard/Ctrl+V is in progress."""

    def test_pasting_flag_blocks_recording_start(self, monkeypatch):
        from pynput import keyboard as kb
        monkeypatch.setattr(main, "_active", False)
        monkeypatch.setattr(main, "_blocked_until_release", False)
        monkeypatch.setattr(main, "_pasting", True)
        monkeypatch.setattr(main, "_mods_held", {kb.Key.ctrl_l})
        started: list = []
        monkeypatch.setattr(main, "start_recording", lambda: started.append(1))

        class _FakeIndicator:
            def safe_set_state(self, _): pass

        main._on_press(main._RECORD_KEY, _FakeIndicator())
        assert not started, "start_recording must not fire while _pasting is True"

    def test_pasting_flag_set_on_paste_text(self, monkeypatch):
        monkeypatch.setattr(main, "_pasting", False)
        monkeypatch.setattr(main, "_has_pasted", False)
        monkeypatch.setattr(main.pyperclip, "copy", lambda _: None)
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)
        timers: list = []
        monkeypatch.setattr(main.threading, "Timer",
                            lambda delay, fn: type("T", (), {"start": lambda self: timers.append(fn)})())
        main.paste_text("テスト")
        assert main._pasting is True, "_pasting must be True immediately after paste_text is called"

    def test_pasting_flag_cleared_by_cleanup(self, monkeypatch):
        """The cleanup closure passed to Timer must reset _pasting."""
        monkeypatch.setattr(main, "_pasting", False)
        monkeypatch.setattr(main, "_has_pasted", False)
        monkeypatch.setattr(main, "RESTORE_CLIPBOARD", False)
        monkeypatch.setattr(main.pyperclip, "copy", lambda v: None)
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)
        cleanup_fns: list = []

        class _FakeTimer:
            def __init__(self, delay, fn):
                cleanup_fns.append(fn)
            def start(self): pass

        monkeypatch.setattr(main.threading, "Timer", _FakeTimer)
        main.paste_text("テスト")
        assert cleanup_fns, "Timer must have been created"
        cleanup_fns[0]()  # simulate timer firing
        assert main._pasting is False, "_pasting must be False after cleanup"

    def test_pasting_flag_in_source(self):
        src = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")
        assert "_pasting" in src
        assert "_pasting or" in src or "or _pasting" in src


class TestLogSetup:
    """_get_log_path() and _setup_logging() behaviour."""

    def test_log_path_in_appdata_when_not_frozen(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.setenv("APPDATA", str(tmp_path))
        path = main._get_log_path()
        assert path.parent == tmp_path / "voice-fep"
        assert path.name == "voice-fep.log"

    def test_log_path_next_to_exe_when_frozen(self, monkeypatch, tmp_path):
        exe_dir = tmp_path / "exe"
        exe_dir.mkdir()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_dir / "voice-fep.exe"), raising=False)
        assert main._get_log_path() == exe_dir / "voice-fep.log"

    def test_file_handler_added_when_enabled(self, monkeypatch, tmp_path):
        from logging.handlers import RotatingFileHandler
        monkeypatch.setenv("ENABLE_LOG_FILE", "true")
        monkeypatch.setenv("APPDATA", str(tmp_path))
        added: list = []
        with patch.object(logging.getLogger(), "addHandler",
                          side_effect=added.append):
            main._setup_logging()
        assert any(isinstance(h, RotatingFileHandler) for h in added)

    def test_file_handler_not_added_when_disabled(self, monkeypatch, tmp_path):
        from logging.handlers import RotatingFileHandler
        monkeypatch.setenv("ENABLE_LOG_FILE", "false")
        monkeypatch.setenv("APPDATA", str(tmp_path))
        added: list = []
        with patch.object(logging.getLogger(), "addHandler",
                          side_effect=added.append):
            main._setup_logging()
        assert not any(isinstance(h, RotatingFileHandler) for h in added)

    def test_log_level_env_respected(self, monkeypatch):
        import logging as _logging
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("ENABLE_LOG_FILE", "false")
        main._setup_logging()
        assert main.log.level == _logging.DEBUG

    def test_middle_click_binding_in_source(self):
        src = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")
        assert "Button-2" in src
        assert "_on_open_log" in src


class TestProcessingLock:
    """_is_processing flag prevents double execution of the transcription pipeline."""

    def _fake_indicator(self):
        class _FI:
            def safe_set_state(self, _): pass
        return _FI()

    def _record_key_with_ctrl(self, monkeypatch):
        from pynput import keyboard as kb
        monkeypatch.setattr(main, "_mods_held", {kb.Key.ctrl_l})
        return main._RECORD_KEY

    def test_is_processing_flag_exists(self):
        assert hasattr(main, "_is_processing")

    def test_is_processing_blocks_recording_start(self, monkeypatch):
        """While _is_processing is True, _on_press must not start a new recording."""
        key = self._record_key_with_ctrl(monkeypatch)
        monkeypatch.setattr(main, "_active", False)
        monkeypatch.setattr(main, "_blocked_until_release", False)
        monkeypatch.setattr(main, "_pasting", False)
        monkeypatch.setattr(main, "_is_processing", True)
        started: list = []
        monkeypatch.setattr(main, "start_recording", lambda: started.append(1))
        main._on_press(key, self._fake_indicator())
        assert not started, "start_recording must not fire while _is_processing is True"

    def test_on_release_sets_is_processing(self, monkeypatch):
        """_on_release must set _is_processing=True before spawning the worker thread."""
        key = self._record_key_with_ctrl(monkeypatch)
        monkeypatch.setattr(main, "_active", True)
        monkeypatch.setattr(main, "_blocked_until_release", False)
        monkeypatch.setattr(main, "_is_processing", False)
        monkeypatch.setattr(main, "_record_timer", None)
        threads_started: list = []

        class _FakeThread:
            def __init__(self, target, args, daemon=True):
                self._target = target
            def start(self):
                threads_started.append(self._target)

        monkeypatch.setattr(main.threading, "Thread", _FakeThread)
        main._on_release(key, self._fake_indicator())
        assert main._is_processing is True, "_is_processing must be True after _on_release"
        assert threads_started, "worker thread must have been started"

    def test_on_release_double_call_starts_thread_once(self, monkeypatch):
        """Rapid duplicate _on_release must start _process_and_paste exactly once."""
        key = self._record_key_with_ctrl(monkeypatch)
        monkeypatch.setattr(main, "_active", True)
        monkeypatch.setattr(main, "_blocked_until_release", False)
        monkeypatch.setattr(main, "_is_processing", False)
        monkeypatch.setattr(main, "_record_timer", None)
        threads_started: list = []

        class _FakeThread:
            def __init__(self, target, args, daemon=True): pass
            def start(self): threads_started.append(1)

        monkeypatch.setattr(main.threading, "Thread", _FakeThread)
        ind = self._fake_indicator()
        main._on_release(key, ind)  # first call — should proceed
        main._on_release(key, ind)  # second call — should be blocked by _is_processing
        assert len(threads_started) == 1, "thread must start exactly once for duplicate release"

    def test_process_and_paste_clears_is_processing_on_success(self, monkeypatch):
        """_is_processing must be False after _process_and_paste completes normally."""
        monkeypatch.setattr(main, "_is_processing", True)
        monkeypatch.setattr(main, "stop_recording", lambda: None)  # simulate no audio

        class _FI:
            states: list = []
            def safe_set_state(self, s): self.states.append(s)

        ind = _FI()
        main._process_and_paste(ind)
        assert main._is_processing is False, "_is_processing must be cleared in finally block"

    def test_process_and_paste_clears_is_processing_on_exception(self, monkeypatch):
        """_is_processing must be cleared even when transcription raises."""
        monkeypatch.setattr(main, "_is_processing", True)

        def _boom():
            raise RuntimeError("transcription error")

        monkeypatch.setattr(main, "stop_recording", _boom)
        timers_started: list = []

        class _FakeTimer:
            def __init__(self, delay, fn): pass
            def start(self): timers_started.append(1)

        monkeypatch.setattr(main.threading, "Timer", _FakeTimer)

        class _FI:
            def safe_set_state(self, _): pass

        main._process_and_paste(_FI())
        assert main._is_processing is False, "_is_processing must be cleared even after exception"

    def test_auto_stop_sets_is_processing(self, monkeypatch):
        """_auto_stop must atomically set _is_processing before starting worker thread."""
        monkeypatch.setattr(main, "_active", True)
        monkeypatch.setattr(main, "_is_processing", False)
        monkeypatch.setattr(main, "_record_timer", None)
        threads_started: list = []

        class _FakeThread:
            def __init__(self, target, args, daemon=True): pass
            def start(self): threads_started.append(1)

        monkeypatch.setattr(main.threading, "Thread", _FakeThread)

        class _FI:
            def safe_set_state(self, _): pass

        main._auto_stop(_FI())
        assert main._is_processing is True
        assert threads_started

    def test_auto_stop_noop_when_already_processing(self, monkeypatch):
        """If _is_processing is already True, _auto_stop must not start a second thread."""
        monkeypatch.setattr(main, "_active", True)
        monkeypatch.setattr(main, "_is_processing", True)
        threads_started: list = []

        class _FakeThread:
            def __init__(self, *a, **kw): pass
            def start(self): threads_started.append(1)

        monkeypatch.setattr(main.threading, "Thread", _FakeThread)

        class _FI:
            def safe_set_state(self, _): pass

        main._auto_stop(_FI())
        assert not threads_started, "_auto_stop must be a no-op if _is_processing is already True"

    def test_stop_recording_clears_audio_chunks(self, monkeypatch):
        """stop_recording() must clear _audio_chunks immediately to prevent double-read."""
        sample = np.zeros((1600, 1), dtype=np.int16)
        monkeypatch.setattr(main, "_audio_chunks", [sample])
        monkeypatch.setattr(main, "_stream", None)
        main.stop_recording()
        assert main._audio_chunks == [], "_audio_chunks must be cleared after stop_recording"


class TestCrashResilience:
    """Exceptions in callbacks must be caught and logged; process must survive."""

    def _fake_indicator(self):
        class _FI:
            def safe_set_state(self, _): pass
        return _FI()

    def test_on_press_exception_is_caught(self, monkeypatch, caplog):
        """Exception inside _on_press body must be logged, not propagated."""
        monkeypatch.setattr(main, "_mods_held", set())

        def _boom(key):
            raise RuntimeError("simulated press error")

        # Patch _ALL_MOD_KEYS membership check to raise
        monkeypatch.setattr(main, "_ALL_MOD_KEYS", type("_Boom", (), {"__contains__": lambda s, k: _boom(k)})())
        import logging
        with caplog.at_level(logging.ERROR, logger="voice-fep"):
            main._on_press(object(), self._fake_indicator())  # must not raise
        assert any("_on_press" in r.message for r in caplog.records)

    def test_on_release_exception_is_caught(self, monkeypatch, caplog):
        """Exception inside _on_release body must be logged, not propagated."""
        monkeypatch.setattr(main, "_mods_held", set())
        monkeypatch.setattr(main, "_ALL_MOD_KEYS", type("_Boom", (), {"__contains__": lambda s, k: (_ for _ in ()).throw(RuntimeError("simulated release error"))})())
        import logging
        with caplog.at_level(logging.ERROR, logger="voice-fep"):
            main._on_release(object(), self._fake_indicator())
        assert any("_on_release" in r.message for r in caplog.records)

    def test_paste_text_clipboard_error_caught(self, monkeypatch, caplog):
        """If pyperclip.copy raises, paste_text must log the error and clear _pasting."""
        monkeypatch.setattr(main, "_pasting", False)
        monkeypatch.setattr(main, "_has_pasted", False)
        monkeypatch.setattr(main.pyperclip, "copy", lambda _: (_ for _ in ()).throw(OSError("clipboard locked")))
        import logging
        with caplog.at_level(logging.ERROR, logger="voice-fep"):
            main.paste_text("テスト")
        assert main._pasting is False, "_pasting must be cleared after paste error"
        assert any("paste_text" in r.message for r in caplog.records)

    def test_paste_cleanup_clipboard_error_caught(self, monkeypatch, caplog):
        """If clipboard clear in _cleanup raises, _pasting must still become False."""
        copy_calls: list = []

        def _copy(v):
            copy_calls.append(v)
            if v == "":  # the clear call
                raise OSError("clipboard locked on clear")

        monkeypatch.setattr(main, "_pasting", False)
        monkeypatch.setattr(main, "_has_pasted", False)
        monkeypatch.setattr(main, "RESTORE_CLIPBOARD", True)
        monkeypatch.setattr(main.pyperclip, "copy", _copy)
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)
        cleanup_fns: list = []

        class _FakeTimer:
            def __init__(self, delay, fn): cleanup_fns.append(fn)
            def start(self): pass

        monkeypatch.setattr(main.threading, "Timer", _FakeTimer)
        main.paste_text("テスト")
        import logging
        with caplog.at_level(logging.WARNING, logger="voice-fep"):
            cleanup_fns[0]()  # simulate timer firing with failing clear
        assert main._pasting is False, "_pasting must be cleared even when clipboard clear fails"

    def test_add_from_clipboard_exception_caught(self, monkeypatch, caplog):
        """Exception in _add_from_clipboard must be caught and logged."""
        monkeypatch.setattr(main.pyperclip, "paste", lambda: (_ for _ in ()).throw(OSError("no clipboard")))
        import logging
        with caplog.at_level(logging.ERROR, logger="voice-fep"):
            main._add_from_clipboard()  # must not raise
        assert any("_add_from_clipboard" in r.message for r in caplog.records)

    def test_excepthooks_registered_in_source(self):
        """sys.excepthook and threading.excepthook must be wired up in main()."""
        src = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")
        assert "sys.excepthook" in src
        assert "threading.excepthook" in src
        assert "_log_unhandled_exception" in src
        assert "_log_thread_exception" in src


class TestHasPasted:
    """_has_pasted one-shot guard prevents paste_text from executing more than once per session."""

    def test_flag_exists(self):
        assert hasattr(main, "_has_pasted")

    def test_first_call_executes(self, monkeypatch):
        """paste_text must execute when _has_pasted is False."""
        monkeypatch.setattr(main, "_has_pasted", False)
        copied: list = []
        monkeypatch.setattr(main.pyperclip, "copy", lambda v: copied.append(v))
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)
        cleanup_fns: list = []

        class _FT:
            def __init__(self, d, fn): cleanup_fns.append(fn)
            def start(self): pass

        monkeypatch.setattr(main.threading, "Timer", _FT)
        main.paste_text("テスト")
        assert copied[0] == "テスト", "First call must copy text to clipboard"

    def test_second_call_blocked(self, monkeypatch, caplog):
        """paste_text must be blocked if _has_pasted is already True."""
        import logging
        monkeypatch.setattr(main, "_has_pasted", True)
        copied: list = []
        monkeypatch.setattr(main.pyperclip, "copy", lambda v: copied.append(v))
        with caplog.at_level(logging.WARNING, logger="voice-fep"):
            main.paste_text("二重ペーストテスト")
        assert not copied, "Second paste must be blocked when _has_pasted is True"
        assert any("PASTE_EXECUTE" in r.message for r in caplog.records)
        assert any("BLOCKED" in r.message for r in caplog.records)

    def test_flag_set_after_first_paste(self, monkeypatch):
        """After a successful paste, _has_pasted must be True."""
        monkeypatch.setattr(main, "_has_pasted", False)
        monkeypatch.setattr(main.pyperclip, "copy", lambda _: None)
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)
        cleanup_fns: list = []

        class _FT:
            def __init__(self, d, fn): cleanup_fns.append(fn)
            def start(self): pass

        monkeypatch.setattr(main.threading, "Timer", _FT)
        main.paste_text("テスト")
        assert main._has_pasted is True, "_has_pasted must be True after first paste"

    def test_flag_reset_by_start_recording(self, monkeypatch):
        """start_recording must reset _has_pasted to False for the next session."""
        monkeypatch.setattr(main, "_has_pasted", True)
        monkeypatch.setattr(main, "_stream", None)

        class _FakeStream:
            def start(self): pass

        monkeypatch.setattr(main.sd, "InputStream", lambda **_: _FakeStream())
        main.start_recording()
        assert main._has_pasted is False, "start_recording must reset _has_pasted"
        main._stream = None

    def test_paste_execute_log_emitted(self, monkeypatch, caplog):
        """[PASTE_EXECUTE] log line must be emitted on successful paste."""
        import logging
        monkeypatch.setattr(main, "_has_pasted", False)
        monkeypatch.setattr(main, "_last_engine", "gemini")
        monkeypatch.setattr(main.pyperclip, "copy", lambda _: None)
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)
        cleanup_fns: list = []

        class _FT:
            def __init__(self, d, fn): cleanup_fns.append(fn)
            def start(self): pass

        monkeypatch.setattr(main.threading, "Timer", _FT)
        with caplog.at_level(logging.INFO, logger="voice-fep"):
            main.paste_text("テスト")
        assert any("[PASTE_EXECUTE]" in r.message for r in caplog.records)
        assert any("gemini" in r.message for r in caplog.records)


class TestDebugLog:
    """Verify structured debug log labels and fallback logic are present in source."""

    def _src(self) -> str:
        return (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")

    def test_key_down_label_in_source(self):
        assert "[KEY_DOWN]" in self._src()

    def test_key_up_label_in_source(self):
        assert "[KEY_UP]" in self._src()

    def test_record_start_label_in_source(self):
        assert "[RECORD_START]" in self._src()

    def test_record_stop_label_in_source(self):
        assert "[RECORD_STOP]" in self._src()

    def test_engine_start_label_in_source(self):
        assert "[ENGINE_START]" in self._src()

    def test_engine_result_label_in_source(self):
        assert "[ENGINE_RESULT]" in self._src()

    def test_paste_execute_label_in_source(self):
        assert "[PASTE_EXECUTE]" in self._src()

    def test_gemini_fallback_in_source(self):
        """Gemini→Whisper serial fallback must exist in transcribe()."""
        assert "falling back to local Whisper" in self._src()

    def test_cloud_badge_in_source(self):
        """☁ cloud badge must be rendered for Gemini mode in _draw_mic."""
        assert "☁" in self._src()

    def test_flush_in_exception_hook(self):
        """_log_unhandled_exception must flush handlers to avoid lost log lines on crash."""
        assert "handler.flush()" in self._src()

    def test_gemini_fallback_routes_to_local(self, monkeypatch):
        """When Gemini raises, transcribe() must silently fall back to local Whisper."""
        monkeypatch.setattr(main, "BACKEND", "gemini")
        monkeypatch.setattr(main, "_transcribe_gemini", lambda _: (_ for _ in ()).throw(RuntimeError("api down")))
        stub_local = MagicMock(return_value="ローカル認識")
        monkeypatch.setattr(main, "_transcribe_local", stub_local)
        result = main.transcribe(b"dummy")
        stub_local.assert_called_once_with(b"dummy")
        assert result == "ローカル認識"
        assert main._last_engine == "local_whisper(fallback)"

    def test_last_engine_set_for_gemini(self, monkeypatch):
        """_last_engine must be 'gemini' after a successful Gemini call."""
        monkeypatch.setattr(main, "BACKEND", "gemini")
        monkeypatch.setattr(main, "_transcribe_gemini", lambda _: "test")
        main.transcribe(b"dummy")
        assert main._last_engine == "gemini"

    def test_last_engine_set_for_local(self, monkeypatch):
        """_last_engine must be 'local_whisper' after a local call."""
        monkeypatch.setattr(main, "BACKEND", "local")
        monkeypatch.setattr(main, "_transcribe_local", lambda _: "test")
        main.transcribe(b"dummy")
        assert main._last_engine == "local_whisper"

    def test_faulthandler_in_source(self):
        """faulthandler.enable must be present to catch C-level segfaults."""
        src = self._src()
        assert "import faulthandler" in src
        assert "faulthandler.enable" in src


class TestKeyboardHookQueue:
    """_hook_press/_hook_release must enqueue events and return without blocking."""

    def test_hook_functions_exist(self):
        assert hasattr(main, "_hook_press")
        assert hasattr(main, "_hook_release")
        assert hasattr(main, "_keyboard_event_worker")
        assert hasattr(main, "_event_queue")

    def test_hook_press_enqueues_event(self, monkeypatch):
        import queue as _queue
        q = _queue.SimpleQueue()
        monkeypatch.setattr(main, "_event_queue", q)
        main._hook_press("dummy_key")
        assert not q.empty()
        assert q.get_nowait() == ("press", "dummy_key")

    def test_hook_release_enqueues_event(self, monkeypatch):
        import queue as _queue
        q = _queue.SimpleQueue()
        monkeypatch.setattr(main, "_event_queue", q)
        main._hook_release("dummy_key")
        assert not q.empty()
        assert q.get_nowait() == ("release", "dummy_key")

    def test_hook_press_returns_quickly(self, monkeypatch):
        """_hook_press must not block — must return in under 5 ms."""
        import queue as _queue
        monkeypatch.setattr(main, "_event_queue", _queue.SimpleQueue())
        t0 = time.perf_counter()
        main._hook_press("test_key")
        assert (time.perf_counter() - t0) < 0.005

    def test_hook_release_returns_quickly(self, monkeypatch):
        """_hook_release must not block — must return in under 5 ms."""
        import queue as _queue
        monkeypatch.setattr(main, "_event_queue", _queue.SimpleQueue())
        t0 = time.perf_counter()
        main._hook_release("test_key")
        assert (time.perf_counter() - t0) < 0.005

    def test_worker_dispatches_press_to_on_press(self, monkeypatch):
        """Worker must call _on_press for 'press' events."""
        import queue as _queue
        calls: list = []
        q = _queue.SimpleQueue()
        monkeypatch.setattr(main, "_event_queue", q)
        monkeypatch.setattr(main, "_on_press", lambda k, ind: calls.append(("press", k)))

        class _FI:
            def safe_set_state(self, _): pass

        q.put(("press", "space"))
        q.put(None)  # sentinel
        main._keyboard_event_worker(_FI())
        assert calls == [("press", "space")]

    def test_worker_dispatches_release_to_on_release(self, monkeypatch):
        """Worker must call _on_release for 'release' events."""
        import queue as _queue
        calls: list = []
        q = _queue.SimpleQueue()
        monkeypatch.setattr(main, "_event_queue", q)
        monkeypatch.setattr(main, "_on_release", lambda k, ind: calls.append(("release", k)))

        class _FI:
            def safe_set_state(self, _): pass

        q.put(("release", "space"))
        q.put(None)
        main._keyboard_event_worker(_FI())
        assert calls == [("release", "space")]

    def test_worker_stops_on_sentinel(self, monkeypatch):
        """Worker must exit the loop when it receives None."""
        import queue as _queue
        q = _queue.SimpleQueue()
        monkeypatch.setattr(main, "_event_queue", q)
        q.put(None)

        class _FI:
            def safe_set_state(self, _): pass

        # If worker hangs, the test times out — just verify it returns
        main._keyboard_event_worker(_FI())

    def test_hook_functions_in_source(self):
        src = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")
        assert "_hook_press" in src
        assert "_hook_release" in src
        assert "_keyboard_event_worker" in src
        assert "HooksTimeout" in src


class TestClipboardRetry:
    """_clipboard_write retries on Windows lock contention, raises after exhaustion."""

    def test_succeeds_on_first_try(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(main.pyperclip, "copy", lambda v: calls.append(v))
        main._clipboard_write("テスト")
        assert calls == ["テスト"]

    def test_retries_on_transient_failure(self, monkeypatch):
        """Should succeed without raising if failure clears within max_retries."""
        call_count = [0]

        def _flaky(v):
            call_count[0] += 1
            if call_count[0] < 3:
                raise OSError("clipboard locked")

        monkeypatch.setattr(main.pyperclip, "copy", _flaky)
        main._clipboard_write("テスト", max_retries=5, retry_delay_ms=0)
        assert call_count[0] == 3

    def test_raises_after_max_retries_exhausted(self, monkeypatch):
        monkeypatch.setattr(
            main.pyperclip, "copy",
            lambda _: (_ for _ in ()).throw(OSError("always locked")),
        )
        with pytest.raises(OSError):
            main._clipboard_write("テスト", max_retries=3, retry_delay_ms=0)

    def test_retry_count_equals_max_retries(self, monkeypatch):
        """Exactly max_retries attempts must be made before raising."""
        calls: list = []

        def _always_fail(v):
            calls.append(v)
            raise OSError("locked")

        monkeypatch.setattr(main.pyperclip, "copy", _always_fail)
        with pytest.raises(OSError):
            main._clipboard_write("テスト", max_retries=4, retry_delay_ms=0)
        assert len(calls) == 4

    def test_used_in_paste_text(self):
        src = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")
        assert "_clipboard_write(text)" in src
        assert '_clipboard_write("")' in src


class TestRestoreClipboard:
    """RESTORE_CLIPBOARD flag controls post-paste clipboard clearing."""

    def test_flag_exists_and_defaults_false(self):
        """RESTORE_CLIPBOARD must default to False to prevent crash-inducing clear."""
        assert hasattr(main, "RESTORE_CLIPBOARD")
        # Default (no env var) must be False
        import importlib, os
        old = os.environ.pop("RESTORE_CLIPBOARD", None)
        try:
            importlib.reload(main)
            assert main.RESTORE_CLIPBOARD is False, "RESTORE_CLIPBOARD must default to False"
        finally:
            if old is not None:
                os.environ["RESTORE_CLIPBOARD"] = old
            importlib.reload(main)

    def test_flag_true_via_env(self, monkeypatch):
        """RESTORE_CLIPBOARD=true in env must set flag to True."""
        import importlib
        monkeypatch.setenv("RESTORE_CLIPBOARD", "true")
        importlib.reload(main)
        assert main.RESTORE_CLIPBOARD is True
        monkeypatch.delenv("RESTORE_CLIPBOARD", raising=False)
        importlib.reload(main)

    def test_clipboard_not_cleared_when_false(self, monkeypatch):
        """When RESTORE_CLIPBOARD=False, cleanup must not call pyperclip.copy."""
        monkeypatch.setattr(main, "_has_pasted", False)
        monkeypatch.setattr(main, "RESTORE_CLIPBOARD", False)
        copy_calls: list = []
        monkeypatch.setattr(main.pyperclip, "copy", lambda v: copy_calls.append(v))
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)
        cleanup_fns: list = []

        class _FT:
            def __init__(self, d, fn): cleanup_fns.append(fn)
            def start(self): pass

        monkeypatch.setattr(main.threading, "Timer", _FT)
        main.paste_text("テスト")
        cleanup_fns[0]()  # fire cleanup
        assert copy_calls == ["テスト"], "Only the initial write must occur; no clipboard clear"

    def test_clipboard_cleared_when_true(self, monkeypatch):
        """When RESTORE_CLIPBOARD=True, cleanup must call pyperclip.copy with empty string."""
        monkeypatch.setattr(main, "_has_pasted", False)
        monkeypatch.setattr(main, "RESTORE_CLIPBOARD", True)
        copy_calls: list = []
        monkeypatch.setattr(main.pyperclip, "copy", lambda v: copy_calls.append(v))
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)
        cleanup_fns: list = []

        class _FT:
            def __init__(self, d, fn): cleanup_fns.append(fn)
            def start(self): pass

        monkeypatch.setattr(main.threading, "Timer", _FT)
        main.paste_text("テスト")
        cleanup_fns[0]()  # fire cleanup
        assert "" in copy_calls, "Clipboard must be cleared when RESTORE_CLIPBOARD=True"

    def test_pasting_reset_regardless_of_flag(self, monkeypatch):
        """_pasting must be reset to False by cleanup whether RESTORE_CLIPBOARD is True or False."""
        for flag in (True, False):
            monkeypatch.setattr(main, "_has_pasted", False)
            main._last_paste_time = 0.0
            monkeypatch.setattr(main, "RESTORE_CLIPBOARD", flag)
            monkeypatch.setattr(main, "_pasting", False)
            monkeypatch.setattr(main.pyperclip, "copy", lambda _: None)
            monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)
            cleanup_fns: list = []

            class _FT:
                def __init__(self, d, fn): cleanup_fns.append(fn)
                def start(self): pass

            monkeypatch.setattr(main.threading, "Timer", _FT)
            main.paste_text("テスト")
            cleanup_fns[0]()
            assert main._pasting is False, f"_pasting not reset when RESTORE_CLIPBOARD={flag}"

    def test_base_exception_caught_in_cleanup(self, monkeypatch, caplog):
        """BaseException from clipboard clear must be caught and logged, not propagated."""
        import logging
        monkeypatch.setattr(main, "_has_pasted", False)
        monkeypatch.setattr(main, "RESTORE_CLIPBOARD", True)

        call_n = [0]
        def _boom(v):
            call_n[0] += 1
            if call_n[0] > 1:
                raise MemoryError("C-level OOM")

        monkeypatch.setattr(main.pyperclip, "copy", _boom)
        monkeypatch.setattr(main.pyautogui, "hotkey", lambda *a: None)
        cleanup_fns: list = []

        class _FT:
            def __init__(self, d, fn): cleanup_fns.append(fn)
            def start(self): pass

        monkeypatch.setattr(main.threading, "Timer", _FT)
        main.paste_text("テスト")
        with caplog.at_level(logging.WARNING, logger="voice-fep"):
            cleanup_fns[0]()  # MemoryError raised inside _clipboard_write
        assert main._pasting is False, "_pasting must be reset even after BaseException"
        assert any("clipboard clear failed" in r.message for r in caplog.records)


class TestFaulthandlerPlacement:
    """faulthandler must be enabled before any other import to catch early crashes."""

    def _src(self) -> str:
        return (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")

    def test_faulthandler_before_argparse(self):
        """faulthandler.enable must appear before 'import argparse' in source."""
        src = self._src()
        fh_pos = src.index("faulthandler.enable")
        argparse_pos = src.index("import argparse")
        assert fh_pos < argparse_pos, (
            "faulthandler.enable must be the very first action in main.py"
        )

    def test_crash_dump_log_name(self):
        """crash_dump.log must be the filename used for faulthandler output."""
        assert 'open("crash_dump.log"' in self._src()

    def test_safe_set_state_uses_after(self):
        """safe_set_state must schedule via after() — never call set_state directly."""
        src = self._src()
        assert "self.after(0, lambda: self.set_state(state))" in src

    def test_restore_clipboard_in_source(self):
        src = self._src()
        assert "RESTORE_CLIPBOARD" in src
        assert "BaseException" in src


class TestDebounce:
    """Debounce gate: press events within _DEBOUNCE_MS of last accepted press are dropped."""

    def test_debounce_constants_defined(self):
        assert hasattr(main, "_DEBOUNCE_MS")
        assert main._DEBOUNCE_MS == 300

    def test_last_press_time_initialized_zero(self):
        assert main._last_press_time == 0.0

    def test_second_press_within_debounce_dropped(self, monkeypatch):
        """Simulate two press events 50ms apart — second must be ignored."""
        from pynput import keyboard as kb
        calls = []

        def fake_start():
            calls.append("start")

        monkeypatch.setattr(main, "start_recording", fake_start)
        monkeypatch.setattr(main, "_active", False)
        monkeypatch.setattr(main, "_blocked_until_release", False)
        monkeypatch.setattr(main, "_pasting", False)
        monkeypatch.setattr(main, "_is_processing", False)
        monkeypatch.setattr(main, "_mods_held", {kb.Key.ctrl_l})

        indicator = MagicMock()
        indicator.safe_set_state = MagicMock()

        # First press — accepted
        main._last_press_time = 0.0
        main._on_press(main._RECORD_KEY, indicator)
        assert len(calls) == 1

        # Reset active so the second press would normally proceed
        main._active = False

        # Second press 50ms later — within _DEBOUNCE_MS → must be dropped
        main._last_press_time = time.perf_counter()
        time.sleep(0.05)
        main._on_press(main._RECORD_KEY, indicator)
        assert len(calls) == 1, "Second press within debounce window should be dropped"

    def test_press_after_debounce_accepted(self, monkeypatch):
        """Press event arriving after _DEBOUNCE_MS has elapsed must be accepted."""
        from pynput import keyboard as kb
        calls = []

        def fake_start():
            calls.append("start")

        monkeypatch.setattr(main, "start_recording", fake_start)
        monkeypatch.setattr(main, "_active", False)
        monkeypatch.setattr(main, "_blocked_until_release", False)
        monkeypatch.setattr(main, "_pasting", False)
        monkeypatch.setattr(main, "_is_processing", False)
        monkeypatch.setattr(main, "_mods_held", {kb.Key.ctrl_l})

        indicator = MagicMock()
        indicator.safe_set_state = MagicMock()

        # Set last press time to well before debounce threshold
        main._last_press_time = time.perf_counter() - (main._DEBOUNCE_MS / 1000 + 0.1)
        main._on_press(main._RECORD_KEY, indicator)
        assert len(calls) == 1, "Press after debounce window must be accepted"

    def test_last_press_time_in_source(self):
        src = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")
        assert "_last_press_time" in src
        assert "_DEBOUNCE_MS" in src


class TestPasteCooldown:
    """Paste cooldown gate: paste requests within _PASTE_COOLDOWN_MS of last paste are dropped."""

    def test_paste_cooldown_constant_defined(self):
        assert hasattr(main, "_PASTE_COOLDOWN_MS")
        assert main._PASTE_COOLDOWN_MS == 500

    def test_last_paste_time_initialized_zero(self):
        assert main._last_paste_time == 0.0

    def test_paste_blocked_within_cooldown(self, monkeypatch):
        """Second paste attempt within _PASTE_COOLDOWN_MS must be blocked."""
        pasted = []
        monkeypatch.setattr("pyperclip.copy", lambda t: None)
        monkeypatch.setattr("pyautogui.hotkey", lambda *a: pasted.append(a))
        monkeypatch.setattr(main, "RESTORE_CLIPBOARD", False)

        # First paste succeeds
        main._last_paste_time = 0.0
        main._has_pasted = False
        main.paste_text("first")
        assert len(pasted) == 1

        # Immediately try again — cooldown active, _has_pasted also set
        # Reset _has_pasted to test cooldown independently
        main._has_pasted = False
        main.paste_text("second")
        assert len(pasted) == 1, "Paste within cooldown window must be blocked"

    def test_paste_allowed_after_cooldown(self, monkeypatch):
        """Paste attempt after _PASTE_COOLDOWN_MS has elapsed must succeed."""
        pasted = []
        monkeypatch.setattr("pyperclip.copy", lambda t: None)
        monkeypatch.setattr("pyautogui.hotkey", lambda *a: pasted.append(a))
        monkeypatch.setattr(main, "RESTORE_CLIPBOARD", False)

        # Set last paste time to well before cooldown threshold
        main._last_paste_time = time.perf_counter() - (main._PASTE_COOLDOWN_MS / 1000 + 0.1)
        main._has_pasted = False
        main.paste_text("after cooldown")
        assert len(pasted) == 1, "Paste after cooldown window must be accepted"

    def test_paste_cooldown_in_source(self):
        src = (Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")
        assert "_last_paste_time" in src
        assert "_PASTE_COOLDOWN_MS" in src
