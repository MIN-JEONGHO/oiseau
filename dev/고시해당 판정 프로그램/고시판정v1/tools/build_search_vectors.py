"""조항 벡터 생성 도구(개발 전용, exe에 넣지 않는다). spec 4.5, plan T3.

실제 검토 항목 507개의 원문을 조각으로 나누고(notice_search.clause_chunks — 줄 단위, 최대 300자, 머리 줄 '통제번호 제목
분야') 고정한 의미 벡터 모델(resources/search_model)로 조각마다 벡터를 계산해 L2 정규화한 float16으로 저장한다.

쓰는 파일
  resources/search_vectors.npy   조각 벡터(조각 수 × 256, float16, 행마다 정규화). 조각은 조항 순서대로 이어진다.
  resources/search_vectors.json  기준본 ID·지문, 모델 이름·지문·파일 SHA256, 조각 규칙, 조항 ID 순서, 조항별 조각 수,
                                 조각 내용 지문, .npy 파일 SHA256·모양, 생성 일시, 파일 지문(fingerprint를 뺀 나머지의
                                 canonical SHA256). 실행용 모듈(notice_search.load_vectors)이 불러올 때 모두 확인한다.

조항 벡터는 관련어 사전과 무관하다(사전을 고쳐도 다시 만들 필요 없음). 고시 기준본·모델·조각 규칙이 바뀌면 다시 만든다.
이 도구는 인터넷에 접속하지 않는다(소켓을 막고 돈다).

사용:  python tools/build_search_vectors.py            생성(두 파일을 씀)
       python tools/build_search_vectors.py --check    지금 파일이 검증을 통과하고 다시 계산한 값과 같은지 확인(쓰지 않음)
       [--model-dir 폴더] [--output search_vectors.json]
종료 코드: 0 성공, 1 확인 실패.
"""
import argparse
import datetime
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
import time

PROGRAM_ROOT = Path(__file__).resolve().parents[1]
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

import numpy as np  # noqa: E402

import notice_search as ns  # noqa: E402
from notice_catalogue import load_catalogue  # noqa: E402

DEFAULT_OUTPUT = PROGRAM_ROOT / "resources" / ns.VECTORS_JSON
BATCH = 256


class _NoNetwork(socket.socket):
    def __init__(self, *args, **kwargs):
        raise RuntimeError("network access blocked while building search vectors")


def block_network():
    socket.socket = _NoNetwork
    socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network blocked"))


def compute_vectors(model, texts):
    """조각 글 → 정규화한 float16 행렬."""
    parts = [model.encode(texts[start:start + BATCH]) for start in range(0, len(texts), BATCH)]
    matrix = np.concatenate(parts, axis=0) if parts else np.zeros((0, model.dims), dtype=np.float32)
    return matrix.astype(np.float16)


def npy_bytes(matrix):
    buffer = io.BytesIO()
    np.save(buffer, matrix, allow_pickle=False)
    return buffer.getvalue()


def build(catalogue, model):
    """(payload, .npy 바이트, 조각 수)."""
    chunks = ns.clause_chunks(catalogue)
    matrix = compute_vectors(model, chunks[1])
    data = npy_bytes(matrix)
    generated_at = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds")
    payload = ns.vectors_payload(catalogue, model, chunks, hashlib.sha256(data).hexdigest(), matrix.shape, generated_at)
    return payload, data, matrix


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--model-dir", default=str(ns.model_dir()))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args(argv)
    block_network()
    output = Path(args.output)
    started = time.perf_counter()
    catalogue = load_catalogue()
    model = ns.StaticEmbeddingModel(args.model_dir)
    payload, data, matrix = build(catalogue, model)
    if args.check:
        try:
            stored, _, _ = ns.load_vectors(output, catalogue, model)
        except ns.SearchVectorsError as error:
            print(f"확인 실패: {error}")
            return 1
        if not np.array_equal(stored.astype(np.float16), matrix):
            print("확인 실패: 저장된 조항 벡터가 다시 계산한 값과 다르다")
            return 1
        print(f"확인 통과: 조항 {len(payload['clause_ids'])}개, 조각 {matrix.shape[0]}개, 차원 {matrix.shape[1]}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    npy = output.with_name(ns.VECTORS_NPY)
    npy.write_bytes(data)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=4, allow_nan=False) + "\n", encoding="utf-8",
                      newline="\n")
    ns.load_vectors(output, catalogue, model)   # 쓴 파일이 실행용 검증을 통과하는지 바로 확인
    print(f"조항 {len(payload['clause_ids'])}개, 조각 {matrix.shape[0]}개, 차원 {matrix.shape[1]} → {output.name}, {npy.name} "
          f"({len(data) / 1024 / 1024:.1f}MB, {time.perf_counter() - started:.1f}s)")
    print(f"지문 {payload['fingerprint']}  모델 지문 {payload['model']['fingerprint']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
