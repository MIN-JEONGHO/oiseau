# -*- coding: utf-8 -*-
"""
음성 -> 텍스트 전사(STT).

OpenAI Whisper API (POST /v1/audio/transcriptions) 하나로 고정되어 있다.
  - 요청당 25MB 제한 -> audio.py 가 16kHz 모노 WAV 로 잘라서 여러 번 올린다
  - 화자 구분 기능이 없다 -> 발언자는 다음 단계에서 요약 모델이 문맥으로 추정한다

외부 의존성 없이 표준 라이브러리(urllib)만 쓴다. 큰 파일은 메모리에 다 올리지 않고
스트리밍으로 업로드한다.
"""
from __future__ import annotations

import json
import mimetypes
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Callable
from urllib import error, request

import audio
import config as CFG

OPENAI_URL = "https://api.openai.com/v1/audio/transcriptions"

Progress = Callable[[str], None]


class STTError(RuntimeError):
    pass


#: 키를 못 찾았을 때 안내 문구 (내장 키가 비어 있는 배포본에서만 나온다)
_NO_KEY = ("OpenAI API 키가 없습니다. embedded_key.py 에 키를 넣어 빌드했거나, "
           "[설정] 탭에서 키를 입력해야 합니다.")


@dataclass
class Segment:
    """전사된 발언 한 토막."""
    index: int
    start: float                  # 초
    end: float                    # 초
    text: str
    speaker: str | None = None    # 이후 단계에서 매칭된 발언자 이름

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "start": self.start, "end": self.end,
                "text": self.text, "speaker": self.speaker}


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    engine: str = ""
    has_diarization: bool = False
    duration: float = 0.0

    @property
    def full_text(self) -> str:
        return "\n".join(s.text for s in self.segments if s.text.strip())

    @property
    def speaker_labels(self) -> list[str]:
        seen: list[str] = []
        for s in self.segments:
            if s.speaker and s.speaker not in seen:
                seen.append(s.speaker)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {"engine": self.engine, "has_diarization": self.has_diarization,
                "duration": self.duration, "speaker_labels": self.speaker_labels,
                "segments": [s.to_dict() for s in self.segments]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Transcript":
        t = cls(engine=d.get("engine", ""), has_diarization=bool(d.get("has_diarization")),
                duration=float(d.get("duration") or 0))
        t.segments = [Segment(int(s["index"]), float(s["start"]), float(s["end"]),
                              s["text"], s.get("speaker"))
                      for s in d.get("segments", [])]
        return t


# ---------------------------------------------------------------------------
# multipart/form-data 스트리밍 업로드
# ---------------------------------------------------------------------------

class _MultipartBody:
    """앞부분 바이트 + 파일 스트림 + 뒷부분 바이트를 이어서 읽히는 파일 객체."""

    def __init__(self, prefix: bytes, fh: BinaryIO, file_size: int, suffix: bytes):
        self._parts: list[tuple[str, Any]] = [("b", prefix), ("f", fh), ("b", suffix)]
        self._pos = 0
        self._boff = 0
        self.length = len(prefix) + file_size + len(suffix)

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = 1 << 20
        while self._pos < len(self._parts):
            kind, obj = self._parts[self._pos]
            if kind == "b":
                chunk = obj[self._boff:self._boff + size]
                self._boff += len(chunk)
                if self._boff >= len(obj):
                    self._pos += 1
                    self._boff = 0
                if chunk:
                    return chunk
            else:
                chunk = obj.read(size)
                if chunk:
                    return chunk
                self._pos += 1
                self._boff = 0
        return b""

    def __len__(self) -> int:  # http.client 가 참고할 수 있게
        return self.length


def _post_multipart(url: str, headers: dict[str, str], fields: dict[str, Any],
                    file_field: str, file_path: Path, timeout: int) -> bytes:
    """텍스트 필드 + 파일 하나를 multipart 로 올린다 (파일은 스트리밍)."""
    boundary = f"----hwpxminutes{uuid.uuid4().hex}"
    bnd = boundary.encode()
    pre = bytearray()
    for name, value in fields.items():
        if isinstance(value, tuple):          # (값, content-type)
            val, ctype = value
            extra = f'\r\nContent-Type: {ctype}'
        else:
            val, extra = value, ""
        pre += b"--" + bnd + b"\r\n"
        pre += f'Content-Disposition: form-data; name="{name}"{extra}\r\n\r\n'.encode()
        pre += str(val).encode("utf-8") + b"\r\n"

    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    pre += b"--" + bnd + b"\r\n"
    pre += (f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\n'
            f'Content-Type: {ctype}\r\n\r\n').encode()
    suffix = b"\r\n--" + bnd + b"--\r\n"

    size = file_path.stat().st_size
    with open(file_path, "rb") as fh:
        body = _MultipartBody(bytes(pre), fh, size, suffix)
        req = request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        req.add_header("Content-Length", str(body.length))
        for k, v in headers.items():
            req.add_header(k, v)
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:  # noqa: BLE001
                pass
            raise STTError(f"HTTP {e.code} {e.reason}\n{detail}") from e
        except error.URLError as e:
            raise STTError(f"서버에 연결하지 못했습니다: {e.reason}") from e


# ---------------------------------------------------------------------------
# OpenAI Whisper API
# ---------------------------------------------------------------------------

def _transcribe_openai(src: Path, cfg: dict[str, Any], workdir: Path,
                       progress: Progress) -> Transcript:
    key = (cfg.get("openai_api_key") or "").strip()
    if not key:
        raise STTError(_NO_KEY)
    model = CFG.STT_MODEL

    progress("녹음파일 확인 중…")
    chunks = audio.prepare_for_openai(src, workdir, progress)
    segments: list[Segment] = []
    total_dur = 0.0
    try:
        for c in chunks:
            if c.total > 1:
                progress(f"전사 중… ({c.index + 1}/{c.total} 조각)")
            else:
                progress("전사 중… (1/1)")
            raw = _post_multipart(
                OPENAI_URL,
                {"Authorization": f"Bearer {key}"},
                {"model": model, "response_format": "verbose_json", "language": "ko",
                 "temperature": "0"},
                "file", c.path, timeout=3600,
            )
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                raise STTError(f"OpenAI 응답을 해석하지 못했습니다: {raw[:200]!r}") from e

            segs = data.get("segments")
            if not segs:  # verbose_json 을 못 주는 모델이면 전체 텍스트만 온다
                text = (data.get("text") or "").strip()
                if text:
                    segs = [{"start": 0.0, "end": c.duration, "text": text}]
                else:
                    segs = []
            for s in segs:
                text = (s.get("text") or "").strip()
                if not text:
                    continue
                segments.append(Segment(
                    index=len(segments),
                    start=c.offset + float(s.get("start") or 0.0),
                    end=c.offset + float(s.get("end") or 0.0),
                    text=text,
                ))
            total_dur = max(total_dur, c.offset + (c.duration or float(data.get("duration") or 0)))
    finally:
        audio.cleanup(chunks)

    if not segments:
        raise STTError("전사 결과가 비어 있습니다. 녹음에 음성이 들어 있는지 확인해 주세요.")
    return Transcript(segments=segments, engine="openai", has_diarization=False,
                      duration=total_dur)


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def transcribe(src: str | Path, cfg: dict[str, Any], workdir: str | Path,
               progress: Progress | None = None) -> Transcript:
    progress = progress or (lambda _m: None)
    src = Path(src)
    if not src.exists():
        raise STTError(f"녹음파일이 없습니다: {src}")
    if src.suffix.lower() not in audio.AUDIO_EXTS:
        raise STTError(f"지원하지 않는 확장자입니다: {src.suffix}\n"
                       f"지원 형식: {', '.join(sorted(audio.AUDIO_EXTS))}")

    return _transcribe_openai(src, cfg, Path(workdir), progress)


def test_connection(cfg: dict[str, Any]) -> str:
    """설정 화면의 [연결 테스트] 용. 성공하면 안내 문구, 실패하면 STTError."""
    key = (cfg.get("openai_api_key") or "").strip()
    if not key:
        raise STTError(_NO_KEY)
    req = request.Request("https://api.openai.com/v1/models",
                          headers={"Authorization": f"Bearer {key}"})
    try:
        with request.urlopen(req, timeout=30) as resp:
            json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as e:
        raise STTError(f"OpenAI 인증 실패 (HTTP {e.code}). API 키를 확인해 주세요.") from e
    except error.URLError as e:
        raise STTError(f"OpenAI 서버에 연결하지 못했습니다: {e.reason}") from e
    backend = audio.backend_name()
    extra = (f"\n오디오 변환기: {backend} (25MB 넘는 긴 녹음도 자동 분할됩니다)"
             if backend else
             "\n※ 오디오 변환기가 없어 25MB 넘는 파일은 처리할 수 없습니다. "
             "긴 회의를 다루려면  pip install av  를 실행하세요.")
    return f"OpenAI 연결 정상 (전사 모델: {CFG.STT_MODEL})." + extra
