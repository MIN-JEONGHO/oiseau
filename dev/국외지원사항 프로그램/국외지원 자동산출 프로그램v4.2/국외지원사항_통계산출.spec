# -*- mode: python ; coding: utf-8 -*-
#
# 배포 스펙 — exe 한 개만 옮기면 되도록 자원을 실행파일 안에 넣는다.
#
#   pyinstaller 국외지원사항_통계산출.spec
#
# datas에 넣은 파일은 실행 시 sys._MEIPASS 아래로 풀린다. resources.py가
# 'exe 옆의 파일 → 내장본' 순서로 찾으므로, 담당자가 [양식·테이블 내려받기]로
# 꺼내 고친 파일이 있으면 그쪽이 이긴다.

datas = [
    ('매핑테이블.xlsx', '.'),
    ('표준보고양식.hwpx', '.'),
    ('사용설명서.md', '.'),
    ('app_icon.ico', '.'),
    ('app_icon.png', '.'),
]

a = Analysis(
    ['국외지원사항_통계산출.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'PIL', 'sqlalchemy', 'pyarrow', 'scipy', 'tables', 'numexpr', 'bottleneck', 'IPython', 'ipython', 'jupyter', 'notebook', 'pytest', 'xlrd', 'xlwt', 's3fs', 'gcsfs', 'fsspec', 'boto3', 'botocore', 'docutils', 'babel', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'psycopg2', 'MySQLdb', 'numpy.f2py'],
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
    name='국외지원사항_통계산출',
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
    icon=['app_icon.ico'],
)
