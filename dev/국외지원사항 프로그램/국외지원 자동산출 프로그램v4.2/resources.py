# -*- coding: utf-8 -*-
"""프로그램 내장 자원(매핑테이블·표준보고양식·아이콘) 해석과 내려받기.

배포를 exe 한 개로 끝내기 위해 자원을 실행파일 안에 넣는다(PyInstaller datas).
그런데 매핑테이블과 양식은 담당자가 고쳐 써야 하는 파일이므로, 내장본을
'수정할 수 없는 기본값'으로만 두고 다음 순서로 찾는다.

    1) exe(또는 .py)와 같은 폴더        ← 담당자가 내려받아 고친 파일. 최우선
    2) exe 안에 내장된 기본값           ← 아무것도 없을 때 쓰는 공장 출하값

그래서 exe만 있어도 바로 돌아가고, [양식·테이블 내려받기]로 꺼내 고치면
그 다음 실행부터 고친 파일이 자동으로 이긴다. 내장본은 그대로 남아 있으니
잘못 고쳤을 때 다시 꺼내 되돌릴 수 있다.
"""
import os
import shutil
import sys

#: 내장 대상. (파일명, 담당자가 고쳐 쓰는 파일인지)
BUNDLED = (
    ('매핑테이블.xlsx', True),
    ('표준보고양식.hwpx', True),
    ('사용설명서.md', False),
    ('app_icon.ico', False),
    ('app_icon.png', False),
)

#: 내려받기 대상 — 담당자가 고쳐 쓰는 파일만
EDITABLE = tuple(n for n, ed in BUNDLED if ed)

MAP_NAME = '매핑테이블.xlsx'
TPL_NAME = '표준보고양식.hwpx'


def frozen():
    """PyInstaller로 묶인 exe로 실행 중인가."""
    return getattr(sys, 'frozen', False)


def app_dir():
    """exe(또는 스크립트)가 놓인 폴더. 담당자가 고친 파일을 두는 자리."""
    if frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def bundle_dir():
    """내장 자원이 풀리는 임시 폴더. exe가 아니면 소스 폴더와 같다."""
    return getattr(sys, '_MEIPASS', None) or app_dir()


def resource_path(name):
    """자원 실제 경로. 옆에 있는 파일이 내장본을 이긴다. 둘 다 없으면 ''."""
    side = os.path.join(app_dir(), name)
    if os.path.exists(side):
        return side
    inner = os.path.join(bundle_dir(), name)
    if os.path.exists(inner):
        return inner
    return ''


def resource_origin(name):
    """그 자원이 어디서 왔는지 → '수정본' / '내장' / ''(없음)."""
    if os.path.exists(os.path.join(app_dir(), name)):
        return '수정본'
    if os.path.exists(os.path.join(bundle_dir(), name)):
        return '내장'
    return ''


def bundled_source(name):
    """내장본 경로. exe가 아니면 소스 폴더의 원본이 곧 내장본이다."""
    p = os.path.join(bundle_dir(), name)
    return p if os.path.exists(p) else ''


def export_resources(dest_dir, names=None, overwrite=False):
    """내장 자원을 dest_dir로 꺼낸다.

    덮어쓰기는 기본으로 하지 않는다. 담당자가 이미 고쳐 둔 파일을 조용히
    날리면 손으로 채운 별칭·규칙이 사라지기 때문이다.

    → [(파일명, 상태, 경로)] / 상태: '내려받음' | '이미 있음' | '내장본 없음' | '실패: 사유'
    """
    names = names or EDITABLE
    out = []
    os.makedirs(dest_dir, exist_ok=True)
    for name in names:
        src = bundled_source(name)
        dst = os.path.join(dest_dir, name)
        if not src:
            out.append((name, '내장본 없음', ''))
            continue
        if os.path.abspath(src) == os.path.abspath(dst):
            # 소스 실행 중 같은 폴더로 내려받기 — 자기 자신을 덮을 일은 없다
            out.append((name, '이미 있음', dst))
            continue
        if os.path.exists(dst) and not overwrite:
            out.append((name, '이미 있음', dst))
            continue
        try:
            shutil.copyfile(src, dst)
            out.append((name, '내려받음', dst))
        except Exception as e:
            out.append((name, f'실패: {e}', dst))
    return out


def existing_overrides(dest_dir, names=None):
    """dest_dir에 이미 있는(=덮어쓰면 사라지는) 자원 이름 목록."""
    names = names or EDITABLE
    return [n for n in names
            if os.path.exists(os.path.join(dest_dir, n))
            and os.path.abspath(os.path.join(dest_dir, n)) !=
                os.path.abspath(bundled_source(n) or '\0')]
