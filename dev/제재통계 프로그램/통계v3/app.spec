# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 빌드 설정 — 제재처분 원인과제 집계

  pip install pyinstaller pywebview
  pyinstaller app.spec --noconfirm

dist/제재처분집계.exe 하나만 나옵니다. ui/index.html 은 exe 안에 포함되고
app.py 의 resource_path() 가 실행 시 임시 폴더에서 찾아 씁니다.
"""

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('template.hwpx', '.'),          # 원인과제 집계 양식
        ('template_monthly.hwpx', '.'),  # 월별 통계 양식
        ('reference.xlsx', '.'),
    ],
    hiddenimports=[
        'openpyxl.cell._writer',   # openpyxl 지연 임포트
        'python_calamine',         # 빠른 엑셀 리더
        'xlsxwriter',
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'scipy', 'PyQt5', 'PySide6', 'tkinter.test',
        'notebook', 'IPython', 'pytest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='제재통계',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 콘솔 창 숨김. 오류 추적이 필요하면 True
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,              # 아이콘이 있으면 'app.ico'
)
