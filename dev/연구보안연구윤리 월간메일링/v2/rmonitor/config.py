# -*- coding: utf-8 -*-
"""config.json 로딩/저장. 민감정보는 환경변수로 덮어쓸 수 있다."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "llm": {
        "provider": "gemini",              # gemini | anthropic | openai
        "model": "gemini-2.5-pro",
        "api_key": "",                     # 환경변수 RM_LLM_API_KEY 로도 지정 가능
        "timeout_sec": 900,
        "max_output_tokens": 20000,
        "temperature": 0.2,
        "enable_web_search": True,
    },
    "smtp": {
        "provider": "gmail",               # gmail | naver | custom
        "host": "smtp.gmail.com",
        "port": 587,
        "security": "starttls",            # starttls | ssl | none
        "user": "",
        "password": "",                    # 환경변수 RM_SMTP_PASSWORD 로도 지정 가능
        "sender_name": "연구보안·연구윤리 모니터링",
        "sender_email": ""                 # 비우면 user 값 사용
    },
    "excel": {
        "path": "data/동향_모니터링_누적.xlsx",
        "sheet": "누적데이터",
        "template": "data/_양식_동향_모니터링.xlsx",
        "skip_duplicate_url": True
    },
    "output_dir": "output",
    "log_dir": "logs",
    "reports": {
        "security": {
            "enabled": True,
            "recipients": [],
            "cc": [],
            "bcc": []
        },
        "ethics": {
            "enabled": True,
            "recipients": [],
            "cc": [],
            "bcc": []
        }
    }
}

SMTP_PRESETS = {
    "gmail":  {"host": "smtp.gmail.com",     "port": 587, "security": "starttls"},
    "naver":  {"host": "smtp.naver.com",     "port": 587, "security": "starttls"},
    "daum":   {"host": "smtp.daum.net",      "port": 465, "security": "ssl"},
    "outlook": {"host": "smtp.office365.com", "port": 587, "security": "starttls"},
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
    cfg = _deep_merge(DEFAULT_CONFIG, user_cfg)

    # 환경변수 우선 적용(운영/스케줄러 환경에서 비밀번호를 파일에 두지 않기 위함)
    if os.getenv("RM_LLM_API_KEY"):
        cfg["llm"]["api_key"] = os.environ["RM_LLM_API_KEY"]
    if os.getenv("RM_SMTP_PASSWORD"):
        cfg["smtp"]["password"] = os.environ["RM_SMTP_PASSWORD"]
    if os.getenv("RM_SMTP_USER"):
        cfg["smtp"]["user"] = os.environ["RM_SMTP_USER"]
    return cfg


def save_config(cfg: Dict[str, Any], path: str | os.PathLike = "config.json") -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:  # 비밀번호가 담기므로 소유자만 읽도록(POSIX 한정)
        os.chmod(p, 0o600)
    except Exception:
        pass


def apply_smtp_preset(cfg: Dict[str, Any], provider: str) -> Dict[str, Any]:
    """gmail/naver 등 프리셋으로 host/port/security 자동 설정."""
    preset = SMTP_PRESETS.get(provider)
    if preset:
        cfg["smtp"].update(preset)
    cfg["smtp"]["provider"] = provider
    return cfg


def sender_address(cfg: Dict[str, Any]) -> str:
    return (cfg["smtp"].get("sender_email") or cfg["smtp"].get("user") or "").strip()
