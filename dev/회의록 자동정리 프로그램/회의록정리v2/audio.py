# -*- coding: utf-8 -*-
"""
녹음파일 전처리.

OpenAI Whisper API 는 요청당 25MB 제한이 있어 긴 회의 녹음은 그대로 못 올린다.
그래서 파일이 크면 16kHz 모노 WAV 로 변환하면서 일정 길이로 잘라 여러 번 올린다.
(16kHz 모노 s16 = 32,000 byte/초 이므로 600초 조각 = 약 19MB)

CLOVA Speech 는 장문 인식이 대용량 파일을 그대로 받으므로 이 전처리를 쓰지 않는다.

변환 백엔드는 두 가지를 순서대로 시도한다.
  1) PyAV      : pip install av  (FFmpeg 라이브러리가 wheel 에 포함 - exe 배포에 유리)
  2) ffmpeg CLI: PATH 또는 실행파일과 같은 폴더의 ffmpeg.exe

파일이 25MB 미만이고 확장자가 지원 대상이면 변환 없이 원본을 그대로 올린다.
(짧은 회의는 추가 설치 없이 바로 동작한다)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

#: OpenAI 업로드 상한(25MB)에 여유를 둔 값
MAX_UPLOAD_BYTES = 24 * 1024 * 1024
#: 조각 하나의 길이(초). 16kHz 모노 WAV 기준 약 19MB
CHUNK_SECONDS = 600

TARGET_RATE = 16000
TARGET_CHANNELS = 1
BYTES_PER_SAMPLE = 2
BYTES_PER_SECOND = TARGET_RATE * TARGET_CHANNELS * BYTES_PER_SAMPLE

#: OpenAI 가 그대로 받아주는 확장자
OPENAI_EXTS = {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"}
#: 프로그램이 열어볼 수 있는 확장자(변환 대상 포함)
AUDIO_EXTS = OPENAI_EXTS | {".aac", ".wma", ".amr", ".opus", ".avi", ".mkv", ".mov", ".3gp"}


class AudioError(RuntimeError):
    pass


@dataclass
class Chunk:
    """전사에 올릴 조각 하나."""
    path: Path
    offset: float          # 원본에서 이 조각이 시작하는 시각(초)
    duration: float        # 조각 길이(초)
    index: int
    total: int
    temporary: bool        # 변환으로 만들어진 파일이면 True (작업 후 삭제)


Progress = Callable[[str], None]


def _noop(_: str) -> None:
    pass


# ---------------------------------------------------------------------------
# 백엔드 탐지
# ---------------------------------------------------------------------------

def _have_pyav() -> bool:
    try:
        import av  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _ffmpeg_path() -> str | None:
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    # 실행파일(또는 스크립트)과 같은 폴더에 동봉된 경우를 먼저 본다
    base = Path(getattr(sys, "_MEIPASS", "") or Path(__file__).resolve().parent)
    for cand in (base / exe, Path(sys.executable).parent / exe):
        if cand.exists():
            return str(cand)
    return shutil.which(exe)


def backend_name() -> str | None:
    if _have_pyav():
        return "PyAV"
    if _ffmpeg_path():
        return "ffmpeg"
    return None


# ---------------------------------------------------------------------------
# 길이 확인
# ---------------------------------------------------------------------------

def probe_duration(path: str | Path) -> float | None:
    """녹음 길이(초). 알 수 없으면 None."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as w:
                return w.getnframes() / float(w.getframerate())
        except Exception:  # noqa: BLE001
            pass
    if _have_pyav():
        try:
            import av
            with av.open(str(path)) as c:
                if c.duration:
                    return float(c.duration) / av.time_base
                st = c.streams.audio[0]
                if st.duration and st.time_base:
                    return float(st.duration * st.time_base)
        except Exception:  # noqa: BLE001
            pass
    ff = _ffmpeg_path()
    if ff:
        probe = str(Path(ff).with_name(Path(ff).name.replace("ffmpeg", "ffprobe")))
        if Path(probe).exists() or shutil.which("ffprobe"):
            try:
                out = subprocess.run(
                    [probe if Path(probe).exists() else "ffprobe", "-v", "error",
                     "-show_entries", "format=duration", "-of",
                     "default=noprint_wrappers=1:nokey=1", str(path)],
                    capture_output=True, text=True, timeout=60,
                    creationflags=_no_window(),
                )
                return float(out.stdout.strip())
            except Exception:  # noqa: BLE001
                pass
    return None


def _no_window() -> int:
    return 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


# ---------------------------------------------------------------------------
# 변환/분할
# ---------------------------------------------------------------------------

def _wav_writer(path: Path) -> wave.Wave_write:
    w = wave.open(str(path), "wb")
    w.setnchannels(TARGET_CHANNELS)
    w.setsampwidth(BYTES_PER_SAMPLE)
    w.setframerate(TARGET_RATE)
    return w


def _split_with_pyav(src: Path, outdir: Path, chunk_seconds: int,
                     progress: Progress) -> list[Path]:
    import av

    chunk_bytes = chunk_seconds * BYTES_PER_SECOND
    made: list[Path] = []
    writer: wave.Wave_write | None = None
    written = 0

    def _open_next() -> wave.Wave_write:
        p = outdir / f"chunk_{len(made):04d}.wav"
        made.append(p)
        progress(f"오디오 변환 중… {len(made)}번째 조각")
        return _wav_writer(p)

    with av.open(str(src)) as container:
        if not container.streams.audio:
            raise AudioError("이 파일에서 오디오 트랙을 찾지 못했습니다.")
        stream = container.streams.audio[0]
        stream.thread_type = "AUTO"
        resampler = av.AudioResampler(format="s16", layout="mono", rate=TARGET_RATE)

        def _frames() -> Iterable:
            for frame in container.decode(stream):
                yield from resampler.resample(frame)
            yield from resampler.resample(None)  # 남은 버퍼 비우기

        for out in _frames():
            if out is None:
                continue
            need = out.samples * BYTES_PER_SAMPLE * TARGET_CHANNELS
            data = bytes(out.planes[0])[:need]   # 평면 버퍼는 정렬 패딩이 있을 수 있다
            if not data:
                continue
            if writer is None:
                writer = _open_next()
                written = 0
            if written + len(data) > chunk_bytes:
                writer.close()
                writer = _open_next()
                written = 0
            writer.writeframes(data)
            written += len(data)

    if writer is not None:
        writer.close()
    if not made:
        raise AudioError("오디오를 한 조각도 읽지 못했습니다. 파일이 손상되었을 수 있습니다.")
    return made


def _split_with_ffmpeg(src: Path, outdir: Path, chunk_seconds: int,
                       progress: Progress) -> list[Path]:
    ff = _ffmpeg_path()
    if not ff:
        raise AudioError("ffmpeg 를 찾지 못했습니다.")
    progress("ffmpeg 로 오디오 변환 중…")
    cmd = [
        ff, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-vn",
        "-ac", str(TARGET_CHANNELS), "-ar", str(TARGET_RATE), "-c:a", "pcm_s16le",
        "-f", "segment", "-segment_time", str(chunk_seconds), "-reset_timestamps", "1",
        str(outdir / "chunk_%04d.wav"),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_no_window())
    if r.returncode != 0:
        raise AudioError(f"ffmpeg 변환 실패: {(r.stderr or '').strip()[:300]}")
    made = sorted(outdir.glob("chunk_*.wav"))
    if not made:
        raise AudioError("ffmpeg 가 결과 파일을 만들지 못했습니다.")
    return made


def prepare_for_openai(src: str | Path, workdir: str | Path,
                       progress: Progress | None = None,
                       chunk_seconds: int = CHUNK_SECONDS) -> list[Chunk]:
    """OpenAI Whisper API 로 올릴 조각 목록을 만든다."""
    progress = progress or _noop
    src = Path(src)
    if not src.exists():
        raise AudioError(f"파일이 없습니다: {src}")

    size = src.stat().st_size
    if size <= MAX_UPLOAD_BYTES and src.suffix.lower() in OPENAI_EXTS:
        dur = probe_duration(src) or 0.0
        return [Chunk(src, 0.0, dur, 0, 1, temporary=False)]

    if backend_name() is None:
        raise AudioError(
            f"녹음파일이 {size / 1024 / 1024:.0f}MB 라 25MB 제한을 넘습니다. "
            "잘라서 올리려면 오디오 변환기가 필요합니다.\n"
            "  · 해결 1: 명령창에서  pip install av\n"
            "  · 해결 2: ffmpeg.exe 를 이 프로그램과 같은 폴더에 두기\n"
            "  · 해결 3: 설정에서 전사 엔진을 CLOVA Speech 로 바꾸기(대용량 그대로 처리)"
        )

    outdir = Path(workdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("chunk_*.wav"):
        old.unlink(missing_ok=True)

    if _have_pyav():
        try:
            made = _split_with_pyav(src, outdir, chunk_seconds, progress)
        except AudioError:
            raise
        except Exception as e:  # noqa: BLE001 - PyAV 실패 시 ffmpeg 로 재시도
            if not _ffmpeg_path():
                raise AudioError(f"오디오 변환 실패: {e}") from e
            made = _split_with_ffmpeg(src, outdir, chunk_seconds, progress)
    else:
        made = _split_with_ffmpeg(src, outdir, chunk_seconds, progress)

    chunks: list[Chunk] = []
    offset = 0.0
    for i, p in enumerate(made):
        with wave.open(str(p), "rb") as w:
            dur = w.getnframes() / float(w.getframerate())
        chunks.append(Chunk(p, offset, dur, i, len(made), temporary=True))
        offset += dur
    return chunks


def cleanup(chunks: list[Chunk]) -> None:
    for c in chunks:
        if c.temporary:
            try:
                c.path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
