"""The nine-operation v15 desktop boundary; no renderer supplied paths or DTOs.

Only explicitly exposed methods are an IPC API. All dependencies, credentials,
path capabilities, immutable run snapshots and retained results stay in Python.
The host MUST use js_api=None and window.expose, never expose this object.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, fields
from functools import wraps
import inspect
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

import batch_v15
import classification_v15
from credential_store import KeyManager
from notice_catalogue_v15 import CatalogueError, load_catalogue
from notice_review_v15 import _preflight
import v15_domain as d


PUBLIC_METHODS = ("get_initial_state", "select_path", "save_key", "delete_key",
                  "start_single", "start_batch", "get_job", "cancel_job", "start_export")
_TERMINAL = frozenset(("done", "cancelled", "failed"))
_STAGES = frozenset(("preflight", "facts", "notices", "candidate", "criteria",
                     "agents", "summary", "documents", "persistence"))
_PURPOSES = frozenset(("input_excel", "output_excel", "output_directory"))
_MESSAGES = {
    "validation": "입력 또는 실행 설정을 확인한 뒤 다시 시도해 주세요.",
    "catalogue": "고시 기준 파일을 확인할 수 없습니다. 앱을 다시 설치한 뒤 실행해 주세요.",
    "credential": "보안 저장소 작업에 실패했거나 키가 없습니다. 키를 다시 입력하거나 저장·삭제를 다시 시도해 주세요.",
    "busy": "진행 중인 작업이 있습니다. 완료되거나 취소된 뒤 다시 시작해 주세요.",
    "not_found": "선택한 작업 또는 결과를 찾을 수 없습니다. 완료된 결과를 다시 선택해 주세요.",
    "io": "파일을 처리하지 못했습니다. 저장 위치·권한과 열린 파일을 확인하고 다시 시도해 주세요.",
    "runtime": "작업을 완료하지 못했습니다. 입력과 설치 상태를 확인한 뒤 다시 실행해 주세요.",
}


class _BoundaryError(Exception):
    def __init__(self, code):
        self.code = code


def _failure(code):
    return {"ok": False, "data": None, "error": {"code": code, "message": _MESSAGES[code]}}


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
            return _failure(error.code)
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
    from llm_client_v14 import LLMClient
    return LLMClient(provider=opts.provider, api_key=key or None, model=opts.model,
                     base_url=opts.local_base_url or None)


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


class _CancellableClient:
    def __init__(self, client, opts, cancel):
        self._client, self._cancel = client, cancel
        self.provider, self.model = opts.provider, opts.model

    def ask_json(self, *args, **kwargs):
        if self._cancel.is_set():
            raise RuntimeError("작업 취소")
        for key in ("provider", "model"):
            if hasattr(self._client, key) and getattr(self._client, key) != getattr(self, key):
                raise RuntimeError("선택 모델 불일치")
        value = self._client.ask_json(*args, **kwargs)
        for key in ("provider", "model"):
            if hasattr(self._client, key) and getattr(self._client, key) != getattr(self, key):
                raise RuntimeError("선택 모델 불일치")
        return value


class DesktopBridge:
    def __init__(self, *, key_manager=None, catalogue_loader=None, client_factory=None,
                 path_selector=None, classify=None, batch_runner=None,
                 regenerator=None, persister=None):
        self._keys = key_manager if key_manager is not None else KeyManager()
        self._catalogue_loader = catalogue_loader or load_catalogue
        self._client_factory = client_factory or _client
        self._path_selector = path_selector
        self._classify = classify or classification_v15.classify_task
        self._batch_runner = batch_runner or batch_v15.run_excel
        self._regenerator = regenerator or batch_v15.regenerate_documents
        self._persister = persister or batch_v15.persist_regenerated_documents
        self._lock = threading.RLock()
        self._credential_lock = threading.RLock()
        self._catalogue = None
        self._manifest = None
        self._paths = {}
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
                    manifest, _ = _preflight(catalogue)
                except Exception:
                    raise _BoundaryError("catalogue") from None
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
                warning = "보안 저장소에 키를 저장하지 못했습니다. 이번 실행에서만 메모리의 입력 키를 사용하며 다음 실행에는 다시 입력해 주세요."
            elif state.source == "environment":
                warning = "환경변수의 API 키를 이번 실행에 사용합니다. 환경변수 키는 보안 저장소에 자동 저장하지 않습니다."
            else:
                _require(not state.warning and state.stored is not None, "credential")
            return state.key, warning

    def _options(self, raw, *, task=None, batch=False):
        _require(type(raw) is dict and set(raw) <= {f.name for f in fields(d.RunOptions)})
        opts = classification_v15.normalize_options(_json_copy(raw),
            ministry_policy_context=task["부처 세부기준"] if task else "", allow_row_policy=batch)
        cat = self._get_catalogue()
        _require(not opts.catalogue_fingerprint or opts.catalogue_fingerprint == cat.fingerprint)
        return classification_v15.normalize_options(opts.to_dict() | {"catalogue_fingerprint": cat.fingerprint},
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
        else:
            _require(not path.exists() or path.is_dir())
            _require(path.is_dir() or path.parent.is_dir())
        return path

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

    def _progress(self, job, event):
        if type(event) is dict:
            stage = event.get("stage", "preflight")
            messages = dict(facts="입력 근거를 확인하고 있습니다.", notices="고시 조건을 대조하고 있습니다.",
                candidate="후보 여부를 검토하고 있습니다.", criteria="공통 검토항목을 확인하고 있습니다.",
                reviewer="AI 에이전트가 독립 검토하고 있습니다.", summary="표준 종합 의견을 작성하고 있습니다.")
            self._event(job, stage, messages.get(stage, "작업을 진행하고 있습니다."),
                        event.get("completed", 0), event.get("total", 0))
        else:
            self._event(job, "persistence", "배치 처리·저장 상태를 확인하고 있습니다.")

    def _launch(self, worker, context=None):
        with self._lock:
            _require(self._active is None, "busy")
            job = _Job(uuid4().hex, context=context)
            self._jobs[job.job_id] = job
            self._active = job.job_id
            self._event(job, "preflight", "작업을 준비하고 있습니다.")

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
                        self._event(job, "summary", "취소 요청을 반영하고 완료된 결과를 보존했습니다.", 1, 1)
                    elif not job.events or job.events[-1]["stage"] not in ("documents", "persistence"):
                        self._event(job, "summary", "작업 결과를 확인할 수 있습니다.", 1, 1)
                    terminal = "cancelled" if job.cancel.is_set() else "done"
            except Exception as error:
                code = (error.code if isinstance(error, _BoundaryError) else
                        "catalogue" if isinstance(error, CatalogueError) else
                        "io" if isinstance(error, (OSError, batch_v15.BatchError)) else
                        "validation" if isinstance(error, (TypeError, ValueError)) else "runtime")
                self._event(job, "preflight", _MESSAGES[code])
                terminal = "cancelled" if job.cancel.is_set() else "failed"
            finally:
                with self._lock:
                    # A terminal snapshot and the next start become visible
                    # together, without a transient terminal-but-busy interval.
                    job.state = terminal
                    if self._active == job.job_id:
                        self._active = None
        thread = threading.Thread(target=run, name="v15-job-" + job.job_id[:8], daemon=True)
        try:
            thread.start()
        except Exception:
            with self._lock:
                job.state, self._active = "failed", None
            raise _BoundaryError("runtime") from None
        return {"job_id": job.job_id}

    def _documents(self, job, saved, directory):
        self._event(job, "documents", "저장된 검토 결과로 의견서를 생성하고 있습니다.")
        result = self._regenerator(deepcopy(saved), directory)
        d.validate_result(result)
        _require({k: v for k, v in result.items() if k != "documents"} ==
                 {k: v for k, v in saved.items() if k != "documents"})
        complete = result["documents"]["status"] == "완료"
        self._event(job, "documents", "의견서 저장을 완료했습니다." if complete else
                    "의견서 일부 또는 전체 저장에 실패했습니다. 저장 위치와 템플릿을 확인하고 다시 내보내세요.", 1, 1)
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
        return dict(defaults=d.RunOptions().to_dict(), criteria=criteria, credential_status=status,
                    catalogue=dict(catalogue_id=self._manifest["catalogue_id"], fingerprint=cat.fingerprint,
                                   status="ready", sources=deepcopy(self._manifest["sources"]), families=families),
                    guideline=dict(id=d.GUIDELINE_ID, definitions=dict(d.LEGAL_DEFINITIONS),
                                   principles=list(d.CLASSIFICATION_PRINCIPLES)))

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
        directory = self._path(request["output_dir_token"], "output_directory", nullable=True)
        key, key_warning = self._key(opts.provider)
        cat = self._catalogue

        def work(job):
            if key_warning:
                self._event(job, "preflight", key_warning)
            client = _CancellableClient(self._client_factory(opts, key), opts, job.cancel)
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
        (key, key_warning), cat = self._key(opts.provider), self._catalogue

        def work(job):
            if key_warning:
                self._event(job, "preflight", key_warning)
            report = self._batch_runner(source, output, opts,
                lambda: _CancellableClient(self._client_factory(opts, key), opts, job.cancel),
                resume=request["resume"], workers=request["workers"], make_forms=request["make_forms"],
                progress_cb=lambda event: self._progress(job, event),
                status_cb=lambda event: self._progress(job, event),
                cancel_event=job.cancel, catalogue=cat, output_dir=directory)
            for result in report["results"]:
                d.validate_result(result)
            with self._lock:
                job.context = _BatchContext(deepcopy(report), d.canonical_hash(report))
            if any(result["documents"]["status"] in ("일부실패", "실패") for result in report["results"]):
                self._event(job, "documents", "의견서 저장에 실패한 과제가 있습니다. 완료 결과에서 다시 내보내세요.")
            if report["warnings"] or report["audit_status"] != "완료":
                self._event(job, "persistence", "일부 입력 또는 저장 경고가 있습니다. 일괄 처리 저장 현황을 확인해 주세요.")
            else:
                self._event(job, "persistence", "완료된 과제의 중간 저장·결과 엑셀·감사 기록을 저장했습니다.", 1, 1)
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
                self._event(job, "preflight", "취소를 요청했습니다. 진행 중인 결과를 보존한 뒤 종료합니다.")
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
                self._event(job, "persistence", "문서 생성 상태를 원래 배치 기록에 저장하고 있습니다.")
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
                    self._event(job, "persistence", "문서 생성 상태의 결과 기록 저장을 완료했습니다." if complete else
                        "문서 생성 결과는 보존했지만 결과 기록 저장에 일부 실패했습니다. 열린 엑셀과 저장 권한을 확인하고 다시 내보내세요.", 1, 1)
                except Exception:
                    self._event(job, "persistence", "문서 생성 결과는 보존했지만 결과 기록 저장에 실패했습니다. 원래 배치 파일과 저장 권한을 확인해 주세요.", 1, 1)
            else:
                self._event(job, "persistence", "단건 의견서를 저장했습니다. 배치 중간 저장은 사용하지 않습니다."
                    if result["documents"]["status"] == "완료" else
                    "단건 의견서 일부 또는 전체 저장에 실패했습니다. 저장 위치와 템플릿을 확인하고 다시 내보내세요.", 1, 1)
            return result
        return self._launch(work, context=context)
