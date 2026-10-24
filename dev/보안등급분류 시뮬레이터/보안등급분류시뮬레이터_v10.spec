# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

# 지연 import(함수 내부 import) 되는 SDK들을 확실히 포함
datas = [('book_icon.ico', '.')]
binaries = []
hiddenimports = ['openpyxl', 'docx', 'requests', 'openai', 'anthropic']

for pkg in ('anthropic', 'openai', 'google.generativeai'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 로컬 ML 스택은 사용하지 않으므로 제외(용량 대폭 감소)
excludes = [
    'torch', 'torchvision', 'torchaudio',
    'transformers', 'tokenizers', 'safetensors',
    'huggingface_hub', 'accelerate', 'datasets',
    'sklearn', 'scipy', 'sympy', 'networkx',
]

a = Analysis(
    ['security_grade_classifier_v10.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='보안등급분류시뮬레이터_v10',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['book_icon.ico'],
)
