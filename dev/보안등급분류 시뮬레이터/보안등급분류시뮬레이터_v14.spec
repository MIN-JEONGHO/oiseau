# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

project = Path(SPECPATH)
# 배포 자료는 아이콘과 두 파생 서식으로 한정한다. 원본 가이드라인은 넣지 않는다.
datas = [(str(project / 'book_icon.ico'), '.')]
datas += [(str(project / 'templates' / name), 'templates')
          for name in ('reviewer_opinion.hwpx', 'committee_summary.hwpx')]
hiddenimports = ['classification_v14', 'batch_v14', 'hwpx_writer', 'llm_client_v14',
                 'v14_domain', 'credential_store', 'requests', 'openpyxl', 'lxml.etree']
for package in ('openai', 'anthropic'):
    hiddenimports += collect_submodules(package)
    datas += collect_data_files(package)
    # SDK가 사용하는 배포 메타데이터와 httpx/httpx2 등 필수 전이 의존성을 수집한다.
    datas += copy_metadata(package, recursive=True)

a = Analysis(
    [str(project / 'security_grade_classifier_v14.py')],
    pathex=[str(project)], binaries=[], datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['PySide6', 'PyQt5', 'PyQt6', 'pandas', 'docx', 'google.generativeai',
              'torch', 'torchvision', 'torchaudio', 'transformers', 'tokenizers',
              'safetensors', 'huggingface_hub', 'accelerate', 'datasets',
              'sklearn', 'scipy', 'sympy', 'networkx', 'matplotlib', 'numpy'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='보안등급분류시뮬레이터_v14', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, upx_exclude=[],
    runtime_tmpdir=None, console=False, disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None, codesign_identity=None,
    entitlements_file=None, icon=[str(project / 'book_icon.ico')],
)
