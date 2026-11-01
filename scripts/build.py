#!/usr/bin/env python3
"""Build voice-fep into a standalone --onedir executable using PyInstaller.

Usage:
    pip install -r requirements-build.txt
    python scripts/build.py

Output:
    dist/voice-fep/voice-fep.exe
    dist/voice-fep-v<version>-win64.zip
"""

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _read_version() -> str:
    """Extract APP_VERSION from main.py without importing the module."""
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*:\s*str\s*=\s*"([^"]+)"', src)
    return m.group(1) if m else "unknown"


def _create_zip(dist: Path, version: str) -> Path:
    """Compress dist/voice-fep/ into dist/voice-fep-v<version>-win64.zip."""
    zip_path = ROOT / "dist" / f"voice-fep-v{version}-win64.zip"
    print(f"\nCreating zip: {zip_path.name} ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in sorted(dist.rglob("*")):
            if file.is_file():
                # Archive as voice-fep/<relative path> so extraction creates the folder
                zf.write(file, file.relative_to(dist.parent))
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"  {zip_path.name}  ({size_mb:.1f} MB)")
    return zip_path


def main() -> None:
    version = _read_version()
    print(f"Building voice-fep v{version} ...")

    # Clean previous build artifacts
    for d in (ROOT / "build", ROOT / "dist"):
        if d.exists():
            try:
                shutil.rmtree(d)
                print(f"Cleaned: {d}")
            except PermissionError as e:
                print(f"ERROR: Cannot clean {d}")
                print(f"  {e}")
                print("  → voice-fep.exe が起動中の場合は終了してから再実行してください。")
                sys.exit(1)

    # Build using the spec file
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "voice-fep.spec", "--noconfirm"],
        cwd=ROOT,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)

    dist = ROOT / "dist" / "voice-fep"

    # Copy user-configurable files next to the exe (NOT bundled inside the exe)
    shutil.copy(ROOT / ".env.example", dist / ".env.example")
    print(f"Copied .env.example")

    if (ROOT / "system_prompt.txt").exists():
        shutil.copy(ROOT / "system_prompt.txt", dist / "system_prompt.txt")
        print(f"Copied system_prompt.txt")

    if (ROOT / "dictionary.txt").exists():
        shutil.copy(ROOT / "dictionary.txt", dist / "dictionary.txt")
        print(f"Copied dictionary.txt")

    # Create distribution zip
    zip_path = _create_zip(dist, version)

    # Report
    exe = dist / "voice-fep.exe"
    print(f"\n{'='*60}")
    print(f"Build complete  (voice-fep v{version})")
    print(f"{'='*60}")
    print(f"  Executable : {exe}  ({exe.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"  Zip        : {zip_path}  ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
    file_count = sum(1 for _ in dist.rglob("*") if _.is_file())
    print(f"  Files in dist/voice-fep/ : {file_count}")
    print(f"\nNext steps:")
    print(f"  1. Distribute {zip_path.name}")
    print(f"  2. Recipient unzips, renames .env.example → .env, adds GEMINI_API_KEY")
    print(f"  3. Run voice-fep.exe  (middle-click to open log)")


if __name__ == "__main__":
    main()
