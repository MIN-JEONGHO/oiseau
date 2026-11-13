"""화면 연결 함수(spec 9). 허용 함수 목록(PUBLIC_METHODS)만 호스트가 노출한다.

원칙:
- renderer가 준 문자열 경로는 쓰지 않는다. 네이티브 열기/저장 창이 고른 경로를 토큰으로 바꿔 돌려주고, 이후 호출은
  그 토큰만 받는다(용도별로 묶임: attachment|batch_input|save_report|save_template).
- 키 원문은 어떤 응답에도 넣지 않는다. 키는 KeyManager에서 꺼내 클라이언트 생성에만 쓴다.
- 한 번에 작업 하나. 작업은 스레드로 돌고 poll_progress로 진행 이벤트와 결과를 받는다.
- 모든 함수는 안전한 오류 경계다: 예외 → {ok:false, code, message}(고정 명사형 문구, 스택·키 없음).
- 판정·집계 계산은 pipeline·judge_engine·batch가 한다. 여기서는 모양만 바꾼다.
- 고시 검색(search_notices·get_notice_detail)은 읽기만 하며 작업 상태와 무관하게 응답한다(검토 작업 중에도). 검색 엔진
  (notice_search.SearchEngine)은 처음 부를 때 한 번 만들고, 이미 불러 둔 고시 기준본·기준값 표를 넘겨 다시 읽지 않는다.
  검색 점수 계산은 엔진이 하며 응답에 점수를 싣지 않는다. 검색어는 어디에도 남기지 않는다(로그·파일·브리지 상태 없음).
- 개별 검토의 선택 칸(연구개발단계·정부지원연구개발비)은 화면이 쓴 글을 그대로 받아 pipeline의 공용 정리 함수로
  확인한다(화면 스크립트는 숫자를 해석하지 않는다). 잘못된 값은 빈칸으로 두고 경고를 시작 응답·결과·처리내역에 남긴다.
- 간단한 결과(1.3.0): 개별·일괄 검토는 03 고시 검색 탭과 같은 검색 엔진을 pipeline.run_task·batch.run_batch에 넘기고
  (세부 기술 일치 확인용 PC 안 의미 검색), 선택 칸 경고를 함께 넘긴다(건수 안내에만 쓰임). 엔진을 만들지 못해도 검토는
  막지 않는다(엔진 없음 → 따질 조항이 있는 과제의 간단한 결과에 '쓸 수 없음'이 드러남). 과제마다 brief(pipeline이 만든
  간단한 결과, 1.4.0 spec R7-1 모양)를 결과에 그대로 싣고, 일괄 결과에는 실행 전체의 선택 칸 경고 안내 줄(hints)을
  Python 글로 싣는다. 공통 안내(notices)는 1.4.0부터 어떤 결과에도 싣지 않는다(화면 맨 아래 한 줄은 처음 상태의 note).
  실행 정보(run_info)에는 의미 검색 지문 두 값(semantic_model_fingerprint·semantic_vectors_fingerprint)을 실행이 끝난
  뒤 엔진이 알려 주는 값으로 담는다(불러오지 않았거나 못 쓰면 빈 글).
- 개별 결과(1.4.0)는 과제 결과(TaskResult.to_dict()) 그대로에 option_warnings와 run만 더한 것이다(아래 일괄 결과의 키는 없다).

일괄 결과(화면용, 1.4.0 spec R4·R7-2) — 작업 결과(poll_progress의 result)의 키:
    name            입력 파일 이름
    counts          기존 건수 줄: total·done·no_facts·no_candidates·error·cancelled·excluded·blank_rows·option_warnings
    tally           종합 건수 [{"kind": "over"|"near"|"under"|"unjudged", "label": str, "count": int}]. R4의 순서이며
                    "unjudged"(오류·취소)는 0이면 목록에 없다. 수의 합은 counts.total과 같다
    groups          과제 묶음 {"focus": [...], "unjudged": [...], "other": [...]} — rows의 위치(0부터)를 화면에 그릴
                    순서대로. focus는 종합 초과 → 종합 근접(같으면 입력 순), 나머지는 입력 순. 모든 행이 한 묶음에 든다
    tally_members   종합 건수 항목마다 그 건수에 든 과제 {"over": [...], "near": [...], "under": [...], "unjudged": [...]}
                    — rows의 위치(입력 순). 화면에서 건수를 누르면 이 과제들만 보인다(1.4.1)
    focus_label     '중점 검토 과제 (초과·근접 n건)'. 0건이어도 이 글이다
    focus_empty_message  중점 과제가 없으면 '고시 사양을 초과하거나 근접한 과제 없음', 있으면 빈 글
    unjudged_label  '판정하지 못한 과제 (오류 n · 취소 n)'. 오류·취소가 모두 0이면 빈 글(화면은 그 묶음을 숨긴다)
    other_label     '그 밖의 과제 (고시 사양 미달 n건)'. 0건이면 빈 글(화면은 그 묶음을 숨긴다)
    excluded·option_warnings  제외 행과 실행 전체의 선택 칸 경고(읽은 그대로)
    hints           안내 줄 목록(실행 전체의 선택 칸 경고가 있을 때 한 줄)
    rows            과제마다 요약 행 하나(입력 순): row_number·title·rnd_stage·gov_fund·status·overall·families·counts·
                    flagged_clause_count·error_reason·calls·dropped_count·brief
    run             provider·model·families·run_time
  tally·groups·tally_members는 brief.tally_briefs(결과 엑셀도 같은 함수를 쓴다)의 결과를 그대로 옮긴 것이다. 이 모듈은 판정 이름을
  비교해 세지 않는다. 묶음 제목 글의 중점·그 밖의 수는 groups에서, 오류·취소의 수는 counts에서 온다. 두 쪽이 서로 맞지
  않으면(판정 못 함 묶음의 행 수 ≠ 오류 + 취소) 틀린 숫자를 보이지 않고 작업을 실패로 끝낸다.

응답 모양: 성공 {"ok": true, "data": ...}, 실패 {"ok": false, "code": str, "message": str}.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from functools import wraps
import inspect
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit
from uuid import uuid4

import batch
import brief
from ai_stages import STAGE_LABELS, estimate_calls
from credential_store import KeyManager, PROVIDER_ENV
import doc_extract
import excel_report
from llm_client import DEFAULT_BASE_URLS, DEFAULT_MODELS
from notice_catalogue import catalogue_summary, clause_index, load_catalogue
import notice_search
from paths import PROGRAM_NAME, PROGRAM_VERSION
import judge_engine as je
import pipeline
from threshold_table import load_threshold_table

PUBLIC_METHODS = ("get_initial_state", "select_path", "extract_attachment", "estimate", "run_single", "read_batch",
                  "run_batch", "cancel", "poll_progress", "save_report", "save_template", "get_key_state",
                  "save_key", "delete_key", "set_model_settings", "search_notices", "get_notice_detail")
NOTE_TEXT = excel_report.NOTE_TEXT
PATH_KINDS = ("attachment", "batch_input", "save_report", "save_template")
PROVIDERS = tuple(DEFAULT_MODELS)
KEY_PROVIDERS = tuple(PROVIDER_ENV)
# 제공자별 모델 출력 한도(토큰, 1.3.1). 세 단계(추출·선별·매핑)가 같은 클라이언트를 쓰므로 모두에 적용된다.
# 로컬 제공자는 모델 문맥 길이보다 큰 한도를 거부할 수 있어 8,000으로 둔다. 키는 PROVIDERS와 같아야 한다(시험).
MAX_OUTPUT_TOKENS = {"claude": 32000, "openai": 32000, "ollama": 8000, "lmstudio": 8000}
# 개별 검토 과제 입력 키(모두 글). 연구개발과제명·과제요약정보 세 칸·확인한 발췌·첨부 이름·연구개발단계·지원금.
TASK_KEYS = frozenset(("title", "final_goal", "rnd_content", "utilization", "excerpt", "attachment_name", "rnd_stage",
                       "gov_fund"))
REPORT_KINDS = ("single", "batch")
WORKERS = batch.DEFAULT_WORKERS
_TERMINAL = frozenset(("done", "cancelled", "failed"))
_RUNNING = frozenset(("running", "cancelling"))

# 화면에만 보이는 고정 문구(명사형). 결과·파일에는 쓰지 않는다.
MESSAGES = {
    "validation": "입력값 또는 선택 값 확인 필요",
    "busy": "진행 중인 작업 있음. 완료 또는 취소 뒤 다시 시작 가능",
    "credential": "API 키 없음 또는 보안 저장소 오류. 설정에서 키 저장 필요",
    "io": "파일 저장 실패. 저장 위치·권한·열린 파일 확인 필요",
    "runtime": "작업 처리 실패. 입력과 설치 상태 확인 필요",
    "not_found": "저장할 결과 없음. 검토 완료 뒤 저장 가능",
    "resources": "고시 자료 또는 고시 기준 사양 표 확인 불가. 프로그램 재설치 필요",
    "input": "입력 엑셀 확인 필요",
    "no_rows": "처리할 행 없음. 입력 엑셀의 연구개발과제명·과제요약정보 확인 필요",
    "queued": "작업 준비 중",
    "done": "검토 완료",
    "cancelling": "취소 요청 반영 중. 진행 중인 AI 요청 완료 뒤 중단",
    "cancelled_single": "취소 요청으로 검토 중단. 결과 없음",
    "cancelled_batch": "취소 반영. 끝난 행 보존, 시작하지 않은 행은 취소 상태",
    "failed": "작업 처리 실패. 입력과 설치 상태 확인 필요",
    "batch_label": "일괄 검토 중",
    "search": "고시 검색 준비 실패. 고시 자료 확인 불가, 프로그램 재설치 필요",
    "search_failed": "고시 검색 처리 실패. 검색어를 바꿔 다시 검색 필요",
    "search_query": f"검색어 확인 필요. {notice_search.MAX_QUERY_CHARS}자 이하 글로 검색 가능",
    "search_filter": "검토 대상 고시 선택 확인 필요",
    "search_page": "검색 결과 더 보기 위치 확인 필요",
    "search_clause": "검색 대상에 없는 고시 조항. 조항 ID 확인 필요",
}
# 일괄 검토 결과의 안내 줄(spec 7.2-2): 실행 전체의 선택 칸 경고가 있을 때만(행 없는 머리글 경고 포함).
# 처리내역은 1.4.0부터 숨김 시트라 그렇게 적는다(1.4.0 spec R5-3).
BATCH_OPTION_HINT = "선택 칸 경고 {}건 — 상세 보기·처리내역(숨김 시트)에서 확인"
# 일괄 검토 결과의 묶음 제목 글과 빈 경우 글(1.4.0 spec R7-2, 글자 그대로). 화면은 이 글을 그대로 넣고 수를 세지 않는다.
BATCH_FOCUS_LABEL = "중점 검토 과제 (초과·근접 {}건)"              # 중점 과제 수. 0건이어도 이 글이다
BATCH_OTHER_LABEL = "그 밖의 과제 (고시 사양 미달 {}건)"           # 그 밖 과제 수. 0건이면 빈 글
BATCH_UNJUDGED_LABEL = "판정하지 못한 과제 (오류 {} · 취소 {})"    # 오류·취소 과제 수. 둘 다 0이면 빈 글
BATCH_FOCUS_EMPTY_MESSAGE = "고시 사양을 초과하거나 근접한 과제 없음"   # 중점 과제가 없을 때만
# 실행 정보에 담는 의미 검색 지문(엔진 속성 이름 그대로). 처리내역에 쓰인다.
SEMANTIC_FINGERPRINT_KEYS = ("semantic_model_fingerprint", "semantic_vectors_fingerprint")
# 고시 검색 필터(검토 대상 고시 선택): '전체'와 고시 넷. 값은 notice_search.FILTERS 그대로.
SEARCH_FILTER_LABELS = {notice_search.FILTER_ALL: notice_search.FILTER_ALL, **pipeline.FAMILY_LABELS}
_STAGE_FALLBACK = "검토"
_STAGE_SUFFIX = " 중"


class _BoundaryError(Exception):
    def __init__(self, code, message=None):
        self.code = code
        self.message = message if message is not None else MESSAGES.get(code, MESSAGES["runtime"])


class _Cancelled(pipeline.CancelledError):
    """취소 뒤 AI 요청을 거부했다. pipeline은 이것을 '취소' 결과로 돌려주고, 개별 검토는 클라이언트의 refused로 결과를 버린다."""


def _failure(code, message=None):
    return {"ok": False, "code": code, "message": message if message is not None else MESSAGES.get(code, MESSAGES["runtime"])}


def _public(function):
    """인자 묶기 오류까지 잡는다. pywebview는 그렇지 않으면 예외 문자열과 스택을 돌려준다."""
    signature = inspect.signature(function)

    @wraps(function)
    def safe(self, *args, **kwargs):
        try:
            signature.bind(self, *args, **kwargs)
            data = function(self, *args, **kwargs)
            return {"ok": True, "data": _json_copy(data)}
        except _BoundaryError as error:
            return _failure(error.code, error.message)
        except doc_extract.DocumentError as error:
            return _failure(error.reason_code, error.message)
        except batch.BatchInputError as error:
            return _failure("input", str(error))
        except (ValueError, TypeError, KeyError, OverflowError):
            return _failure("validation")
        except OSError:
            return _failure("io")
        except Exception:  # noqa: BLE001 — 경계 밖으로 예외 본문을 내보내지 않는다
            return _failure("runtime")
    return safe


def _require(condition, code="validation", message=None):
    if not condition:
        raise _BoundaryError(code, message)


def _json_copy(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _text(value, allow_empty=True):
    _require(isinstance(value, str))
    if not allow_empty:
        _require(bool(value.strip()))
    return value


def _families(value):
    _require(isinstance(value, list) and value)
    families = [str(f) for f in dict.fromkeys(value)]
    _require(all(f in pipeline.FAMILY_ORDER for f in families))
    return families


# ── 자원·클라이언트 ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class Resources:
    """고시 기준본 요약(JSON 가능), 조항 색인, 기준값 표. 한 번 읽어 고정한다.

    full_catalogue는 고시 검색 엔진에 넘길 기준본 자체(load_catalogue 결과)다. 없으면(합성 자원) 검색 엔진이
    프로그램 자원에서 스스로 읽는다.
    """
    catalogue: dict
    index: list
    table: object
    full_catalogue: object = None


def load_resources():
    catalogue = load_catalogue()
    table = load_threshold_table(catalogue=catalogue)
    return Resources(catalogue=catalogue_summary(catalogue), index=clause_index(catalogue), table=table,
                     full_catalogue=catalogue)


def make_search_engine(resources):
    """고시 검색 엔진. 브리지가 불러 둔 기준본·기준값 표를 넘겨 다시 읽지 않는다(합성 자원이면 엔진이 스스로 읽음)."""
    if resources.full_catalogue is not None:
        return notice_search.SearchEngine(resources.full_catalogue, resources.table)
    return notice_search.SearchEngine()


def _search_boundary(error):
    """검색 엔진의 거부 → 화면 경계 오류(validation + 명사형 문구). 엔진 문구는 내보내지 않는다."""
    if isinstance(error, notice_search.SearchQueryError):
        return _BoundaryError("validation", MESSAGES["search_query"])
    if isinstance(error, notice_search.SearchFilterError):
        return _BoundaryError("validation", MESSAGES["search_filter"])
    if isinstance(error, notice_search.UnknownClauseError):
        return _BoundaryError("validation", MESSAGES["search_clause"])
    return _BoundaryError("validation", MESSAGES["search_page"])


def make_client(settings, key):
    """선택한 제공자·모델·주소로 모델 클라이언트를 만든다. 키는 여기서만 쓰인다. 출력 한도는 MAX_OUTPUT_TOKENS."""
    from llm_json import TolerantLLMClient
    provider = settings["provider"]
    return TolerantLLMClient(provider=provider, api_key=key or None, model=settings["model"] or None,
                             base_url=settings["base_url"] or None, max_tokens=MAX_OUTPUT_TOKENS[provider])


def normalize_settings(provider, model, base_url):
    """제공자·모델·로컬 주소를 확인하고 실제로 쓸 값으로 정리한다. 어긋나면 _BoundaryError(validation)."""
    _require(isinstance(provider, str) and provider in PROVIDERS)
    model = _text(model).strip() or DEFAULT_MODELS[provider]
    if provider in KEY_PROVIDERS:
        # llm_client는 클라우드 제공자에 기본 모델만 허용한다.
        _require(model == DEFAULT_MODELS[provider])
        return dict(provider=provider, model=model, base_url="")
    base_url = _text(base_url).strip() or DEFAULT_BASE_URLS[provider]
    try:
        parts = urlsplit(base_url)
        valid = (parts.scheme in ("http", "https") and bool(parts.hostname) and not parts.username
                 and not parts.password and not parts.query and not parts.fragment)
    except (TypeError, ValueError):
        valid = False
    _require(valid)
    return dict(provider=provider, model=model, base_url=base_url.rstrip("/"))


class _CancellableClient:
    """취소 뒤의 AI 요청을 거부한다. refused가 True이면 그 결과는 취소로 본다."""

    def __init__(self, client, cancel):
        self._client = client
        self._cancel = cancel
        self.refused = False

    def ask_json(self, *args, **kwargs):
        if self._cancel.is_set():
            self.refused = True
            raise _Cancelled("작업 취소")
        return self._client.ask_json(*args, **kwargs)


@dataclass
class _Job:
    kind: str
    state: str = "running"
    events: list = field(default_factory=list)
    result: dict | None = None
    message: str = ""
    completed: int = 0
    total: int = 0
    cancel: threading.Event = field(default_factory=threading.Event)
    # save_report용 원본 결과(TaskResult 목록)와 실행 정보. 화면에는 보내지 않는다.
    full_results: list = field(default_factory=list)
    run_info: dict = field(default_factory=dict)


# ── 브리지 ─────────────────────────────────────────────────────────────

class Bridge:
    def __init__(self, *, key_manager=None, resources_loader=None, client_factory=None, path_selector=None,
                 extractor=None, task_runner=None, batch_runner=None, batch_reader=None, report_writer=None,
                 template_maker=None, workers=WORKERS, clock=None, search_factory=None):
        self._keys = key_manager if key_manager is not None else KeyManager()
        self._resources_loader = resources_loader or load_resources
        self._client_factory = client_factory or make_client
        self._path_selector = path_selector
        self._extractor = extractor or self._default_extract
        self._task_runner = task_runner or pipeline.run_task
        self._batch_runner = batch_runner or batch.run_batch
        self._batch_reader = batch_reader or batch.read_batch_input
        self._report_writer = report_writer or excel_report.write_report
        self._template_maker = template_maker or batch.make_template
        self._workers = workers
        self._clock = clock or datetime.now
        self._search_factory = search_factory or make_search_engine
        self._lock = threading.RLock()
        # 검색 엔진 만들기 전용 잠금. 작업 잠금(_lock)과 따로 두어 검토 작업 중에도 검색이 기다리지 않는다.
        self._search_lock = threading.Lock()
        self._search_engine = None
        self._resources = None
        self._settings = dict(provider="claude", model=DEFAULT_MODELS["claude"], base_url="")
        self._paths = {}
        self._batch_reads = {}
        self._extractions = {}
        self._job = None

    # ── 내부 도우미 ────────────────────────────────────────────────────
    @staticmethod
    def _default_extract(path):
        extracted = doc_extract.extract_text(path)
        return extracted, doc_extract.find_goal_sections(extracted.text)

    def _get_resources(self):
        with self._lock:
            if self._resources is None:
                try:
                    resources = self._resources_loader()
                except Exception:
                    raise _BoundaryError("resources") from None
                _require(isinstance(resources, Resources), "resources")
                self._resources = resources
            return self._resources

    def _search(self):
        """검색 엔진(처음 부를 때 한 번 만든다). 만들지 못하면 _BoundaryError(search) — 다음 호출에서 다시 시도한다."""
        with self._search_lock:
            if self._search_engine is None:
                try:
                    resources = self._get_resources()
                    self._search_engine = self._search_factory(resources)
                except Exception:
                    raise _BoundaryError("search") from None
            return self._search_engine

    def _review_engine(self):
        """검토가 함께 쓰는 검색 엔진(03 탭과 같은 것). 만들지 못하면 None — 검토는 막지 않는다(세부 기술 일치를 따질
        조항이 있는 과제의 간단한 결과에 '의미 검색을 쓸 수 없음'이 드러난다). 작업 스레드에서 부른다."""
        try:
            return self._search()
        except Exception:  # noqa: BLE001 — 엔진 오류 본문은 내보내지 않는다
            return None

    @staticmethod
    def _semantic_fingerprints(engine):
        """엔진이 알려 주는 의미 검색 지문 두 값. 엔진이 없거나 아직 불러오지 않았거나 못 쓰면 빈 글."""
        values = {}
        for name in SEMANTIC_FINGERPRINT_KEYS:
            try:
                value = getattr(engine, name, "") if engine is not None else ""
            except Exception:  # noqa: BLE001
                value = ""
            values[name] = value if isinstance(value, str) else ""
        return values

    def _search_state(self):
        """초기 상태에 싣는 고시 검색 정보: 필터·검색어 상한·안내 문구와 엔진 상태(관련어 사전·의미 유사)."""
        base = dict(filters=[dict(id=value, label=SEARCH_FILTER_LABELS[value]) for value in notice_search.FILTERS],
                    default_filter=notice_search.FILTER_ALL, max_query_chars=notice_search.MAX_QUERY_CHARS,
                    default_limit=notice_search.DEFAULT_LIMIT, footer=notice_search.NOTICE_FOOTER,
                    similar_notice=notice_search.NOTICE_SIMILAR)
        try:
            status = self._search().status()
        except _BoundaryError as error:
            return dict(base, available=False, message=error.message, status=None)
        except Exception:
            return dict(base, available=False, message=MESSAGES["search"], status=None)
        return dict(base, available=True, message="", status=status)

    def _idle(self):
        with self._lock:
            _require(self._job is None or self._job.state not in _RUNNING, "busy")

    def _path(self, token, kind):
        _require(isinstance(token, str) and bool(token))
        with self._lock:
            entry = self._paths.get(token)
        _require(entry is not None and entry[0] == kind)
        return entry[1]

    def _key_state(self, provider):
        try:
            state = self._keys.resolve(provider)
        except Exception:
            raise _BoundaryError("credential") from None
        return state

    def _public_key_state(self, provider):
        try:
            info = self._key_state(provider).public_info()
        except _BoundaryError:
            info = dict(provider=provider, source="missing", stored=None, has_key=False,
                        warning="보안 저장소 확인 불가. 키 재입력 필요")
        return dict(provider=provider, has_key=bool(info["has_key"]), stored=info["stored"], source=info["source"],
                    warning=info["warning"])

    def _key_for(self, settings):
        """클라우드 제공자는 키가 있어야 한다. 로컬 제공자는 빈 키."""
        if settings["provider"] not in KEY_PROVIDERS:
            return ""
        state = self._key_state(settings["provider"])
        _require(state.has_key, "credential")
        return state.key

    def _event(self, job, stage, label, message="", completed=0, total=0):
        with self._lock:
            if self._job is not job:
                return
            completed = completed if type(completed) is int and completed >= 0 else 0
            total = total if type(total) is int and total >= completed else completed
            # 상태 이벤트(준비·완료·취소·실패)는 설명 칸에도 같은 글을 둔다.
            message = str(message) if message else str(label)
            job.events.append(dict(sequence=len(job.events) + 1, stage=str(stage), label=str(label), message=message,
                                   completed=completed, total=total))
            job.completed, job.total = completed, total

    def _progress(self, job, event):
        if type(event) is not dict:
            return
        stage = str(event.get("stage", ""))
        completed, total = event.get("completed", 0), event.get("total", 0)
        if stage == batch.PROGRESS_STAGE:
            label = f"{MESSAGES['batch_label']} {completed}/{total}"
            message = f"{event.get('row_number', '?')}행 {event.get('status', '')}"
        else:
            label = STAGE_LABELS.get(stage, _STAGE_FALLBACK) + _STAGE_SUFFIX
            if type(total) is int and total > 1:
                label += f" {completed}/{total}"
            message = event.get("message", "")
        self._event(job, stage, label, message, completed, total)

    def _launch(self, kind, worker):
        with self._lock:
            _require(self._job is None or self._job.state not in _RUNNING, "busy")
            job = _Job(kind=kind)
            self._job = job
            self._event(job, "queued", MESSAGES["queued"])

        def run():
            terminal = "failed"
            try:
                worker(job)
                terminal = "cancelled" if job.cancel.is_set() else "done"
                if terminal == "done":
                    self._event(job, "done", MESSAGES["done"], "", job.completed, job.total)
                    job.message = MESSAGES["done"]
                else:
                    job.message = MESSAGES["cancelled_single" if kind == "single" else "cancelled_batch"]
                    self._event(job, "cancelled", job.message, "", job.completed, job.total)
            except Exception:  # noqa: BLE001 — 예외 본문은 화면·결과 어디에도 내보내지 않는다
                terminal = "failed"
                job.result = None
                job.full_results = []
                job.message = MESSAGES["failed"]
                self._event(job, "failed", job.message)
            finally:
                with self._lock:
                    job.state = terminal

        # 스레드가 바로 끝나도 시작 응답은 '진행' 상태를 담도록 먼저 찍는다.
        snapshot = _json_copy(self._snapshot(job, 0))
        thread = threading.Thread(target=run, name="judge-job", daemon=True)
        try:
            thread.start()
        except Exception:
            with self._lock:
                job.state = "failed"
            raise _BoundaryError("runtime") from None
        return snapshot

    def _snapshot(self, job, after):
        if job is None:
            return dict(state="idle", kind=None, events=[], result=None, message="", completed=0, total=0)
        return dict(state=job.state, kind=job.kind, events=[e for e in job.events if e["sequence"] > after],
                    result=job.result if job.state in _TERMINAL else None, message=job.message,
                    completed=job.completed, total=job.total)

    def _run_info(self, settings, families, resources, *, excluded=(), file_warnings=(), blank_rows=0, option_warnings=(),
                  engine=None):
        """실행 정보(결과 엑셀 처리내역에 쓰임). 의미 검색 지문 두 값은 이때의 엔진 값이며, 작업은 실행이 끝난 뒤
        _semantic_fingerprints로 다시 채운다(의미 모델은 처음 쓸 때 불러오므로 시작할 때는 빈 글일 수 있다)."""
        return dict(run_time=self._clock().strftime("%Y-%m-%d %H:%M:%S"), catalogue_id=resources.catalogue.get("catalogue_id", ""),
                    catalogue_fingerprint=resources.catalogue.get("fingerprint", ""), table_fingerprint=resources.table.fingerprint,
                    provider=settings["provider"], model=settings["model"], near_percent=str(je.NEAR_PERCENT),
                    families=list(families), excluded=list(excluded), file_warnings=list(file_warnings), blank_rows=blank_rows,
                    option_warnings=deepcopy(list(option_warnings)), **self._semantic_fingerprints(engine))

    @staticmethod
    def _row_summary(result):
        """일괄 결과의 화면용 요약 행. judge 상세는 보내지 않는다(엑셀에 들어간다). brief는 간단한 결과 그대로."""
        return dict(row_number=result.row_number, title=result.title, rnd_stage=result.rnd_stage, gov_fund=result.gov_fund,
                    status=result.status,
                    overall=result.overall, families=dict(result.families), counts=dict(result.counts),
                    flagged_clause_count=result.flagged_clause_count, error_reason=result.error_reason,
                    calls=dict(result.calls), dropped_count=len(result.dropped), brief=deepcopy(result.brief))

    @staticmethod
    def _batch_hints(option_warnings):
        """일괄 결과의 안내 줄: 실행 전체의 선택 칸 경고가 있으면 그 건수 한 줄(없으면 빈 목록)."""
        count = len(option_warnings)
        return [BATCH_OPTION_HINT.format(count)] if count else []

    @staticmethod
    def _batch_overview(results, counts):
        """일괄 결과의 종합 건수·과제 묶음·묶음 제목 글(1.4.0 spec R4·R7-2). 돌려주는 것은 일괄 결과에 더하는 키 일곱.

        tally·groups·tally_members는 brief.tally_briefs의 결과 그대로다(여기서 판정 이름을 비교해 세지 않는다. groups의 위치는
        results의 위치이고 rows가 같은 순서다). 제목 글의 중점·그 밖의 수는 groups에서, 오류·취소의 수는 기존 건수
        줄(counts)에서 온다. 간단한 결과가 없는 과제, 모르는 종합 결과·묶음 값은 tally_briefs가 ValueError로 드러내고,
        판정 못 함 묶음의 행 수가 오류 + 취소와 다르면 여기서 ValueError를 낸다(작업이 실패로 끝난다 — 서로 다른
        숫자를 조용히 보이지 않는다).
        """
        overview = brief.tally_briefs([result.brief for result in results])
        groups = overview["groups"]
        focus, other, unjudged = (len(groups[name]) for name in (brief.GROUP_FOCUS, brief.GROUP_OTHER, brief.GROUP_UNJUDGED))
        errors, cancelled = counts["error"], counts["cancelled"]
        if errors + cancelled != unjudged:
            raise ValueError(f"판정 못 함 묶음의 과제 수({unjudged})가 오류({errors})·취소({cancelled}) 건수와 다르다")
        return dict(tally=overview["tally"], groups=groups, tally_members=overview["members"],
                    focus_label=BATCH_FOCUS_LABEL.format(focus),
                    focus_empty_message="" if focus else BATCH_FOCUS_EMPTY_MESSAGE,
                    unjudged_label=BATCH_UNJUDGED_LABEL.format(errors, cancelled) if errors or cancelled else "",
                    other_label=BATCH_OTHER_LABEL.format(other) if other else "")

    # ── 공개 함수 ──────────────────────────────────────────────────────
    @_public
    def get_initial_state(self):
        resources = self._get_resources()
        counts = resources.catalogue.get("family_item_counts", {})
        with self._lock:
            settings = dict(self._settings)
            job = self._snapshot(self._job, 0)
        return dict(
            program=dict(name=PROGRAM_NAME, version=PROGRAM_VERSION),
            catalogue=dict(catalogue_id=resources.catalogue.get("catalogue_id", ""), fingerprint=resources.catalogue.get("fingerprint", ""),
                           item_count=resources.catalogue.get("item_count", len(resources.index)),
                           notices=deepcopy(resources.catalogue.get("notices", []))),
            table=dict(fingerprint=resources.table.fingerprint, near_percent=str(je.NEAR_PERCENT),
                       record_count=len(resources.table.records)),
            families=[dict(id=family, label=pipeline.FAMILY_LABELS[family], count=counts.get(family, 0))
                      for family in pipeline.FAMILY_ORDER],
            providers=[dict(id=provider, default_model=DEFAULT_MODELS[provider], needs_key=provider in KEY_PROVIDERS,
                            default_base_url=DEFAULT_BASE_URLS.get(provider, "")) for provider in PROVIDERS],
            key_state={provider: self._public_key_state(provider) for provider in KEY_PROVIDERS},
            settings=settings, note=NOTE_TEXT, supported_extensions=list(doc_extract.SUPPORTED_EXTENSIONS),
            workers=self._workers, job=job, search=self._search_state())

    @_public
    def select_path(self, kind):
        _require(isinstance(kind, str) and kind in PATH_KINDS)
        self._idle()
        _require(self._path_selector is not None, "runtime")
        selected = self._path_selector(kind)
        if selected is None or selected == "":
            return dict(cancelled=True, token=None, name=None)
        _require(isinstance(selected, (str, os.PathLike)))
        path = Path(selected).resolve()
        if kind in ("attachment", "batch_input"):
            _require(not path.is_dir())
        else:
            _require(path.suffix.lower() == ".xlsx" and path.parent.is_dir() and not path.is_dir())
        token = uuid4().hex
        with self._lock:
            self._paths[token] = (kind, path)
        return dict(cancelled=False, token=token, name=path.name or str(path))

    @_public
    def extract_attachment(self, token):
        self._idle()
        path = self._path(token, "attachment")
        extracted, sections = self._extractor(path)
        with self._lock:
            self._extractions[path.name] = list(extracted.warnings)
        return dict(name=path.name, kind=extracted.kind, page_count=extracted.page_count, warnings=list(extracted.warnings),
                    text=extracted.text, text_length=len(extracted.text),
                    sections=[dict(heading=s.heading, start=s.start, end=s.end, body=s.body) for s in sections])

    @_public
    def estimate(self, families, is_batch=False, row_count=1):
        families = _families(families)
        _require(isinstance(is_batch, bool) and type(row_count) is int and row_count >= 1)
        count = row_count if is_batch else 1
        low, high = estimate_calls(families, self._get_resources().table)
        return dict(families=families, count=count, per_task=[low, high], total=[low * count, high * count])

    @_public
    def run_single(self, task, families):
        _require(isinstance(task, dict) and set(task) <= TASK_KEYS and all(isinstance(v, str) for v in task.values()))
        families = _families(families)
        # 선택 칸은 일괄 검토와 같은 공용 정리 함수로 확인한다. 잘못된 값은 빈칸 + 경고(검토는 막지 않는다).
        rnd_stage, stage_warning = pipeline.normalize_rnd_stage(task.get("rnd_stage", ""))
        gov_fund, fund_warning = pipeline.normalize_gov_fund(task.get("gov_fund", ""))
        option_warnings = [warning for warning in (stage_warning, fund_warning) if warning]
        clean_task = {key: task.get(key, "") for key in ("title", "final_goal", "rnd_content", "utilization", "excerpt",
                                                         "attachment_name")}
        clean_task.update(rnd_stage=rnd_stage, gov_fund=gov_fund)
        try:
            clean = pipeline.validate_task(clean_task)
        except pipeline.InputError:
            raise _BoundaryError("validation") from None
        self._idle()
        resources = self._get_resources()
        with self._lock:
            settings = dict(self._settings)
            warnings = list(self._extractions.get(clean["attachment_name"], ())) if clean["attachment_name"] else []
        key = self._key_for(settings)

        def work(job):
            engine = self._review_engine()
            run_info = self._run_info(settings, families, resources, file_warnings=warnings, option_warnings=option_warnings,
                                      engine=engine)
            client = _CancellableClient(self._client_factory(settings, key), job.cancel)
            result = self._task_runner(clean, families, client, resources.table, resources.index,
                                       progress=lambda event: self._progress(job, event), search_engine=engine,
                                       option_warnings=deepcopy(option_warnings))
            if client.refused or job.cancel.is_set():
                job.cancel.set()
                return
            # 지문은 실행이 끝난 뒤 값(이 과제가 의미 모델을 처음 불러왔을 수 있다).
            run_info.update(self._semantic_fingerprints(engine))
            data = result.to_dict()
            data["option_warnings"] = deepcopy(option_warnings)
            data["run"] = {key_: value for key_, value in run_info.items() if key_ not in ("excluded", "option_warnings")}
            with self._lock:
                job.result = data
                job.full_results = [result]
                job.run_info = run_info
        snapshot = self._launch("single", work)
        return dict(snapshot, option_warnings=deepcopy(option_warnings))

    @_public
    def read_batch(self, token):
        self._idle()
        path = self._path(token, "batch_input")
        read = self._batch_reader(path)
        with self._lock:
            self._batch_reads[token] = deepcopy(read)
        return dict(name=path.name, count=len(read["rows"]), total_rows=read["total_rows"], blank_rows=read["blank_rows"],
                    excluded=deepcopy(read["excluded"]), option_warnings=deepcopy(read["option_warnings"]),
                    rows=[dict(row_number=r["row_number"], title=r["title"], rnd_stage=r["rnd_stage"]) for r in read["rows"]])

    @_public
    def run_batch(self, token, families):
        families = _families(families)
        self._idle()
        path = self._path(token, "batch_input")
        with self._lock:
            read = self._batch_reads.get(token)
        if read is None:
            read = self._batch_reader(path)
        rows = list(read["rows"])
        _require(bool(rows), "validation", MESSAGES["no_rows"])
        resources = self._get_resources()
        with self._lock:
            settings = dict(self._settings)
        key = self._key_for(settings)
        excluded = list(read["excluded"])
        option_warnings = list(read["option_warnings"])

        def work(job):
            engine = self._review_engine()
            run_info = self._run_info(settings, families, resources, excluded=excluded, blank_rows=read["blank_rows"],
                                      option_warnings=option_warnings, engine=engine)
            self._event(job, batch.PROGRESS_STAGE, f"{MESSAGES['batch_label']} 0/{len(rows)}", "", 0, len(rows))
            results = self._batch_runner(rows, families, lambda: _CancellableClient(self._client_factory(settings, key), job.cancel), resources.table,
                                         resources.index, workers=self._workers,
                                         progress=lambda event: self._progress(job, event), cancel_event=job.cancel,
                                         search_engine=engine, option_warnings=deepcopy(option_warnings))
            # 지문은 실행이 끝난 뒤 값(행 하나가 의미 모델을 처음 불러왔을 수 있다).
            run_info.update(self._semantic_fingerprints(engine))
            counts = dict(total=len(results), done=batch.count_status(results, pipeline.STATUS_DONE),
                          no_facts=batch.count_status(results, pipeline.STATUS_NO_FACTS),
                          no_candidates=batch.count_status(results, pipeline.STATUS_NO_CANDIDATES),
                          error=batch.count_status(results, pipeline.STATUS_ERROR),
                          cancelled=batch.count_status(results, pipeline.STATUS_CANCELLED),
                          excluded=len(excluded), blank_rows=read["blank_rows"], option_warnings=len(option_warnings))
            # 종합 건수·과제 묶음·묶음 제목 글. 건수가 서로 맞지 않으면 예외로 작업이 실패한다(결과를 내지 않는다).
            overview = self._batch_overview(results, counts)
            with self._lock:
                job.result = dict(name=path.name, counts=counts, **overview, excluded=deepcopy(excluded),
                                  option_warnings=deepcopy(option_warnings),
                                  hints=self._batch_hints(option_warnings),
                                  rows=[self._row_summary(r) for r in results],
                                  run=dict(provider=settings["provider"], model=settings["model"], families=list(families),
                                           run_time=run_info["run_time"]))
                job.full_results = list(results)
                job.run_info = run_info
        return self._launch("batch", work)

    @_public
    def cancel(self):
        with self._lock:
            job = self._job
            if job is None:
                return dict(state="idle")
            if job.state == "running":
                job.cancel.set()
                job.state = "cancelling"
                self._event(job, "cancelling", MESSAGES["cancelling"], "", job.completed, job.total)
            return dict(state=job.state)

    @_public
    def poll_progress(self, after_sequence=0):
        _require(type(after_sequence) is int and after_sequence >= 0)
        with self._lock:
            return self._snapshot(self._job, after_sequence)

    @_public
    def save_report(self, token, which):
        _require(isinstance(which, str) and which in REPORT_KINDS)
        self._idle()
        path = self._path(token, "save_report")
        with self._lock:
            job = self._job
            _require(job is not None and job.state in _TERMINAL and job.kind == which and job.full_results, "not_found")
            results = list(job.full_results)
            run_info = deepcopy(job.run_info)
        self._report_writer(path, results, run_info)
        return dict(saved=True, name=path.name, which=which, count=len(results))

    @_public
    def save_template(self, token):
        self._idle()
        path = self._path(token, "save_template")
        self._template_maker(path)
        return dict(saved=True, name=path.name)

    @_public
    def get_key_state(self):
        return {provider: self._public_key_state(provider) for provider in KEY_PROVIDERS}

    @_public
    def save_key(self, provider, key):
        _require(isinstance(provider, str) and provider in KEY_PROVIDERS)
        _require(isinstance(key, str) and bool(key.strip()))
        try:
            state = self._keys.apply(provider, key)
        except ValueError:
            raise _BoundaryError("validation") from None
        except Exception:
            raise _BoundaryError("credential") from None
        _require(state.has_key and state.stored is True and not state.warning, "credential")
        return self._public_key_state(provider)

    @_public
    def delete_key(self, provider):
        _require(isinstance(provider, str) and provider in KEY_PROVIDERS)
        try:
            state = self._keys.delete(provider)
        except Exception:
            raise _BoundaryError("credential") from None
        _require(state.stored is False, "credential")
        return dict(provider=provider, has_key=state.has_key, stored=False, source=state.source, warning=state.warning)

    @_public
    def set_model_settings(self, provider, model="", base_url=""):
        settings = normalize_settings(provider, model, base_url)
        with self._lock:
            self._settings = dict(settings)
        return settings

    # ── 고시 검색(읽기만 함. 작업 상태와 무관하게 응답) ─────────────────────
    @_public
    def search_notices(self, query, family=notice_search.FILTER_ALL, limit=notice_search.DEFAULT_LIMIT, offset=0,
                       similar_offset=0):
        """검색 → 두 묶음(results: 검색 결과, similar: 비슷한 뜻)·찾은 이유·원문 일부 강조 위치·엔진 상태. 점수 없음."""
        _require(isinstance(query, str), "validation", MESSAGES["search_query"])
        _require(isinstance(family, str), "validation", MESSAGES["search_filter"])
        engine = self._search()
        try:
            result = engine.search(query, family=family, limit=limit, offset=offset, similar_offset=similar_offset)
        except notice_search.SearchError as error:
            raise _search_boundary(error) from None
        except Exception:
            raise _BoundaryError("runtime", MESSAGES["search_failed"]) from None
        # '더 보기'가 넘길 다음 위치를 여기서 정한다(화면 스크립트는 숫자 계산을 하지 않는다).
        for name in ("results", "similar"):
            group = result[name]
            group["next_offset"] = group["offset"] + len(group["items"])
        return result

    @_public
    def get_notice_detail(self, clause_id, query=""):
        """조항 상세 → 원문 전체(국문·영문)와 강조 위치, 고시 기준 사양 목록. 검색 대상(507개)에 없는 ID는 거부."""
        _require(isinstance(clause_id, str) and bool(clause_id), "validation", MESSAGES["search_clause"])
        _require(isinstance(query, str), "validation", MESSAGES["search_query"])
        engine = self._search()
        try:
            return engine.detail(clause_id, query)
        except notice_search.SearchError as error:
            raise _search_boundary(error) from None
        except Exception:
            raise _BoundaryError("runtime", MESSAGES["search_failed"]) from None
