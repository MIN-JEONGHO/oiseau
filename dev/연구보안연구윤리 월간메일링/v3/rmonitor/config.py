# -*- coding: utf-8 -*-
"""config.json 로딩/저장.

LLM 연동(provider/모델/API 키)은 v3부터 설정 항목이 아니다 — Claude Sonnet 5.5로 고정되어
있고 API 키도 rmonitor/_secrets.py 에 하드코딩되어 있다(RM_LLM_API_KEY 환경변수로 재정의
가능). 자세한 내용은 rmonitor/llm.py 참고.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "period": {
        "mode": "monthly",                 # "monthly" | "weekly" -- 실행 화면 기본 선택값
    },
    "excel": {
        "path": "data/동향_모니터링_누적.xlsx",
        "sheet": "누적데이터",
        "template": "data/_양식_동향_모니터링.xlsx",
        "skip_duplicate_url": True
    },
    "history": {
        "path": "history/history.jsonl",   # 실행 이력 저장 위치
    },
    "output_dir": "output",
    "log_dir": "logs",
    "reports": {
        "security": {
            "enabled": True
        },
        "ethics": {
            "enabled": True
        }
    }
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | os.PathLike = "config.json") -> Dict[str, Any]:
    """설정 로드. 파일이 없으면 기본값을 사용한다."""
    p = Path(path)
    user_cfg = {}
    if p.exists():
        user_cfg = json.loads(p.read_text(encoding="utf-8"))
    return _deep_merge(DEFAULT_CONFIG, user_cfg)


def save_config(cfg: Dict[str, Any], path: str | os.PathLike = "config.json") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:  # 소유자만 읽도록(POSIX 한정)
        os.chmod(p, 0o600)
    except Exception:
        pass
