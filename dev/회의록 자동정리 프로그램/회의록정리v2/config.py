# -*- coding: utf-8 -*-
r"""
설정 저장/불러오기 + 사용할 모델 고정값.

전사(Whisper)와 요약(GPT) 모두 OpenAI 를 쓰므로 필요한 키는 OpenAI API 키 하나다.
키를 찾는 순서는 다음과 같다.

  1) embedded_key.py 에 적어 둔 내장 키   ← 배포용. 받는 사람이 입력할 것이 없다
  2) 환경변수 OPENAI_API_KEY             ← 개발 중 편의
  3) [설정] 탭에서 입력해 저장한 키       ← Windows DPAPI 로 암호화해 보관

3) 은 현재 사용자 계정에 묶여 암호화되므로 config.json 을 다른 계정·다른 PC 로
복사해도 복호화되지 않는다. DPAPI 를 못 쓰는 환경에서는 평문(base64)으로 저장하고
화면에 그 사실을 알린다.

저장 위치
  %APPDATA%\KISTEP회의록정리\config.json
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
from ctypes import wintypes
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
#: 모델을 바꿀 일이 생기면 이 한 줄만 고치면 된다. 모델 ID 가 틀리면
#: [설정] 탭의 [요약 모델 연결 테스트] 가 "모델을 찾을 수 없다"고 알려 준다.
SUMMARY_MODEL = "gpt-5.6-luna"

#: 암호화해서 저장할 키 목록
SECRET_KEYS = ("openai_api_key",)

DEFAULTS: dict[str, Any] = {
    "openai_api_key": "",
    # --- 문서 기본값 ---
    "org_footer": "KISTEP 연구윤리자산보호센터",
    "attach_transcript": True,           # 참고: 회의록 원문 첨부 여부
    "last_outdir": "",
}


def embedded_api_key() -> str:
    """embedded_key.py 에 적어 둔 내장 키 (없으면 빈 문자열)."""
    return (_EMBEDDED_KEY or "").strip()


def key_embedded() -> bool:
    return bool(embedded_api_key())


# ---------------------------------------------------------------------------
# DPAPI
# ---------------------------------------------------------------------------

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _blob_bytes(blob: _Blob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _dpapi(fn_name: str, data: bytes) -> bytes | None:
    if sys.platform != "win32":
        return None
    try:
        crypt32 = ctypes.WinDLL("crypt32.dll")
        kernel32 = ctypes.WinDLL("kernel32.dll")
        fn = getattr(crypt32, fn_name)
        fn.argtypes = [
            ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
        ]
        fn.restype = wintypes.BOOL
        out = _Blob()
        src = _blob(data)
        if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
            return None
        try:
            return _blob_bytes(out)
        finally:
            kernel32.LocalFree(out.pbData)
    except Exception:  # noqa: BLE001
        return None


def encrypt(text: str) -> str:
    """평문 -> 저장용 문자열. 암호화되면 'dpapi:' 접두어가 붙는다."""
    if not text:
        return ""
    enc = _dpapi("CryptProtectData", text.encode("utf-8"))
    if enc is None:
        return "plain:" + base64.b64encode(text.encode("utf-8")).decode("ascii")
    return "dpapi:" + base64.b64encode(enc).decode("ascii")


def decrypt(stored: str) -> str:
    """저장용 문자열 -> 평문. 복호화 실패 시 빈 문자열."""
    if not stored:
        return ""
    if stored.startswith("dpapi:"):
        raw = base64.b64decode(stored[6:])
        dec = _dpapi("CryptUnprotectData", raw)
        return dec.decode("utf-8") if dec else ""
    if stored.startswith("plain:"):
        return base64.b64decode(stored[6:]).decode("utf-8")
    return stored  # 구버전 평문 호환


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
    """복호화된 설정을 돌려준다. 키는 내장 > 환경변수 > 저장된 값 순으로 고른다."""
    cfg = dict(DEFAULTS)
    p = config_path()
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            raw = {}
        for k, v in raw.items():
            if k in SECRET_KEYS:
                cfg[k] = decrypt(v if isinstance(v, str) else "")
            elif k in DEFAULTS:
                cfg[k] = v

    emb = embedded_api_key()
    if emb:
        cfg["openai_api_key"] = emb
    elif not cfg.get("openai_api_key"):
        cfg["openai_api_key"] = (os.environ.get("OPENAI_API_KEY") or "").strip()
    return cfg


def save(cfg: dict[str, Any]) -> Path:
    """설정을 저장한다. 비밀 키는 암호화해서 기록(내장 키는 기록하지 않음)."""
    emb = embedded_api_key()
    out: dict[str, Any] = {}
    for k in DEFAULTS:
        v = cfg.get(k, DEFAULTS[k])
        if k not in SECRET_KEYS:
            out[k] = v
        elif emb and str(v) == emb:
            out[k] = ""            # 내장 키를 파일에 옮겨 적을 이유가 없다
        else:
            out[k] = encrypt(str(v or ""))
    p = config_path()
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    try:  # 다른 사용자가 못 읽게 (Windows 에서는 무시됨)
        os.chmod(p, 0o600)
    except Exception:  # noqa: BLE001
        pass
    return p


def masked(cfg: dict[str, Any]) -> dict[str, Any]:
    """화면으로 내보낼 때 비밀 키를 가린 사본."""
    out = dict(cfg)
    for k in SECRET_KEYS:
        v = cfg.get(k) or ""
        out[k] = ("*" * max(0, len(v) - 4) + v[-4:]) if v else ""
        out[k + "_set"] = bool(v)
    return out


def dpapi_available() -> bool:
    return sys.platform == "win32" and _dpapi("CryptProtectData", b"x") is not None
