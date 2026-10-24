# -*- coding: utf-8 -*-
"""검토 결과 자료구조."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class Level(str, Enum):
    """검토 판정 등급."""

    REJECT = "반려"       # 기준 미준수 → 등록 불가
    ACTION = "보완필요"    # 기타유의사항 기재 등 조건 충족 시 승인 가능
    REVIEW = "확인권장"    # 담당자가 직접 확인해야 하는 항목
    PASS = "적합"


ORDER = {Level.REJECT: 0, Level.ACTION: 1, Level.REVIEW: 2, Level.PASS: 3}


@dataclass
class Finding:
    """개별 검토 지적사항."""

    rule_id: str                                        # 기준 조항 (예: "10-바")
    item: str                                           # 항목 구분 (예: "CSV 기준준수")
    level: Level
    message: str                                        # 무엇이 문제인지
    fix: str = ""                                       # 어떻게 고치는지
    locations: List[str] = field(default_factory=list)  # 셀 위치 (예: "C4")
    samples: List[str] = field(default_factory=list)    # 실제 값 예시
    count: int = 0                                      # 발견 건수
    fix_key: str = ""                                   # 자동 수정 키(없으면 수정 불가)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["level"] = self.level.value
        return d


@dataclass
class ColumnInfo:
    index: int
    name: str
    empty_count: int = 0
    numeric_like: bool = False


@dataclass
class Result:
    """검토 1건의 결과.

    `domain` 이 "file" 이면 데이터 파일 검토, "api" 면 OPEN API 등록 검토다.
    지적사항 구조(Finding)는 두 쪽이 같고, 파일 쪽에만 있는 것(셀 좌표 지도·인코딩)과
    API 쪽에만 있는 것(오퍼레이션·파라메터 수)만 각자 칸을 따로 쓴다.
    """

    file_name: str
    file_path: str
    file_size: int = 0
    ext: str = ""
    encoding: str = ""
    delimiter: str = ""
    rows: int = 0
    cols: int = 0
    columns: List[ColumnInfo] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    suggested_base_date: Optional[str] = None
    source_kind: str = ""        # csv / xlsx / json / zip / other
    json_root: str = ""          # JSON 최상위 키(있는 경우)
    grid: Dict[str, str] = field(default_factory=dict)   # "A1" -> 등급 (미니맵용)
    error: str = ""
    domain: str = "file"         # file | api
    api: Dict[str, Any] = field(default_factory=dict)    # OPEN API 요약·명세

    def add(self, f: Finding) -> None:
        if f.count == 0:
            f.count = max(1, len(f.locations) or len(f.samples) or 1)
        self.findings.append(f)
        if self.domain != "file":
            # API 쪽 locations 는 셀 좌표가 아니라 '오퍼레이션 · 응답 · 항목명' 이라
            # 셀 지도에 넣지 않는다.
            return
        for loc in f.locations[:5000]:
            cur = self.grid.get(loc)
            if cur is None or ORDER[Level(f.level)] < ORDER[Level(cur)]:
                self.grid[loc] = f.level.value

    @property
    def verdict(self) -> Level:
        if self.error:
            return Level.REJECT
        if not self.findings:
            return Level.PASS
        return sorted(self.findings, key=lambda f: ORDER[f.level])[0].level

    def counts(self) -> Dict[str, int]:
        out = {lv.value: 0 for lv in Level if lv is not Level.PASS}
        for f in self.findings:
            if f.level is not Level.PASS:
                out[f.level.value] += 1
        return out

    def sorted_findings(self) -> List[Finding]:
        return sorted(self.findings, key=lambda f: (ORDER[f.level], f.rule_id))

    def to_dict(self) -> Dict[str, Any]:
        # 순환 참조 방지용 지연 임포트. 조항 번호가 두 영역에서 겹치므로
        # (파일 "10-라" ↔ API "10-나") 반드시 domain 으로 표를 갈라 봐야 한다.
        if self.domain == "api":
            from .api_fixer import API_FIXABLE as FIXABLE
            from .api_fixer import API_NOT_FIXABLE_REASON as NOT_FIXABLE_REASON
        else:
            from .fixer import FIXABLE, NOT_FIXABLE_REASON

        findings = []
        for f in self.sorted_findings():
            d = f.to_dict()
            spec = FIXABLE.get(f.fix_key) if f.fix_key else None
            d["fixable"] = spec is not None
            d["fix_label"] = spec[0] if spec else ""
            d["fix_tier"] = spec[1] if spec else ""
            d["fix_note"] = spec[3] if spec else ""
            d["manual_reason"] = NOT_FIXABLE_REASON.get(
                f.rule_id, "담당자가 직접 판단해 수정해야 합니다.")
            findings.append(d)

        return {
            "file_name": self.file_name,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "ext": self.ext,
            "encoding": self.encoding,
            "delimiter": self.delimiter,
            "rows": self.rows,
            "cols": self.cols,
            "columns": [asdict(c) for c in self.columns],
            "findings": findings,
            "suggested_base_date": self.suggested_base_date,
            "source_kind": self.source_kind,
            "verdict": self.verdict.value,
            "counts": self.counts(),
            "grid": self.grid,
            "error": self.error,
            "domain": self.domain,
            "api": self.api,
        }
