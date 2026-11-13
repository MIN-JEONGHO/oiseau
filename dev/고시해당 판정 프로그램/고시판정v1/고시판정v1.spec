# -*- mode: python ; coding: utf-8 -*-
# 고시판정v1 빌드(1.2.0부터 폴더형). 프로그램 폴더에서 `python -m PyInstaller --noconfirm 고시판정v1.spec`로 실행하면
# dist\고시판정v1\ 폴더(고시판정v1.exe + _internal)가 생기고, installer\고시수준검토.iss로 설치 파일을 만든다.
# 개발 전용(tools/)·시험(tests/)·AGPL PDF 라이브러리(PyMuPDF)는 넣지 않는다.
import hashlib
import json
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

project = Path(SPECPATH)
datas = []

# 실행 자원: 화면(로컬 폰트 포함)·고시 자료·기준값 표·아이콘. 상대 경로 구조를 그대로 보존한다.
for relative in ('ui', 'resources'):
    directory = project / relative
    for source in sorted(directory.rglob('*')):
        if source.is_file():
            datas.append((str(source), str(source.parent.relative_to(project))))

# 고시 자료 복사본의 해시가 manifest와 다르면 빌드를 멈춘다.
notice_root = project / 'resources' / 'notices'
manifest = json.loads((notice_root / 'manifest.json').read_text(encoding='utf-8'))
for entry in manifest['files']:
    source = notice_root / entry['relative_path']
    if hashlib.sha256(source.read_bytes()).hexdigest() != entry['sha256']:
        raise ValueError('고시 자료 복사본의 해시가 manifest와 다름: ' + entry['relative_path'])
if not (project / 'resources' / 'thresholds.json').is_file():
    raise ValueError('기준값 표 resources/thresholds.json이 없음. tools/build_threshold_table.py를 먼저 실행')
# 고시 검색 자원(관련어 사전·의미 벡터 모델·조항 벡터)이 모두 있어야 한다.
for required in ('search_dictionary.json', 'search_vectors.json', 'search_vectors.npy', 'search_model/MODEL_INFO.json'):
    if not (project / 'resources' / required).is_file():
        raise ValueError('고시 검색 자원이 없음: resources/' + required)

# brief(1.3.0 간단한 결과)는 pipeline이 함수 안에서 import하므로(순환 import 회피) 분석이 놓치지 않게 적어 둔다.
hiddenimports = [
    'bridge', 'pipeline', 'brief', 'batch', 'excel_report', 'judge_engine', 'units', 'threshold_table',
    'notice_catalogue', 'doc_extract', 'ai_stages', 'llm_client', 'llm_json', 'credential_store', 'paths',
    'webview', 'webview.platforms.winforms', 'webview.platforms.edgechromium',
    'webview.platforms.win32', 'clr', 'pythonnet', 'clr_loader', '_cffi_backend',
    'requests', 'openpyxl', 'lxml.etree', 'pypdf', 'notice_search', 'numpy', 'tokenizers',
]
for package in ('openai', 'anthropic', 'pypdf'):
    hiddenimports += collect_submodules(package)
    datas += collect_data_files(package)
    datas += copy_metadata(package, recursive=True)

datas += collect_data_files('webview', subdir='js')
datas += collect_data_files('webview', subdir='lib')
datas += copy_metadata('pywebview')
datas += collect_data_files('pythonnet', subdir='runtime')
datas += collect_data_files('clr_loader', subdir='ffi/dlls')
datas = list(dict.fromkeys(datas))

a = Analysis(
    [str(project / 'app.py')],
    pathex=[str(project)], binaries=[], datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=[
        'tkinter', '_tkinter', 'webview.platforms.mshtml',
        'PySide2', 'PySide6', 'PyQt5', 'PyQt6', 'qtpy', 'cefpython3', 'gi',
        'webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cocoa',
        'webview.platforms.cef', 'webview.platforms.android',
        # AGPL·불필요 PDF 라이브러리와 개발 도구
        'fitz', 'pymupdf', 'pymupdf4llm', 'PyPDF2', 'pdfplumber', 'pdfminer', 'pikepdf',
        'playwright', 'pytest', '_pytest', 'unittest', 'tests', 'tools',
        'pandas', 'matplotlib', 'scipy', 'sympy', 'networkx', 'sklearn',
        'torch', 'torchvision', 'torchaudio', 'transformers', 'safetensors',
        # 고시 검색은 numpy·tokenizers만 쓴다. 모델 허브·내려받기·비교용 라이브러리는 넣지 않는다(실행 중 인터넷 접속 없음).
        'huggingface_hub', 'hf_xet', 'fsspec', 'filelock', 'onnxruntime', 'flatbuffers',
        'accelerate', 'datasets', 'google.generativeai', 'embedded_key',
    ],
    noarchive=False, optimize=0,
)
unused_native_assets = {'WebBrowserInterop.x64.dll', 'WebBrowserInterop.x86.dll', 'pywebview-android.jar'}
a.datas = [entry for entry in a.datas if Path(entry[0]).name not in unused_native_assets]
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name not in unused_native_assets]
pyz = PYZ(a.pure)
# 폴더형: 켤 때마다 파일을 풀지 않으므로 모델이 있어도 켜는 시간이 늘지 않는다(결정 0012).
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='고시판정v1', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=True,
    argv_emulation=False, target_arch=None, codesign_identity=None,
    entitlements_file=None, icon=[str(project / 'resources' / 'book_icon.ico')],
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name='고시판정v1',
)
