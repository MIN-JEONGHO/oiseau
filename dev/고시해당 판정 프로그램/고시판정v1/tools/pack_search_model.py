"""고른 의미 벡터 모델을 배포 형식으로 묶는 도구(개발 전용, exe에 넣지 않는다). spec 4.5, plan T1.

고른 모델: minishlab/potion-multilingual-128M(정적 단어 벡터, MIT). 원본 표는 500,353 낱말 × 256차원 float32(489MB)라
크기 한도(약 150MB)를 넘으므로 다음 두 가지만 바꿔 줄인다. 토크나이저(tokenizer.json)는 원본 그대로 둔다.
  ① 낱말 줄이기: 한글·ASCII·한자·기호(문자가 아닌 것)로만 된 낱말, 그리고 고시 원문 507개 항목을 토큰화했을 때
     나오는 낱말 전부를 남긴다. 다른 문자(키릴·아랍·라틴 확장 글자 등)가 든 낱말은 벡터를 두지 않는다
     (실행 중 그 낱말은 모르는 낱말처럼 건너뛴다). 남긴 낱말의 벡터 값은 원본과 같다(아래 ② 양자화 오차만).
  ② 행별 int8 양자화: 행마다 최대 절댓값/127을 축척으로 두고 반올림한다(축척은 float32로 따로 저장).
고시 원문을 토큰화한 낱말이 모두 남았는지, 남긴 행이 원본과 양자화 오차 안에서 같은지 검사한다(어긋나면 종료 코드 ≠ 0).

사용:  python tools/pack_search_model.py [--source 후보폴더] [--dest resources/search_model]
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import unicodedata

PROGRAM_ROOT = Path(__file__).resolve().parents[1]
if str(PROGRAM_ROOT) not in sys.path:
    sys.path.insert(0, str(PROGRAM_ROOT))
TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import numpy as np  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

from compare_search_models import block_network, clause_chunks, load_safetensors  # noqa: E402
from notice_catalogue import load_catalogue  # noqa: E402

DEFAULT_SOURCE = PROGRAM_ROOT / "resources" / "search_model" / "_candidates" / "potion_128m"
DEFAULT_DEST = PROGRAM_ROOT / "resources" / "search_model"
SPACE_MARK = "▁"  # 낱말 앞 공백 표시(SentencePiece)

FILE_EMBEDDINGS = "embeddings_int8.npy"
FILE_SCALES = "scales_float32.npy"
FILE_TOKEN_IDS = "token_ids_int32.npy"
FILE_TOKENIZER = "tokenizer.json"
FILE_LICENSE = "LICENSE.txt"
FILE_CARD = "MODEL_CARD.md"
FILE_CONFIG = "config.json"
FILE_INFO = "MODEL_INFO.json"

# tools/compare_search_models.py 결과로 정한 값(tools/output/모델_비교.md). 김치찌개 최고 0.3022 <  이 값 <
# 통과 질의 기대 조항 최저 0.3376(디스플레이). 실행 코드의 최소 유사도 상수는 T3가 이 값을 옮겨 쓴다.
SUGGESTED_MIN_SIMILARITY = 0.32
CHUNK_CHARS_USED = 300


def allowed_char(ch):
    o = ord(ch)
    if o < 0x80:
        return True  # ASCII(영문·숫자·기호)
    if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F or 0xA960 <= o <= 0xA97F \
            or 0xD7B0 <= o <= 0xD7FF:
        return True  # 한글
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF:
        return True  # 한자
    return not unicodedata.category(ch).startswith("L")  # 문자가 아닌 것(숫자·기호·구두점·단위 기호)


def keep_token(token):
    text = token.replace(SPACE_MARK, "")
    # 한 글자 낱말은 문자 종류와 관계없이 남긴다(작고, 단위·기호 글자를 놓치지 않으려고).
    return len(text) == 1 or (bool(text) and all(allowed_char(ch) for ch in text))


def quantize(rows):
    scale = np.abs(rows).max(axis=1) / 127.0
    scale[scale == 0] = 1.0
    quantized = np.clip(np.round(rows / scale[:, None]), -127, 127).astype(np.int8)
    return quantized, scale.astype(np.float32)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    args = parser.parse_args(argv)
    block_network()
    source, dest = Path(args.source), Path(args.dest)
    tokenizer = Tokenizer.from_file(str(source / FILE_TOKENIZER))
    vocab = tokenizer.get_vocab()
    (name, table), = load_safetensors(source / "model.safetensors").items()
    if table.shape[0] != len(vocab):
        raise SystemExit(f"표 행 수 {table.shape[0]} != 낱말 수 {len(vocab)}")
    unk = tokenizer.token_to_id("[UNK]")
    if unk is None:
        raise SystemExit("토크나이저에 [UNK] 없음")
    _, texts, _ = clause_chunks(load_catalogue())
    corpus_ids = set()
    for encoding in tokenizer.encode_batch(texts, add_special_tokens=False):
        corpus_ids.update(encoding.ids)
    corpus_ids.discard(unk)
    keep = sorted({i for t, i in vocab.items() if keep_token(t)} | corpus_ids)
    missing = corpus_ids - set(keep)
    if missing:
        raise SystemExit(f"고시 원문 낱말 {len(missing)}개가 빠짐")
    ids = np.asarray(keep, dtype=np.int32)
    rows = np.asarray(table[ids], dtype=np.float32)
    quantized, scales = quantize(rows)
    error = np.abs(quantized.astype(np.float32) * scales[:, None] - rows).max(axis=1)
    if not np.all(error <= scales * 0.5 * (1 + 1e-4) + 1e-6):  # 반올림 오차(축척의 절반) 안
        raise SystemExit("양자화 오차 검사 실패")
    dest.mkdir(parents=True, exist_ok=True)
    np.save(dest / FILE_EMBEDDINGS, quantized, allow_pickle=False)
    np.save(dest / FILE_SCALES, scales, allow_pickle=False)
    np.save(dest / FILE_TOKEN_IDS, ids, allow_pickle=False)
    shutil.copyfile(source / FILE_TOKENIZER, dest / FILE_TOKENIZER)
    shutil.copyfile(source / "README.md", dest / FILE_CARD)
    shutil.copyfile(source / FILE_CONFIG, dest / FILE_CONFIG)
    if not (dest / FILE_LICENSE).is_file():
        raise SystemExit(f"{dest / FILE_LICENSE} 없음(라이선스 원문을 먼저 둔다)")
    shipped = (FILE_EMBEDDINGS, FILE_SCALES, FILE_TOKEN_IDS, FILE_TOKENIZER, FILE_CONFIG, FILE_CARD, FILE_LICENSE)
    files = {n: dict(sha256=sha256(dest / n), size=(dest / n).stat().st_size) for n in shipped}
    origin = json.loads((source / "source.json").read_text(encoding="utf-8"))
    info = build_info(origin, files, name, table.shape, len(keep), len(corpus_ids), unk)
    (dest / FILE_INFO).write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(kept_rows=len(keep), corpus_tokens=len(corpus_ids), files=files), ensure_ascii=False, indent=2))
    return 0


def build_info(origin, files, tensor, shape, kept_rows, corpus_tokens, unk):
    return {
        "schema": 1,
        "name": "potion-multilingual-128M (낱말 줄임·int8)",
        "kind": "static_word_embedding",
        "source": dict(repo=origin["repo"], revision=origin["revision"], repo_url=origin["repo_url"],
                       files=[dict(path=f["path"], url=f["url"], sha256=f["sha256"], size=f["size"],
                                   verified_against=f["verified_against"]) for f in origin["files"]],
                       fetched_by="tools/fetch_search_model.py --only potion_128m"),
        "license": dict(spdx="MIT", file=FILE_LICENSE, card_license=origin["card_license"],
                        holders="Minish Lab (Stephan Tulkens, Thomas van Dongen)",
                        tokenizer_origin="BAAI/bge-m3 (MIT)",
                        training_data_note="모델 카드: C4 데이터셋(101개 언어 문장 200만 개)으로 학습. 모델 자체 라이선스는 MIT."),
        "derivation": dict(
            tool="tools/pack_search_model.py",
            source_tensor=tensor, source_rows=int(shape[0]), dims=int(shape[1]), kept_rows=kept_rows,
            corpus_tokens_all_kept=corpus_tokens,
            keep_rule="한글·ASCII·한자·문자가 아닌 글자(숫자·기호·구두점)로만 된 낱말, 한 글자 낱말, 고시 원문 507개 항목 토큰화에 나온 낱말 전부",
            quantization="행별 대칭 int8: scale = max(|row|)/127, q = round(row/scale) ∈ [-127,127], 복원 = q × scale",
            unchanged=[FILE_TOKENIZER, FILE_CONFIG, FILE_CARD]),
        "files": files,
        "runtime": dict(
            libraries={"numpy": "BSD-3-Clause (2.5.1)", "tokenizers": "Apache-2.0 (0.23.3)"},
            embedding_dim=int(shape[1]),
            similarity="cosine (벡터를 L2 정규화한 뒤 내적)",
            query_prefix="", document_prefix="",
            encode=[
                "tok = tokenizers.Tokenizer.from_file('tokenizer.json'); tok.no_truncation(); tok.no_padding()",
                "ids = tok.encode(text, add_special_tokens=False).ids",
                f"[UNK](id {unk})와 token_ids_int32.npy에 없는 id는 건너뛴다(row_of[id] = -1)",
                "row_of = np.full(tok.get_vocab_size(with_added_tokens=True), -1); row_of[token_ids] = arange(len(token_ids))",
                "vec = mean(embeddings_int8[rows].astype(float32) * scales_float32[rows, None]); 남은 낱말이 없으면 영벡터(점수 0)",
                "vec = vec / ||vec||  (config.json normalize=true)",
            ],
            load="np.load(path, allow_pickle=False) — 세 .npy 파일. 불러오기 전에 files의 sha256을 확인하고 다르면 의미 검색을 끈다.",
            document_chunks=f"조항 글을 줄 단위로 모아 최대 {CHUNK_CHARS_USED}자 조각으로 나누고 각 조각 앞에 '통제번호 제목 분야' 머리 줄을 붙인다. 조항 점수 = 가장 비슷한 조각의 점수 (tools/compare_search_models.clause_chunks와 같게)",
            suggested_min_similarity=SUGGESTED_MIN_SIMILARITY,
            suggested_min_similarity_basis="김치찌개 최고 0.3022, 통과 질의 기대 조항 최고 순위 유사도 최저 0.3376(디스플레이 advanced:item:009). 참고: 된장국 최고 0.3554(0.32 이상 5건)",
            offline=dict(
                network="실행 중 인터넷 접속 없음. Tokenizer.from_file과 np.load만 쓰며 from_pretrained·huggingface_hub를 쓰지 않는다.",
                huggingface_hub="tokenizers를 import해도 huggingface_hub는 import되지 않음(확인). 방어로 import 전에 환경변수 HF_HUB_OFFLINE=1, HF_HUB_DISABLE_TELEMETRY=1, HF_HUB_DISABLE_IMPLICIT_TOKEN=1을 두고, 빌드에서 huggingface_hub·hf_xet는 제외한다.",
                telemetry="numpy·tokenizers는 사용 통계 전송 기능이 없다. onnxruntime은 쓰지 않는다(넣지 않음).",
                verified_by="소켓 차단(socket.socket·create_connection·getaddrinfo를 막음) 상태에서 로딩·질의 벡터·조항 점수 계산 성공 — tools/output/모델_비교.md"),
        ),
        "comparison": "tools/output/모델_비교.md",
    }


if __name__ == "__main__":
    sys.exit(main())
