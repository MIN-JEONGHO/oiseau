# -*- mode: python ; coding: utf-8 -*-
# Claude 전용 슬림 빌드: anthropic만 포함, openai / google(gemini) 제외 + API 키 하드코딩

from PyInstaller.utils.hooks import collect_all

datas = [('book_icon.ico', '.')]
binaries = []
hiddenimports = ['openpyxl', 'docx', 'requests', 'anthropic']

# Claude(anthropic) SDK만 완전 포함
d, b, h = collect_all('anthropic')
datas += d
binaries += b
hiddenimports += h

# openai / gemini(google) 및 무거운 딸림 패키지 제외
# + 로컬 ML 스택(torch/transformers 등) 제외 — 이 앱은 API 호출만 함
excludes = [
    'openai',
    'google',
    'google.generativeai',
    'google.api_core',
    'google.auth',
    'google.protobuf',
    'grpc',
    'grpc_status',
    'googleapiclient',
    'proto',
    'torch', 'torchvision', 'torchaudio',
    'transformers', 'tokenizers', 'safetensors',
    'huggingface_hub', 'accelerate', 'datasets',
    'sklearn', 'scipy', 'sympy', 'networkx',
]

a = Analysis(
    ['security_grade_classifier_v12_claude.py'],
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
    name='보안등급분류시뮬레이터_v12_claude',
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
