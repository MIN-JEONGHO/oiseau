# -*- coding: utf-8 -*-
r"""
설정 저장/불러오기 + 사용할 모델 고정값.

API 키는 화면에서 입력받지 않는다. 빌드할 때 embedded_key.py 에 적어 둔 키를 쓰고,
개발 중에는 환경변수로 대신할 수 있다.

  1) embedded_key.py 의 OPENAI_API_KEY   <- 배포용. exe 에 함께 묶인다
  2) 환경변수 OPENAI_API_KEY             <- 개발 중 편의

그래서 config.json 에는 비밀 값이 들어가지 않고, 화면(브라우저)으로도 키가 전달되지
않는다. 저장되는 것은 작성 부서 같은 문서 기본값뿐이다.

저장 위치
  %APPDATA%\KISTEP회의록정리\config.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:                                     # 내장 키 (없어도 동작)
    from embedded_key import OPENAI_API_KEY as _EMBEDDED_KEY
except Exception:                        # noqa: BLE001
    _EMBEDDED_KEY = ""

APP_DIR_NAME = "KISTEP회의록정리"
CONFIG_NAME = "config.json"

#: 전사 모델 — 구간별 시각(verbose_json 의 segments)을 주는 Whisper 모델로 고정.
#: 다른 모델은 구간 정보를 주지 않아 발언자 매칭이 불가능해진다.
STT_MODEL = "whisper-1"

#: 요약 모델 — 발언자 매칭과 기관별 요약에 쓴다.
#: 모델을 바꿀 일이 생기면 이 한 줄만 고치고 다시 빌드하면 된다.
SUMMARY_MODEL = "gpt-5.6-luna"

#: 화면에서 고칠 수 있는 설정 (= config.json 에 저장되는 값). API 키는 여기 없다.
DEFAULTS: dict[str, Any] = {
    "org_footer": "KISTEP 연구윤리자산보호센터",
    "attach_transcript": True,           # 참고: 회의록 원문 첨부 여부
    "last_outdir": "",
}


# ---------------------------------------------------------------------------
# API 키
# ---------------------------------------------------------------------------

def embedded_api_key() -> str:
    """embedded_key.py 에 적어 둔 내장 키 (없으면 빈 문자열)."""
    return (_EMBEDDED_KEY or "").strip()


def key_embedded() -> bool:
    return bool(embedded_api_key())


def api_key() -> str:
    """실제로 쓸 API 키. 내장 키가 없으면 환경변수를 본다."""
    return embedded_api_key() or (os.environ.get("OPENAI_API_KEY") or "").strip()


# ---------------------------------------------------------------------------
# 파일 입출력
# ---------------------------------------------------------------------------

def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    d = Path(base) / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / CONFIG_NAME


def load() -> dict[str, Any]:
    """저장된 문서 기본값 + 실행 중 쓸 API 키를 합쳐 돌려준다."""
    cfg = dict(DEFAULTS)
    p = config_path()
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            raw = {}
        for k, v in raw.items():
            if k in DEFAULTS:            # 구버전 파일에 남은 항목은 무시한다
                cfg[k] = v
    cfg["openai_api_key"] = api_key()    # 저장 대상이 아니라 실행 중에만 쓰는 값
    return cfg


def save(cfg: dict[str, Any]) -> Path:
    """설정을 저장한다. DEFAULTS 에 있는 값만 기록하므로 키는 파일에 남지 않는다."""
    out = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    p = config_path()
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def settings(cfg: dict[str, Any]) -> dict[str, Any]:
    """화면으로 내보낼 설정. API 키는 포함하지 않는다."""
    return {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
