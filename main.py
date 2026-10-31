#!/usr/bin/env python3
"""voice-fep: Windows常駐型 音声入力FEPツール (F8 トグル録音 → Gemini 書き起こし → 自動ペースト)"""

import io
import logging
import os
import threading

import numpy as np
import pyautogui
import pyperclip
import sounddevice as sd
from dotenv import load_dotenv
from pynput import keyboard
from scipy.io import wavfile

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_VERSION: str = "0.2.1"
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
BACKEND: str = os.environ.get("BACKEND", "gemini")
SAMPLE_RATE: int = 16000
HOTKEY = keyboard.Key.f8

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
    "【分かち書き禁止】\n"
    "- 日本語を出力する際は、単語間に半角スペース・全角スペース・空白を一切挟まない。\n"
    "- 「これ まだ バージョン が 上がっ て ない の ?」のような分かち書き形式は厳禁。\n"
    "- 通常の自然な日本語の文として続けて出力すること。\n"
)

# ---------------------------------------------------------------------------
# Logging  — audio content is NEVER written to logs
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("voice-fep")

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
_active = False          # True while F8 is held and recording
_audio_chunks: list = []
_stream: sd.InputStream | None = None
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Indicator UI (tkinter floating window, top-right corner)
# ---------------------------------------------------------------------------
try:
    import tkinter as tk

    class Indicator(tk.Tk):
        _STATES = {
            "idle":       ("○", "#888888"),
            "recording":  ("●", "#e53935"),
            "processing": ("◎", "#fbc02d"),
            "error":      ("×", "#f57c00"),
        }

        def __init__(self):
            super().__init__()
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            self.attributes("-alpha", 0.85)
            self.configure(bg="#1e1e1e")
            sw = self.winfo_screenwidth()
            self.geometry(f"72x72+{sw - 84}+8")

            self._canvas = tk.Canvas(self, width=72, height=72, bg="#1e1e1e", highlightthickness=0)
            self._canvas.pack()
            self._item = self._canvas.create_text(
                36, 36, text="○", fill="#888888",
                font=("Segoe UI Symbol", 30, "bold"),
            )
            self._blink_job: str | None = None
            self.set_state("idle")

            # Right-click to exit
            self._canvas.bind("<Button-3>", lambda _: self.destroy())

        def set_state(self, state: str):
            icon, color = self._STATES.get(state, self._STATES["idle"])
            self._canvas.itemconfig(self._item, text=icon, fill=color)
            if self._blink_job:
                self.after_cancel(self._blink_job)
                self._blink_job = None
            if state == "recording":
                self._blink(True)

        def _blink(self, bright: bool):
            color = "#e53935" if bright else "#b71c1c"
            self._canvas.itemconfig(self._item, fill=color)
            self._blink_job = self.after(400, lambda: self._blink(not bright))

        def safe_set_state(self, state: str):
            """Thread-safe state update via tkinter event queue."""
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
    global _stream, _audio_chunks
    with _lock:
        _audio_chunks = []
    _stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        callback=_audio_callback,
    )
    _stream.start()
    log.info("recording started")


def stop_recording() -> bytes | None:
    global _stream
    if _stream:
        _stream.stop()
        _stream.close()
        _stream = None
    with _lock:
        chunks = list(_audio_chunks)
    if not chunks:
        log.info("no audio captured")
        return None
    audio = np.concatenate(chunks, axis=0)
    buf = io.BytesIO()
    wavfile.write(buf, SAMPLE_RATE, audio)
    log.info("recording stopped: %d samples (%.1fs)", len(audio), len(audio) / SAMPLE_RATE)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------
def transcribe(wav_bytes: bytes) -> str:
    if BACKEND == "gemini":
        return _transcribe_gemini(wav_bytes)
    if BACKEND == "cloudflare":
        return _transcribe_cloudflare(wav_bytes)
    if BACKEND == "local_whisper":
        return _transcribe_local(wav_bytes)
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
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
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
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio_float32, language="ja", sampling_rate=SAMPLE_RATE)
    return "".join(s.text for s in segments).strip()


# ---------------------------------------------------------------------------
# Paste (preserves focus on active window)
# ---------------------------------------------------------------------------
def paste_text(text: str):
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    # Clear clipboard after paste — do not leave transcribed text in clipboard
    threading.Timer(0.5, lambda: pyperclip.copy("")).start()


# ---------------------------------------------------------------------------
# Key event handlers
# ---------------------------------------------------------------------------
def _on_press(key, indicator: Indicator):
    global _active
    if key != HOTKEY or _active:
        return
    _active = True
    indicator.safe_set_state("recording")
    start_recording()


def _on_release(key, indicator: Indicator):
    global _active
    if key != HOTKEY or not _active:
        return
    _active = False
    indicator.safe_set_state("processing")
    threading.Thread(target=_process_and_paste, args=(indicator,), daemon=True).start()


def _process_and_paste(indicator: Indicator):
    import time  # noqa: PLC0415
    try:
        wav_bytes = stop_recording()
        if not wav_bytes:
            indicator.safe_set_state("idle")
            return
        t0 = time.perf_counter()
        text = transcribe(wav_bytes)
        elapsed = time.perf_counter() - t0
        log.info("transcription took %.2fs, %d chars", elapsed, len(text))
        if text:
            paste_text(text)
        indicator.safe_set_state("idle")
    except Exception as exc:
        log.error("error during transcription: %s: %s", type(exc).__name__, exc)
        indicator.safe_set_state("error")
        threading.Timer(3.0, lambda: indicator.safe_set_state("idle")).start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    indicator = Indicator()

    listener = keyboard.Listener(
        on_press=lambda key: _on_press(key, indicator),
        on_release=lambda key: _on_release(key, indicator),
    )
    listener.start()
    log.info("voice-fep v%s ready (model: %s) — F8 to record, right-click indicator to quit",
             APP_VERSION, GEMINI_MODEL)

    try:
        indicator.mainloop()
    finally:
        listener.stop()
        log.info("voice-fep stopped")


if __name__ == "__main__":
    main()
