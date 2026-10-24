# -*- mode: python ; coding: utf-8 -*-
import hashlib
import json
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

project = Path(SPECPATH)
datas = [(str(project / 'book_icon.ico'), '.')]

# Only application assets: preserve the frozen catalogue's complete relative tree.
for relative in ('ui_v16', 'templates/v15', 'resources_v16/notices'):
    directory = project / relative
    for source in sorted(directory.rglob('*')):
        if source.is_file():
            datas.append((str(source), str(source.parent.relative_to(project))))

notice_root = project / 'resources_v16' / 'notices'
manifest = json.loads((notice_root / 'manifest.json').read_text(encoding='utf-8'))
for entry in manifest['files']:
    source = notice_root / entry['relative_path']
    if hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
        raise ValueError('Frozen catalogue file hash differs')

hiddenimports = [
    'desktop_bridge_v16', 'classification_v16', 'batch_v16', 'hwpx_writer_v16',
    'v16_domain', 'notice_catalogue_v16', 'notice_review_v16',
    'credential_store', 'llm_client_v14', 'llm_json_v16',
    'webview', 'webview.platforms.winforms', 'webview.platforms.edgechromium',
    'webview.platforms.win32', 'clr', 'pythonnet', 'clr_loader', '_cffi_backend',
    'requests', 'openpyxl', 'lxml.etree',
]
for package in ('openai', 'anthropic'):
    hiddenimports += collect_submodules(package)
    datas += collect_data_files(package)
    datas += copy_metadata(package, recursive=True)

# pywebview's upstream hook also collects lib/js; explicit data protects the
# version-pinned native host from a lower-priority hook's incomplete JS policy.
datas += collect_data_files('webview', subdir='js')
datas += collect_data_files('webview', subdir='lib')
datas += copy_metadata('pywebview')
datas += collect_data_files('pythonnet', subdir='runtime')
datas += collect_data_files('clr_loader', subdir='ffi/dlls')
datas = list(dict.fromkeys(datas))

a = Analysis(
    [str(project / 'security_grade_classifier_v16.py')],
    pathex=[str(project)], binaries=[], datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter', 'webview.platforms.mshtml',
        'PySide2', 'PySide6', 'PyQt5', 'PyQt6', 'qtpy', 'cefpython3', 'gi',
        'webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cocoa',
        'webview.platforms.cef', 'webview.platforms.android',
        'fitz', 'pymupdf', 'pymupdf4llm', 'pypdf', 'PyPDF2', 'pdfplumber',
        'pdfminer', 'pikepdf', 'playwright', 'pytest', '_pytest',
        'pandas', 'docx', 'google.generativeai', 'torch', 'torchvision', 'torchaudio',
        'transformers', 'tokenizers', 'safetensors', 'huggingface_hub', 'accelerate',
        'datasets', 'sklearn', 'scipy', 'sympy', 'networkx', 'matplotlib', 'numpy',
        'security_grade_classifier_v12', 'security_grade_classifier_v13_test',
        'security_grade_classifier_v14', 'classification_v14', 'batch_v14',
        'v14_domain', 'hwpx_writer', 'embedded_key',
        # v16 never bundles the preserved v15 runtime path (spec 4.10).
        'security_grade_classifier_v15', 'desktop_bridge_v15', 'v15_domain',
        'notice_catalogue_v15', 'notice_review_v15', 'classification_v15',
        'batch_v15', 'hwpx_writer_v15',
    ],
    noarchive=False, optimize=0,
)
# The upstream hook also brings MSHTML interop and Android Java assets. The
# host refuses those renderers; retain only the pinned Edge runtime libraries.
unused_native_assets = {'WebBrowserInterop.x64.dll', 'WebBrowserInterop.x86.dll',
                        'pywebview-android.jar'}
a.datas = [entry for entry in a.datas if Path(entry[0]).name not in unused_native_assets]
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name not in unused_native_assets]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='보안등급분류시뮬레이터_v16', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, upx_exclude=[],
    runtime_tmpdir=None, console=False, disable_windowed_traceback=True,
    argv_emulation=False, target_arch=None, codesign_identity=None,
    entitlements_file=None, icon=[str(project / 'book_icon.ico')],
)
