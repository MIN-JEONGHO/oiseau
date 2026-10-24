"""The twelve-operation v16 desktop boundary; no renderer supplied paths or DTOs.

Only explicitly exposed methods are an IPC API. All dependencies, credentials,
path capabilities, immutable run snapshots and retained results stay in Python.
The host MUST use js_api=None and window.expose, never expose this object.

v16 differs from v15 in these places only: two read-only notice lookups
(search_notice_clauses, get_notice_clause), the initial state's notice list,
title table and display-only guideline quotations, the dedicated stop event for
a protected previous result (batch_v16.PreviousResultError, code io),
screen-only fixed error and progress messages written as noun-ending 개조식,
the default model client llm_json_v16.TolerantLLMClient (one JSON object taken
out of surrounding prose), and two screen-only notices shown at most once per
job: input_cleaned (task or common policy text changed by
v16_domain.clean_input_text, or batch_v16.run_excel's notice_cb) and
response_trimmed (a client's trimmed_responses grew during a call).
Nothing persisted in a result, checkpoint, workbook, audit or document changes.
The twelfth operation, save_input_template, writes the batch input template
(batch_v16.make_template) to an input_template path token and refuses a path
this session reviews or a result workbook with a checkpoint or audit sibling.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, fields
from functools import wraps
import inspect
import json
import os
from pathlib import Path
import re
import threading
import unicodedata
from uuid import uuid4

import batch_v16
import classification_v16
from credential_store import KeyManager
from notice_catalogue_v16 import CatalogueError, load_catalogue
from notice_review_v16 import _preflight
import v16_domain as d


PUBLIC_METHODS = ("get_initial_state", "select_path", "save_key", "delete_key",
                  "start_single", "start_batch", "get_job", "cancel_job", "start_export",
                  "search_notice_clauses", "get_notice_clause", "save_input_template")
_TERMINAL = frozenset(("done", "cancelled", "failed"))
_STAGES = frozenset(("preflight", "facts", "notices", "candidate", "criteria",
                     "agents", "summary", "documents", "persistence"))
_PURPOSES = frozenset(("input_excel", "output_excel", "output_directory", "input_template"))
# Spec 4.4: a template is never written over a file the review uses.
_REVIEW_PURPOSES = frozenset(("input_excel", "output_excel"))
_RESULT_SIBLINGS = (".checkpoint.jsonl", ".audit.jsonl")
# Screen-only fixed messages (spec 4.8); never stored in any result or file.
_MESSAGES = {
    "validation": "입력 또는 실행 설정 확인 후 다시 시도",
    "catalogue": "고시 기준 파일 확인 불가. 앱 재설치 후 실행 필요",
    "credential": "보안 저장소 작업 실패 또는 키 없음. 키 재입력 또는 저장·삭제 재시도 필요",
    "busy": "진행 중인 작업 있음. 완료 또는 취소 후 다시 시작",
    "not_found": "선택한 작업 또는 결과 없음. 완료된 결과 다시 선택 필요",
    "io": "파일 처리 실패. 저장 위치·권한과 열린 파일 확인 후 다시 시도",
    "runtime": "작업 미완료. 입력과 설치 상태 확인 후 다시 실행",
}
# Screen-only progress and warning events (spec 4.8), one table so the style
# check sees every literal the bridge can emit.
_EVENTS = {
    "key_session": "보안 저장소 키 저장 실패. 이번 실행에서만 메모리의 입력 키 사용, 다음 실행 시 키 재입력 필요",
    "key_environment": "환경변수의 API 키를 이번 실행에 사용. 환경변수 키는 보안 저장소에 자동 저장하지 않음",
    "facts": "입력 근거 확인 중",
    "notices": "고시 조건 대조 중",
    "candidate": "등급분류 대상 여부 검토 중",
    "criteria": "검토항목 확인 중",
    "reviewer": "AI 에이전트 독립 검토 중",
    "summary": "표준 종합 의견 작성 중",
    "progress": "작업 진행 중",
    "batch_status": "일괄 처리·저장 상태 확인 중",
    "queued": "작업 준비 중",
    "cancel_retained": "취소 요청 반영. 완료된 결과 보존",
    "result_ready": "작업 결과 확인 가능",
    "documents_start": "저장된 검토 결과로 의견서 생성 중",
    "documents_done": "의견서 저장 완료",
    "documents_failed": "의견서 일부 또는 전체 저장 실패. 저장 위치와 서식 확인 후 다시 내보내기 필요",
    "batch_documents_failed": "의견서 저장 실패 과제 있음. 완료 결과에서 다시 내보내기 필요",
    "batch_warnings": "일부 입력 또는 저장 경고 있음. 일괄 처리 저장 현황 확인 필요",
    "batch_saved": "완료된 과제의 중간 저장·결과 엑셀·감사 기록 저장 완료",
    "cancel_requested": "취소 요청됨. 진행 중인 결과 보존 후 종료",
    "export_persisting": "문서 생성 상태를 원래 일괄 처리 기록에 저장 중",
    "export_persisted": "문서 생성 상태의 결과 기록 저장 완료",
    "export_partial": "문서 생성 결과 보존, 결과 기록 저장 일부 실패. 열린 엑셀과 저장 권한 확인 후 다시 내보내기 필요",
    "export_failed": "문서 생성 결과 보존, 결과 기록 저장 실패. 원래 일괄 처리 파일과 저장 권한 확인 필요",
    "single_saved": "단건 의견서 저장 완료. 일괄 처리 중간 저장 미사용",
    "single_failed": "단건 의견서 일부 또는 전체 저장 실패. 저장 위치와 서식 확인 후 다시 내보내기 필요",
    # Spec 4.5: the dedicated stop for a protected previous result (code io).
    "previous_result": batch_v16.PREVIOUS_RESULT_MESSAGE,
    # Spec 4.4/4.5: save_input_template's protected-path refusal (code validation).
    "template_protected": "검토에 쓰는 파일 보호를 위해 저장 중단. 다른 파일 이름 선택 필요",
    # Spec 4.3: screen-only notices, each at most once per job (_notice).
    "input_cleaned": "입력 글의 엑셀 줄바꿈 표시·줄 끝 공백·연속 빈 줄 정리 후 검토",
    "response_trimmed": "AI 응답 앞뒤 설명문 제외 후 JSON 결과만 사용",
}
_NOTICES = frozenset(("input_cleaned", "response_trimmed"))
_SEARCH_KEYS = frozenset(("query", "family", "offset", "limit"))
_QUERY_MAX = 200
_LIMIT_DEFAULT, _LIMIT_MAX = 50, 100
_ITEM_KEYS = ("clause_id", "family", "source_id", "notice_number", "code", "title", "field")
_MATCH_FIELDS = ("clause_id", "code", "title", "field", "text")
_WHITESPACE = re.compile(r"\s+")


class _BoundaryError(Exception):
    # message_key optionally names a fixed _EVENTS text shown instead of
    # _MESSAGES[code]; the code set itself never grows.
    def __init__(self, code, message_key=None):
        self.code = code
        self.message_key = message_key


def _failure(code, message_key=None):
    message = _EVENTS[message_key] if message_key is not None else _MESSAGES[code]
    return {"ok": False, "data": None, "error": {"code": code, "message": message}}


def _public(function):
    """Catch binding errors too: pywebview otherwise returns exception/traceback."""
    signature = inspect.signature(function)

    @wraps(function)
    def safe(self, *args, **kwargs):
        try:
            signature.bind(self, *args, **kwargs)
            data = function(self, *args, **kwargs)
            # Never hand shared mutable state to a caller/serialization thread.
            return {"ok": True, "data": deepcopy(data), "error": None}
        except _BoundaryError as error:
            return _failure(error.code, error.message_key)
        except CatalogueError:
            return _failure("catalogue")
        except (ValueError, TypeError, KeyError, OverflowError):
            return _failure("validation")
        except OSError:
            return _failure("io")
        except Exception:
            return _failure("runtime")
    return safe


def _require(condition, code="validation"):
    if not condition:
        raise _BoundaryError(code)


def _json_copy(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _request(value, required):
    _require(type(value) is dict and set(value) == set(required))
    return _json_copy(value)


def _text(value):
    _require(type(value) is str and bool(value.strip()))
    return value


def _client(opts, key):
    from llm_json_v16 import TolerantLLMClient
    return TolerantLLMClient(provider=opts.provider, api_key=key or None, model=opts.model,
                             base_url=opts.local_base_url or None)


def _policy_cleaned(raw, opts):
    """Spec 4.3: the common policy text changed beyond a plain strip()."""
    return str(raw.get("ministry_policy") or "").strip() != opts.ministry_policy


def _trimmed_count(client):
    count = getattr(client, "trimmed_responses", 0)
    return count if type(count) is int else 0


def _normalise(text):
    """Comparison-only form: NFKC, then every whitespace removed, then casefold."""
    return _WHITESPACE.sub("", unicodedata.normalize("NFKC", text)).casefold()


def _catalogue_require(condition):
    if not condition:
        raise CatalogueError("고시 기준본 구성 확인 불가")


def _notice_list(manifest):
    """Group sources by notice number in first-appearance order (spec 4.6)."""
    notices, bodies = {}, {}
    for source in manifest["sources"]:
        number = source["notice_number"]
        dates = (source["announcement_date"], source["effective_date"])
        if number not in notices:
            _catalogue_require(number in d.NOTICE_TITLES)
            notices[number] = dict(notice_number=number, title=d.NOTICE_TITLES[number],
                                   announcement_date=dates[0], effective_date=dates[1],
                                   families=[], source_ids=[], official_url=None)
            bodies[number] = []
        notice = notices[number]
        _catalogue_require((notice["announcement_date"], notice["effective_date"]) == dates)
        notice["families"].extend(family for family in source["families"] if family not in notice["families"])
        notice["source_ids"].append(source["source_id"])
        if source["source_id"].endswith(d.BODY_SOURCE_SUFFIX):
            bodies[number].append(source["official_url"])
    for number, notice in notices.items():
        # Exactly one body source per notice; zero or several is a catalogue error.
        _catalogue_require(len(bodies[number]) == 1)
        notice["official_url"] = bodies[number][0]
    return list(notices.values())


def _clause_index(manifest, clauses):
    """Immutable search rows and detail records in catalogue clause order."""
    sources = {source["source_id"]: source for source in manifest["sources"]}
    rows, details = [], {}
    for clause in clauses:
        source = sources.get(clause["source_id"])
        _catalogue_require(source is not None and clause["clause_id"] not in details)
        # Search items never carry the clause text (spec 4.6).
        item = {key: source["notice_number"] if key == "notice_number" else clause[key] for key in _ITEM_KEYS}
        haystacks = tuple(_normalise(clause[key]) for key in _MATCH_FIELDS)
        rows.append((item, clause["family"], haystacks))
        details[clause["clause_id"]] = dict(
            clause_id=clause["clause_id"], family=clause["family"], source_id=clause["source_id"],
            notice_number=source["notice_number"], notice_title=d.NOTICE_TITLES[source["notice_number"]],
            announcement_date=source["announcement_date"], effective_date=source["effective_date"],
            official_url=source["official_url"], code=clause["code"], title=clause["title"],
            field=clause["field"], source_anchor=clause["source_anchor"], text=clause["text"])
    return tuple(rows), details


@dataclass
class _BatchContext:
    report: dict
    digest: str


@dataclass
class _Job:
    job_id: str
    state: str = "queued"
    events: list = field(default_factory=list)
    result: dict | None = None
    result_digest: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    context: _BatchContext | None = None
    notices: set = field(default_factory=set)


class _CancellableClient:
    def __init__(self, client, opts, cancel, on_trimmed=None):
        self._client, self._cancel, self._on_trimmed = client, cancel, on_trimmed
        self.provider, self.model = opts.provider, opts.model

    def ask_json(self, *args, **kwargs):
        if self._cancel.is_set():
            raise RuntimeError("작업 취소")
        for key in ("provider", "model"):
            if hasattr(self._client, key) and getattr(self._client, key) != getattr(self, key):
                raise RuntimeError("선택 모델 불일치")
        before = _trimmed_count(self._client)
        value = self._client.ask_json(*args, **kwargs)
        for key in ("provider", "model"):
            if hasattr(self._client, key) and getattr(self._client, key) != getattr(self, key):
                raise RuntimeError("선택 모델 불일치")
        # Each client counts its own calls; the job-wide once rule is _notice's.
        if self._on_trimmed is not None and _trimmed_count(self._client) > before:
            self._on_trimmed()
        return value


class DesktopBridge:
    def __init__(self, *, key_manager=None, catalogue_loader=None, client_factory=None,
                 path_selector=None, classify=None, batch_runner=None,
                 regenerator=None, persister=None):
        self._keys = key_manager if key_manager is not None else KeyManager()
        self._catalogue_loader = catalogue_loader or load_catalogue
        self._client_factory = client_factory or _client
        self._path_selector = path_selector
        self._classify = classify or classification_v16.classify_task
        self._batch_runner = batch_runner or batch_v16.run_excel
        self._regenerator = regenerator or batch_v16.regenerate_documents
        self._persister = persister or batch_v16.persist_regenerated_documents
        self._lock = threading.RLock()
        self._credential_lock = threading.RLock()
        self._catalogue = None
        self._manifest = None
        self._notices = None
        self._clause_rows = ()
        self._clause_details = {}
        self._paths = {}
        self._review_paths = set()
        self._jobs = {}
        self._active = None

    def _idle(self):
        with self._lock:
            _require(self._active is None, "busy")

    def _get_catalogue(self):
        with self._lock:
            if self._catalogue is None:
                try:
                    catalogue = self._catalogue_loader()
                    manifest, by_id = _preflight(catalogue)
                    notices = _notice_list(manifest)
                    # by_id holds the validated plain clauses in catalogue order.
                    rows, details = _clause_index(manifest, list(by_id.values()))
                except Exception:
                    raise _BoundaryError("catalogue") from None
                self._notices, self._clause_rows, self._clause_details = notices, rows, details
                self._catalogue, self._manifest = catalogue, manifest
            return self._catalogue

    def _key(self, provider):
        if provider not in ("claude", "openai"):
            return "", ""
        with self._credential_lock:
            try:
                state = self._keys.resolve(provider)
            except Exception:
                raise _BoundaryError("credential") from None
            _require(state.has_key, "credential")
            warning = ""
            if state.source == "session" and (state.warning or state.stored is not True):
                warning = _EVENTS["key_session"]
            elif state.source == "environment":
                warning = _EVENTS["key_environment"]
            else:
                _require(not state.warning and state.stored is not None, "credential")
            return state.key, warning

    def _options(self, raw, *, task=None, batch=False):
        _require(type(raw) is dict and set(raw) <= {f.name for f in fields(d.RunOptions)})
        opts = classification_v16.normalize_options(_json_copy(raw),
            ministry_policy_context=task["부처 세부기준"] if task else "", allow_row_policy=batch)
        cat = self._get_catalogue()
        _require(not opts.catalogue_fingerprint or opts.catalogue_fingerprint == cat.fingerprint)
        return classification_v16.normalize_options(opts.to_dict() | {"catalogue_fingerprint": cat.fingerprint},
            ministry_policy_context=task["부처 세부기준"] if task else "", allow_row_policy=batch)

    def _path(self, token, purpose, nullable=False):
        if token is None and nullable:
            return None
        _text(token)
        with self._lock:
            entry = self._paths.get(token)
        _require(entry is not None and entry[0] == purpose)
        path = entry[1]
        if purpose == "input_excel":
            _require(path.is_file() and path.suffix.lower() == ".xlsx")
        elif purpose == "output_excel":
            _require(path.suffix.lower() == ".xlsx" and path.parent.is_dir() and not path.is_dir())
        elif purpose == "input_template":
            _require(path.suffix.lower() == ".xlsx" and path.parent.is_dir() and not path.is_dir())
        elif purpose == "output_directory":
            _require(not path.exists() or path.is_dir())
            _require(path.is_dir() or path.parent.is_dir())
        else:
            # An unknown purpose is never treated as a directory.
            _require(False)
        return path

    def _protected(self, path):
        """Spec 4.4: a path chosen for review this session, or a result workbook."""
        if any(Path(str(path) + suffix).exists() for suffix in _RESULT_SIBLINGS):
            return True
        key = os.path.normcase(str(path))
        with self._lock:
            reviewed = tuple(self._review_paths)
        for other in reviewed:
            if os.path.normcase(str(other)) == key:
                return True
            try:
                if path.exists() and other.exists() and os.path.samefile(path, other):
                    return True
            except OSError:
                # Undecidable identity of two existing files: keep them safe.
                return True
        return False

    def _event(self, job, stage, message, completed=0, total=0):
        with self._lock:
            # A delayed callback belongs only to its own nonterminal job.
            if self._jobs.get(job.job_id) is not job or job.state in _TERMINAL:
                return
            if stage == "reviewer":
                stage = "agents"
            if stage not in _STAGES:
                stage = "preflight"
            completed = completed if type(completed) is int and completed >= 0 else 0
            total = total if type(total) is int and total >= completed else completed
            job.events.append(dict(sequence=len(job.events) + 1, stage=stage,
                                   message=message, completed=completed, total=total))

    def _notice(self, job, name):
        """Spec 4.3: one screen-only notice per job, at the last event's progress.

        Batch workers call this concurrently, so the check, the record and the
        event share one section of the reentrant bridge lock (_event re-enters it).
        """
        if name not in _NOTICES:
            return
        with self._lock:
            if name in job.notices:
                return
            job.notices.add(name)
            last = job.events[-1] if job.events else dict(stage="preflight", completed=0, total=0)
            self._event(job, last["stage"], _EVENTS[name], last["completed"], last["total"])

    def _client_for(self, job, opts, key):
        return _CancellableClient(self._client_factory(opts, key), opts, job.cancel,
                                  lambda: self._notice(job, "response_trimmed"))

    def _progress(self, job, event):
        if type(event) is dict:
            stage = event.get("stage", "preflight")
            messages = {name: _EVENTS[name] for name in
                        ("facts", "notices", "candidate", "criteria", "reviewer", "summary")}
            self._event(job, stage, messages.get(stage, _EVENTS["progress"]),
                        event.get("completed", 0), event.get("total", 0))
        else:
            self._event(job, "persistence", _EVENTS["batch_status"])

    def _launch(self, worker, context=None):
        with self._lock:
            _require(self._active is None, "busy")
            job = _Job(uuid4().hex, context=context)
            self._jobs[job.job_id] = job
            self._active = job.job_id
            self._event(job, "preflight", _EVENTS["queued"])

        def run():
            terminal = "failed"
            try:
                with self._lock:
                    if job.cancel.is_set():
                        terminal = "cancelled"
                        return
                    job.state = "running"
                result = worker(job)
                with self._lock:
                    job.result = _json_copy(result)
                    job.result_digest = d.canonical_hash(job.result)
                    if job.cancel.is_set():
                        self._event(job, "summary", _EVENTS["cancel_retained"], 1, 1)
                    elif not job.events or job.events[-1]["stage"] not in ("documents", "persistence"):
                        self._event(job, "summary", _EVENTS["result_ready"], 1, 1)
                    terminal = "cancelled" if job.cancel.is_set() else "done"
            except Exception as error:
                if isinstance(error, batch_v16.PreviousResultError):
                    # Spec 4.5: code stays io; the event is the dedicated fixed
                    # guidance (never exception text) and the job ends failed.
                    code, message, terminal = "io", _EVENTS["previous_result"], "failed"
                else:
                    code = (error.code if isinstance(error, _BoundaryError) else
                            "catalogue" if isinstance(error, CatalogueError) else
                            "io" if isinstance(error, (OSError, batch_v16.BatchError)) else
                            "validation" if isinstance(error, (TypeError, ValueError)) else "runtime")
                    message = _MESSAGES[code]
                    terminal = "cancelled" if job.cancel.is_set() else "failed"
                self._event(job, "preflight", message)
            finally:
                with self._lock:
                    # A terminal snapshot and the next start become visible
                    # together, without a transient terminal-but-busy interval.
                    job.state = terminal
                    if self._active == job.job_id:
                        self._active = None
        thread = threading.Thread(target=run, name="v16-job-" + job.job_id[:8], daemon=True)
        try:
            thread.start()
        except Exception:
            with self._lock:
                job.state, self._active = "failed", None
            raise _BoundaryError("runtime") from None
        return {"job_id": job.job_id}

    def _documents(self, job, saved, directory):
        self._event(job, "documents", _EVENTS["documents_start"])
        result = self._regenerator(deepcopy(saved), directory)
        d.validate_result(result)
        _require({k: v for k, v in result.items() if k != "documents"} ==
                 {k: v for k, v in saved.items() if k != "documents"})
        complete = result["documents"]["status"] == "완료"
        self._event(job, "documents", _EVENTS["documents_done"] if complete else _EVENTS["documents_failed"], 1, 1)
        return result

    @_public
    def get_initial_state(self):
        cat = self._get_catalogue()
        with self._credential_lock:
            status = {}
            for provider in ("claude", "openai"):
                try:
                    state = self._keys.resolve(provider)
                except Exception:
                    raise _BoundaryError("credential") from None
                _require(not state.warning and type(state.stored) is bool, "credential")
                status[provider] = state.stored
        plain = cat.to_dict()
        families = []
        for family in d.FAMILIES:
            clauses = plain["by_family"][family]
            unsupported = sum(any(leaf["type"] == "unsupported" for leaf in d.condition_leaves(c["condition"]))
                              for c in clauses)
            families.append(dict(family=family, total_clauses=len(clauses),
                                 interpreted_clauses=len(clauses) - unsupported, unsupported_clauses=unsupported))
        criteria = [dict(id=c["id"], name=c["name"], security_refs=list(c["security_refs"]),
                         sensitive_refs=list(c["sensitive_refs"]), rubric=dict(c["rubric"])) for c in d.CRITERIA]
        # The guideline window shows display-only quotations; the AI prompt keeps
        # LEGAL_DEFINITIONS and CLASSIFICATION_PRINCIPLES unchanged.
        return dict(defaults=d.RunOptions().to_dict(), criteria=criteria, credential_status=status,
                    catalogue=dict(catalogue_id=self._manifest["catalogue_id"], fingerprint=cat.fingerprint,
                                   status="ready", sources=deepcopy(self._manifest["sources"]), families=families,
                                   notices=deepcopy(self._notices), notice_titles=dict(d.NOTICE_TITLES)),
                    guideline=d.guideline_display())

    @_public
    def select_path(self, purpose):
        self._idle()
        _require(type(purpose) is str and purpose in _PURPOSES)
        _require(self._path_selector is not None, "runtime")
        selected = self._path_selector(purpose)
        if selected is None or selected == "":
            return dict(cancelled=True, path_token=None, display_name=None)
        _require(isinstance(selected, (str, os.PathLike)))
        path = Path(selected).resolve()
        token = uuid4().hex
        with self._lock:
            self._paths[token] = (purpose, path)
        try:
            self._path(token, purpose)
        except Exception:
            with self._lock:
                self._paths.pop(token, None)
            raise
        if purpose in _REVIEW_PURPOSES:
            with self._lock:
                self._review_paths.add(path)
        return dict(cancelled=False, path_token=token, display_name=path.name or str(path.anchor))

    @_public
    def save_key(self, provider, key):
        self._idle()
        _require(type(provider) is str and provider in ("claude", "openai"))
        _text(key)
        with self._credential_lock:
            try:
                state = self._keys.apply(provider, key)
            except ValueError:
                raise _BoundaryError("validation") from None
            except Exception:
                raise _BoundaryError("credential") from None
            _require(state.stored is True and not state.warning, "credential")
        return dict(provider=provider, stored=True)

    @_public
    def delete_key(self, provider):
        self._idle()
        _require(type(provider) is str and provider in ("claude", "openai"))
        with self._credential_lock:
            try:
                state = self._keys.delete(provider)
            except Exception:
                raise _BoundaryError("credential") from None
            _require(state.stored is False, "credential")
        return dict(provider=provider, stored=False)

    @_public
    def start_single(self, request):
        self._idle()
        request = _request(request, ("task", "options", "output_dir_token"))
        task = request["task"]
        _require(type(task) is dict and set(task) <= set(d.TASK_COLUMNS + d.OPTIONAL_TASK_COLUMNS)
                 and all(type(value) is str for value in task.values()))
        snapshot = d.task_snapshot(task)
        opts = self._options(request["options"], task=snapshot)
        cleaned = (any(snapshot[column] != str(task.get(column, "")).strip() for column in snapshot)
                   or _policy_cleaned(request["options"], opts))
        directory = self._path(request["output_dir_token"], "output_directory", nullable=True)
        key, key_warning = self._key(opts.provider)
        cat = self._catalogue

        def work(job):
            if key_warning:
                self._event(job, "preflight", key_warning)
            if cleaned:
                self._notice(job, "input_cleaned")
            client = self._client_for(job, opts, key)
            result = self._classify(deepcopy(snapshot), opts, client,
                progress_callback=lambda event: self._progress(job, event), catalogue=cat)
            d.validate_result(result, opts, snapshot)
            if directory is not None and not job.cancel.is_set():
                result = self._documents(job, result, directory)
            return result
        return self._launch(work)

    @_public
    def start_batch(self, request):
        self._idle()
        request = _request(request, ("input_token", "output_token", "output_dir_token", "options", "workers", "resume", "make_forms"))
        _require(type(request["workers"]) is int and 1 <= request["workers"] <= 8)
        _require(type(request["resume"]) is bool and type(request["make_forms"]) is bool)
        source = self._path(request["input_token"], "input_excel")
        output = self._path(request["output_token"], "output_excel")
        _require(source != output and not (output.exists() and os.path.samefile(source, output)))
        directory = self._path(request["output_dir_token"], "output_directory", nullable=True)
        opts = self._options(request["options"], batch=True)
        policy_cleaned = _policy_cleaned(request["options"], opts)
        (key, key_warning), cat = self._key(opts.provider), self._catalogue

        def notice(job, name):
            # The runner reports only cleaned rows; response_trimmed is the client's.
            if name == "input_cleaned":
                self._notice(job, name)

        def work(job):
            if key_warning:
                self._event(job, "preflight", key_warning)
            if policy_cleaned:
                self._notice(job, "input_cleaned")
            report = self._batch_runner(source, output, opts,
                lambda: self._client_for(job, opts, key),
                resume=request["resume"], workers=request["workers"], make_forms=request["make_forms"],
                progress_cb=lambda event: self._progress(job, event),
                status_cb=lambda event: self._progress(job, event),
                cancel_event=job.cancel, catalogue=cat, output_dir=directory,
                notice_cb=lambda name: notice(job, name))
            for result in report["results"]:
                d.validate_result(result)
            with self._lock:
                job.context = _BatchContext(deepcopy(report), d.canonical_hash(report))
            if any(result["documents"]["status"] in ("일부실패", "실패") for result in report["results"]):
                self._event(job, "documents", _EVENTS["batch_documents_failed"])
            if report["warnings"] or report["audit_status"] != "완료":
                self._event(job, "persistence", _EVENTS["batch_warnings"])
            else:
                self._event(job, "persistence", _EVENTS["batch_saved"], 1, 1)
            count = report["counts"]
            return dict(results=deepcopy(report["results"]), counts=dict(total=report["task_count"],
                completed=count["완료"], failed=count["오류"],
                cancelled=max(0, report["task_count"] - len(report["results"])) if job.cancel.is_set() else 0,
                needs_review=count["검토필요"], excluded=count["후보제외"]),
                paths=dict(input_excel=report["input_path"], output_excel=report["output_path"],
                           checkpoint=report["checkpoint_path"], audit=report["audit_path"], output_dir=report["documents_dir"]),
                warnings=deepcopy(report["warnings"]), persistence=dict(status="완료" if report["audit_status"] == "완료" else "일부실패",
                    checkpoint="완료", workbook="완료", audit=report["audit_status"], warnings=deepcopy(report["warnings"])))
        return self._launch(work)

    @_public
    def get_job(self, job_id, after_sequence):
        _text(job_id)
        _require(type(after_sequence) is int and after_sequence >= 0)
        with self._lock:
            job = self._jobs.get(job_id)
            _require(job is not None, "not_found")
            return dict(job_id=job_id, state=job.state,
                        events=deepcopy([event for event in job.events if event["sequence"] > after_sequence]),
                        result=deepcopy(job.result) if job.state in _TERMINAL else None)

    @_public
    def cancel_job(self, job_id):
        _text(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            _require(job is not None, "not_found")
            if job.state not in _TERMINAL:
                job.cancel.set()
                job.state = "cancelling"
                self._event(job, "preflight", _EVENTS["cancel_requested"])
            return dict(job_id=job_id, state=job.state)

    @_public
    def start_export(self, request):
        self._idle()
        request = _request(request, ("job_id", "task_fingerprint", "output_dir_token"))
        _text(request["job_id"])
        fingerprint = _text(request["task_fingerprint"])
        directory = self._path(request["output_dir_token"], "output_directory")
        with self._lock:
            previous = self._jobs.get(request["job_id"])
            _require(previous is not None and previous.state in _TERMINAL and previous.result is not None, "not_found")
            _require(d.canonical_hash(previous.result) == previous.result_digest)
            context = previous.context
            if context is not None:
                _require(d.canonical_hash(context.report) == context.digest)
                matches = [result for result in context.report["results"] if result["task_fingerprint"] == fingerprint]
            else:
                matches = [previous.result] if previous.result.get("task_fingerprint") == fingerprint else []
            _require(len(matches) == 1, "not_found")
            saved = deepcopy(matches[0])
            d.validate_result(saved)

        def work(job):
            result = self._documents(job, saved, directory)
            if context is not None:
                self._event(job, "persistence", _EVENTS["export_persisting"])
                try:
                    update = self._persister(deepcopy(context.report), deepcopy(saved), deepcopy(result))
                    _require(update["result"] == result)
                    persistence = update["persistence"]
                    # Do not replace durable context with an unsaved document DTO.
                    if persistence["checkpoint"] == "완료":
                        report = _json_copy(update["report"])
                        with self._lock:
                            context.report, context.digest = report, d.canonical_hash(report)
                    complete = persistence["status"] == "완료"
                    self._event(job, "persistence", _EVENTS["export_persisted"] if complete else
                        _EVENTS["export_partial"], 1, 1)
                except Exception:
                    self._event(job, "persistence", _EVENTS["export_failed"], 1, 1)
            else:
                self._event(job, "persistence", _EVENTS["single_saved"]
                    if result["documents"]["status"] == "완료" else _EVENTS["single_failed"], 1, 1)
            return result
        return self._launch(work, context=context)

    # The two notice lookups are read-only: no key, file, path, job or model
    # access, so they stay available while a job is running (spec 4.6).
    @_public
    def search_notice_clauses(self, request):
        _require(type(request) is dict and set(request) <= _SEARCH_KEYS)
        query = request.get("query", "")
        family = request.get("family")
        offset = request.get("offset", 0)
        limit = request.get("limit", _LIMIT_DEFAULT)
        # The length limit applies to the raw string, before normalisation.
        _require(type(query) is str and len(query) <= _QUERY_MAX)
        _require(family is None or (type(family) is str and family in d.FAMILIES))
        _require(type(offset) is int and offset >= 0)
        _require(type(limit) is int and 1 <= limit <= _LIMIT_MAX)
        self._get_catalogue()
        needle = _normalise(query)
        matches = [item for item, clause_family, haystacks in self._clause_rows
                   if (family is None or clause_family == family)
                   and (not needle or any(needle in haystack for haystack in haystacks))]
        return dict(total=len(matches), offset=offset, limit=limit, items=matches[offset:offset + limit])

    @_public
    def get_notice_clause(self, clause_id):
        _require(type(clause_id) is str)
        self._get_catalogue()
        detail = self._clause_details.get(clause_id)
        _require(detail is not None, "not_found")
        return detail

    # Spec 4.4/4.5: runs at once, not as a job. The busy check, token and path
    # checks and the write share one lock section, so no batch can start in
    # between; the template is small, so the lock is held briefly.
    @_public
    def save_input_template(self, request):
        self._idle()
        request = _request(request, ("output_token",))
        with self._lock:
            _require(self._active is None, "busy")
            path = self._path(request["output_token"], "input_template")
            if self._protected(path):
                raise _BoundaryError("validation", "template_protected")
            try:
                batch_v16.make_template(path)
            except (batch_v16.BatchError, OSError):
                raise _BoundaryError("io") from None
        return dict(saved=True, display_name=path.name)
