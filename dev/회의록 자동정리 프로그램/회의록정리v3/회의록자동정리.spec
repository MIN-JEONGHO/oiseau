# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 설정 — 단일 exe 로 묶는다.

  python -m PyInstaller --noconfirm --clean 회의록자동정리.spec

같은 폴더에 ffmpeg.exe 를 두면 함께 묶여 25MB 넘는 녹음파일도 분할할 수 있다.
(av 패키지를 설치해 두었다면 ffmpeg.exe 는 없어도 된다)

embedded_key.py 에 API 키를 적어 두면 그대로 exe 안에 들어간다.
"""
import os

from PyInstaller.utils.hooks import collect_all

datas = [
    ("template.hwpx", "."),
    ("ui/index.html", "ui"),
]
binaries = []
hiddenimports = []

# ffmpeg.exe 가 옆에 있으면 동봉
if os.path.exists("ffmpeg.exe"):
    binaries.append(("ffmpeg.exe", "."))
if os.path.exists("ffprobe.exe"):
    binaries.append(("ffprobe.exe", "."))

for pkg in ("webview",):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:                      # 미설치 시 건너뜀
        pass

# PyAV 은 설치되어 있을 때만 포함 (없으면 CLOVA 또는 25MB 이하 파일만 처리)
try:
    d, b, h = collect_all("av")
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    pass


a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["lxml._elementpath", "tkinter", "tkinter.filedialog"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "scipy", "PIL", "PySide6", "PyQt5"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="회의록자동정리",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 콘솔 창 숨김 (GUI)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
