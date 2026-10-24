# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 빌드 설정 — 연구보안·연구윤리 리포트 모니터링 (GUI)

  pip install -r requirements.txt pyinstaller
  pyinstaller 연구보안연구윤리_모니터링.spec --noconfirm

PyInstaller 6 기준 문법입니다.

dist/연구보안연구윤리_모니터링.exe 하나만 나옵니다(onefile). ui/index.html, prompts/*.txt,
엑셀 템플릿/샘플 데이터는 exe 안에 읽기 전용으로 포함되고 rmonitor/utils.py 의
resource_dir() 이 실행 시 임시 폴더(sys._MEIPASS)에서 찾아 씁니다.

반대로 config.json·output·logs·history·누적 엑셀처럼 "쓰기"가 필요한 데이터는
rmonitor/utils.py 의 app_dir() 이 exe 파일이 있는 폴더(고정 위치)를 가리키므로,
임시 폴더가 정리되어도 다음 실행에 그대로 남습니다.

주의: run_cli.py(명령줄/작업 스케줄러용)는 이 spec 에 포함되지 않습니다 — 자동 실행은
지금처럼 Python 스크립트(`python run_cli.py ...`)로 그대로 사용하세요.
"""

a = Analysis(
    ['run_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('prompts', 'prompts'),
        ('data/_양식_동향_모니터링.xlsx', 'data'),
        ('data/sample_security.json', 'data'),
        ('data/sample_ethics.json', 'data'),
    ],
    hiddenimports=[
        'openpyxl.cell._writer',   # openpyxl 지연 임포트
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
    name='연구보안연구윤리_모니터링',
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
