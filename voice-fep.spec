# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for voice-fep (--onedir, no console window)
#
# Usage:
#   pip install -r requirements-build.txt
#   python scripts/build.py         # recommended (handles post-build copies)
#   # or directly:
#   pyinstaller voice-fep.spec --noconfirm

from PyInstaller.utils.hooks import collect_all

block_cipher = None

# Collect all files/binaries/hiddenimports from packages with native code
datas_fw, binaries_fw, hiddenimports_fw = collect_all("faster_whisper")
datas_ct2, binaries_ct2, hiddenimports_ct2 = collect_all("ctranslate2")

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries_fw + binaries_ct2,
    datas=datas_fw + datas_ct2,
    hiddenimports=(
        hiddenimports_fw
        + hiddenimports_ct2
        + [
            "google.genai",
            "google.auth",
            "google.auth.transport.requests",
            "scipy.io.wavfile",
            "tkinter",
            "tkinter.messagebox",
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="voice-fep",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # no console window; use run_silent.vbs for silent background start
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="voice-fep",
)
