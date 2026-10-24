# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 빌드 설정 — 국가연구개발 제재처분 통계산출

  pip install pyinstaller pywebview
  pyinstaller app.spec --noconfirm

PyInstaller 6 기준 문법입니다. (5.x 의 cipher / win_no_prefer_redirects /
a.zipped_data 인자는 6.0 에서 제거되어 쓰지 않습니다.)

dist/제재처분집계.exe 하나만 나옵니다. ui/index.html 은 exe 안에 포함되고
app.py 의 resource_path() 가 실행 시 임시 폴더에서 찾아 씁니다.
"""

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('template.hwpx', '.'),          # 연구수행 기준 양식
        ('template_monthly.hwpx', '.'),  # 처분연도 기준 양식
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
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
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
