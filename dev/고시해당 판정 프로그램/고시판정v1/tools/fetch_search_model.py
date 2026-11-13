"""고시 검색용 의미 벡터 모델 후보 내려받기 도구(개발 전용, exe에 넣지 않는다). spec 4.5, plan T1.

하는 일
  ① CANDIDATES에 고정한 공개 모델 저장소(Hugging Face)의 리비전(커밋 해시)에서 정해진 파일만 내려받는다.
  ② 파일마다 저장소가 밝힌 지문(LFS 파일은 SHA256, 일반 파일은 git blob SHA1)과 맞는지 확인한다.
     맞지 않으면 그 파일을 지우고 종료 코드 ≠ 0.
  ③ 라이선스 원문(모델 카드가 밝힌 라이선스의 공식 원문)을 함께 받는다.
  ④ 후보 폴더마다 source.json(출처 URL·리비전·파일별 SHA256·크기·라이선스)을 쓴다.

이 도구만 인터넷에 접속한다. 프로그램 실행 중에는 모델을 내려받지 않는다.

사용:  python tools/fetch_search_model.py [--dest 폴더] [--only 후보키 ...] [--list]
       기본 저장 위치: resources/search_model/_candidates/<후보키>/
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

PROGRAM_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = PROGRAM_ROOT / "resources" / "search_model" / "_candidates"
HF = "https://huggingface.co"

LICENSE_TEXT_URLS = {
    "apache-2.0": "https://www.apache.org/licenses/LICENSE-2.0.txt",
    # MIT 모델은 저장소에 LICENSE 파일이 없어 SPDX 표준 원문을 받는다(저작권자 줄은 모델 카드 기준으로 source.json에 적음).
    "mit": "https://raw.githubusercontent.com/spdx/license-list-data/main/text/MIT.txt",
}

# 후보: 다국어(한국어 포함)·MIT/Apache 2.0·작은 실행 크기. 리비전은 커밋 해시로 고정한다.
CANDIDATES = {
    "e5_small_int8": dict(
        repo="intfloat/multilingual-e5-small",
        revision="614241f622f53c4eeff9890bdc4f31cfecc418b3",
        license="mit",
        kind="onnx_transformer",
        files=["onnx/model_qint8_avx512_vnni.onnx", "onnx/tokenizer.json", "onnx/config.json",
               "1_Pooling/config.json", "README.md"],
    ),
    "minilm_l12_int8": dict(
        repo="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        revision="e8f8c211226b894fcb81acc59f3b34ba3efd5f42",
        license="apache-2.0",
        kind="onnx_transformer",
        files=["onnx/model_quint8_avx2.onnx", "tokenizer.json", "config.json", "1_Pooling/config.json",
               "sentence_bert_config.json", "README.md"],
    ),
    "static_mrl": dict(
        repo="sentence-transformers/static-similarity-mrl-multilingual-v1",
        revision="b68f4122911bcffcd6e1f695f2d99cd6788972d8",
        license="apache-2.0",
        kind="static",
        files=["0_StaticEmbedding/model.safetensors", "0_StaticEmbedding/tokenizer.json", "modules.json",
               "config_sentence_transformers.json", "README.md"],
    ),
    "potion_128m": dict(
        repo="minishlab/potion-multilingual-128M",
        revision="73908c3438cf03b6a01bcb9611d62b23d0726f08",
        license="mit",
        kind="static",
        files=["model.safetensors", "tokenizer.json", "config.json", "README.md"],
    ),
}


def _get(url, timeout=120):
    request = urllib.request.Request(url, headers={"User-Agent": "notice-level-judge-dev-fetch/1"})
    return urllib.request.urlopen(request, timeout=timeout)


def _expected_digests(repo, revision):
    with _get(f"{HF}/api/models/{repo}/revision/{revision}?blobs=true") as response:
        info = json.load(response)
    if info.get("sha") != revision:
        raise SystemExit(f"리비전 불일치: {repo} {info.get('sha')} != {revision}")
    card = info.get("cardData") or {}
    out = {}
    for sibling in info.get("siblings", []):
        out[sibling["rfilename"]] = dict(size=sibling.get("size"), blob=sibling.get("blobId"),
                                         lfs_sha256=(sibling.get("lfs") or {}).get("sha256"))
    return out, card.get("license"), card.get("language")


def _download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    sha256 = hashlib.sha256()
    size = 0
    tmp = target.with_name(target.name + ".part")
    with _get(url, timeout=600) as response, open(tmp, "wb") as handle:
        while True:
            block = response.read(1 << 20)
            if not block:
                break
            handle.write(block)
            sha256.update(block)
            size += len(block)
    tmp.replace(target)
    return sha256.hexdigest(), size


def _git_blob_sha1(path):
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fetch(key, dest_root):
    spec = CANDIDATES[key]
    repo, revision = spec["repo"], spec["revision"]
    expected, card_license, languages = _expected_digests(repo, revision)
    if card_license != spec["license"]:
        raise SystemExit(f"{repo}: 모델 카드 라이선스 {card_license!r} != 기대 {spec['license']!r}")
    if isinstance(languages, list) and "ko" not in languages and "multilingual" not in languages:
        raise SystemExit(f"{repo}: 모델 카드 언어에 한국어 없음")
    dest = Path(dest_root) / key
    records = []
    for name in spec["files"]:
        if name not in expected:
            raise SystemExit(f"{repo}@{revision}: 파일 없음 {name}")
        url = f"{HF}/{repo}/resolve/{revision}/{name}"
        target = dest / name
        digest, size = _download(url, target)
        want = expected[name]
        ok = (want["lfs_sha256"] == digest) if want["lfs_sha256"] else (_git_blob_sha1(target) == want["blob"])
        if not ok or (want["size"] is not None and want["size"] != size):
            target.unlink(missing_ok=True)
            raise SystemExit(f"지문 불일치: {repo} {name}")
        records.append(dict(path=name, url=url, sha256=digest, size=size,
                            verified_against="lfs_sha256" if want["lfs_sha256"] else "git_blob_sha1"))
        print(f"  {key}: {name} {size:,} bytes sha256={digest}")
    license_url = LICENSE_TEXT_URLS.get(spec["license"])
    license_record = None
    if license_url:
        digest, size = _download(license_url, dest / "LICENSE.txt")
        license_record = dict(path="LICENSE.txt", url=license_url, sha256=digest, size=size)
    source = dict(key=key, repo=repo, revision=revision, repo_url=f"{HF}/{repo}/tree/{revision}",
                  license=spec["license"], card_license=card_license, kind=spec["kind"],
                  card_languages_has_ko=isinstance(languages, list) and "ko" in languages,
                  files=records, license_text=license_record)
    (dest / "source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
    return source


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", default=str(DEFAULT_DEST))
    parser.add_argument("--only", nargs="*", choices=sorted(CANDIDATES))
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        for key, spec in CANDIDATES.items():
            print(key, spec["repo"], spec["revision"], spec["license"], spec["kind"])
        return 0
    for key in args.only or list(CANDIDATES):
        print(f"[{key}] {CANDIDATES[key]['repo']}")
        fetch(key, args.dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
