# -*- coding: utf-8 -*-
"""리포트 종류별 정의(연구보안 / 연구윤리).

원본 G-Cloud HTML 템플릿의 색상·구조를 그대로 재현하기 위한 설정값 모음.
템플릿 문구나 카테고리를 바꾸고 싶으면 이 파일과 prompts/*.txt 만 수정하면 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

# 국가 코드 → (표시명, 국기 이모지)
COUNTRY_NAMES: Dict[str, tuple] = {
    "US": ("미국 (United States)", "🇺🇸"),
    "UK": ("영국 (United Kingdom)", "🇬🇧"),
    "FR": ("프랑스 (France)", "🇫🇷"),
    "DE": ("독일 (Germany)", "🇩🇪"),
    "IT": ("이탈리아 (Italy)", "🇮🇹"),
    "CA": ("캐나다 (Canada)", "🇨🇦"),
    "JP": ("일본 (Japan)", "🇯🇵"),
    "EU": ("유럽연합 (European Union)", "🇪🇺"),
    "KR": ("대한민국 (South Korea)", "🇰🇷"),
    "INTL": ("주요 국제기관 (International)", "🌐"),
}

# 엑셀 '국가' 열에 기록할 짧은 표기
COUNTRY_SHORT: Dict[str, str] = {
    "US": "미국", "UK": "영국", "FR": "프랑스", "DE": "독일", "IT": "이탈리아",
    "CA": "캐나다", "JP": "일본", "EU": "EU", "KR": "한국", "INTL": "국제기관",
}


@dataclass
class ReportProfile:
    key: str                       # security / ethics
    name: str                      # 화면 표시용 이름
    title_kr: str
    title_en: str
    accent: str                    # 주 색상
    accent_soft: str               # 보조(연한) 색상
    link_color: str
    max_width: int
    font_family: str
    subject_format: str            # {report_month} 치환
    countries: List[str]           # 2장에 표시할 국가(한국 제외)
    has_intl_section: bool         # 국제기관 별도 장 여부
    has_status: bool               # '진행 상태' 필드 사용 여부
    categories: List[str]
    statuses: List[str] = field(default_factory=list)
    analysis_items: List[tuple] = field(default_factory=list)  # (키, 라벨)
    scope_rows: List[tuple] = field(default_factory=list)      # 리포트 정보표 (라벨, 값)
    default_recipients: List[str] = field(default_factory=list)
    footer_note: str = ""
    prompt_file: str = ""
    max_issue_per_country: int = 3


SECURITY = ReportProfile(
    key="security",
    name="글로벌 연구보안 월간 이슈 리포트",
    title_kr="글로벌 연구보안 월간 이슈 리포트",
    title_en="Global Research Security Monthly Issue Report",
    accent="#1f4e79",
    accent_soft="#eef3f8",
    link_color="#1f4e79",
    max_width=820,
    font_family="'맑은 고딕','Malgun Gothic',Arial,sans-serif",
    subject_format="[글로벌 연구보안 월간 이슈 리포트] {report_month}",
    countries=["US", "UK", "FR", "DE", "IT", "CA", "JP", "EU"],
    has_intl_section=False,
    has_status=False,
    categories=[
        "법률/규제 변화", "핵심기술 보호", "이중용도 기술", "연구기관 보안 강화",
        "국제 연구협력 가이드라인", "경제안보 관련 연구 규제", "국가 간 협력", "조사·보고서",
    ],
    analysis_items=[
        ("monthly_trend", "① 월간 트렌드"),
        ("country_comparison", "② 국가 간 비교"),
        ("korea_implication", "③ 한국에의 정책적 함의"),
        ("monitoring_points", "④ 향후 모니터링 포인트"),
    ],
    scope_rows=[("수집 범위", "G7(미국·영국·프랑스·독일·이탈리아·캐나다·일본), EU, 대한민국")],
    default_recipients=[],
    footer_note=(
        "본 리포트는 검증 가능한 1차 출처(정부·기관 공식 발표) 우선 원칙에 따라 작성되었으며, "
        "모든 이슈에 원문 링크를 포함합니다. KISTEP 글로벌 연구보안 모니터링 자동 발송."
    ),
    prompt_file="prompts/security_collection.txt",
    max_issue_per_country=3,
)

ETHICS = ReportProfile(
    key="ethics",
    name="글로벌 연구윤리·연구진실성 월간 이슈 리포트",
    title_kr="글로벌 연구윤리·연구진실성 월간 이슈 리포트",
    title_en="Global Research Ethics & Research Integrity Monthly Issue Report",
    accent="#6a3d9a",
    accent_soft="#f1ecf8",
    link_color="#0b63ce",
    max_width=900,
    font_family="'맑은 고딕','Malgun Gothic','Noto Sans KR',Arial,sans-serif",
    subject_format="글로벌 연구윤리·연구진실성 월간 이슈 리포트 – 수집 기간: {start_kr} ~ {end_kr}",
    countries=["US", "UK", "FR", "DE", "IT", "CA", "JP", "EU"],
    has_intl_section=True,
    has_status=True,
    categories=[
        "제도·규정 개정", "부정행위 조사·판정", "논문 철회·정정", "출판윤리",
        "논문공장·조직적 부정", "AI 연구윤리", "연구평가·RCR", "보고서·실태조사",
    ],
    statuses=[
        "조사 중", "최종 판정", "제재 확정", "철회 확정", "우려표명(EoC)",
        "정정", "정책 발표", "가이드라인 개정", "진행 중 동향",
    ],
    analysis_items=[
        ("monthly_trend", "① 월간 주요 트렌드"),
        ("country_comparison", "② 국가 간 비교"),
        ("korea_implication", "③ 한국에 대한 정책적 함의"),
        ("institution_implication", "④ 연구기관·대학에 대한 시사점"),
        ("monitoring_points", "⑤ 향후 모니터링 필요 사항"),
    ],
    scope_rows=[
        ("수집 범위",
         "G7 주요국, EU, 대한민국 및 주요 국제기관의 연구윤리·연구진실성 관련 정책, 제도, "
         "조사·제재, 출판윤리, 논문 철회, AI 연구윤리 및 책임 있는 연구수행 동향"),
        ("주요 참고 기관",
         "정부·공공기관, 연구지원기관, 대학·연구기관, 출판사·학회, COPE, WCRI, "
         "Retraction Watch, ICMJE, OECD GSF, UNESCO 등"),
        ("작성 기준",
         "검증 가능한 원문 URL이 확인된 공식 발표, 기관 자료, 학술 출판 공지 및 "
         "신뢰 가능한 언론 보도 기반"),
    ],
    default_recipients=[],
    footer_note="본 메일은 글로벌 연구윤리·연구진실성 월간 이슈 모니터링을 위해 자동 생성된 리포트입니다.",
    prompt_file="prompts/ethics_collection.txt",
    max_issue_per_country=3,
)

PROFILES: Dict[str, ReportProfile] = {"security": SECURITY, "ethics": ETHICS}


def get_profile(key: str) -> ReportProfile:
    if key not in PROFILES:
        raise KeyError(f"알 수 없는 리포트 종류: {key} (가능: {list(PROFILES)})")
    return PROFILES[key]
