"""AFC suppression verification — runs against real Gemini API.

Usage: python scripts/verify_afc.py
Requires GEMINI_API_KEY in .env or environment.

Checks that "AFC is enabled" does NOT appear in SDK debug logs when
AutomaticFunctionCallingConfig(disable=True) is set.
"""
import logging
import os
import sys
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

api_key = os.environ.get("GEMINI_API_KEY", "")
if not api_key:
    print("SKIP: GEMINI_API_KEY not set in .env")
    sys.exit(0)

from google import genai
from google.genai import types

# Use whatever model is configured; fall back to a known working model
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
print(f"Model: {MODEL}")

# ---- Helper: capture SDK debug logs ----------------------------------------
def _call_with_log_capture(config: types.GenerateContentConfig, retries: int = 3) -> tuple[str, str]:
    """Call generate_content and return (response_text, captured_debug_logs)."""
    last_exc = None
    for attempt in range(retries):
        buf = StringIO()
        handler = logging.StreamHandler(buf)
        handler.setLevel(logging.DEBUG)
        sdk_logger = logging.getLogger("google.genai")
        sdk_logger.setLevel(logging.DEBUG)
        sdk_logger.addHandler(handler)
        try:
            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model=MODEL,
                contents="Say hello in exactly one word.",
                config=config,
            )
            text = (resp.text or "").strip()
            return text, buf.getvalue()
        except Exception as exc:
            last_exc = exc
            print(f"  Attempt {attempt + 1} failed: {type(exc).__name__}: {exc}")
            import time as _time
            _time.sleep(2)
        finally:
            sdk_logger.removeHandler(handler)
    raise RuntimeError(f"All {retries} attempts failed") from last_exc


# ---- Test 1: WITHOUT disable → AFC should appear ---------------------------
print("=" * 60)
print("Test 1: WITHOUT AutomaticFunctionCallingConfig(disable=True)")
config_without = types.GenerateContentConfig(
    temperature=0.0,
    max_output_tokens=16,
    tool_config=types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(mode="NONE"),
    ),
)
text1, logs1 = _call_with_log_capture(config_without)
afc_present_1 = "AFC is enabled" in logs1
print(f"  Response  : {text1!r}")
print(f"  AFC log   : {'FOUND' if afc_present_1 else 'not found'}")
print()

# ---- Test 2: WITH disable=True → AFC must NOT appear -----------------------
print("Test 2: WITH AutomaticFunctionCallingConfig(disable=True)")
config_with = types.GenerateContentConfig(
    temperature=0.0,
    max_output_tokens=16,
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    tool_config=types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(mode="NONE"),
    ),
)
text2, logs2 = _call_with_log_capture(config_with)
afc_present_2 = "AFC is enabled" in logs2
print(f"  Response  : {text2!r}")
print(f"  AFC log   : {'FOUND (FAIL)' if afc_present_2 else 'not found (OK)'}")
print()

# ---- Result ----------------------------------------------------------------
print("=" * 60)
if not afc_present_2:
    print("PASS: AutomaticFunctionCallingConfig(disable=True) suppresses AFC.")
else:
    print("FAIL: AFC still present even with disable=True — investigate SDK version.")
    sys.exit(1)
