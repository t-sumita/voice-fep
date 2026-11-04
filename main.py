#!/usr/bin/env python3
"""voice-fep: Windows常駐型 音声入力FEPツール (F8 トグル録音 → Gemini 書き起こし → 自動ペースト)"""

# faulthandler must be enabled before any other import so C-level segfaults are captured
import faulthandler
faulthandler.enable(file=open("crash_dump.log", "a", encoding="utf-8"))  # noqa: WPS421

import argparse
import io
import json
import logging
import math
import os
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pyautogui
import pyperclip
import sounddevice as sd
from dotenv import load_dotenv
from pynput import keyboard
from scipy.io import wavfile

load_dotenv()
# When running as a frozen exe, also load .env from the exe's directory
if getattr(sys, "frozen", False):
    load_dotenv(Path(sys.executable).parent / ".env", override=False)

# ---------------------------------------------------------------------------
# Hotkey parser  (runs at module load to resolve HOTKEY / DICT_HOTKEY)
# ---------------------------------------------------------------------------
_MODIFIER_MAP: dict = {
    "ctrl":    frozenset({keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}),
    "control": frozenset({keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}),
    "shift":   frozenset({keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}),
    "alt":     frozenset({keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}),
}


def _parse_hotkey(spec: str):
    """Parse 'ctrl+space' → (trigger Key, modifier frozenset)."""
    parts = [p.strip().lower() for p in spec.split("+")]
    mods: set = set()
    trigger = None
    for part in parts:
        if part in _MODIFIER_MAP:
            mods |= _MODIFIER_MAP[part]
        else:
            try:
                trigger = getattr(keyboard.Key, part)
            except AttributeError:
                trigger = keyboard.KeyCode.from_char(part)
    return trigger, frozenset(mods)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_exe_dir() -> Path:
    """Return directory of the executable (frozen) or this source file (dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _get_log_path() -> Path:
    """Return the log file path (next to exe when frozen, else in APPDATA/voice-fep/)."""
    if getattr(sys, "frozen", False):
        return _get_exe_dir() / "voice-fep.log"
    appdata = os.environ.get("APPDATA", "")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / "voice-fep" / "voice-fep.log"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_VERSION: str = "0.8.8"
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
BACKEND: str = os.environ.get("BACKEND", "gemini")
WHISPER_MODEL: str = os.environ.get("WHISPER_MODEL", "base")
try:
    RECORD_MAX_SEC: int = max(1, int(float(os.environ.get("RECORD_MAX_SEC", "30") or "30")))
except (ValueError, TypeError):
    RECORD_MAX_SEC = 30
SAMPLE_RATE: int = 16000
HOTKEY: str = os.environ.get("HOTKEY", "ctrl+space")
DICT_HOTKEY: str = os.environ.get("DICT_HOTKEY", "shift+space")
# When False (default), clipboard is NOT cleared after paste — safest against C-level crashes.
# Set RESTORE_CLIPBOARD=true in .env to re-enable the post-paste clipboard clear (S-4).
RESTORE_CLIPBOARD: bool = os.environ.get("RESTORE_CLIPBOARD", "false").lower() in ("true", "1", "yes")
# Hotkey chatter guard: press events arriving within this window of the last accepted press are dropped.
_DEBOUNCE_MS: int = 300
# Paste cooldown: paste requests within this window of the last paste are dropped.
_PASTE_COOLDOWN_MS: int = 500
_RECORD_KEY, _RECORD_MODS = _parse_hotkey(HOTKEY)
_DICT_KEY, _DICT_MODS = _parse_hotkey(DICT_HOTKEY)
_ALL_MOD_KEYS: frozenset = _RECORD_MODS | _DICT_MODS

# ---------------------------------------------------------------------------
# Transcription prompt  — edit here to tune output style
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "あなたは日本語音声書き起こし専用エンジンです。以下のルールを絶対に守ってください。\n"
    "\n"
    "【出力ルール】\n"
    "- 書き起こし本文のみを出力する。\n"
    "- 前置き・挨拶・返答・説明・「書き起こし結果:」等は一切含めない。\n"
    "- マークダウン記法（**太字**、# 見出し等）・余分な括弧・記号は使わない。\n"
    "\n"
    "【フィラー・言い淀みの除去】\n"
    "- 「あー」「えー」「えーと」「あの」「まあ」「うーん」「なんか」「そのー」等のフィラーは削除する。\n"
    "- 言い直し（「〜じゃなくて、〜」「〜いや、〜」）は最終的な表現だけを残す。\n"
    "\n"
    "【漢字・語彙の最適化】\n"
    "- 同音異義語は文脈から最適な漢字に変換する（例: 'きかい' → 文脈に応じて「機械」「機会」）。\n"
    "- 話し言葉は自然な書き言葉に整える（例: 'やっぱり' → 'やはり'）。\n"
    "- 助詞・接続詞を補完し、読みやすい文にする。\n"
    "\n"
    "【IT・プログラミング用語の正規化】\n"
    "- 英略語・固有名詞はアルファベット表記にする（例: API, GitHub, .env, CI/CD, URL, HTTP）。\n"
    "- カタカナIT用語は正確に表記する（例: 'くらうど' → 'クラウド'、'ぷるりく' → 'プルリク'）。\n"
    "- コマンド・ファイル名・コード片はそのまま出力する（例: git commit, main.py）。\n"
    "\n"
    "【句読点】\n"
    "- 文末には必ず自然な句点（。）を付与する。\n"
    "- 文中の区切りにも適切に読点（、）を補完すること。\n"
    "\n"
    "【分かち書き禁止】\n"
    "- 日本語を出力する際は、単語間に半角スペース・全角スペース・空白を一切挟まない。\n"
    "- 「これ まだ バージョン が 上がっ て ない の ?」のような分かち書き形式は厳禁。\n"
    "- 通常の自然な日本語の文として続けて出力すること。\n"
)

# ---------------------------------------------------------------------------
# Logging  — audio content is NEVER written to logs
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("voice-fep")


def _setup_logging() -> None:
    """Adjust log level and add RotatingFileHandler if ENABLE_LOG_FILE is true.

    Called once from main() so test imports don't create log files.
    """
    from logging.handlers import RotatingFileHandler  # noqa: PLC0415
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.getLogger().setLevel(level)
    log.setLevel(level)
    if os.environ.get("ENABLE_LOG_FILE", "true").lower() not in ("true", "1", "yes"):
        return
    log_path = _get_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(fh)
    log.info("Log file: %s", log_path)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
_active = False               # True while trigger key is held and recording
_blocked_until_release = False  # True after auto-stop; blocks key-repeat from restarting
_pasting = False              # True during clipboard write + Ctrl+V; blocks spurious recording
_is_processing = False        # True from recording-stop through paste-done; prevents double execution
_has_pasted: bool = False     # one-shot guard; reset at recording-start; prevents double paste
_last_engine: str = ""        # set by transcribe(); used in [PASTE_EXECUTE] log
_last_press_time: float = 0.0 # perf_counter() of last accepted press; debounce gate
_last_paste_time: float = 0.0 # perf_counter() of last completed paste; cooldown gate
_event_queue: queue.SimpleQueue = queue.SimpleQueue()  # keyboard events → worker thread
_mods_held: set = set()       # currently depressed modifier keys (ctrl/shift/alt variants)
_audio_chunks: list = []
_stream: sd.InputStream | None = None
_record_timer: threading.Timer | None = None
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Window state (position persistence)
# ---------------------------------------------------------------------------
def _get_config_path() -> Path:
    appdata = os.environ.get("APPDATA", "")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / "voice-fep" / "config.json"


def _load_window_pos() -> tuple[int, int] | None:
    path = _get_config_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return int(data["window_x"]), int(data["window_y"])
    except Exception:
        return None


def _save_window_pos(x: int, y: int) -> None:
    path = _get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"window_x": x, "window_y": y}), encoding="utf-8")


# ---------------------------------------------------------------------------
# Indicator UI (tkinter floating window, top-right corner)
# ---------------------------------------------------------------------------
# Precomputed sinusoidal wave frames: 8 frames × 4 bars, heights in [6, 28]
_WAVE_FRAMES: list[list[int]] = [
    [max(6, int(14 + 14 * math.sin(2 * math.pi * i / 8 + math.pi / 2 * j)))
     for j in range(4)]
    for i in range(8)
]

try:
    import tkinter as tk

    class Indicator(tk.Tk):
        _W = 72
        _H = 72
        _N_BARS = 4
        _BAR_W = 6
        _BAR_GAP = 4
        _WAVE_MS = 120

        def __init__(self):
            super().__init__()
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            self.attributes("-alpha", 0.85)
            self.configure(bg="#1e1e1e")

            pos = _load_window_pos()
            if pos:
                self.geometry(f"{self._W}x{self._H}+{pos[0]}+{pos[1]}")
            else:
                sw = self.winfo_screenwidth()
                self.geometry(f"{self._W}x{self._H}+{sw - 84}+8")

            self._canvas = tk.Canvas(
                self, width=self._W, height=self._H, bg="#1e1e1e", highlightthickness=0
            )
            self._canvas.pack()

            self._wave_job: str | None = None
            self._wave_frame: int = 0
            self._done_job: str | None = None
            self._drag_ox: int = 0
            self._drag_oy: int = 0

            self._canvas.bind("<Button-3>", lambda _: self.destroy())
            self._canvas.bind("<Button-2>", self._on_open_log)
            self._canvas.bind("<Button-1>", self._on_drag_start)
            self._canvas.bind("<B1-Motion>", self._on_drag_move)
            self._canvas.bind("<ButtonRelease-1>", self._on_drag_end)

            self.set_state("idle")

        def _on_open_log(self, event=None) -> None:
            """Middle-click: open voice-fep.log in the default text editor."""
            log_path = _get_log_path()
            if log_path.exists():
                os.startfile(str(log_path))
            else:
                try:
                    import tkinter.messagebox as _mb
                    _mb.showinfo(
                        "voice-fep",
                        f"ログファイルが見つかりません:\n{log_path}\n\n"
                        "ENABLE_LOG_FILE=true を .env に設定してください。",
                    )
                except Exception:
                    pass

        def _on_drag_start(self, event: tk.Event) -> None:
            self._drag_ox = event.x_root - self.winfo_x()
            self._drag_oy = event.y_root - self.winfo_y()

        def _on_drag_move(self, event: tk.Event) -> None:
            self.geometry(f"+{event.x_root - self._drag_ox}+{event.y_root - self._drag_oy}")

        def _on_drag_end(self, event: tk.Event) -> None:
            _save_window_pos(self.winfo_x(), self.winfo_y())

        def _draw_mic(self, col: str = "#aaaaaa") -> None:
            c = self._canvas
            c.delete("all")
            # round-capped line is the only seam-free way to render a symmetric pill in tkinter
            c.create_line(36, 16, 36, 36, fill=col, width=16, capstyle="round")
            # U-arm: tops at capsule waist (y=33), bottoms meet arc at y=44 (~2/3 of old arm length)
            c.create_line(22, 33, 22, 44, fill=col, width=2)
            c.create_arc(22, 36, 50, 52, start=180, extent=180, style="arc", outline=col, width=2)
            c.create_line(50, 33, 50, 44, fill=col, width=2)
            c.create_line(36, 52, 36, 57, fill=col, width=2)
            c.create_line(27, 57, 45, 57, fill=col, width=2)
            if BACKEND == "gemini":
                c.create_text(62, 62, text="☁", fill="#38bdf8", font=("Segoe UI", 10), anchor="se")

        def _draw_wave(self) -> None:
            c, col = self._canvas, "#38bdf8"
            c.delete("all")
            heights = _WAVE_FRAMES[self._wave_frame % len(_WAVE_FRAMES)]
            x0 = (self._W - self._N_BARS * self._BAR_W - (self._N_BARS - 1) * self._BAR_GAP) // 2
            cy = self._H // 2
            for i, h in enumerate(heights):
                x1 = x0 + i * (self._BAR_W + self._BAR_GAP)
                c.create_rectangle(x1, cy - h // 2, x1 + self._BAR_W, cy + h // 2,
                                   fill=col, outline="")
            self._wave_frame += 1

        def _tick_wave(self) -> None:
            if self._wave_job is None:
                return
            self._draw_wave()
            self._wave_job = self.after(self._WAVE_MS, self._tick_wave)

        def set_state(self, state: str) -> None:
            if self._wave_job is not None:
                self.after_cancel(self._wave_job)
                self._wave_job = None
            if self._done_job is not None:
                self.after_cancel(self._done_job)
                self._done_job = None
            c = self._canvas
            if state == "idle":
                self._draw_mic()
            elif state == "recording":
                self._wave_frame = 0
                self._wave_job = self.after(0, self._tick_wave)
            elif state == "processing":
                self._draw_mic("#fbc02d")
            elif state == "done":
                c.delete("all")
                c.create_line(24, 36, 32, 44, fill="#4ade80", width=3,
                              capstyle="round", joinstyle="round")
                c.create_line(32, 44, 50, 26, fill="#4ade80", width=3,
                              capstyle="round", joinstyle="round")
                self._done_job = self.after(400, lambda: self.set_state("idle"))
            elif state == "error":
                c.delete("all")
                c.create_text(36, 36, text="×", fill="#f57c00",
                              font=("Segoe UI Symbol", 30, "bold"))

        def safe_set_state(self, state: str) -> None:
            """Schedule a state change on the Tk main thread via after().
            Safe to call from any worker thread — never call set_state() directly."""
            self.after(0, lambda: self.set_state(state))

except Exception:  # pragma: no cover
    class Indicator:  # type: ignore[no-redef]
        """Fallback: no-op indicator when tkinter is unavailable."""
        def mainloop(self): import time; [time.sleep(1) for _ in iter(int, 1)]  # noqa: E702,I001
        def safe_set_state(self, _): pass
        def destroy(self): os._exit(0)


# ---------------------------------------------------------------------------
# Audio recording
# ---------------------------------------------------------------------------
def _audio_callback(indata, frames, time_info, status):
    if status:
        log.warning("sounddevice: %s", status)
    with _lock:
        if _active:
            _audio_chunks.append(indata.copy())


def start_recording():
    global _stream, _audio_chunks, _has_pasted, _last_engine
    with _lock:
        _audio_chunks = []
        _has_pasted = False
        _last_engine = ""
    _stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        callback=_audio_callback,
    )
    _stream.start()
    log.debug("[RECORD_START] ts=%.3f", time.perf_counter())
    log.info("recording started")


def stop_recording() -> bytes | None:
    global _stream
    if _stream:
        _stream.stop()
        _stream.close()
        _stream = None
    with _lock:
        chunks = list(_audio_chunks)
        _audio_chunks.clear()  # immediate clear prevents re-read if stop_recording() is called twice
    if not chunks:
        log.info("no audio captured")
        return None
    audio = np.concatenate(chunks, axis=0)
    if len(audio) < int(0.3 * SAMPLE_RATE):
        log.info("recording ignored: duration too short (< 0.3s)")
        return None
    buf = io.BytesIO()
    wavfile.write(buf, SAMPLE_RATE, audio)
    duration = len(audio) / SAMPLE_RATE
    log.info("recording stopped: %d samples (%.1fs)", len(audio), duration)
    log.debug("[RECORD_STOP] duration=%.3fs", duration)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
def transcribe(wav_bytes: bytes) -> str:
    global _last_engine
    if BACKEND == "gemini":
        log.debug("[ENGINE_START] engine=gemini")
        try:
            result = _transcribe_gemini(wav_bytes)
            _last_engine = "gemini"
            log.debug("[ENGINE_RESULT] engine=gemini length=%d", len(result))
            return result
        except Exception as exc:
            log.warning(
                "Gemini transcription failed (%s: %s); falling back to local Whisper",
                type(exc).__name__, exc,
            )
            log.debug("[ENGINE_START] engine=local_whisper (gemini_fallback)")
            result = _transcribe_local(wav_bytes)
            _last_engine = "local_whisper(fallback)"
            log.debug("[ENGINE_RESULT] engine=local_whisper(fallback) length=%d", len(result))
            return result
    if BACKEND == "cloudflare":
        log.debug("[ENGINE_START] engine=cloudflare")
        result = _transcribe_cloudflare(wav_bytes)
        _last_engine = "cloudflare"
        log.debug("[ENGINE_RESULT] engine=cloudflare length=%d", len(result))
        return result
    if BACKEND in ("local", "local_whisper"):  # local_whisper kept for backward compat
        log.debug("[ENGINE_START] engine=local_whisper")
        result = _transcribe_local(wav_bytes)
        _last_engine = "local_whisper"
        log.debug("[ENGINE_RESULT] engine=local_whisper length=%d", len(result))
        return result
    raise ValueError(f"Unknown BACKEND: {BACKEND!r}")


def _transcribe_gemini(wav_bytes: bytes) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set in .env")
    from google import genai  # noqa: PLC0415
    from google.genai import types  # noqa: PLC0415

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Content(parts=[
                types.Part(inline_data=types.Blob(mime_type="audio/wav", data=wav_bytes)),
                types.Part(text="上記の音声を書き起こしてください。"),
            ])
        ],
        config=types.GenerateContentConfig(
            system_instruction=_build_system_prompt(),
            temperature=0.0,
            max_output_tokens=512,
            # Disable server-side function calling so the model never emits tool_call parts.
            # This prevents AFC (Automatic Function Calling) from retrying and adding ~20s latency.
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE"),
            ),
        ),
    )
    return (response.text or "").strip()


def _transcribe_cloudflare(wav_bytes: bytes) -> str:
    import httpx  # noqa: PLC0415
    api_key = os.environ.get("CLOUDFLARE_API_KEY", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not api_key or not account_id:
        raise RuntimeError("CLOUDFLARE_API_KEY / CLOUDFLARE_ACCOUNT_ID not set in .env")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/openai/whisper"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        content=wav_bytes,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("result", {}).get("text", "").strip()


def _transcribe_local(wav_bytes: bytes) -> str:
    # faster-whisper accepts np.ndarray directly — no disk write needed (S-2)
    from faster_whisper import WhisperModel  # noqa: PLC0415

    buf = io.BytesIO(wav_bytes)
    _, audio_int16 = wavfile.read(buf)
    audio_float32 = audio_int16.astype(np.float32) / 32768.0
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    words = load_dictionary()
    initial_prompt = ", ".join(words) if words else None
    # sampling_rate is not a valid arg for transcribe(); faster-whisper expects 16kHz internally
    segments, _ = model.transcribe(audio_float32, language="ja", initial_prompt=initial_prompt)
    return "".join(s.text for s in segments).strip()


def _backend_info() -> str:
    """Return a startup-log description of the active backend and model."""
    if BACKEND in ("local", "local_whisper"):
        return f"backend: local, model: {WHISPER_MODEL}"
    if BACKEND == "cloudflare":
        return "backend: cloudflare, model: @cf/openai/whisper"
    return f"backend: {BACKEND}, model: {GEMINI_MODEL}"


def _check_backend_config() -> None:
    """Validate backend config at startup; fall back to local if GEMINI_API_KEY is missing."""
    global BACKEND
    if BACKEND != "gemini" or GEMINI_API_KEY:
        return
    log.warning(
        "GEMINI_API_KEY is not set; falling back to local Whisper backend. "
        "Set GEMINI_API_KEY in .env to use Gemini."
    )
    try:
        import tkinter.messagebox as _mb
        _mb.showwarning(
            "voice-fep — APIキー未設定",
            "GEMINI_API_KEY が未設定のため、ローカル Whisper モード（BACKEND=local）で起動します。\n\n"
            "Gemini を使うには .env ファイルに GEMINI_API_KEY を設定してください。",
        )
    except Exception:
        pass  # headless environment; log warning already emitted
    BACKEND = "local"


# ---------------------------------------------------------------------------
# Dictionary (カスタム辞書)
# ---------------------------------------------------------------------------
def get_dictionary_path() -> Path:
    """Resolve dictionary file location: env var > ./dictionary.txt > APPDATA fallback."""
    env_path = os.environ.get("DICTIONARY_FILE", "")
    if env_path:
        return Path(env_path)
    local = Path("dictionary.txt")
    if local.exists():
        return local.resolve()
    appdata = os.environ.get("APPDATA", "")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / "voice-fep" / "dictionary.txt"


def load_dictionary() -> list[str]:
    path = get_dictionary_path()
    if not path.exists():
        return []
    return [
        w for line in path.read_text(encoding="utf-8").splitlines()
        if (w := line.strip()) and not w.startswith("#")
    ]


def load_system_prompt() -> str:
    """Return system_prompt.txt content if present and non-empty, else SYSTEM_PROMPT constant."""
    candidates: list[Path] = [Path("system_prompt.txt")]
    if getattr(sys, "frozen", False):
        candidates.append(_get_exe_dir() / "system_prompt.txt")
    for path in candidates:
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content
    return SYSTEM_PROMPT


def _build_system_prompt() -> str:
    """Return base prompt with user vocabulary appended when dictionary has entries."""
    base = load_system_prompt()
    words = load_dictionary()
    if not words:
        return base
    return (
        base
        + "\n\n【優先使用する語彙】\n"
        + "発話内に明確に該当語彙が含まれている場合のみ、正確にこの表記で書き起こすこと:\n"
        + "、".join(words)
    )


def _add_from_clipboard():
    """Ctrl+F8 handler: append clipboard text to dictionary if non-empty and not duplicate."""
    try:
        word = pyperclip.paste().strip()
        if not word:
            return
        if word in load_dictionary():
            return
        path = get_dictionary_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(word + "\n")
        log.info("Added to dictionary: %s", word)
    except Exception as exc:
        log.error("_add_from_clipboard error: %s: %s", type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# Paste (preserves focus on active window)
# ---------------------------------------------------------------------------
def _clipboard_write(text: str, max_retries: int = 5, retry_delay_ms: int = 10) -> None:
    """Copy text to clipboard with retry to survive Windows OpenClipboard lock contention."""
    for attempt in range(max_retries):
        try:
            pyperclip.copy(text)
            return
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(retry_delay_ms / 1000)
            else:
                raise


def paste_text(text: str):
    global _pasting, _has_pasted, _last_paste_time
    now = time.perf_counter()
    with _lock:
        if _has_pasted:
            log.warning("[PASTE_EXECUTE] BLOCKED: double-paste guard triggered (already pasted this session)")
            return
        elapsed_ms = (now - _last_paste_time) * 1000
        if elapsed_ms < _PASTE_COOLDOWN_MS:
            log.warning("[PASTE_EXECUTE] BLOCKED: cooldown active (%.0fms since last paste, need %dms)",
                        elapsed_ms, _PASTE_COOLDOWN_MS)
            return
        _has_pasted = True
        _last_paste_time = now
    _pasting = True
    try:
        _clipboard_write(text)
        pyautogui.hotkey("ctrl", "v")
    except Exception as exc:
        log.error("paste_text error: %s: %s", type(exc).__name__, exc)
        _pasting = False
        return
    log.info("[PASTE_EXECUTE] engine=%s length=%d chars", _last_engine or "?", len(text))
    # Release pasting guard after the Ctrl+V key state settles.
    # Clipboard clear is skipped when RESTORE_CLIPBOARD=false (default) to avoid
    # the C-level crash that was occurring inside pyperclip's Windows API call.
    def _cleanup():
        global _pasting
        if RESTORE_CLIPBOARD:
            try:
                _clipboard_write("")
            except BaseException as e:  # BaseException catches C-ext errors too
                log.warning("clipboard clear failed: %s: %s", type(e).__name__, e)
        _pasting = False
    threading.Timer(0.5, _cleanup).start()


# ---------------------------------------------------------------------------
# Key event handlers
# ---------------------------------------------------------------------------
def _auto_stop(indicator: Indicator):
    """Called by _record_timer when RECORD_MAX_SEC is reached."""
    global _active, _record_timer, _blocked_until_release, _is_processing
    try:
        with _lock:
            if not _active or _is_processing:
                return
            _active = False
            _is_processing = True
            # Prevent OS key-repeat from starting a new recording before the key is physically released
            _blocked_until_release = True
        _record_timer = None
        log.info("recording stopped: reached max duration (%ds)", RECORD_MAX_SEC)
        indicator.safe_set_state("processing")
        threading.Thread(target=_process_and_paste, args=(indicator,), daemon=True).start()
    except Exception as exc:
        log.error("_auto_stop error: %s: %s", type(exc).__name__, exc)


def _on_press(key, indicator: Indicator):
    global _active, _record_timer, _mods_held, _last_press_time
    try:
        if key in _ALL_MOD_KEYS:
            _mods_held.add(key)
            return
        # Dict hotkey (default shift+space): add selected text to dictionary
        if key == _DICT_KEY and _DICT_MODS and bool(_DICT_MODS & _mods_held):
            threading.Thread(target=_add_from_clipboard, daemon=True).start()
            return
        # Record hotkey (default ctrl+space): start PTT recording
        if key != _RECORD_KEY:
            return
        if _RECORD_MODS and not bool(_RECORD_MODS & _mods_held):
            return
        now = time.perf_counter()
        log.debug("[KEY_DOWN] key=%s ts=%.3f", key, now)
        with _lock:
            elapsed_ms = (now - _last_press_time) * 1000
            if elapsed_ms < _DEBOUNCE_MS:
                log.debug("[KEY_DOWN] DEBOUNCED: %.1fms since last press (threshold %dms)",
                          elapsed_ms, _DEBOUNCE_MS)
                return
            if _active or _blocked_until_release or _pasting or _is_processing:
                return
            _active = True
            _last_press_time = now
        indicator.safe_set_state("recording")
        start_recording()
        _record_timer = threading.Timer(RECORD_MAX_SEC, _auto_stop, args=(indicator,))
        _record_timer.daemon = True
        _record_timer.start()
    except Exception as exc:
        log.error("_on_press error: %s: %s", type(exc).__name__, exc)


def _on_release(key, indicator: Indicator):
    global _active, _record_timer, _blocked_until_release, _mods_held, _is_processing
    try:
        if key in _ALL_MOD_KEYS:
            _mods_held.discard(key)
            return
        if key != _RECORD_KEY:
            return
        log.debug("[KEY_UP] key=%s ts=%.3f", key, time.perf_counter())
        with _lock:
            # Physical release always clears the block — do this before checking _active
            if _blocked_until_release:
                _blocked_until_release = False
                return  # _process_and_paste was already launched by _auto_stop
            if not _active or _is_processing:
                return
            _active = False
            _is_processing = True
        if _record_timer is not None:
            _record_timer.cancel()
            _record_timer = None
        indicator.safe_set_state("processing")
        threading.Thread(target=_process_and_paste, args=(indicator,), daemon=True).start()
    except Exception as exc:
        log.error("_on_release error: %s: %s", type(exc).__name__, exc)


def _process_and_paste(indicator: Indicator):
    global _is_processing
    try:
        wav_bytes = stop_recording()
        if not wav_bytes:
            indicator.safe_set_state("idle")
            return
        t0 = time.perf_counter()
        text = transcribe(wav_bytes).strip()
        elapsed = time.perf_counter() - t0
        log.info("transcription took %.2fs, %d chars", elapsed, len(text))
        if text:
            paste_text(text)
            indicator.safe_set_state("done")
        else:
            indicator.safe_set_state("idle")
    except Exception as exc:
        log.error("error during transcription: %s: %s", type(exc).__name__, exc)
        indicator.safe_set_state("error")
        threading.Timer(3.0, lambda: indicator.safe_set_state("idle")).start()
    finally:
        with _lock:
            _is_processing = False


# ---------------------------------------------------------------------------
# Keyboard event worker — decouples pynput hook thread from all heavy work
# ---------------------------------------------------------------------------
def _keyboard_event_worker(indicator) -> None:
    """Consume keyboard events from _event_queue so the Windows hook thread stays unblocked.

    Windows terminates low-level keyboard hooks that don't return within HooksTimeout
    (~200 ms by default). By dispatching through a queue the hook callbacks return
    instantly; all real work happens here in a normal daemon thread.
    """
    while True:
        try:
            item = _event_queue.get()
            if item is None:  # sentinel — shutdown requested
                break
            event_type, key = item
            if event_type == "press":
                _on_press(key, indicator)
            elif event_type == "release":
                _on_release(key, indicator)
        except Exception as exc:
            log.error("keyboard event worker error: %s: %s", type(exc).__name__, exc)


def _hook_press(key) -> None:
    """pynput on_press: enqueue event and return immediately to satisfy HooksTimeout."""
    _event_queue.put(("press", key))


def _hook_release(key) -> None:
    """pynput on_release: enqueue event and return immediately to satisfy HooksTimeout."""
    _event_queue.put(("release", key))


# ---------------------------------------------------------------------------
# Unhandled exception hooks — keep the process alive and log to file
# ---------------------------------------------------------------------------
def _log_unhandled_exception(exc_type, exc_value, exc_tb):
    """sys.excepthook: log uncaught main-thread exceptions instead of silent crash."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    log.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
    for handler in logging.getLogger().handlers:
        handler.flush()


def _log_thread_exception(args):
    """threading.excepthook: log uncaught exceptions in daemon threads."""
    if args.exc_type is SystemExit:
        return
    log.critical(
        "Unhandled thread exception in %s",
        getattr(args.thread, "name", str(args.thread)),
        exc_info=(args.exc_type, args.exc_value, args.exc_tb),
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        prog="voice-fep",
        description="Windows 常駐型音声入力 FEP ツール",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the effective Gemini system prompt (with dictionary injected) and exit.",
    )
    args = parser.parse_args()

    if args.show_prompt:
        print(_build_system_prompt())
        return

    _setup_logging()
    sys.excepthook = _log_unhandled_exception
    threading.excepthook = _log_thread_exception
    _check_backend_config()
    indicator = Indicator()

    worker = threading.Thread(
        target=_keyboard_event_worker, args=(indicator,), daemon=True, name="keyboard-worker",
    )
    worker.start()

    listener = keyboard.Listener(on_press=_hook_press, on_release=_hook_release)
    listener.start()
    log.info("voice-fep v%s ready (%s) — %s to record, %s to add dict — right-click to quit",
             APP_VERSION, _backend_info(), HOTKEY, DICT_HOTKEY)

    try:
        indicator.mainloop()
    finally:
        _event_queue.put(None)  # signal keyboard worker to stop
        listener.stop()
        log.info("voice-fep stopped")


if __name__ == "__main__":
    main()
