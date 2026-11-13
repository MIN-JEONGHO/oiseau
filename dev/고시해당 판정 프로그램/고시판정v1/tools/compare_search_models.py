"""고시 검색용 의미 벡터 모델 비교 도구(개발 전용, exe에 넣지 않는다). spec 4.5·5, plan T1.

후보 모델(tools/fetch_search_model.py로 받은 것)마다 실제 검토 항목 507개의 조항 벡터를 만들고
(긴 조항은 조각으로 나눠 가장 비슷한 조각의 점수), **벡터만으로**(관련어 사전·글자 검색 없이)
시험 질의 여섯 개와 무관한 말(김치찌개)을 돌려 순위·유사도를 낸다.

합격 기준(spec 4.5): 기대 조항이 507개 중 상위 10건(디스플레이는 20건) 안이면 그 질의 통과,
여섯 중 다섯 이상 통과면 합격. 크기 한도는 모델 파일 + 실행 라이브러리 약 150MB.

이 도구는 인터넷에 접속하지 않는다(소켓을 막고 돈다). 고시 자료·모델 파일은 읽기만 한다.

사용:  python tools/compare_search_models.py [--candidates-root 폴더] [--only 변형 ...] [--json 결과.json]
       python tools/compare_search_models.py --model-dir resources/search_model   (고정한 모델 하나만)
"""
import argparse
import importlib.util
import json
from pathlib import Path
import socket
import struct
import sys
import time

PROGRAM_ROOT = Path(__file__).resolve().parents[1]
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))

import numpy as np  # noqa: E402

from notice_catalogue import clause_index, clause_record, load_catalogue  # noqa: E402

DEFAULT_CANDIDATES = PROGRAM_ROOT / "resources" / "search_model" / "_candidates"
CHUNK_CHARS = 300  # 조각 하나의 최대 글자 수(머리 줄 제외). 모든 후보에 같게 둔다.
MB = 1024 * 1024

# 시험 질의(spec 4.5). 기대 조항 ID는 원문을 보고 고정했다(이차전지는 리튬이차전지 조항 여섯 개).
QUERIES = [
    dict(query="DRAM", top=10, expect=["advanced:item:001", "advanced:item:002", "core:item:001", "core:item:002"]),
    dict(query="디스플레이", top=20, expect=["advanced:item:009", "core:item:013"]),
    dict(query="이차전지", top=10, expect=["advanced:item:013", "advanced:item:014", "advanced:item:015",
                                          "core:item:014", "core:item:015", "core:item:017"]),
    dict(query="드론", top=10, expect=["dual_use:control:9A012"]),
    dict(query="암호", top=10, expect=["dual_use:control:5A002"]),
    dict(query="레이저", top=10, expect=["dual_use:control:6A005"]),
]
NEGATIVE_QUERY = "김치찌개"
EXTRA_NEGATIVES = ["된장국", "축구 경기", "날씨 예보", "점심 메뉴", "연애 소설"]  # 참고용(합격 기준 아님)

# 비교할 변형. store: 배포 때 저장할 형식(float16 / int8 행별 축척 / 원본). dims: 앞에서부터 자를 차원(MRL·PCA 순서).
VARIANTS = {
    "e5_small_int8": dict(candidate="e5_small_int8", kind="onnx", model="onnx/model_qint8_avx512_vnni.onnx",
                          tokenizer="onnx/tokenizer.json", max_tokens=512,
                          query_prefix="query: ", passage_prefix="passage: "),
    "minilm_l12_int8": dict(candidate="minilm_l12_int8", kind="onnx", model="onnx/model_quint8_avx2.onnx",
                            tokenizer="tokenizer.json", max_tokens=128, query_prefix="", passage_prefix=""),
    "static_mrl_1024_f32": dict(candidate="static_mrl", kind="static", model="0_StaticEmbedding/model.safetensors",
                                tokenizer="0_StaticEmbedding/tokenizer.json", dims=1024, store="float32"),
    "static_mrl_512_f16": dict(candidate="static_mrl", kind="static", model="0_StaticEmbedding/model.safetensors",
                               tokenizer="0_StaticEmbedding/tokenizer.json", dims=512, store="float16"),
    "static_mrl_384_f16": dict(candidate="static_mrl", kind="static", model="0_StaticEmbedding/model.safetensors",
                               tokenizer="0_StaticEmbedding/tokenizer.json", dims=384, store="float16"),
    "static_mrl_256_f16": dict(candidate="static_mrl", kind="static", model="0_StaticEmbedding/model.safetensors",
                               tokenizer="0_StaticEmbedding/tokenizer.json", dims=256, store="float16"),
    "static_mrl_512_i8": dict(candidate="static_mrl", kind="static", model="0_StaticEmbedding/model.safetensors",
                              tokenizer="0_StaticEmbedding/tokenizer.json", dims=512, store="int8"),
    "potion_256_f32": dict(candidate="potion_128m", kind="static", model="model.safetensors",
                           tokenizer="tokenizer.json", dims=256, store="float32"),
    "potion_256_i8": dict(candidate="potion_128m", kind="static", model="model.safetensors",
                          tokenizer="tokenizer.json", dims=256, store="int8"),
    # 배포 형식(tools/pack_search_model.py): 낱말 줄이기 + 행별 int8. 토크나이저는 원본 그대로.
    "potion_256_i8_pruned": dict(candidate="../", kind="packed", tokenizer="tokenizer.json", dims=256,
                                 store="int8"),
    "potion_128_i8": dict(candidate="potion_128m", kind="static", model="model.safetensors",
                          tokenizer="tokenizer.json", dims=128, store="int8"),
}

# 실행 라이브러리(설치 폴더에 더해지는 것). 크기는 이 PC에 설치된 패키지 폴더 크기로 잰다(빌드 전 상한값).
RUNTIME_PACKAGES = {
    "onnx": ["onnxruntime", "tokenizers", "numpy", "numpy.libs", "google.protobuf", "flatbuffers"],
    "static": ["tokenizers", "numpy", "numpy.libs"],
    "packed": ["tokenizers", "numpy", "numpy.libs"],
}


class _NoNetwork(socket.socket):
    def __init__(self, *args, **kwargs):
        raise RuntimeError("network access blocked during model comparison")


def block_network():
    socket.socket = _NoNetwork
    socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network blocked"))


def _dir_size(path):
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def package_size(name):
    if name == "numpy.libs":
        spec = importlib.util.find_spec("numpy")
        folder = Path(spec.origin).parent.parent / "numpy.libs"
        return _dir_size(folder) if folder.exists() else 0
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    if spec.submodule_search_locations:
        return sum(_dir_size(p) for p in spec.submodule_search_locations)
    return _dir_size(spec.origin)


# ---------------------------------------------------------------------------
# 조항 조각
# ---------------------------------------------------------------------------

def _clean(value):
    return " ".join(str(value).split())


def clause_chunks(catalogue, chunk_chars=CHUNK_CHARS):
    """(clause_id 목록, 조각 글 목록, 조각마다 조항 번호). 조각 앞에 통제번호·제목·분야 머리 줄을 붙인다."""
    ids, texts, owners = [], [], []
    for number, entry in enumerate(clause_index(catalogue)):
        ids.append(entry["clause_id"])
        header = _clean(" ".join(x for x in (entry["code"], entry["title"], entry["field"]) if x))
        body = clause_record(catalogue, entry["clause_id"])["text"]
        pieces, current = [], ""
        for line in (_clean(x) for x in body.splitlines()):
            if not line:
                continue
            while len(line) > chunk_chars:
                if current:
                    pieces.append(current)
                    current = ""
                pieces.append(line[:chunk_chars])
                line = line[chunk_chars:]
            if current and len(current) + 1 + len(line) > chunk_chars:
                pieces.append(current)
                current = line
            else:
                current = f"{current} {line}".strip()
        if current:
            pieces.append(current)
        if not pieces:
            pieces = [""]
        for piece in pieces:
            texts.append(f"{header}\n{piece}".strip())
            owners.append(number)
    return ids, texts, np.asarray(owners, dtype=np.int64)


# ---------------------------------------------------------------------------
# 모델
# ---------------------------------------------------------------------------

def load_safetensors(path):
    dtypes = {"F32": np.float32, "F16": np.float16, "I8": np.int8, "F64": np.float64}
    with open(path, "rb") as handle:
        length = struct.unpack("<Q", handle.read(8))[0]
        header = json.loads(handle.read(length))
    tensors = {}
    for name, info in header.items():
        if name == "__metadata__":
            continue
        start, end = info["data_offsets"]
        tensors[name] = np.memmap(path, dtype=dtypes[info["dtype"]], mode="r", offset=8 + length + start,
                                  shape=tuple(info["shape"]))
    return tensors


def _normalize(matrix):
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _store(matrix, store):
    """배포 형식으로 저장했다가 다시 읽은 것과 같은 값을 돌려준다(크기 바이트와 함께)."""
    if store == "float32":
        return matrix.astype(np.float32), matrix.shape[0] * matrix.shape[1] * 4
    if store == "float16":
        return matrix.astype(np.float16).astype(np.float32), matrix.shape[0] * matrix.shape[1] * 2
    if store == "int8":
        scale = np.abs(matrix).max(axis=1, keepdims=True) / 127.0
        scale[scale == 0] = 1.0
        quantized = np.clip(np.round(matrix / scale), -127, 127).astype(np.int8)
        return quantized.astype(np.float32) * scale.astype(np.float32), matrix.shape[0] * (matrix.shape[1] + 4)
    raise ValueError(store)


class StaticEncoder:
    def __init__(self, folder, variant):
        from tokenizers import Tokenizer
        self.tokenizer = Tokenizer.from_file(str(folder / variant["tokenizer"]))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        tensors = load_safetensors(folder / variant["model"])
        (name, table), = tensors.items()
        self.tensor_name = name
        self.vocab_size, self.full_dims = table.shape
        dims = variant["dims"]
        self.table, self.stored_bytes = _store(np.asarray(table[:, :dims], dtype=np.float32), variant["store"])
        self.dims = dims
        unk = self.tokenizer.token_to_id("[UNK]")
        self.unk = unk if unk is not None else self.tokenizer.token_to_id("<unk>")
        self.model_bytes = self.stored_bytes

    def encode(self, texts, query=False):
        out = np.zeros((len(texts), self.dims), dtype=np.float32)
        for row, encoding in enumerate(self.tokenizer.encode_batch(list(texts), add_special_tokens=False)):
            ids = [i for i in encoding.ids if i != self.unk]
            if ids:
                out[row] = self.table[ids].mean(axis=0)
        return _normalize(out)


class PackedStaticEncoder:
    """배포 형식(resources/search_model)의 정적 모델. 벡터가 없는 낱말과 [UNK]는 건너뛴다."""

    FILES = ("embeddings_int8.npy", "scales_float32.npy", "token_ids_int32.npy")

    def __init__(self, folder, variant):
        from tokenizers import Tokenizer
        folder = Path(folder)
        self.tokenizer = Tokenizer.from_file(str(folder / variant["tokenizer"]))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        embeddings, scales, token_ids = (np.load(folder / n, allow_pickle=False) for n in self.FILES)
        self.embeddings, self.scales = embeddings, scales
        self.row_of = np.full(self.tokenizer.get_vocab_size(with_added_tokens=True), -1, dtype=np.int64)
        self.row_of[token_ids] = np.arange(len(token_ids))
        unk = self.tokenizer.token_to_id("[UNK]")
        if unk is not None:
            self.row_of[unk] = -1
        self.dims = embeddings.shape[1]
        self.model_bytes = sum((folder / n).stat().st_size for n in self.FILES)

    def encode(self, texts, query=False):
        out = np.zeros((len(texts), self.dims), dtype=np.float32)
        for row, encoding in enumerate(self.tokenizer.encode_batch(list(texts), add_special_tokens=False)):
            rows = self.row_of[np.asarray(encoding.ids, dtype=np.int64)]
            rows = rows[rows >= 0]
            if rows.size:
                out[row] = (self.embeddings[rows].astype(np.float32) * self.scales[rows, None]).mean(axis=0)
        return _normalize(out)


class OnnxEncoder:
    def __init__(self, folder, variant):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.variant = variant
        self.tokenizer = Tokenizer.from_file(str(folder / variant["tokenizer"]))
        self.tokenizer.enable_truncation(max_length=variant["max_tokens"])
        pad_token = "<pad>" if self.tokenizer.token_to_id("<pad>") is not None else "[PAD]"
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id(pad_token), pad_token=pad_token)
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(folder / variant["model"]), sess_options=options,
                                            providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.model_bytes = (folder / variant["model"]).stat().st_size
        self.dims = None

    def encode(self, texts, query=False, batch=32):
        prefix = self.variant["query_prefix" if query else "passage_prefix"]
        texts = [prefix + t for t in texts]
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        result = [None] * len(texts)
        for start in range(0, len(order), batch):
            index = order[start:start + batch]
            encodings = self.tokenizer.encode_batch([texts[i] for i in index])
            ids = np.asarray([e.ids for e in encodings], dtype=np.int64)
            mask = np.asarray([e.attention_mask for e in encodings], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs:
                feed["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feed)[0]
            summed = (hidden * mask[..., None]).sum(axis=1)
            pooled = summed / np.clip(mask.sum(axis=1, keepdims=True), 1, None)
            for row, i in enumerate(index):
                result[i] = pooled[row]
        matrix = np.asarray(result, dtype=np.float32)
        self.dims = matrix.shape[1]
        return _normalize(matrix)


def make_encoder(folder, variant):
    kinds = dict(onnx=OnnxEncoder, static=StaticEncoder, packed=PackedStaticEncoder)
    return kinds[variant["kind"]](Path(folder), variant)


# ---------------------------------------------------------------------------
# 비교
# ---------------------------------------------------------------------------

def clause_scores(query_vector, chunk_vectors, owners, clause_count):
    sims = chunk_vectors @ query_vector
    scores = np.full(clause_count, -1.0, dtype=np.float32)
    np.maximum.at(scores, owners, sims)
    return scores


def evaluate(name, variant, folder, catalogue_chunks):
    ids, texts, owners = catalogue_chunks
    started = time.perf_counter()
    encoder = make_encoder(folder, variant)
    loaded = time.perf_counter()
    chunk_vectors = encoder.encode(texts)
    encoded = time.perf_counter()
    position = {cid: i for i, cid in enumerate(ids)}
    rows = []
    for item in QUERIES:
        qv = encoder.encode([item["query"]], query=True)[0]
        scores = clause_scores(qv, chunk_vectors, owners, len(ids))
        ranking = np.argsort(-scores, kind="stable")
        rank_of = {ids[j]: r + 1 for r, j in enumerate(ranking)}
        expected = [dict(clause_id=c, rank=rank_of[c], similarity=round(float(scores[position[c]]), 4))
                    for c in item["expect"]]
        best = min(expected, key=lambda e: e["rank"])
        rows.append(dict(query=item["query"], top=item["top"], passed=best["rank"] <= item["top"], best=best,
                         expected=expected, top_hits=[dict(clause_id=ids[j], similarity=round(float(scores[j]), 4))
                                                      for j in ranking[:item["top"]]]))
    qv = encoder.encode([NEGATIVE_QUERY], query=True)[0]
    scores = clause_scores(qv, chunk_vectors, owners, len(ids))
    top = int(np.argmax(scores))
    extra = {}
    for text in EXTRA_NEGATIVES:
        extra_scores = clause_scores(encoder.encode([text], query=True)[0], chunk_vectors, owners, len(ids))
        extra[text] = round(float(extra_scores.max()), 4)
    query_started = time.perf_counter()
    for _ in range(20):
        encoder.encode(["반도체 노광 장비"], query=True)
    query_ms = (time.perf_counter() - query_started) / 20 * 1000
    tokenizer_bytes = (Path(folder) / variant["tokenizer"]).stat().st_size
    libs = {pkg: package_size(pkg) for pkg in RUNTIME_PACKAGES[variant["kind"]]}
    dims = encoder.dims
    vector_bytes = len(texts) * dims * 2  # 조항 벡터를 float16으로 저장할 때
    return dict(
        variant=name, candidate=variant["candidate"], kind=variant["kind"], dims=dims,
        store=variant.get("store", "onnx-int8"), passed=sum(r["passed"] for r in rows), queries=rows,
        negative=dict(query=NEGATIVE_QUERY, top_clause=ids[top], top_similarity=round(float(scores[top]), 4)),
        extra_negatives=extra,
        min_best_expected_similarity=round(min(r["best"]["similarity"] for r in rows if r["passed"]), 4)
        if any(r["passed"] for r in rows) else None,
        sizes_mb=dict(model=round(encoder.model_bytes / MB, 1), tokenizer=round(tokenizer_bytes / MB, 1),
                      vectors_f16=round(vector_bytes / MB, 1),
                      libraries={k: (round(v / MB, 1) if v is not None else None) for k, v in libs.items()},
                      libraries_total=round(sum(v for v in libs.values() if v) / MB, 1)),
        chunk_count=len(texts), seconds=dict(load=round(loaded - started, 1), encode_chunks=round(encoded - loaded, 1)),
        query_ms=round(query_ms, 2),
    ) | dict(total_mb=None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--candidates-root", default=str(DEFAULT_CANDIDATES))
    parser.add_argument("--only", nargs="*", choices=sorted(VARIANTS))
    parser.add_argument("--json")
    parser.add_argument("--model-dir", help="배포 형식으로 고정한 모델 폴더 하나만 비교(potion_256_i8_pruned 형식)")
    args = parser.parse_args(argv)
    block_network()
    catalogue = load_catalogue()
    chunks = clause_chunks(catalogue)
    print(f"조항 {len(chunks[0])}개, 조각 {len(chunks[1])}개 (조각 최대 {CHUNK_CHARS}자)")
    results = []
    names = ["potion_256_i8_pruned"] if args.model_dir else (args.only or list(VARIANTS))
    for name in names:
        variant = VARIANTS[name]
        folder = Path(args.model_dir) if args.model_dir else Path(args.candidates_root) / variant["candidate"]
        if not folder.exists():
            print(f"[{name}] 후보 폴더 없음: {folder}")
            continue
        result = evaluate(name, variant, folder, chunks)
        sizes = result["sizes_mb"]
        result["total_mb"] = round(sizes["model"] + sizes["tokenizer"] + sizes["vectors_f16"] + sizes["libraries_total"], 1)
        results.append(result)
        print(f"[{name}] 통과 {result['passed']}/6, 차원 {result['dims']}, 합계 {result['total_mb']}MB "
              f"(모델 {sizes['model']} + 토크나이저 {sizes['tokenizer']} + 벡터 {sizes['vectors_f16']} + 라이브러리 {sizes['libraries_total']}), "
              f"조각 계산 {result['seconds']['encode_chunks']}s, 질의 {result['query_ms']}ms")
        for row in result["queries"]:
            print(f"    {row['query']}: {'통과' if row['passed'] else '실패'} 최고 순위 {row['best']['rank']} "
                  f"({row['best']['clause_id']}, {row['best']['similarity']}) / 1위 {row['top_hits'][0]}")
        print(f"    {NEGATIVE_QUERY}: 최고 {result['negative']['top_similarity']} ({result['negative']['top_clause']}), "
              f"통과 질의 기대 최저 {result['min_best_expected_similarity']}, 그 밖의 무관한 말 최고 {result['extra_negatives']}")
        sys.stdout.flush()
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
