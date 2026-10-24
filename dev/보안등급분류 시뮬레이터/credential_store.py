"""Provider-specific API keys held in memory or Windows Credential Manager.

Only ``KeyState.public_info()`` is suitable for UI status/configuration output.
``key`` is deliberately excluded from repr but must never be serialized or logged.
The backend touches exactly the application's two named generic credentials.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import os
from typing import Mapping, Protocol


SERVICE_NAMESPACE = "ResearchSecurityGradeClassifier/api-key"
PROVIDER_ENV = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
MAX_CREDENTIAL_BYTES = 2560


def _provider(value: str) -> str:
    if value not in PROVIDER_ENV:
        raise ValueError("지원하지 않는 API 키 제공자입니다.")
    return value


def _clean_key(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("API 키는 문자열로 입력해 주세요.")
    value = value.strip()
    if any(character in value for character in ("*", "•", "●", "…", "\x00", "\r", "\n")):
        raise ValueError("마스킹 표시 대신 새 API 키 원문을 입력해 주세요.")
    if value.lower() in {"<saved>", "[saved]", "저장됨", "저장된 키"}:
        raise ValueError("마스킹 표시 대신 새 API 키 원문을 입력해 주세요.")
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeError:
        raise ValueError("API 키에 지원하지 않는 문자가 있습니다.") from None
    if encoded_length > MAX_CREDENTIAL_BYTES:
        raise ValueError("API 키의 저장 가능한 길이를 초과했습니다.")
    return value


class CredentialStoreError(RuntimeError):
    """An operation failed; callers should display a fixed message, not raw errors."""


class CredentialBackend(Protocol):
    def get(self, provider: str) -> str | None: ...
    def set(self, provider: str, key: str) -> None: ...
    def delete(self, provider: str) -> None: ...


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialBackend:
    """Generic, local-machine-persistent credentials for the current Windows user.

    No enumeration, plaintext fallback, or system settings dialog is used.
    API construction is lazy so tests and offline imports need no native store.
    """

    def __init__(self) -> None:
        self._api = None

    def _native(self):
        if self._api is None:
            if os.name != "nt":
                raise CredentialStoreError("Windows 보안 저장소를 사용할 수 없습니다.")
            try:
                api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
                api.CredReadW.argtypes = [
                    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                    ctypes.POINTER(ctypes.POINTER(_CredentialW)),
                ]
                api.CredReadW.restype = wintypes.BOOL
                api.CredWriteW.argtypes = [ctypes.POINTER(_CredentialW), wintypes.DWORD]
                api.CredWriteW.restype = wintypes.BOOL
                api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
                api.CredDeleteW.restype = wintypes.BOOL
                api.CredFree.argtypes = [ctypes.c_void_p]
                api.CredFree.restype = None
                self._api = api
            except Exception:
                raise CredentialStoreError("Windows 보안 저장소를 열 수 없습니다.") from None
        return self._api

    @staticmethod
    def target_name(provider: str) -> str:
        return f"{SERVICE_NAMESPACE}/{_provider(provider)}"

    @staticmethod
    def _failure(operation: str) -> CredentialStoreError:
        # Never include FormatError, backend exception text, or credential data.
        code = ctypes.get_last_error()
        return CredentialStoreError(f"보안 저장소 {operation} 실패 (Windows 오류 {code}).")

    def get(self, provider: str) -> str | None:
        target = self.target_name(provider)
        api = self._native()
        pointer = ctypes.POINTER(_CredentialW)()
        if not api.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == ERROR_NOT_FOUND:
                return None
            raise self._failure("읽기")
        try:
            credential = pointer.contents
            size = credential.CredentialBlobSize
            if size > MAX_CREDENTIAL_BYTES or (size and not credential.CredentialBlob):
                raise CredentialStoreError("저장된 API 키를 읽을 수 없습니다.")
            try:
                key = ctypes.string_at(credential.CredentialBlob, size).decode("utf-8")
                return _clean_key(key) or None
            except (UnicodeError, ValueError):
                raise CredentialStoreError("저장된 API 키를 읽을 수 없습니다.") from None
        finally:
            api.CredFree(pointer)

    def set(self, provider: str, key: str) -> None:
        target = self.target_name(provider)
        key = _clean_key(key)
        if not key:
            raise ValueError("빈 API 키는 저장할 수 없습니다.")
        api = self._native()
        raw = key.encode("utf-8")
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        credential = _CredentialW()
        credential.Type = CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(raw)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = provider
        try:
            if not api.CredWriteW(ctypes.byref(credential), 0):
                raise self._failure("저장")
        finally:
            ctypes.memset(blob, 0, len(raw))

    def delete(self, provider: str) -> None:
        target = self.target_name(provider)
        api = self._native()
        if not api.CredDeleteW(target, CRED_TYPE_GENERIC, 0):
            if ctypes.get_last_error() != ERROR_NOT_FOUND:
                raise self._failure("삭제")


@dataclass(frozen=True)
class KeyState:
    provider: str
    key: str = field(default="", repr=False)
    source: str = "missing"
    stored: bool | None = False
    warning: str = ""

    @property
    def has_key(self) -> bool:
        return bool(self.key)

    def public_info(self) -> dict:
        """Status safe for GUI/logs; has_key is not authentication validation."""
        return {
            "provider": self.provider, "source": self.source,
            "stored": self.stored, "has_key": self.has_key,
            "warning": self.warning,
        }


class KeyManager:
    """Resolve session > saved > environment; only explicit entry is persisted.

    ``apply`` is called by Apply/Start with the *new* entry widget value, never
    a placeholder. ``delete`` should also cause the GUI to clear its entry.
    Storage errors are returned as safe warnings while entered keys stay usable.
    """

    def __init__(self, backend: CredentialBackend | None = None,
                 environ: Mapping[str, str] | None = None) -> None:
        self._backend = backend if backend is not None else WindowsCredentialBackend()
        self._environ = environ if environ is not None else os.environ
        self._session: dict[str, str] = {}
        self._stored: dict[str, bool | None] = {}
        self._warnings: dict[str, str] = {}

    def _environment_key(self, provider: str) -> str:
        try:
            return _clean_key(self._environ.get(PROVIDER_ENV[provider], ""))
        except (ValueError, UnicodeError):
            return ""

    def resolve(self, provider: str) -> KeyState:
        provider = _provider(provider)
        if provider in self._session:
            return KeyState(provider, self._session[provider], "session",
                            self._stored.get(provider), self._warnings.get(provider, ""))
        warning = ""
        try:
            saved = self._backend.get(provider)
            saved = _clean_key(saved) if saved is not None else ""
            self._stored[provider] = bool(saved)
        except Exception:
            saved = ""
            self._stored[provider] = None
            warning = "보안 저장소에서 키를 불러오지 못했습니다. 새 키를 입력해 주세요."
        self._warnings[provider] = warning
        if saved:
            return KeyState(provider, saved, "saved", True, warning)
        environment = self._environment_key(provider)
        return KeyState(provider, environment, "environment" if environment else "missing",
                        self._stored[provider], warning)

    def apply(self, provider: str, entered_key: str | None = None) -> KeyState:
        provider = _provider(provider)
        entered = _clean_key(entered_key) if entered_key is not None else ""
        if not entered:
            return self.resolve(provider)
        self._session[provider] = entered
        try:
            self._backend.set(provider, entered)
            self._stored[provider] = True
            self._warnings[provider] = ""
        except Exception:
            self._stored[provider] = None
            self._warnings[provider] = (
                "보안 저장소에 키를 저장하지 못했습니다. 이번 실행에서만 사용합니다. "
                "다음 실행에는 다시 입력해 주세요."
            )
        return self.resolve(provider)

    def delete(self, provider: str) -> KeyState:
        provider = _provider(provider)
        self._session.pop(provider, None)
        try:
            self._backend.delete(provider)
            self._stored[provider] = False
            warning = ""
        except Exception:
            self._stored[provider] = None
            warning = "현재 입력은 지웠지만 보안 저장소의 키를 삭제하지 못했습니다. 삭제를 다시 시도해 주세요."
        environment = self._environment_key(provider)
        if environment:
            warning = (warning + " " if warning else "") + "환경변수에 별도 키가 있어 해당 키를 사용합니다."
        self._warnings[provider] = warning
        return KeyState(provider, environment, "environment" if environment else "missing",
                        self._stored[provider], warning)
