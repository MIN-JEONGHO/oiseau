# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['국외지원사항_통계산출.py'],
    pathex=[],
    binaries=[],
    datas=[],
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
