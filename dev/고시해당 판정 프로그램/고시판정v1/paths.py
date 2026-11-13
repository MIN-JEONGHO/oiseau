"""내장 자원 경로. 소스 실행과 PyInstaller exe 양쪽에서 같은 함수로 자원을 찾는다.

모든 모듈은 이 함수로만 자원 경로를 얻는다. 스크립트 기준 상대 경로를 직접 쓰면 exe에서 깨진다.
"""
from pathlib import Path
import sys

PROGRAM_NAME = "연구보안 등급분류 분류기준(고시) 검토"
PROGRAM_VERSION = "1.4.2"


def asset_root() -> Path:
    """빌드한 프로그램이면 PyInstaller 자원 폴더(1.2.0부터 폴더형이라 실행 파일 옆 `_internal`), 소스이면 이 파일이 있는 폴더."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).resolve()


def resource_path(*parts: str) -> Path:
    """`resources/` 아래 자원(고시 자료·고시 기준 사양 표(thresholds.json)·아이콘)의 절대 경로."""
    return asset_root().joinpath("resources", *parts)


def notices_root() -> Path:
    """고시 자료 폴더(시뮬레이터 resources_v16/notices를 바이트 그대로 복사한 것)."""
    return resource_path("notices")


def threshold_table_path() -> Path:
    """개발 때 한 번 만들어 고정한 기준값 표(화면·처리내역 이름: 고시 기준 사양 표)."""
    return resource_path("thresholds.json")


def ui_root() -> Path:
    """화면 자산(HTML·CSS·JS·로컬 폰트)."""
    return asset_root() / "ui"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
