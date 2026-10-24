# -*- coding: utf-8 -*-
# security_grade_classifier_v12.py — 연구보안 등급분류 시뮬레이터(ver26.7)
# 연구개발과제 보안등급 분류 시뮬레이터
# 필요 패키지: pip install openai anthropic google-generativeai pandas openpyxl python-docx requests
#
# [v12 변경 사항]
#  - 위원용 심의서 '분류항목별 검토' 표: AI 사전검토 칸에 평균점수뿐 아니라 위원별 점수 함께 표기
# [v11 변경 사항 — 등급·점수 구간 정합성]
#  - 상향 편향 억제: 4단계 의결 프롬프트에 '점수 구간 등급 = 기본값' 원칙 명시.
#    구간보다 높은 등급 의견은 영 제45조 특정 호 '해당' 확인 + 근거 명시 시에만 예외 허용
#    (CONFIG grade_consistency.strict_band_default)
#  - 신뢰도 규칙: 최종등급이 점수 구간과 불일치하면 코드에서 신뢰도 '낮음' 강제,
#    불일치 방향·사유를 보고서/심의서/위원회 논의사항/감사로그에 표기
#    (CONFIG grade_consistency.force_low_confidence_on_mismatch)
# [v10 변경 사항]
#  - 최초 실행 시 화면 잘림 수정: 화면 해상도에 맞춘 창 크기 자동 조정·중앙 배치,
#    Windows 배율(125/150%) DPI 인식, grid 레이아웃으로 로그 영역만 신축(하단 상태바 항상 표시)
#  - 자가점검(연구자용) 기능 전체 삭제
#  - 대량 분류 '과제별 심의서(docx) 함께 생성' 기본값 체크로 변경
#  - 상태바 개선: 상태 점(●) + 대량 분류 시 'n/N · 경과 · 잔여 예상시간', 단건 분류 시 경과 시간 표시
#  - 내비게이션 재설계: 클릭 시 크기가 변하던 기본 탭 대신, 크기 고정형 언더라인 세그먼트 탭
# [v9 변경 사항 — 성능 정리 + UI 현대화]
#  - 성능: 별표 참조 프롬프트 lru_cache, 감사로그·체크포인트 파일 핸들 재사용(건별 open 제거),
#    입력 엑셀 이중 열기 제거, 엑셀 스타일 객체 캐시, 대량(2천건↑) 저장 시 셀 테두리 생략,
#    결과 로그창 자동 트리밍(대량 처리 시 GUI 지연 방지), 미사용 import 정리
#  - UI: 탭 기반 재구성(단건 분류 / 엑셀 대량 분류 / 설정), 카드형 레이아웃과 플랫 스타일,
#    상단 헤더바(제공자·모델 배지 — 로컬/외부 구분 색상), 진행 표시줄이 있는 상태바,
#    대량 분류를 ①양식 준비 → ②실행 → ③결과 확인 절차형 화면으로 정리
# [v8 변경 사항 — 최신 모델 호환성 전면 개편]
#  - Claude 어댑터를 최신 모델(claude-sonnet-5 등 thinking 지원 모델) 기준으로 재설계:
#    · assistant 프리필 제거(미지원 모델 대응) — JSON 강제는 프롬프트 지시 + 견고한 파서로 처리
#    · 응답 파싱을 위치(content[0]) 대신 블록 타입 기반으로 변경(ThinkingBlock 오류 해결)
#    · max_tokens 8000으로 상향(thinking 토큰이 한도 잠식하는 문제 방지, CONFIG에서 조정 가능)
#  - temperature/response_format 미지원 모델 자동 감지 후 제외(세션 내 기억)
#  - Gemini 빈 응답(안전차단) 폴백, OpenAI/LM Studio response_format 폴백 추가
#  - 인증·권한·모델명 오류는 재시도 없이 즉시 실패 처리(불필요한 4회 대기 제거)
# [v7 = ver26.7 변경 사항]
#  - 대량 처리(최대 10만 건급) 대응: 결과를 체크포인트(JSONL)에 건별 즉시 기록,
#    엑셀은 save_every(기본 50건)마다 원자적 교체 저장, 과제 단위 병렬 처리(max_workers 1~8)
#  - 결과표 개편: 연번 열 추가, 재분류조건·면책문구·상세(JSON) 열 제거(체크포인트·감사로그에 보존)
#  - 국가영향 지표 2번 항목명 변경: '기술자립·공급망 전략성' → '외교·경제안보 관련성'
#  - 우선 식별 선별대상 문구 변경: '세계최고 수준의 성능목표 및 기술사양을 지향하는 연구개발과제'
#  - 프로그램명: 연구보안 등급분류 시뮬레이터(ver26.7)
# [v6 변경 사항]
#  - 법령 고시 별표 임베딩: 국가첨단전략기술 지정 고시 별표, 국가핵심기술 지정 고시 별표,
#    전략물자 수출입고시 별표2(이중용도품목)를 내장하여 2단계 체크리스트·3단계 채점 시
#    관련 기술 목록을 LLM 프롬프트에 주입(관련성 후보 좁히기). 결과에 대조된 별표 기술명·출처 표기.
#    ※ 별표는 개정이 잦으므로 상단 REFERENCE_DATA(=SOURCES/…목록)만 수정하면 갱신됨.
# [v5] 절차 개선(항목 선택→선택 항목만 채점→평균 등급), 위원 1명/3명 구성, 결과 보고서화
# [v4] Ollama(로컬 LLM) 지원  [v3] 위원용 심의서·자가점검 양식 생성
#
# ★ 중요 안내 ★
# 1) 본 도구의 결과는 '보안등급분류위원회 심의를 위한 참고자료'이며,
#    최종 보안등급은 위원회 심의·의결 및 중앙행정기관 확정 절차를 따라야 합니다.
# 2) 등급 구간(보안≥4.5, 민감≥3.5)은 가이드라인(안)의 '예시' 기준으로 미확정 사항입니다.
# 3) 보안·민감과제 후보의 과제정보를 외부 상용 LLM API로 전송하는 행위 자체가
#    정보 유출 리스크가 될 수 있습니다. 실제 운영 시 내부망 모델 사용,
#    입력정보 최소화, API 제공사의 데이터 미학습 계약 여부 등을 반드시 확인하세요.
# 4) 내장된 법령 고시 별표는 특정 시점 기준의 요약본입니다. 개정 여부·정확한 사양은
#    반드시 원문(국가법령정보센터, 전략물자관리시스템 등)과 대조하세요.

import os
import sys
import json
import time
import datetime
import threading
import traceback
import subprocess
import functools
import concurrent.futures

import pandas as pd


def resource_path(rel_path):
    """스크립트로 실행 시/PyInstaller onefile exe로 실행 시 모두 동작하는 리소스 경로 반환."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel_path)

# =========================================================
# 1. 설정
# =========================================================
CONFIG = {
    # "openai" | "claude" | "gemini" 중 선택
    "provider": "claude",

    "openai": {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "model": "gpt-5-mini",
    },
    "claude": {
        "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "model": "claude-sonnet-5",
        # 최신 모델은 내부 추론(thinking) 토큰이 한도를 잠식할 수 있어 여유 있게 설정
        "max_tokens": 8000,
    },
    "gemini": {
        "api_key": os.getenv("GEMINI_API_KEY", ""),
        "model": "gemini-3.5-flash",
    },
    # 로컬 LLM (Ollama) — 과제정보가 외부로 나가지 않는 폐쇄망/내부망 운영에 적합
    # 사전 준비: ollama serve 실행 및 모델 다운로드 (예: ollama pull qwen2.5:14b)
    "ollama": {
        "api_key": "",  # 불필요 (로컬 서버)
        "model": os.getenv("OLLAMA_MODEL", "gemma4"),
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "timeout": 600,  # 로컬 모델은 응답이 느릴 수 있어 여유 있게 설정
    },
    # 로컬 LLM (LM Studio) — LM Studio의 OpenAI 호환 로컬 서버 사용
    # 사전 준비: LM Studio 앱에서 모델 다운로드 후 '로컬 서버 시작'(기본 포트 1234)
    "lmstudio": {
        "api_key": "",  # 불필요 (로컬 서버)
        "model": os.getenv("LMSTUDIO_MODEL", "gemma4"),
        "base_url": os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234"),
        "timeout": 600,
    },

    # 위원 구성: 1 또는 3 (각 위원은 아래 전문가 관점에서 '독립 호출'로 평가)
    "reviewer_panel": 3,
    "panel_personas": {
        1: ["기술분야 전문가"],
        3: ["기술분야 전문가", "연구보안·수출통제 전문가", "기술사업화 전문가"],
    },

    # 위원 평가 시 temperature (관점 다양성 확보용)
    "reviewer_temperature": 0.7,
    # 일반 판단(1,2,4단계) temperature
    "temperature": 0.2,

    # 등급 구간(가이드라인(안) 판정 가이드 기준)
    # 평균 4.5 이상: 보안과제 / 3.5 이상~4.5 미만: 민감과제 / 3.5 미만: 일반과제 우선 검토
    "thresholds": {"security": 4.5, "sensitive": 3.5},

    # ── 등급-점수 구간 정합성 관리 ──
    "grade_consistency": {
        # 4단계 프롬프트에서 점수 구간 등급을 '기본값'으로 삼도록 지시(상향 편향 억제).
        # 구간과 다른 등급(특히 상향)은 영 제45조 각 호 해당이 명확할 때만 예외 허용
        "strict_band_default": True,
        # 최종등급이 점수 구간과 불일치하면 신뢰도를 '낮음'으로 강제(코드에서 결정적 적용)
        "force_low_confidence_on_mismatch": True,
    },

    # API 재시도 설정
    "max_retries": 3,
    "retry_base_wait": 2.0,   # 지수 백오프: 2, 4, 8초...

    # 감사로그(판단근거 기록·관리) 파일 경로. None이면 기록 안 함.
    "audit_log": "분류_감사로그.jsonl",

    # 대량 분류 시 건별 대기(초) — 동시 처리 수가 1일 때만 적용
    "batch_sleep": 1.0,

    # ── 대량 처리(수만~10만 건) 설정 ──
    # 동시 처리 수(1~8): API rate limit과 로컬 모델 성능에 맞춰 조정
    "max_workers": 1,
    # 엑셀 파일 주기 저장 간격(건) — 건별 전체 재저장은 대량 처리에서 병목이므로
    # 결과는 체크포인트(JSONL)에 건별 즉시 기록하고, 엑셀은 이 간격마다 갱신
    "save_every": 50,
}

# 제공자별 모델 선택 목록(참고용) — GUI 콤보박스는 편집 가능하므로 목록에 없는 모델명도 직접 입력 가능
OPENAI_MODELS = [
    "gpt-5-mini",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
]
CLAUDE_MODELS = [
    "claude-sonnet-5",
    "claude-opus-4.8",
    "claude-haiku-4-5-20251001",
    "claude-fable-5",
]
GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.5-pro-preview",
    "gemini-3.5-pro",
    "gemini-3.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]
OLLAMA_MODELS = [
    "gemma4",
    "gemma4:12b",
    "gemma4:26b",
    "llama3.1:70b",
    "gemma2:9b",
    "mistral:7b",
    "deepseek-r1:14b",
]
LMSTUDIO_MODELS = [
    "qwen2.5-14b-instruct",
    "llama-3.1-8b-instruct",
    "llama-3.2-3b-instruct",
    "gemma-4-12b-it",
    "mistral-7b-instruct-v0.3",
    "deepseek-r1-distill-qwen-14b",
]
MODEL_OPTIONS = {
    "openai": OPENAI_MODELS,
    "claude": CLAUDE_MODELS,
    "gemini": GEMINI_MODELS,
    "ollama": OLLAMA_MODELS,     # 실제 사용 가능 모델은 'ollama pull'로 설치한 목록에 따라 다름 — 직접 입력 가능
    "lmstudio": LMSTUDIO_MODELS,  # 실제 사용 가능 모델은 LM Studio에 다운로드한 목록에 따라 다름 — 직접 입력 가능
}

# 위원별 평가 헌장 — 각 위원의 관점 차이를 프롬프트로 명시하여
# temperature(무작위성)에 의존하지 않고 '근거 있는 이견'이 만들어지도록 함.
# (temperature 미지원 최신 모델에서도 위원 간 점수·근거가 유의미하게 달라짐)
REVIEWER_PROFILES = {
    "기술분야 전문가": {
        "관점": ("해당 기술의 실체를 기준으로 판단하는 기술 심사 전문가. "
                "기술 성숙도(TRL), 세계 수준과의 격차, 해외에서의 재현·대체 난이도, "
                "원천성·희소성을 중심으로 검토한다."),
        "성향": ("기술 실체 우선 원칙 — 과제계획서의 목표 서술만으로 과대평가하지 않는다. "
                "재현 난이도·기술 격차의 구체적 근거가 없으면 한 단계 낮게 평가하고, "
                "반대로 세계 최고 수준·독자 원천기술의 근거가 명확하면 주저 없이 높게 평가한다."),
        "착안": ("이 기술이 해외 선도그룹에서 1~2년 내 재현 가능한가? / "
                "유사·대체 기술이 존재하는가? / 성능목표가 현 세계 수준 대비 어느 위치인가?"),
    },
    "연구보안·수출통제 전문가": {
        "관점": ("유출 경로와 악용 가능성을 기준으로 판단하는 연구보안·수출통제 전문가. "
                "이중용도(민군 전용) 가능성, 전략물자·국가핵심기술 등 통제체계 연계성, "
                "국제공동연구·외국인 참여 등 유출 채널, 외교·경제안보 파장을 중심으로 검토한다."),
        "성향": ("사전예방 원칙 — 군사 전용 가능성이나 수출통제 해당성이 '불확실'한 경우에는 "
                "위험을 낮춰 잡지 않고 한 단계 높게 평가한다. 다만 통제 근거가 전혀 연결되지 "
                "않는 항목까지 관성적으로 높게 주지는 않는다."),
        "착안": ("결과물이 무기체계·감시체계에 결합될 수 있는가? / 별표(전략물자·국가핵심기술)와 "
                "직·간접 연계가 있는가? / 유출 시 상대국이 얻는 전략적 이득은 무엇인가?"),
    },
    "기술사업화 전문가": {
        "관점": ("시장과 산업 생태계 관점에서 판단하는 기술사업화 전문가. "
                "시장 규모·성장성, 상용화까지의 거리, 특허·표준 선점 가능성, "
                "국가 주력산업·공급망과의 연계를 중심으로 검토한다."),
        "성향": ("시장 실증 원칙 — 수요처·시장 근거가 구체적이면 산업·경제 파급력을 적극적으로 "
                "높게 평가하고, 상용화가 멀거나 대체재가 많으면 기술적 화려함과 무관하게 낮게 "
                "평가한다. 군사·안보 항목은 시장·산업 관점에서 본 파급 경로로 판단한다."),
        "착안": ("유출 시 어느 기업·산업이 실질 타격을 받는가? / 시장 선점 효과가 몇 년 유지되는가? / "
                "특허·표준으로 보호 가능한가, 유출되면 끝인가?"),
    },
}
_DEFAULT_PROFILE = {"관점": "보안등급분류위원회 위원", "성향": "균형 잡힌 종합 판단", "착안": ""}

# 분류항목 7개 (부처 재량 항목 제외)
# — ①법적 기준 체크리스트 검토 대상이자 ②선택 시 국가영향 수준 채점 대상
IMPACT_ITEMS = [
    "군사·안보 활용성",
    "외교·경제안보 관련성",
    "국가핵심기술",
    "전략물자",
    "기술 수준 및 희소성",
    "산업·경제적 파급력",
    "연구수행 관리 필요성",
]

DISCLAIMER = ("- 본 결과는 보안등급 분류위원회 심의를 위한 참고자료이며, "
              "최종 보안등급은 중앙행정기관에서 확정합니다.")

# 위원용 심의서(붙임2 평가양식) 분류항목 8개: (항목명, 분류기준 상세, 근거 법령)
# ※ 8번 항목은 국가영향 점수(IMPACT_ITEMS 7개) 산출 대상이 아닌 정성 검토 항목
FORM_ITEMS = [
    ("1. 군사·안보 활용성",
     "「방위사업법」 제3조제1호에 따른 방위력개선사업과 직접 관련된 과제 / "
     "기술의 활용 방식·적용 맥락상 민간 목적 외 국가안보·방위 분야 활용 가능성",
     "[보안] 영제45조1항1호 / [민감] 영제45조2항1호"),
    ("2. 외교·경제안보 관련성",
     "외국 기술이전 거부로 국산화 추진 중인 기술 관련 / "
     "공급망 안정성·필수자원 확보·국제통상 대응 등 국가 차원의 전략적 관리 필요성",
     "[보안] 영제45조1항2호다 또는 1항3호 / [민감] 영제45조2항1호"),
    ("3. 국가핵심기술",
     "「산업기술의 유출방지 및 보호에 관한 법률」상 국가핵심기술 관련 "
     "(「국가첨단전략산업법」상 국가첨단전략기술 포함) / "
     "향후 국가핵심기술·첨단전략기술로 발전할 가능성",
     "[보안] 영제45조1항2호다 또는 1항3호 / [민감] 영제45조2항1호"),
    ("4. 전략물자",
     "「대외무역법」상 수출허가 등 제한이 필요한 기술 관련 과제",
     "[보안] 영제45조1항2호다 또는 1항3호 / [민감] 영제45조2항1호"),
    ("5. 기술 수준 및 희소성",
     "세계적 수준의 기술경쟁력 확보 가능성이 높거나 "
     "해외에서 독자적으로 재현·대체하기 어려운 희소 원천기술 포함",
     "[보안] 영제45조1항2호나 또는 1항3호 / [민감] 영제45조2항2호"),
    ("6. 산업·경제적 파급력",
     "미래 신산업·국가 주력산업과 밀접 연계되어 산업 생태계·시장 형성에 중대한 영향 / "
     "기술자립·글로벌 특허·국제표준 선점 기여 가능성",
     "[보안] 영제45조1항2호나 또는 1항3호 / [민감] 영제45조2항2호"),
    ("7. 연구수행 관리 필요성",
     "연구수행 과정 또는 연구성과의 활용·이전 과정에서 추가적인 관리가 필요하다고 인정되는 경우 "
     "(국제공동연구, 데이터·시료·장비 관리 등)",
     "[보안] 영제45조1항3호 / [민감] 영제45조2항3호"),
    ("8. (기타) 부처 정책상 관리 필요성",
     "중앙행정기관의 세부기준에 따라 보호 또는 추가관리가 필요하다고 인정되는 과제",
     "[보안] 영제45조1항3호 / [민감] 영제45조2항3호"),
]

# =========================================================
# 1-B. 법령 고시 별표 참조 데이터 (임베딩)
#   - 국가첨단전략기술 / 국가핵심기술 / 전략물자 이중용도품목
#   - LLM 프롬프트에 주입하여 관련성 후보를 좁히는 용도. 최종 판단은 원문·전문기관.
# =========================================================
SOURCES = {
    "national_advanced_strategic_tech": {
        "title": "국가첨단전략기술 지정 등에 관한 고시 [별표]",
        "authority": "산업통상자원부",
        "notice_no": "제2025-071호",
        "effective": "2025-05-12",
        "scope": "4개 분야 19개 기술 (반도체8·디스플레이4·이차전지3·바이오2·로봇1·방위산업1)",
        "url": "https://www.motie.go.kr/kor/article/ATCL0c554f816/64810/view",
    },
    "national_core_tech": {
        "title": "국가핵심기술 지정 등에 관한 고시 [별표]",
        "authority": "산업통상자원부",
        "notice_no": "제2025-002호 계열(2025.10.2. 개정 시행)",
        "effective": "2025-10-02",
        "scope": "13개 분야 79개 기술",
        "url": "https://www.law.go.kr/행정규칙/국가핵심기술지정등에관한고시",
    },
    "strategic_items_dual_use": {
        "title": "전략물자 수출입고시 [별표2] 이중용도품목",
        "authority": "산업통상자원부",
        "notice_no": "전략물자 수출입고시(수시 개정)",
        "effective": "상시(개정 반영 필요)",
        "scope": "10개 부(제1부~제10부), 국제수출통제체제(WA·NSG·MTCR·AG) 기반",
        "url": "https://www.law.go.kr/행정규칙/전략물자 수출입고시",
        "official_lookup": "전략물자관리시스템 www.yestrade.go.kr (자가판정/전문판정)",
    },
}

# =========================================================
# 1) 국가첨단전략기술 (분야별 지정 기술 목록)
# =========================================================
NATIONAL_ADVANCED_STRATEGIC_TECH = {
    "반도체": [
        "16나노 이하급 D램 설계·공정·소자기술 및 3차원 적층형성 기술",
        "16나노 이하급 D램 적층조립기술 및 검사기술",
        "128단 이상 적층 3D 낸드플래시 설계·공정·소자 기술",
        "128단 이상 적층 3D 낸드플래시 적층조립기술 및 검사기술",
        "픽셀 0.8㎛ 이하 이미지센서 설계·공정·소자 기술",
        "디스플레이 패널 구동용 OLED DDI(Display Driver IC) 설계 기술",
        "14나노급 이하 파운드리 공정·소자기술 및 3차원 적층형성 기술",
        "시스템반도체용 첨단 패키지(FO-WLP, FO-PLP, FO-PoP, SiP 등) 공정·조립·검사기술",
    ],
    "디스플레이": [
        "능동유기발광다이오드(AMOLED) 패널 설계·공정·제조 기술",
        "초고해상도(초고정세) 디스플레이 관련 기술",
        "플렉시블·폴더블 등 차세대 디스플레이 관련 기술",
        "대면적·고효율 디스플레이 관련 핵심 기술",
    ],
    "이차전지": [
        "고에너지밀도 리튬이차전지(양극·음극·전해질 등) 설계·공정·제조 기술",
        "차세대 이차전지(전고체 전지 등) 관련 핵심 기술",
        "이차전지 소재·부품 및 셀·모듈·팩 관련 핵심 기술",
    ],
    "바이오": [
        "바이오의약품 개발·제조 적용 동물세포 배양·정제 기술(다회용 바이오리액터 1만 리터 이상)",
        "고품질 오가노이드 재생치료제 개발·제조 적용 분화 및 배양 기술",
    ],
    "로봇": [
        "최고 초속 3.3m 이상 이동·전신조작으로 20kg 이상 중량물 운반 가능한 휴머노이드 로봇 구동기 및 프레임 설계·제조·공정 기술",
    ],
    "방위산업": [
        "방위산업 분야 국가첨단전략기술 (2025.5월 신규 지정)",
    ],
}

# =========================================================
# 2) 국가핵심기술 (13개 분야, 분야별 대표 기술 요약)
#    ※ 개별 기술의 정확한 사양은 원문 별표 대조 필요
# =========================================================
NATIONAL_CORE_TECH = {
    "반도체": [
        "30나노 이하급 D램 설계·공정·소자기술 및 3차원 적층형성 기술",
        "D램 적층조립기술 및 검사기술",
        "64단 이상 적층 3D 낸드플래시 설계·공정·소자 기술",
        "낸드플래시 적층조립기술 및 검사기술",
        "30나노급 이하 파운드리 공정·소자기술 및 3차원 적층형성 기술",
        "시스템반도체용 첨단 패키지 공정·조립·검사 기술",
        "LTE/LTE-adv/5G/5G-adv Baseband Modem 설계 기술",
    ],
    "디스플레이": [
        "AMOLED 패널 설계·공정·제조 기술",
        "TFT-LCD 관련 핵심 기술",
        "차세대 디스플레이(플렉시블 등) 관련 기술",
    ],
    "전기전자": [
        "21uF/mm³ 이상 초고용량밀도 MLCC 설계·공정 및 제조 기술",
        "고성능 수동소자 관련 핵심 기술",
    ],
    "자동차·철도": [
        "자율주행자동차 핵심 부품·시스템 설계 및 제조 기술(상용화 3년 이내 카메라·레이더·라이더·정밀측위모듈 및 제어시스템에 한함)",
        "친환경차(수소·전기차) 핵심 부품·시스템 기술",
        "고속철도차량 차체 설계·해석·제조 기술",
        "자동차 공조시스템 관련 기술",
    ],
    "철강(금속)": [
        "항복강도 700MPa급 이상 철근 및 인장강도 650MPa급 이상 형강 제조 기술(저탄소강, 전기로 방식)",
        "고망간(10wt.% Mn 이상) 함유 특수강 제조 기술",
        "합금원소 총량 4wt.% 이하 기가급 고강도 철강판재 제조 기술",
        "아연제련공정에서의 저온 저압 헤마타이트 공정 기술",
    ],
    "조선": [
        "LNG선·LNG운반선 화물창(멤브레인 등) 설계·제조 기술",
        "고부가가치 선박 설계·건조 관련 핵심 기술",
    ],
    "원자력": [
        "원자로 설계·핵심 계통 기술",
        "발전용 가스터빈 수소연소 기술",
    ],
    "정보통신": [
        "5G/차세대 이동통신 핵심 기술",
        "광통신·네트워크 장비 관련 핵심 기술",
    ],
    "우주": [
        "1m 이하 해상도의 SAR 탑재체 제작 및 신호처리 기술",
        "위성·발사체 핵심 기술",
    ],
    "생명공학": [
        "바이오의약품(항체·백신 등) 개발·제조 핵심 기술",
        "유전자·세포치료제 관련 핵심 기술",
    ],
    "기계": [
        "고정밀 공작기계·제조장비 핵심 기술",
        "첨단 제조공정 관련 핵심 기술",
    ],
    "로봇": [
        "지능형 로봇 핵심 부품·구동·제어 기술",
    ],
    "수소": [
        "건설·산업용 연료전지 기술",
        "수소 생산·저장·활용 관련 핵심 기술",
    ],
}

# =========================================================
# 3) 전략물자 이중용도품목 (별표2, 10개 부 카테고리)
#    ※ 개별 통제번호(예: 1A002) 판정은 원문·전문판정 필요
# =========================================================
STRATEGIC_ITEMS_DUAL_USE = {
    "제1부": {
        "name": "특수재료 및 관련 장비",
        "examples": "복합재료·적층재료, 불소계 화합물, 특수 고분자물질, 유전적으로 변형된 미생물 등",
    },
    "제2부": {
        "name": "재료가공",
        "examples": "베어링, 수치제어 공작기계(다축), 로봇, 측정·검사 장비 등",
    },
    "제3부": {
        "name": "전자",
        "examples": "고성능 집적회로, 내방사선 소자, 고주파 소자, 특수 전자부품 등",
    },
    "제4부": {
        "name": "컴퓨터",
        "examples": "고성능 컴퓨터, 특수 연산장치 등",
    },
    "제5부": {
        "name": "통신 및 정보보안",
        "examples": "특수 통신장비, 암호화 장비·소프트웨어(정보보안) 등",
    },
    "제6부": {
        "name": "센서 및 레이저",
        "examples": "고성능 센서, 레이저, 광학장비, 수중음향 장비 등",
    },
    "제7부": {
        "name": "항법 및 항공전자",
        "examples": "관성항법장치(INS), 자이로스코프, 가속도계 등",
    },
    "제8부": {
        "name": "해양",
        "examples": "잠수정, 수중 추진·항법 장비, 해양 관련 특수 장비 등",
    },
    "제9부": {
        "name": "항공우주 및 추진",
        "examples": "항공기 엔진, 가스터빈, 로켓 추진체, UAV, 관련 부품 등",
    },
    "제10부": {
        "name": "원자력전용품목 (NSG Part 1)",
        "examples": "핵물질, 원자로·재처리·농축 설비 및 장비 등 (한국원자력통제기술원 판정)",
    },
}


def build_reference_prompt(selected_items=None):
    """선택된 분류항목과 관련된 별표 참조 데이터를 프롬프트용 텍스트로 생성.
    내용이 정적이므로 캐싱 — 대량 처리(수만 건) 시 매 호출 문자열 재조립을 제거."""
    key = tuple(selected_items) if selected_items else None
    return _build_reference_prompt_cached(key)


@functools.lru_cache(maxsize=64)
def _build_reference_prompt_cached(selected_key):
    selected_items = list(selected_key) if selected_key else None
    want_core = want_adv = want_dual = True
    if selected_items is not None:
        names = " ".join(selected_items)
        want_core = ("국가핵심기술" in names) or ("기술 수준" in names) or ("산업" in names)
        want_adv = ("국가핵심기술" in names) or ("경제안보" in names) or ("산업" in names)
        want_dual = ("전략물자" in names) or ("군사" in names) or ("경제안보" in names) or ("외교" in names)
        # 아무 것도 안 걸리면 핵심기술·첨단전략기술은 기본 포함
        if not (want_core or want_adv or want_dual):
            want_core = want_adv = True

    parts = ["[참조: 관련 법령 고시 별표 요약 — 관련성 판단 보조용, 최종 판정은 원문·전문기관 확인]"]

    if want_adv:
        s = SOURCES["national_advanced_strategic_tech"]
        parts.append(f"\n◆ 국가첨단전략기술 ({s['notice_no']}, {s['effective']} 시행 / {s['scope']})")
        for field, techs in NATIONAL_ADVANCED_STRATEGIC_TECH.items():
            parts.append(f"  [{field}] " + " / ".join(techs))

    if want_core:
        s = SOURCES["national_core_tech"]
        parts.append(f"\n◆ 국가핵심기술 ({s['notice_no']}, {s['scope']})")
        for field, techs in NATIONAL_CORE_TECH.items():
            parts.append(f"  [{field}] " + " / ".join(techs))

    if want_dual:
        s = SOURCES["strategic_items_dual_use"]
        parts.append(f"\n◆ 전략물자 이중용도품목(별표2, {s['scope']})")
        for part, info in STRATEGIC_ITEMS_DUAL_USE.items():
            parts.append(f"  [{part}·{info['name']}] {info['examples']}")

    parts.append("\n※ 위 목록은 개정될 수 있으며, 개별 기술의 정확한 사양·통제번호는 원문 별표와 대조해야 합니다.")
    return "\n".join(parts)


def sources_note():
    """결과·심의서에 표기할 출처 요약 한 줄."""
    return (f"참조 별표: 국가첨단전략기술({SOURCES['national_advanced_strategic_tech']['effective']}), "
            f"국가핵심기술({SOURCES['national_core_tech']['effective']}), "
            f"전략물자 이중용도품목(별표2). 개정 여부는 원문 확인 필요.")


# GUI '참조 별표 보기'용 출처 목록
REFERENCE_SOURCES_LIST = [
    SOURCES["national_advanced_strategic_tech"],
    SOURCES["national_core_tech"],
    SOURCES["strategic_items_dual_use"],
]


# =========================================================
# 2. LLM 어댑터
# =========================================================
class LLMClient:
    def __init__(self, cfg):
        self.provider = cfg["provider"]
        self.cfg = cfg
        self._init_client()

    def _init_client(self):
        p = self.provider
        if p == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=self.cfg["openai"]["api_key"])
            self.model = self.cfg["openai"]["model"]
        elif p == "claude":
            import anthropic
            self.client = anthropic.Anthropic(api_key=self.cfg["claude"]["api_key"])
            self.model = self.cfg["claude"]["model"]
        elif p == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=self.cfg["gemini"]["api_key"])
            self.client = genai
            self.model = self.cfg["gemini"]["model"]
        elif p == "ollama":
            import requests
            self.client = requests
            self.model = self.cfg["ollama"]["model"]
            self.base_url = self.cfg["ollama"]["base_url"].rstrip("/")
            self.timeout = self.cfg["ollama"].get("timeout", 600)
            # 서버 연결 및 모델 존재 여부 사전 확인
            try:
                r = requests.get(f"{self.base_url}/api/tags", timeout=5)
                r.raise_for_status()
                names = [m.get("name", "") for m in r.json().get("models", [])]
                if names and not any(n == self.model or n.split(":")[0] == self.model
                                     for n in names):
                    raise RuntimeError(
                        f"Ollama에 '{self.model}' 모델이 없습니다. "
                        f"설치된 모델: {', '.join(names) or '없음'} "
                        f"(설치: ollama pull {self.model})")
            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(
                    f"Ollama 서버({self.base_url})에 연결할 수 없습니다. "
                    f"'ollama serve' 실행 여부를 확인하세요. ({e})")
        elif p == "lmstudio":
            import requests
            self.client = requests
            self.model = self.cfg["lmstudio"]["model"]
            self.base_url = self.cfg["lmstudio"]["base_url"].rstrip("/")
            self.timeout = self.cfg["lmstudio"].get("timeout", 600)
            # 서버 연결 및 모델 로드 여부 사전 확인(OpenAI 호환 /v1/models)
            try:
                r = requests.get(f"{self.base_url}/v1/models", timeout=5)
                r.raise_for_status()
                names = [m.get("id", "") for m in r.json().get("data", [])]
                if names and not any(n == self.model for n in names):
                    raise RuntimeError(
                        f"LM Studio에 '{self.model}' 모델이 로드되어 있지 않습니다. "
                        f"로드된 모델: {', '.join(names) or '없음'} "
                        f"(LM Studio 앱에서 모델을 다운로드·로드한 뒤 다시 시도하세요)")
            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(
                    f"LM Studio 서버({self.base_url})에 연결할 수 없습니다. "
                    f"LM Studio 앱의 '로컬 서버 시작' 여부를 확인하세요. ({e})")
        else:
            raise ValueError(f"지원하지 않는 provider: {p}")

    def _ask_once(self, system_prompt, user_prompt, temperature):
        p = self.provider
        # 일부 최신 모델(claude-sonnet-5, OpenAI 최신 모델 등)은 temperature 파라미터를
        # 지원하지 않음 → 미지원이 확인된 모델은 이후 호출에서 자동 제외
        if getattr(self, "_no_temperature", False):
            temperature = None

        if p == "openai":
            kwargs = dict(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            if not getattr(self, "_no_response_format", False):
                kwargs["response_format"] = {"type": "json_object"}
            if temperature is not None:
                kwargs["temperature"] = temperature
            try:
                resp = self.client.chat.completions.create(**kwargs)
            except Exception as e:
                if self._is_temperature_error(e) and temperature is not None:
                    self._no_temperature = True
                    kwargs.pop("temperature", None)
                    resp = self.client.chat.completions.create(**kwargs)
                elif self._is_response_format_error(e) and "response_format" in kwargs:
                    self._no_response_format = True
                    kwargs.pop("response_format", None)
                    resp = self.client.chat.completions.create(**kwargs)
                else:
                    raise
            text = resp.choices[0].message.content
            if not text:
                raise ValueError("모델이 빈 응답을 반환했습니다(거부 또는 토큰 한도).")
            return text

        elif p == "claude":
            # [최신 모델 기준 설계]
            # · assistant 프리필 미사용: thinking 지원 모델(claude-sonnet-5 등)은 프리필을
            #   거부하므로, JSON 강제는 시스템 프롬프트 지시 + parse_json의 견고한 추출로 처리
            # · 응답 파싱: content가 [ThinkingBlock, TextBlock, ...] 형태일 수 있으므로
            #   위치(content[0])가 아닌 블록 타입으로 텍스트를 수집
            # · max_tokens: thinking 토큰이 한도를 잠식할 수 있어 여유 있게 설정
            kwargs = dict(
                model=self.model,
                max_tokens=int(self.cfg["claude"].get("max_tokens", 8000)),
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            if temperature is not None:
                kwargs["temperature"] = temperature
            try:
                resp = self.client.messages.create(**kwargs)
            except Exception as e:
                if self._is_temperature_error(e) and temperature is not None:
                    self._no_temperature = True
                    kwargs.pop("temperature", None)
                    resp = self.client.messages.create(**kwargs)
                else:
                    raise
            return self._extract_claude_text(resp)

        elif p == "gemini":
            gen_cfg = {"response_mime_type": "application/json"}
            if temperature is not None:
                gen_cfg["temperature"] = temperature
            model = self.client.GenerativeModel(
                self.model,
                system_instruction=system_prompt,
                generation_config=gen_cfg,
            )
            resp = model.generate_content(user_prompt)
            # resp.text는 안전차단·빈 응답 시 예외 발생 → 후보 파트에서 직접 수집 폴백
            try:
                text = resp.text
            except Exception:
                parts = []
                for cand in getattr(resp, "candidates", []) or []:
                    for part in getattr(getattr(cand, "content", None), "parts", []) or []:
                        t = getattr(part, "text", "")
                        if t:
                            parts.append(t)
                text = "".join(parts)
            if not text:
                raise ValueError("Gemini가 빈 응답을 반환했습니다(안전차단 또는 토큰 한도).")
            return text

        elif p == "ollama":
            options = {}
            if temperature is not None:
                options["temperature"] = temperature
            resp = self.client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "format": "json",  # JSON-only 응답 강제
                    "options": options,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json().get("message", {})
            # 일부 Ollama 추론(thinking) 모델은 content 외 thinking 필드를 함께 반환
            return data.get("content", "") or ""

        elif p == "lmstudio":
            # LM Studio 로컬 서버는 OpenAI 호환 API 형식을 사용
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            if not getattr(self, "_no_response_format", False):
                payload["response_format"] = {"type": "json_object"}
            if temperature is not None:
                payload["temperature"] = temperature
            resp = self.client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code == 400 and "response_format" in resp.text:
                # 구버전 LM Studio는 response_format 미지원 → 제외 후 재호출
                self._no_response_format = True
                payload.pop("response_format", None)
                resp = self.client.post(f"{self.base_url}/v1/chat/completions",
                                        json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _extract_claude_text(resp):
        """Claude 응답에서 텍스트 블록만 수집.
        최신 모델은 content가 [ThinkingBlock, TextBlock, ...]일 수 있으므로
        위치가 아닌 블록 타입(type=='text')으로 판별한다."""
        parts = []
        for block in getattr(resp, "content", []) or []:
            btype = getattr(block, "type", "")
            if btype == "text":
                parts.append(getattr(block, "text", ""))
            elif btype in ("thinking", "redacted_thinking"):
                continue  # 추론 블록은 결과 텍스트가 아님
            elif not btype and hasattr(block, "text"):
                # type 속성이 없는 구형 SDK 응답 호환
                parts.append(block.text)
        text = "".join(parts).strip()
        if not text:
            stop = getattr(resp, "stop_reason", "")
            hint = (" — max_tokens 한도로 추론(thinking)만 반환된 것으로 보입니다. "
                    "CONFIG['claude']['max_tokens']를 늘려보세요." if stop == "max_tokens" else "")
            raise ValueError(f"Claude 응답에 텍스트 블록이 없습니다(stop_reason={stop}){hint}")
        return text

    @staticmethod
    def _is_temperature_error(exc):
        """'temperature is deprecated/unsupported for this model' 계열 오류 판별."""
        msg = str(exc).lower()
        return "temperature" in msg and any(
            k in msg for k in ("deprecated", "unsupported", "not supported",
                               "invalid_request", "does not support"))

    @staticmethod
    def _is_response_format_error(exc):
        """response_format 미지원 계열 오류 판별."""
        msg = str(exc).lower()
        return "response_format" in msg

    @staticmethod
    def _is_fatal_error(exc):
        """재시도해도 해결되지 않는 오류(인증·권한·모델없음 등) 판별 — 즉시 실패 처리."""
        msg = str(exc).lower()
        return any(k in msg for k in (
            "authentication", "invalid api key", "api key", "unauthorized",
            "permission", "401", "403", "not_found_error", "model not found",
            "insufficient_quota", "billing"))

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        """JSON dict를 반환. 파싱 실패·일시 오류는 지수 백오프 재시도,
        인증·권한 등 재시도 무의미한 오류는 즉시 실패."""
        if temperature is None:
            temperature = self.cfg.get("temperature", 0.2)
        retries = self.cfg.get("max_retries", 3)
        base = self.cfg.get("retry_base_wait", 2.0)
        last_err = None
        for attempt in range(retries + 1):
            try:
                raw = self._ask_once(system_prompt, user_prompt, temperature)
                return parse_json(raw)
            except Exception as e:
                if self._is_fatal_error(e):
                    raise RuntimeError(
                        f"LLM 호출 실패(재시도 불가 오류 — API 키·권한·모델명 확인 필요): {e}")
                last_err = e
                if attempt < retries:
                    time.sleep(base * (2 ** attempt))
        raise RuntimeError(f"LLM 호출/파싱 {retries + 1}회 실패: {last_err}")


def parse_json(text):
    """LLM 응답에서 JSON 객체를 안전하게 추출."""
    if not text:
        raise ValueError("빈 응답")
    text = text.strip()
    # 마크다운 펜스 제거 후 첫 '{' ~ 마지막 '}' 구간 파싱
    text = text.replace("```json", "```")
    if "```" in text:
        parts = [p for p in text.split("```") if "{" in p]
        if parts:
            text = parts[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"JSON 객체를 찾을 수 없음: {text[:200]}")
    return json.loads(text[start:end + 1])


# =========================================================
# 3. 감사로그 (위원회 운영기준: 주요 판단 근거 기록·관리)
# =========================================================
_audit_lock = threading.Lock()
_audit_state = {"path": None, "fh": None}  # 파일 핸들 재사용 — 대량 처리 시 매 이벤트 open 방지


def audit_log(event, payload):
    path = CONFIG.get("audit_log")
    if not path:
        return
    record = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "provider": CONFIG["provider"],
        "model": CONFIG[CONFIG["provider"]]["model"],
        "event": event,
        "payload": payload,
    }
    try:
        with _audit_lock:
            if _audit_state["fh"] is None or _audit_state["path"] != path:
                if _audit_state["fh"] is not None:
                    try:
                        _audit_state["fh"].close()
                    except OSError:
                        pass
                _audit_state["fh"] = open(path, "a", encoding="utf-8")
                _audit_state["path"] = path
            _audit_state["fh"].write(json.dumps(record, ensure_ascii=False) + "\n")
            _audit_state["fh"].flush()  # 건별 즉시 반영(중단 대비)
    except OSError:
        _audit_state["fh"] = None  # 다음 호출에서 재오픈 시도
        # 로그 실패가 분류를 중단시키지 않도록 무시


# =========================================================
# 4. 분류 프로세스 (가이드라인(안) 4단계)
# =========================================================
SYSTEM_PROMPT = """당신은 국가연구개발 보안등급분류위원회의 심의를 보조하는 전문가입니다.
「국가연구개발혁신법」 제21조제4항·제5항 및 같은 법 시행령 제45조제1항·제2항에 근거하여
연구개발과제의 보안등급 분류를 위한 참고 의견을 제시합니다.

[등급 정의]
- 보안과제(법 제21조제4항): 외부 유출 시 기술적·재산적 가치에 상당한 손실이 예상되거나
  국가안보를 위하여 별도로 높은 수준의 보안관리가 필요한 연구개발과제
- 민감과제(법 제21조제5항): 보안과제로 분류하지 아니하였으나 유출 시 국가에 미치는
  영향을 고려하여 추가적인 관리가 필요한 연구개발과제
- 일반과제: 위에 해당하지 않고 유출 시 국가에 미치는 영향이 크지 않아
  일반적 연구관리·기본 보안조치 하에서 수행 가능한 과제

[보안과제 분류기준(영 제45조제1항)]
① 방위력개선사업 관련 ② 외국 기술이전 거부로 국산화 추진 중인 기술
③ 보호 필요성이 인정되는 미래핵심기술 ④ 국가핵심기술
⑤ 대외무역법상 수출허가 등 제한 필요 기술 ⑥ 그 밖에 중앙행정기관장이 인정하는 과제

[민감과제 분류기준(영 제45조제2항) — 종합 고려]
① 국가안보·외교 등을 위한 전략적 필요성
② 기술적·경제적 가치 및 관련 산업의 성장 잠재력
③ 그 밖에 연구수행 과정 및 결과에 따른 추가적 관리 필요성

[판단 원칙]
- 기술의 우수성·성공 가능성이 아니라 '유출 시 국가에 미치는 영향과 보호 필요 수준'을 판단
- 단일 요건이 아닌 종합적 판단, 법적 기준 해당 여부와 정의 부합 여부를 함께 검토
- 판단이 불확실하면 불확실하다고 명시

반드시 지정된 JSON 형식으로만 답변하세요. JSON 외의 텍스트를 출력하지 마세요."""


def _task_block(task):
    return (f"과제명: {task.get('과제명', '')}\n"
            f"연구목표: {task.get('연구목표', '')}\n"
            f"연구내용: {task.get('연구내용', '')}\n"
            f"기대효과: {task.get('기대효과', '')}")


def step1_identify(llm, task):
    """1단계: 등급분류 대상(후보군) 식별"""
    prompt = f"""[과제정보]
{_task_block(task)}

[1단계: 등급분류 대상 식별]
다음 후보군 선별 기준에 비추어 이 과제가 보안등급 분류 검토 대상에 해당하는지 판단하세요.
- 혁신법 및 타 법령상 보호 대상 기술(국가전략기술, 국가핵심기술, 방위산업기술 등)
- 연구개발정보·성과의 비공개 필요성이 인정되는 경우
- 국제공동연구 과제(수출통제 기술·중요 연구자산 포함 여부)
- 세계최고 수준의 성능목표 및 기술사양을 지향하는 연구개발과제
- 그 밖에 국가적 중요성이 높은 과제

JSON 형식:
{{"is_candidate": true/false, "reason": "간단한 사유", "uncertainty": "판단이 불확실한 부분(없으면 빈 문자열)"}}"""
    return llm.ask_json(SYSTEM_PROMPT, prompt)


def step2_criteria(llm, task):
    """2단계: 법적 정의·기준 체크리스트 검토 — 7개 분류항목별 해당 여부 판단.
    '해당/일부/판단곤란' 항목이 3단계 국가영향 채점 대상으로 선택됨.
    국가첨단전략기술/국가핵심기술/전략물자 이중용도품목 별표를 참조로 주입."""
    checklist = "\n".join(
        f"{i + 1}. {name.split('. ', 1)[-1]}: {crit} ({law})"
        for i, (name, crit, law) in enumerate(FORM_ITEMS[:7]))
    reference = build_reference_prompt(None)  # 2단계는 전체 별표 참조
    prompt = f"""[과제정보]
{_task_block(task)}

{reference}

[2단계: 법적 정의·기준 체크리스트 검토]
아래 7개 분류항목 각각에 대해 이 과제의 해당 여부(해당/일부/미해당/판단곤란)와 근거를 제시하세요.
'판단곤란'은 제공된 정보만으로 판단할 수 없는 경우에만 사용하세요.
항목명은 아래에 제시된 명칭을 그대로 사용하세요.
위 '별표 요약'과 과제 내용을 대조하여, 관련 기술명이 있으면 근거(note)에 구체적으로 인용하세요.
(단, 별표는 개정될 수 있으므로 단정하지 말고 '관련 가능성' 수준으로 판단하며,
 정확한 사양·통제번호 확인이 필요하면 needs_expert_review를 true로 하세요.)

{checklist}

JSON 형식:
{{"criteria": [{{"item": "항목명", "level": "해당|일부|미해당|판단곤란", "note": "근거(관련 별표 기술명 인용 가능)", "matched_reference": "대조된 별표 기술명(없으면 빈 문자열)"}}],
  "summary": "종합 검토의견",
  "needs_expert_review": true/false,
  "expert_review_reason": "전문 기술판정(무역안보관리원·산업기술보호협회 등) 필요 여부와 사유"}}"""
    return llm.ask_json(SYSTEM_PROMPT, prompt)


def select_items_from_criteria(s2):
    """2단계 결과에서 3단계 채점 대상 항목 추출('해당/일부/판단곤란')."""
    selected = []
    for c in s2.get("criteria", []):
        name = str(c.get("item", "")).strip()
        # 항목명 매칭(번호·공백 차이 허용)
        matched = next((it for it in IMPACT_ITEMS
                        if it == name or it in name or name in it), None)
        if matched and c.get("level") in ("해당", "일부", "판단곤란"):
            if matched not in selected:
                selected.append(matched)
    return selected


def _validate_scores(scores_dict, items, n):
    """점수 검증: 선택 항목 기준으로 누락 보정, 1~5 클램핑, 위원 수 맞춤."""
    fixed = {}
    for item in items:
        vals = scores_dict.get(item, [])
        if not isinstance(vals, list):
            vals = [vals]
        clean = []
        for v in vals:
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            clean.append(min(5.0, max(1.0, v)))
        if not clean:
            clean = [3.0]  # 정보 부족 시 중간값 — 감사로그로 추적 가능
        clean = (clean + [clean[-1]] * n)[:n]
        fixed[item] = clean
    return fixed


def grade_by_avg(avg):
    """가이드라인(안) 판정 가이드에 따른 점수 기반 등급(우선 검토)."""
    th = CONFIG["thresholds"]
    if avg >= th["security"]:
        return "보안과제"      # 평균 4.5 이상: 보안과제 지정 필요성 우선 검토
    if avg >= th["sensitive"]:
        return "민감과제"      # 평균 3.5 이상~4.5 미만: 민감과제 지정 필요성 우선 검토
    return "일반과제"          # 평균 3.5 미만: 일반과제 우선 검토


def step3_impact(llm, task, selected_items, criteria_notes=None):
    """3단계: '선택된 분류항목에 대해서만' 유출 시 국가영향 수준 지표 채점.
    위원 구성(1명 또는 3명)에 따라 각 위원이 전문가 관점에서 독립 호출로 평가.
    평균은 반드시 파이썬에서 재계산."""
    panel = int(CONFIG.get("reviewer_panel", 3))
    personas = CONFIG["panel_personas"].get(panel, CONFIG["panel_personas"][3])
    n = len(personas)

    scale = """[유출 시 국가영향 수준 척도]
5점: 상당한 국가영향 — 국가 안보·외교·산업 등에 상당한 영향
4점: 높은 국가영향 — 보안과제 수준은 아니나 직접적 파급·민감 영향으로 별도 관리 필요
3점: 제한적 국가영향 — 일부 영향 가능하나 직접적 손실은 제한적
2점: 경미한 영향 — 국가 안보·외교·산업 등에 미치는 영향이 경미한 수준
1점: 영향 미미 — 공개·확산 시 국가 안보·외교·산업 등에 영향이 크지 않은 수준"""

    ref = ""
    if criteria_notes:
        ref = f"\n[2단계 법적 기준 검토 참고]\n{json.dumps(criteria_notes, ensure_ascii=False)}\n"
    # 선택 항목과 관련된 별표만 주입(토큰 절약)
    reference = build_reference_prompt(selected_items)

    scores = {item: [] for item in selected_items}
    notes = []
    for i, persona in enumerate(personas):
        prof = REVIEWER_PROFILES.get(persona, _DEFAULT_PROFILE)
        prompt = f"""[과제정보]
{_task_block(task)}

[당신의 역할: 보안등급분류위원회 위원 — {persona}]
· 평가 관점: {prof['관점']}
· 점수 산정 성향: {prof['성향']}
· 착안 질문: {prof['착안']}

당신은 다른 위원과 합의할 필요가 없으며, 위 관점과 성향에 따라 소신껏 독립적으로 평가합니다.
같은 과제라도 위원의 전문 관점에 따라 항목별 점수가 1~2점 다른 것이 자연스럽고 바람직합니다.
평균적·중립적 점수(3점)로 수렴하려 하지 말고, 당신의 관점에서 근거가 있는 방향으로 분명하게 평가하세요.
각 항목의 근거(notes)에는 반드시 '{persona}'의 관점이 드러나는 판단 이유를 쓰세요.
{ref}
{reference}

[3단계: 유출 시 국가영향 수준 평가]
{scale}

이 과제는 2단계 법적 기준 체크리스트 검토 결과, 아래 분류항목이 검토 대상으로 선택되었습니다.
※ 반드시 아래 '선택된 항목'에 대해서만 평가하세요. 다른 항목은 평가하지 않습니다.
위 '별표 요약'에 해당 기술이 명확히 포함될수록 국가영향 수준을 높게 평가하되,
별표 개정 가능성·사양 불확실성이 있으면 근거에 함께 기재하세요.

선택된 평가항목: {", ".join(selected_items)}

각 항목에 대해 1~5점(정수)으로 평가하고 항목별 근거를 간단히 제시하세요.

JSON 형식:
{{"scores": {{"항목명": 점수(정수)}}, "notes": {{"항목명": "근거"}}}}"""
        res = llm.ask_json(SYSTEM_PROMPT, prompt,
                           temperature=CONFIG.get("reviewer_temperature", 0.7))
        one = res.get("scores", {})
        for item in selected_items:
            # 항목명 유연 매칭
            val = one.get(item)
            if val is None:
                for k, v in one.items():
                    if item in str(k) or str(k) in item:
                        val = v
                        break
            scores[item].append(val if val is not None else 3)
        notes.append({"위원": f"위원{i + 1}({persona})", "근거": res.get("notes", {})})

    scores = _validate_scores(scores, selected_items, n)
    # ★ 평균은 LLM이 아닌 파이썬에서 계산 — '선택 항목'의 평균만 사용
    item_avg = {k: round(sum(v) / len(v), 2) for k, v in scores.items()}
    overall_avg = round(sum(item_avg.values()) / len(item_avg), 2) if item_avg else 0.0
    return {"위원구성": [f"위원{i + 1}: {p}" for i, p in enumerate(personas)],
            "선택항목": selected_items,
            "scores": scores, "item_avg": item_avg,
            "overall_avg": overall_avg, "notes": notes}


def step4_decide(llm, task, s2, s3):
    """4단계: 종합 의결(참고 의견).
    - strict_band_default: 점수 구간 등급을 기본값으로 지시해 상향 편향 억제
    - force_low_confidence_on_mismatch: 구간-등급 불일치 시 신뢰도 '낮음' 강제(결정적)"""
    th = CONFIG["thresholds"]
    gc = CONFIG.get("grade_consistency", {})
    avg = s3["overall_avg"]
    rule_grade = grade_by_avg(avg)

    if gc.get("strict_band_default", True):
        deviation_rule = f"""[등급 결정 원칙 — 반드시 준수]
1. 점수 기반 우선 검토 등급({rule_grade})을 최종 등급의 '기본값'으로 삼으세요.
   위원회가 이미 항목별 국가영향 수준을 정량 평가한 결과이므로, 특별한 사정이 없으면 그대로 따릅니다.
2. 기본값보다 '높은' 등급 의견은 다음 두 조건을 모두 충족할 때만 예외적으로 제시하세요.
   (a) 영 제45조 제1항 또는 제2항의 특정 호에 해당함이 2단계 검토에서 '해당'으로 명확히 확인됨
   (b) 해당 조항과 구체적 사실을 deviation_reason에 명시할 수 있음
   과제계획서의 목표 서술, 기대효과의 잠재력, '가능성이 있다' 수준의 추정만으로는 상향하지 마세요.
3. 기본값보다 '낮은' 등급 의견도 마찬가지로 법적 근거와 사유를 deviation_reason에 명시하세요.
4. 기본값과 동일한 등급을 제시하는 경우 deviation_reason은 빈 문자열로 두세요."""
    else:
        deviation_rule = ("점수 구간은 우선 검토 참고 도구이며, 법 제21조의 보안·민감과제 '정의' "
                          "부합 여부를 함께 확인하세요.\n"
                          "점수 기반 등급과 다른 의견을 제시하는 경우 그 사유를 명확히 하세요.")

    criteria_detail = json.dumps(s2.get("criteria", []), ensure_ascii=False)
    prompt = f"""[과제명] {task.get('과제명', '')}
[2단계 법적기준 체크리스트 결과] {criteria_detail}
[2단계 종합의견] {s2.get('summary', '')}
[3단계 채점 대상(선택 항목)] {", ".join(s3.get('선택항목', []))}
[3단계 선택 항목별 위원회 평균] {json.dumps(s3['item_avg'], ensure_ascii=False)}
[3단계 위원회 종합평균] {avg}
[판정 가이드] 평균 {th['security']} 이상: 보안과제 우선 검토 / {th['sensitive']} 이상~{th['security']} 미만: 민감과제 우선 검토 / {th['sensitive']} 미만: 일반과제 우선 검토
[점수 기반 우선 검토 등급] {rule_grade}

[4단계: 최종 등급 의견 제시]
{deviation_rule}

JSON 형식:
{{"final_grade": "보안과제|민감과제|일반과제",
  "confidence": "높음|보통|낮음",
  "rationale": "의견 사유(법적 근거 조항 포함)",
  "deviation_reason": "점수 구간과 다른 등급을 제시한 경우 그 법적 근거·사유(동일하면 빈 문자열)",
  "key_factor": "등급 판단에 가장 중요하게 고려한 지표",
  "committee_discussion_points": "위원회 종합 토론 시 중점 논의가 필요한 사항",
  "reclassify_condition": "향후 재분류 검토 조건",
  "measures": "등급별 주요 보안조치 요지"}}"""
    result = llm.ask_json(SYSTEM_PROMPT, prompt)
    result["rule_grade_reference"] = rule_grade
    result["overall_avg"] = avg

    # ── 결정적 후처리: 구간-등급 정합성 ──
    final = str(result.get("final_grade", ""))
    mismatch = bool(final) and (final != rule_grade)
    result["구간일치"] = not mismatch
    if mismatch:
        direction = "상향" if _grade_rank(final) > _grade_rank(rule_grade) else "하향"
        note = (f"[구간 불일치·{direction}] 점수 구간({rule_grade}, 평균 {avg}) ≠ 의결 의견({final})"
                f" — 사유: {result.get('deviation_reason') or result.get('rationale', '')}")
        if gc.get("force_low_confidence_on_mismatch", True):
            result["confidence"] = "낮음"
            note += " → 신뢰도 '낮음' 처리, 위원회 중점 검토 필요"
        prev = result.get("committee_discussion_points", "")
        result["committee_discussion_points"] = (note + (" / " + prev if prev else ""))
        audit_log("grade_mismatch", {"과제명": task.get("과제명", ""),
                                     "rule_grade": rule_grade, "final_grade": final,
                                     "avg": avg, "direction": direction,
                                     "deviation_reason": result.get("deviation_reason", "")})
    return result


_GRADE_RANK = {"일반과제": 0, "민감과제": 1, "보안과제": 2}


def _grade_rank(grade):
    for k, v in _GRADE_RANK.items():
        if str(grade).startswith(k):
            return v
    return -1


def classify_one(llm, task, selected_override=None):
    """단일 과제 전체 프로세스 실행.
    selected_override: 사용자가 GUI에서 직접 선택한 분류항목 목록(없으면 2단계 결과로 자동 선택)."""
    out = {"과제명": task.get("과제명", ""), "면책문구": DISCLAIMER,
           "참조별표": sources_note()}
    audit_log("classify_start", {"task": task, "selected_override": selected_override})

    s1 = step1_identify(llm, task)
    out["1_식별"] = s1
    audit_log("step1", {"과제명": out["과제명"], "result": s1})

    if not s1.get("is_candidate", True):
        out["최종등급"] = "일반과제(후보 제외)"
        out["사유"] = s1.get("reason", "")
        audit_log("classify_end", {"과제명": out["과제명"], "최종등급": out["최종등급"]})
        return out

    s2 = step2_criteria(llm, task)
    audit_log("step2", {"과제명": out["과제명"], "result": s2})
    out["2_기준검토"] = s2

    # 채점 대상 항목 결정: 사용자 선택 우선, 없으면 2단계 결과로 자동 선택
    if selected_override:
        selected = [it for it in IMPACT_ITEMS if it in selected_override]
        out["항목선택방식"] = "사용자 직접 선택"
    else:
        selected = select_items_from_criteria(s2)
        out["항목선택방식"] = "2단계 체크리스트 자동 선택"
    out["선택항목"] = selected

    if not selected:
        # 7개 법적 기준 모두 미해당 → 국가영향 채점 생략, 일반과제 우선 검토
        out["최종등급"] = "일반과제"
        out["종합평균"] = "-"
        out["사유"] = ("2단계 법적 정의·기준 체크리스트 검토 결과 7개 분류항목 모두 미해당으로 "
                       "판단되어 국가영향 수준 채점을 생략하고 일반과제 우선 검토로 분류")
        audit_log("classify_end", {"과제명": out["과제명"], "최종등급": out["최종등급"]})
        return out

    criteria_notes = [c for c in s2.get("criteria", [])
                      if any(it in str(c.get("item", "")) for it in selected)]
    s3 = step3_impact(llm, task, selected, criteria_notes)
    audit_log("step3", {"과제명": out["과제명"], "result": s3})
    s4 = step4_decide(llm, task, s2, s3)
    audit_log("step4", {"과제명": out["과제명"], "result": s4})

    out["3_국가영향"] = s3
    out["4_의결의견"] = s4
    out["최종등급"] = s4.get("final_grade", "")
    out["신뢰도"] = s4.get("confidence", "")
    out["종합평균"] = s3["overall_avg"]
    audit_log("classify_end", {"과제명": out["과제명"], "최종등급": out["최종등급"]})
    return out


def format_report(res):
    """분류 결과를 사람이 읽기 좋은 보고서 텍스트로 정리(GUI 출력용)."""
    L = []
    bar = "━" * 46
    L.append(bar)
    L.append(f"  분류 결과: {res.get('과제명', '')}")
    L.append(bar)
    grade = res.get("최종등급", "-")
    avg = res.get("종합평균", "-")
    conf = res.get("신뢰도", "")
    line = f"  ▶ 등급 의견: {grade}"
    if conf:
        line += f"   (신뢰도: {conf})"
    L.append(line)
    if avg != "-":
        th = CONFIG["thresholds"]
        L.append(f"  ▶ 위원회 종합평균: {avg}점"
                 f"  [보안 ≥{th['security']} / 민감 {th['sensitive']}~{th['security']} / 일반 <{th['sensitive']}]")
    s4_ = res.get("4_의결의견", {})
    if s4_ and not s4_.get("구간일치", True):
        L.append(f"  ⚠ 점수 구간({s4_.get('rule_grade_reference', '-')})과 의결 의견({grade}) 불일치"
                 f" — 신뢰도 '낮음' 처리, 위원회 중점 검토 필요")
        if s4_.get("deviation_reason"):
            L.append(f"     상이 사유: {s4_.get('deviation_reason')}")
    L.append("")

    s1 = res.get("1_식별", {})
    if s1:
        mark = "해당" if s1.get("is_candidate", True) else "미해당"
        L.append(f"[1단계] 분류대상 식별: {mark} — {s1.get('reason', '')}")

    s2 = res.get("2_기준검토", {})
    if s2:
        L.append(f"[2단계] 법적 정의·기준 체크리스트 ({res.get('항목선택방식', '')})")
        selected = res.get("선택항목", [])
        for c in s2.get("criteria", []):
            name = str(c.get("item", ""))
            chk = "■" if any(it in name or name in it for it in selected) else "□"
            L.append(f"  {chk} {name:<16s} [{c.get('level', '-')}] {c.get('note', '')}")
            matched = c.get("matched_reference", "")
            if matched:
                L.append(f"       ↳ 대조 별표: {matched}")
        if s2.get("needs_expert_review"):
            L.append(f"  ※ 전문 기술판정 검토 필요: {s2.get('expert_review_reason', '')}")

    s3 = res.get("3_국가영향", {})
    if s3:
        L.append("")
        L.append(f"[3단계] 유출 시 국가영향 채점 — 선택 항목만 평가 "
                 f"({' / '.join(s3.get('위원구성', []))})")
        rev_notes = s3.get("notes", [])
        for item in s3.get("선택항목", []):
            sc = s3.get("scores", {}).get(item, [])
            iavg = s3.get("item_avg", {}).get(item, "-")
            sc_txt = ", ".join(str(int(x)) if float(x).is_integer() else str(x) for x in sc)
            L.append(f"  · {item:<16s} 평균 {iavg}점  (위원별: {sc_txt})")
            # 위원 간 점수 차이가 있는 항목은 관점별 근거를 함께 표시
            if sc and (max(sc) - min(sc)) >= 1 and isinstance(rev_notes, list):
                for rv in rev_notes:
                    reason = rv.get("근거", {})
                    if isinstance(reason, dict):
                        txt = str(reason.get(item, "")).strip()
                        if txt:
                            txt = txt if len(txt) <= 80 else txt[:80] + "…"
                            L.append(f"      └ {rv.get('위원', '')}: {txt}")
        L.append(f"  ⇒ 종합평균 {s3.get('overall_avg', '-')}점 → "
                 f"{grade_by_avg(s3.get('overall_avg', 0))} 지정 필요성 우선 검토")

    s4 = res.get("4_의결의견", {})
    L.append("")
    if s4:
        L.append("[4단계] 의결 의견 (AI 참고)")
        L.append(f"  · 사유: {s4.get('rationale', '')}")
        L.append(f"  · 핵심 고려 지표: {s4.get('key_factor', '')}")
        L.append(f"  · 위원회 논의 필요사항: {s4.get('committee_discussion_points', '')}")
        L.append(f"  · 재분류 검토 조건: {s4.get('reclassify_condition', '')}")
        L.append(f"  · 보안조치 요지: {s4.get('measures', '')}")
    elif res.get("사유"):
        L.append(f"[의견] {res.get('사유', '')}")
    L.append("")
    L.append(DISCLAIMER)
    if res.get("참조별표"):
        L.append(res["참조별표"])
    L.append(bar)
    return "\n".join(L)




# =========================================================
# 5. 엑셀 대량 처리 (건별 저장 + 재개 기능)
# =========================================================
# 결과 컬럼: 연번 + 10개 (재분류조건·면책문구·상세JSON은 제외 — 상세는 감사로그/체크포인트에 보존)
RESULT_COLUMNS = ["연번", "과제명", "상태", "최종등급(참고)", "신뢰도", "종합평균",
                  "채점항목(선택)", "항목선택방식", "핵심고려지표", "의결사유",
                  "위원회논의필요사항"]

# 입력 양식 컬럼 — 세부사업명은 선택 입력(위원용 심의서에 표기됨)
TEMPLATE_COLUMNS = ["세부사업명", "과제명", "연구목표", "연구내용", "기대효과"]

_FONT = "맑은 고딕"
_HDR_FILL = "305496"
_HDR_FONT = "FFFFFF"
_EX_FILL = "F2F2F2"
_GRADE_STYLE = {
    "보안과제": ("FFC7CE", "9C0006"),
    "민감과제": ("FFEB9C", "9C6500"),
    "일반과제": ("C6EFCE", "006100"),
    "오류":    ("D9D9D9", "3F3F3F"),
}


@functools.lru_cache(maxsize=1)
def _xl_styles():
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    thin = Side(style="thin", color="BFBFBF")
    return {
        "hdr_font": Font(name=_FONT, bold=True, color=_HDR_FONT, size=10),
        "hdr_fill": PatternFill("solid", start_color=_HDR_FILL),
        "hdr_align": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "body_font": Font(name=_FONT, size=10),
        "wrap": Alignment(vertical="top", wrap_text=True),
        "center": Alignment(horizontal="center", vertical="center"),
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
        "Font": Font, "PatternFill": PatternFill,
    }


def make_template(path="분류대상_양식.xlsx"):
    """대량 분류용 입력 양식: 작성안내 시트 + 서식 적용 입력 시트(예시 2행 포함)."""
    from openpyxl import Workbook
    st = _xl_styles()
    wb = Workbook()

    g = wb.active
    g.title = "작성안내"
    g.column_dimensions["A"].width = 118
    guide_lines = [
        ("연구개발과제 보안등급 분류 — 대량 입력 양식 작성안내", True),
        ("", False),
        ("1. '분류대상' 시트에 과제를 한 행에 하나씩 입력합니다. (2~3행의 회색 예시는 참고 후 삭제)", False),
        ("2. 컬럼 설명", True),
        ("   · 세부사업명(선택): 위원용 심의서에 표기됩니다. 없으면 비워두세요.", False),
        ("   · 과제명(필수): 비어 있으면 제외되며, 중복 시 첫 건만 처리되므로 중복 없이 입력하세요.", False),
        ("   · 연구목표/연구내용/기대효과: 구체적일수록 판단 정확도가 올라갑니다.", False),
        ("     — '연구내용'에 개발 대상 기술, 성능목표, 활용처(수요기관) 포함을 권장합니다.", False),
        ("3. 대량 처리 안내", True),
        ("   · 결과는 건별로 체크포인트 파일(<결과명>.checkpoint.jsonl)에 즉시 기록되고,", False),
        ("     엑셀 파일은 일정 간격(기본 50건)마다 갱신됩니다. 중단 후 재실행하면 완료 건은 건너뜁니다.", False),
        ("   · 수만 건 이상 처리 시 GUI의 '동시 처리' 수를 높이고, 위원 1명 구성 사용을 권장합니다.", False),
        ("4. 유의사항", True),
        ("   · 외부 API(openai/claude/gemini) 사용 시 과제정보가 외부 서버로 전송됩니다.", False),
        ("     비공개·민감 정보가 포함된 과제는 로컬 LLM(ollama/LM Studio)을 사용하세요.", False),
        ("   · 본 도구의 결과는 보안등급분류위원회 심의를 위한 참고자료입니다.", False),
    ]
    for i, (text, bold) in enumerate(guide_lines, start=1):
        c = g.cell(row=i, column=1, value=text)
        c.font = st["Font"](name=_FONT, size=11 if bold else 10, bold=bold)

    ws = wb.create_sheet("분류대상")
    widths = {"세부사업명": 22, "과제명": 42, "연구목표": 40, "연구내용": 60, "기대효과": 36}
    for j, col in enumerate(TEMPLATE_COLUMNS, start=1):
        c = ws.cell(row=1, column=j,
                    value=col + ("(선택)" if col == "세부사업명" else "(필수)" if col == "과제명" else ""))
        c.font, c.fill, c.alignment, c.border = st["hdr_font"], st["hdr_fill"], st["hdr_align"], st["border"]
        ws.column_dimensions[c.column_letter].width = widths[col]
    ws.row_dimensions[1].height = 24
    ws.freeze_panes = "A2"

    examples = [
        ["(예시) 차세대 전력반도체 기술개발사업",
         "(예시) 1.5kW급 태양전지용 GaN 전력반도체 기술개발",
         "고효율 GaN 전력반도체 소자·모듈 개발",
         "태양광 인버터용 화합물반도체 소자 설계·공정·실증, 전력변환 효율 98% 이상, 수요기관: 인버터 제조기업",
         "전력변환 효율 향상 및 소자 국산화, 수입 의존도 완화"],
        ["(예시) 국민안전 대응 무인이동체 사업",
         "(예시) 재난현장 정찰용 자율비행 드론 군집제어 기술개발",
         "GPS 음영지역 자율비행 및 군집제어 알고리즘 개발",
         "실내·재난환경 자율비행, 군집 편대 제어, 영상 기반 실시간 탐색, TRL 6 실증",
         "재난대응 골든타임 단축, 공공 무인이동체 산업 활성화"],
    ]
    ex_fill = st["PatternFill"]("solid", start_color=_EX_FILL)
    ex_font = st["Font"](name=_FONT, size=10, italic=True, color="808080")
    for r, row in enumerate(examples, start=2):
        for j, v in enumerate(row, start=1):
            c = ws.cell(row=r, column=j, value=v)
            c.font, c.fill, c.alignment, c.border = ex_font, ex_fill, st["wrap"], st["border"]
        ws.row_dimensions[r].height = 34
    for r in range(4, 24):
        for j in range(1, len(TEMPLATE_COLUMNS) + 1):
            c = ws.cell(row=r, column=j)
            c.font, c.alignment, c.border = st["body_font"], st["wrap"], st["border"]

    wb.save(path)
    print(f"양식 생성 완료: {path}")
    return path


def _row_to_result(res):
    """분류 결과 → 결과표 1행. (재분류조건·상세JSON 등 전체 정보는 체크포인트·감사로그에 보존)"""
    s4 = res.get("4_의결의견", {})
    return {
        "과제명": res.get("과제명", ""),
        "상태": "완료",
        "최종등급(참고)": res.get("최종등급", ""),
        "신뢰도": res.get("신뢰도", ""),
        "종합평균": res.get("종합평균", ""),
        "채점항목(선택)": ", ".join(res.get("선택항목", [])),
        "항목선택방식": res.get("항목선택방식", ""),
        "핵심고려지표": s4.get("key_factor", ""),
        "의결사유": s4.get("rationale", res.get("사유", "")),
        "위원회논의필요사항": s4.get("committee_discussion_points", ""),
        # 이하 엑셀 미표시 — 체크포인트(JSONL)에만 보존
        "_재분류조건": s4.get("reclassify_condition", ""),
        "_상세": res,
    }


def _save_results(rows, out_path):
    """분류결과를 서식 적용 엑셀로 저장: 연번, 등급 색상, 자동필터, 요약 시트(수식).
    대량(2,000건 초과) 시 행 높이 지정을 생략해 저장 속도·용량 최적화."""
    from openpyxl import Workbook
    st = _xl_styles()
    big = len(rows) > 2000
    wb = Workbook()

    ws = wb.active
    ws.title = "분류결과"
    widths = {"연번": 7, "과제명": 38, "상태": 8, "최종등급(참고)": 14, "신뢰도": 8,
              "종합평균": 9, "채점항목(선택)": 34, "항목선택방식": 20, "핵심고려지표": 20,
              "의결사유": 46, "위원회논의필요사항": 40}
    for j, col in enumerate(RESULT_COLUMNS, start=1):
        c = ws.cell(row=1, column=j, value=col)
        c.font, c.fill, c.alignment, c.border = st["hdr_font"], st["hdr_fill"], st["hdr_align"], st["border"]
        ws.column_dimensions[c.column_letter].width = widths.get(col, 16)
    ws.row_dimensions[1].height = 26
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=len(RESULT_COLUMNS)).coordinate}"

    center_cols = {"연번", "상태", "최종등급(참고)", "신뢰도", "종합평균"}
    grade_col = RESULT_COLUMNS.index("최종등급(참고)") + 1
    body_border = None if big else st["border"]  # 대량 시 테두리 생략(저장 속도·용량 최적화)
    for i, row in enumerate(rows, start=2):
        for j, col in enumerate(RESULT_COLUMNS, start=1):
            v = (i - 1) if col == "연번" else row.get(col, "")
            c = ws.cell(row=i, column=j, value=v)
            c.font = st["body_font"]
            if body_border is not None:
                c.border = body_border
            c.alignment = st["center"] if col in center_cols else st["wrap"]
        grade = str(row.get("최종등급(참고)", ""))
        status = str(row.get("상태", ""))
        key = "오류" if status == "오류" else next(
            (g for g in ("보안과제", "민감과제", "일반과제") if grade.startswith(g)), None)
        if key:
            fill, color = _GRADE_STYLE[key]
            gc = ws.cell(row=i, column=grade_col)
            gc.fill = st["PatternFill"]("solid", start_color=fill)
            gc.font = st["Font"](name=_FONT, size=10, bold=True, color=color)
        if not big:
            ws.row_dimensions[i].height = 60

    # 요약 시트 (엑셀 수식 집계 — 최대 100만 행 커버)
    s = wb.create_sheet("요약")
    for col, w in (("A", 24), ("B", 12), ("C", 12)):
        s.column_dimensions[col].width = w
    s.cell(row=1, column=1, value="보안등급 분류 결과 요약").font = st["Font"](name=_FONT, size=12, bold=True)
    s.cell(row=2, column=1, value=f"생성일시: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
           ).font = st["Font"](name=_FONT, size=9, color="808080")
    for j, h in enumerate(("구분", "건수", "비율"), start=1):
        c = s.cell(row=4, column=j, value=h)
        c.font, c.fill, c.alignment, c.border = st["hdr_font"], st["hdr_fill"], st["hdr_align"], st["border"]
    items = [
        ("전체 과제 수", '=COUNTA(분류결과!B2:B1048576)', None),
        ("보안과제(참고)", '=COUNTIF(분류결과!D2:D1048576,"보안과제*")', "보안과제"),
        ("민감과제(참고)", '=COUNTIF(분류결과!D2:D1048576,"민감과제*")', "민감과제"),
        ("일반과제(참고)", '=COUNTIF(분류결과!D2:D1048576,"일반과제*")', "일반과제"),
        ("오류(재실행 필요)", '=COUNTIF(분류결과!C2:C1048576,"오류")', "오류"),
    ]
    for k, (label, formula, key) in enumerate(items, start=5):
        a = s.cell(row=k, column=1, value=label)
        b = s.cell(row=k, column=2, value=formula)
        r = s.cell(row=k, column=3, value=f'=IF($B$5=0,"-",B{k}/$B$5)')
        r.number_format = "0.0%"
        for c in (a, b, r):
            c.font, c.border = st["body_font"], st["border"]
        b.alignment = r.alignment = st["center"]
        if key:
            fill, color = _GRADE_STYLE[key]
            a.fill = st["PatternFill"]("solid", start_color=fill)
            a.font = st["Font"](name=_FONT, size=10, bold=True, color=color)
    s.cell(row=11, column=1, value=DISCLAIMER).font = st["Font"](name=_FONT, size=9, color="808080")
    s.cell(row=12, column=1, value=sources_note()).font = st["Font"](name=_FONT, size=9, color="808080")

    tmp = out_path + ".tmp"
    wb.save(tmp)
    os.replace(tmp, out_path)  # 원자적 교체 — 저장 중 중단돼도 기존 파일 보존


def _open_file(path):
    """운영체제 기본 프로그램으로 파일/폴더 열기."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def _checkpoint_path(out_path):
    return out_path + ".checkpoint.jsonl"


def _load_checkpoint(out_path):
    """체크포인트(JSONL)에서 기존 결과 로드. '완료' 건은 재실행 시 건너뜀."""
    rows, done = [], set()
    cp = _checkpoint_path(out_path)
    if os.path.exists(cp):
        with open(cp, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows.append(d)
                if d.get("상태") == "완료":
                    done.add(str(d.get("과제명", "")))
    return rows, done


def run_excel(in_path, out_path="분류결과.xlsx", resume=True,
              progress_cb=None, make_forms=False, status_cb=None):
    """엑셀 대량 분류 (최대 수십만 건 대응).
    - 결과는 체크포인트(JSONL)에 건별 즉시 기록(append) → 중단·오류 시에도 유실 없음
    - 엑셀 파일은 CONFIG['save_every'] 건마다 및 종료 시 갱신(원자적 교체)
    - CONFIG['max_workers']>1이면 과제 단위 병렬 처리 (재시도·백오프는 건별 유지)
    - 재실행 시 체크포인트의 '완료' 건은 건너뛰고 오류 건만 재시도"""
    def log(msg):
        if progress_cb:
            progress_cb(msg)

    xls = pd.ExcelFile(in_path)  # 시트 확인과 읽기를 한 번의 열기로 처리
    sheet = "분류대상" if "분류대상" in xls.sheet_names else 0
    df = xls.parse(sheet).fillna("")
    df.columns = [str(c).replace("(필수)", "").replace("(선택)", "").strip() for c in df.columns]
    if "과제명" not in df.columns:
        raise ValueError("입력 엑셀에 '과제명' 컬럼이 필요합니다. '엑셀 양식 생성'을 이용하세요.")

    # 입력 과제 목록 구성 (빈 과제명·예시 행·중복 제외)
    tasks, seen = [], set()
    for _, r in df.iterrows():
        task = {k: str(v).strip() for k, v in r.to_dict().items()}
        name = task.get("과제명", "")
        if not name or name.startswith("(예시)") or name in seen:
            continue
        seen.add(name)
        tasks.append(task)
    order = {t["과제명"]: i for i, t in enumerate(tasks)}

    rows, done = ([], set())
    if resume:
        rows, done = _load_checkpoint(out_path)
        # 오류 건은 재시도 대상 — 결과 목록에서 제거
        rows = [d for d in rows if d.get("상태") == "완료"]
    pending = [t for t in tasks if t["과제명"] not in done]

    workers = max(1, min(8, int(CONFIG.get("max_workers", 1))))
    panel = int(CONFIG.get("reviewer_panel", 3))
    calls_per_task = 3 + panel  # 1·2·4단계 + 위원 수(선택 항목 없으면 더 적음)
    log(f"대상 {len(tasks)}건 중 완료 {len(done)}건 건너뜀 → 처리 예정 {len(pending)}건 "
        f"(위원 {panel}명 기준 과제당 최대 {calls_per_task}회 호출, 동시 처리 {workers})")
    if make_forms and len(pending) > 1000:
        make_forms = False
        log("※ 심의서 생성은 1,000건 초과 대량 처리에서 자동 비활성화됩니다"
            " (필요 과제만 별도 파일로 분류해 생성하세요).")

    forms_dir = None
    if make_forms:
        forms_dir = os.path.splitext(out_path)[0] + "_심의서"
        os.makedirs(forms_dir, exist_ok=True)

    llm = LLMClient(CONFIG)
    lock = threading.Lock()
    save_lock = threading.Lock()
    cp = _checkpoint_path(out_path)
    # 엑셀 주기 저장 간격: 대량일수록 자동 확대(전체 재저장 비용 방지).
    # 건별 보존은 체크포인트(JSONL)가 담당하므로 엑셀 갱신은 드물어도 안전.
    save_every = max(max(1, int(CONFIG.get("save_every", 50))), len(pending) // 20)
    if len(pending) > 1000:
        log(f"※ 대량 처리 모드: 엑셀 파일은 {save_every}건마다 갱신됩니다"
            f" (건별 결과는 체크포인트에 즉시 기록).")
    counter = {"n": 0}
    start_ts = time.time()

    def sort_rows():
        return sorted(rows, key=lambda d: order.get(str(d.get("과제명", "")), 10**9))

    def process(task):
        name = task["과제명"]
        try:
            res = classify_one(llm, task)
            row = _row_to_result(res)
            if forms_dir:
                try:
                    export_review_form_docx(
                        task, res, os.path.join(forms_dir, _safe_filename(name) + "_심의서.docx"))
                except Exception as fe:
                    log(f"    [심의서 생성 실패] {name}: {fe}")
        except Exception as e:
            audit_log("error", {"과제명": name, "error": str(e),
                                "trace": traceback.format_exc()})
            row = {"과제명": name, "상태": "오류", "의결사유": str(e)}
        snapshot = None
        with lock:
            rows.append(row)
            cp_fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            cp_fh.flush()  # 건별 즉시 반영(중단 대비)
            counter["n"] += 1
            n = counter["n"]
            if n % save_every == 0:
                snapshot = sort_rows()
            elapsed = time.time() - start_ts
            rate = n / elapsed if elapsed > 0 else 0
            remain = (len(pending) - n) / rate if rate > 0 else 0
            if status_cb:  # 상태바용 — 매 건 갱신
                status_cb(f"{n}/{len(pending)} 분류 중 · 경과 {elapsed/60:.0f}분 · "
                          f"잔여 예상 {max(remain/60, 0):.0f}분")
            if n == 1 or n % 10 == 0 or n == len(pending):
                log(f"[{n}/{len(pending)}] {name} → {row.get('최종등급(참고)', row.get('상태'))} "
                    f"(경과 {elapsed/60:.1f}분, 잔여 예상 {remain/60:.0f}분)")
        if snapshot is not None:
            # 저장은 분류 잠금 밖에서 수행 — 저장 중에도 다른 과제 분류 계속 진행
            with save_lock:
                _save_results(snapshot, out_path)
        return name

    cp_fh = open(cp, "a", encoding="utf-8")  # 대량 처리 동안 핸들 재사용(건별 open 제거)
    try:
        if not pending:
            log("처리할 신규 과제가 없습니다.")
        elif workers == 1:
            for t in pending:
                process(t)
                time.sleep(CONFIG.get("batch_sleep", 1.0))
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(process, pending))
    finally:
        try:
            cp_fh.close()
        except OSError:
            pass

    _save_results(sort_rows(), out_path)
    log(f"완료: {out_path} 저장됨 (오류 건은 '상태' 열 필터 후 동일 명령 재실행 시 자동 재시도)")
    log(f"체크포인트: {cp} (전체 상세 결과 보존 — 완료 후 삭제 가능)")
    return out_path


# =========================================================
# 6. 위원용 심의서(붙임2 양식 기반) Word 생성
# =========================================================
def _safe_filename(name, maxlen=60):
    bad = '\\/:*?"<>|\n\r\t'
    out = "".join(c for c in str(name) if c not in bad).strip()
    return (out or "무제")[:maxlen]


def _require_docx():
    try:
        from docx import Document
        return Document
    except ImportError:
        raise RuntimeError("python-docx가 설치되어 있지 않습니다: pip install python-docx")


def _impact_note_text(res, item_name):
    """3단계 결과에서 항목별 근거 텍스트 추출(단일/독립 위원 모드 모두 지원)."""
    s3 = res.get("3_국가영향", {})
    notes = s3.get("notes", {})
    if isinstance(notes, dict):
        return str(notes.get(item_name, ""))
    if isinstance(notes, list):  # 독립 위원 모드: 위원별 근거 일부 요약
        parts = []
        for rev in notes:
            reason = rev.get("근거", {})
            if isinstance(reason, dict) and reason.get(item_name):
                label = str(rev.get("위원", "")).strip()
                if label and not label.startswith("위원"):
                    label = f"위원{label}"
                parts.append(f"{label}: {reason[item_name]}")
        return " / ".join(parts[:3])
    return ""


def _impact_reviewer_scores(res, item_name):
    """항목별 위원 점수를 '위원1(기술분야 전문가) 5점 / 위원2(...) 4점' 형태로 반환.
    위원 명칭(위원구성)과 점수 리스트(scores)를 매칭한다."""
    s3 = res.get("3_국가영향", {})
    scores = s3.get("scores", {}).get(item_name, [])
    if not scores:
        return ""
    labels = s3.get("위원구성", [])  # 예: "위원1: 기술분야 전문가"
    parts = []
    for i, sc in enumerate(scores):
        label = labels[i] if i < len(labels) else f"위원{i + 1}"
        # "위원1: 기술분야 전문가" → "위원1(기술분야 전문가)"
        if ": " in label:
            no, persona = label.split(": ", 1)
            label = f"{no}({persona})"
        val = int(sc) if float(sc).is_integer() else sc
        parts.append(f"{label} {val}점")
    return " / ".join(parts)


def export_review_form_docx(task, res, path):
    """AI 사전검토 결과가 참고정보로 포함된 위원용 심의서(붙임2 양식 기반) 생성.
    '위원 판단'란과 서명란은 공란으로 두어 위원이 직접 기재."""
    Document = _require_docx()
    from docx.shared import Pt

    doc = Document()
    doc.styles["Normal"].font.size = Pt(10)

    doc.add_heading("연구개발과제 보안등급 심의서 (위원용)", level=1)
    doc.add_paragraph(
        "※ 본 심의는 유출 시 국가영향 수준을 결정하기 위한 절차이며, "
        "기술의 우수성 등을 평가하는 과제평가와는 다른 성격임")
    doc.add_paragraph(
        "※ 'AI 사전검토' 열은 심의 보조용 참고정보이며, '위원 판단'란은 위원이 직접 기재합니다. "
        + DISCLAIMER)

    # 과제 기본 정보
    doc.add_heading("과제 기본 정보", level=2)
    t = doc.add_table(rows=4, cols=2)
    t.style = "Table Grid"
    rows_info = [
        ("세부사업명", task.get("세부사업명", "")),
        ("과제명", task.get("과제명", "")),
        ("연구목표", task.get("연구목표", "")),
        ("연구내용 요약", (task.get("연구내용", "") or "")[:300]),
    ]
    for i, (k, v) in enumerate(rows_info):
        t.cell(i, 0).text = k
        t.cell(i, 1).text = str(v)

    # AI 사전검토 요약
    s4 = res.get("4_의결의견", {})
    doc.add_heading("AI 사전검토 요약 (참고)", level=2)
    doc.add_paragraph(
        f"등급 의견: {res.get('최종등급', '-')}  |  "
        f"국가영향 종합평균: {res.get('종합평균', '-')}  |  "
        f"신뢰도: {res.get('신뢰도', '-')}")
    if s4 and not s4.get("구간일치", True):
        doc.add_paragraph(
            f"⚠ 점수 구간({s4.get('rule_grade_reference', '-')})과 AI 의결 의견"
            f"({res.get('최종등급', '-')}) 불일치 — 신뢰도 '낮음' 처리. "
            f"상이 사유: {s4.get('deviation_reason', '-')} → 위원회 중점 검토 필요")
    doc.add_paragraph(f"핵심 고려 지표: {s4.get('key_factor', '-')}")
    doc.add_paragraph(f"의견 사유: {s4.get('rationale', res.get('사유', '-'))}")

    # 분류항목별 검토표
    doc.add_heading("분류항목별 검토", level=2)
    item_avg = res.get("3_국가영향", {}).get("item_avg", {})
    tbl = doc.add_table(rows=1, cols=5)
    tbl.style = "Table Grid"
    hdr = tbl.rows[0].cells
    for j, h in enumerate(["분류항목", "보안등급 분류 기준 상세",
                           "AI 사전검토 (참고)", "위원 판단\n(⑤~① 기재)", "근거 법령"]):
        hdr[j].text = h
    for name, criteria, law in FORM_ITEMS:
        row = tbl.add_row().cells
        row[0].text = name
        row[1].text = criteria
        plain = name.split(". ", 1)[-1].replace("(기타) ", "")
        selected = res.get("선택항목", list(item_avg.keys()))
        avg = item_avg.get(plain)
        if avg is not None:
            ai_txt = f"평균 {avg}점"
            rev_scores = _impact_reviewer_scores(res, plain)
            if rev_scores:
                ai_txt += f"\n(위원별: {rev_scores})"
            note = _impact_note_text(res, plain)
            if note:
                ai_txt += f"\n{note}"
        elif plain in IMPACT_ITEMS and plain not in selected:
            ai_txt = "체크리스트 미해당 → 미채점"
        else:
            ai_txt = "정성 검토 항목"
        # 2단계에서 대조된 별표 기술명이 있으면 함께 표기
        matched = _matched_reference(res, plain)
        if matched:
            ai_txt += f"\n[대조 별표] {matched}"
        row[2].text = ai_txt
        row[3].text = "□ ⑤  □ ④  □ ③  □ ②  □ ①"
        row[4].text = law

    # 보안등급 결정
    doc.add_heading("보안등급 결정 (위원 기재)", level=2)
    ai_grade = res.get("최종등급", "")
    grade_rows = [
        ("보안과제", "국가안보 위한 별도 관리 필요 → 강력한 통제 및 비공개 관리"),
        ("민감과제", "국가전략에 잠재적 영향 줄 수 있어 추가 관리 필요 → 기관·연구자 단위 관리하되 개방 가능"),
        ("일반과제", "유출 시 국가안보 및 전략 등 영향 제한적 → 성과공개·확산 원칙"),
    ]
    gt = doc.add_table(rows=len(grade_rows), cols=3)
    gt.style = "Table Grid"
    for i, (g, desc) in enumerate(grade_rows):
        gt.cell(i, 0).text = g
        gt.cell(i, 1).text = "□"
        mark = "  ← AI 참고의견" if g and g in ai_grade else ""
        gt.cell(i, 2).text = desc + mark

    # 종합 의견 서술
    doc.add_heading("종합 의견 서술", level=2)
    doc.add_paragraph("등급 결정에 가장 중요하게 고려한 지표 및 이유:")
    doc.add_paragraph(f"(AI 참고: {s4.get('key_factor', '-')})")
    doc.add_paragraph("\n\n")
    doc.add_paragraph("위원회 종합 토론 시 중점 논의가 필요한 사항:")
    doc.add_paragraph(f"(AI 참고: {s4.get('committee_discussion_points', '-')})")
    doc.add_paragraph("\n\n")

    # 제출 확인
    doc.add_heading("제출 확인", level=2)
    st = doc.add_table(rows=3, cols=2)
    st.style = "Table Grid"
    st.cell(0, 0).text = "제출일시"
    st.cell(0, 1).text = "20    년     월     일"
    st.cell(1, 0).text = "평가위원 서명"
    st.cell(1, 1).text = "(서명)"
    st.cell(2, 0).text = "간사 확인"
    st.cell(2, 1).text = "(서명)"

    # 참조 별표 출처
    doc.add_paragraph("")
    doc.add_paragraph(res.get("참조별표", sources_note()))

    doc.save(path)
    return path


def _matched_reference(res, item_name):
    """2단계 criteria에서 해당 항목에 대조된 별표 기술명 추출."""
    for c in res.get("2_기준검토", {}).get("criteria", []):
        nm = str(c.get("item", ""))
        if item_name in nm or nm in item_name:
            return str(c.get("matched_reference", ""))
    return ""


# =========================================================
# 8. GUI (스레드 처리로 화면 멈춤 방지)
# =========================================================
# ── GUI 디자인 토큰 ──
# 팔레트: 정부 심의 문서의 신뢰감 — 딥 잉크 헤더 + 코발트 액센트, 종이색 배경
UI = {
    "bg":      "#F5F6F8",   # 종이(창 배경)
    "card":    "#FFFFFF",   # 카드
    "header":  "#16233F",   # 딥 잉크(헤더)
    "accent":  "#2456C4",   # 코발트(주요 동작·활성 탭)
    "accent2": "#1B429C",   # 코발트 hover
    "soft":    "#EAF0FC",   # 액센트 연한 배경
    "text":    "#1E2530",
    "sub":     "#5B6472",
    "warn":    "#B4232A",
    "warnbg":  "#FCECEC",
    "ok":      "#1E6E43",
    "okbg":    "#245C43",
    "line":    "#DCE1EA",
    "font":    "맑은 고딕",
}


def _setup_style(root):
    """clam 테마 기반 플랫 스타일 정의."""
    from tkinter import ttk
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    F = UI["font"]
    root.configure(bg=UI["bg"])
    style.configure(".", font=(F, 10), background=UI["bg"], foreground=UI["text"])
    style.configure("Card.TFrame", background=UI["card"])
    style.configure("Card.TLabel", background=UI["card"], foreground=UI["text"])
    style.configure("CardSub.TLabel", background=UI["card"], foreground=UI["sub"], font=(F, 9))
    style.configure("CardTitle.TLabel", background=UI["card"], foreground=UI["text"],
                    font=(F, 10, "bold"))
    style.configure("Ok.TLabel", background=UI["card"], foreground=UI["ok"], font=(F, 9, "bold"))
    style.configure("TButton", font=(F, 10), padding=(14, 7), background="#E9EDF3",
                    foreground=UI["text"], borderwidth=0, focusthickness=0)
    style.map("TButton", background=[("active", "#DBE1EA"), ("disabled", "#F1F3F7")],
              foreground=[("disabled", "#A9B0BD")])
    style.configure("Accent.TButton", background=UI["accent"], foreground="#FFFFFF",
                    font=(F, 10, "bold"), padding=(18, 8))
    style.map("Accent.TButton", background=[("active", UI["accent2"]),
                                            ("disabled", "#9FB6E8")])
    style.configure("TEntry", fieldbackground="#FFFFFF", bordercolor=UI["line"])
    style.configure("TCombobox", fieldbackground="#FFFFFF")
    style.configure("TCheckbutton", background=UI["card"])
    style.configure("TRadiobutton", background=UI["card"])
    style.configure("TSpinbox", fieldbackground="#FFFFFF")
    return style


def launch_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, scrolledtext

    # Windows 배율(125/150%) 환경에서 창이 잘려 보이는 문제 방지 — DPI 인식 선언
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    root.title("연구보안 등급분류 시뮬레이터(ver26.7)")
    # 화면 크기에 맞춰 창 크기 자동 조정 + 중앙 배치 (최초 실행 시 잘림 방지)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = min(1200, sw - 80), min(1500, sh - 120)
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(8, (sh - h) // 2 - 24)}")
    root.minsize(950, 850)
    try:
        root.iconbitmap(resource_path("book_icon.ico"))
    except Exception:
        pass
    _setup_style(root)
    F = UI["font"]

    busy = threading.Event()
    last = {"task": None, "res": None}      # 최근 단건 결과(심의서용)
    last_batch = {"path": None}              # 최근 대량 결과 파일
    stat = {"t0": None, "batch": None}       # 상태바: 시작시각 / 대량 진행 문구

    # ══════════════ grid 레이아웃 — 로그 영역만 신축, 나머지 고정(하단 잘림 방지) ══════════════
    root.rowconfigure(4, weight=1)
    root.columnconfigure(0, weight=1)

    # ── 헤더 ──
    header = tk.Frame(root, bg=UI["header"])
    header.grid(row=0, column=0, sticky="ew")
    tk.Label(header, text="연구보안 등급분류 시뮬레이터", bg=UI["header"], fg="#FFFFFF",
             font=(F, 15, "bold")).pack(side="left", padx=(18, 8), pady=11)
    tk.Label(header, text="KISTEP 연구윤리자산보호센터 · ver26.7", bg=UI["header"], fg="#8FA5C6",
             font=(F, 10)).pack(side="left", pady=11)
    provider_badge = tk.Label(header, text="", bg="#26395F", fg="#FFFFFF",
                              font=(F, 9, "bold"), padx=10, pady=3)
    provider_badge.pack(side="right", padx=16)

    banner = tk.Label(root, text=DISCLAIMER + "\n ·  외부 API 사용 시 과제정보가 외부로 전송될 수 있습니다. — "
                      "비공개 정보는 로컬 LLM(ollama/LM Studio) 사용 권장",
                      bg=UI["warnbg"], fg=UI["warn"], font=(F, 9), anchor="w", justify="left",
                      wraplength=w - 40, padx=14, pady=5)
    banner.grid(row=1, column=0, sticky="ew")
    # 창 크기 변경 시 배너 줄바꿈 폭 추종
    root.bind("<Configure>", lambda e: banner.config(wraplength=max(600, root.winfo_width() - 40))
              if e.widget is root else None, add="+")

    # ── 세그먼트 내비게이션 (크기 고정 · 활성 탭은 색상+언더라인만 변경) ──
    navstrip = tk.Frame(root, bg=UI["card"])
    navstrip.grid(row=2, column=0, sticky="ew")
    tk.Frame(navstrip, bg=UI["line"], height=1).pack(side="bottom", fill="x")

    content = tk.Frame(root, bg=UI["bg"])
    content.grid(row=3, column=0, sticky="ew", padx=12, pady=(10, 4))
    content.columnconfigure(0, weight=1)

    pages, nav_items = {}, {}

    def select_page(name):
        for n, (lbl, bar) in nav_items.items():
            active = (n == name)
            lbl.config(fg=UI["accent"] if active else UI["sub"],
                       font=(F, 10, "bold"))
            bar.config(bg=UI["accent"] if active else UI["card"])
        for n, fr in pages.items():
            fr.grid_remove()
        pages[name].grid(row=0, column=0, sticky="nsew")

    def add_page(name):
        holder = tk.Frame(navstrip, bg=UI["card"])
        holder.pack(side="left")
        lbl = tk.Label(holder, text=name, bg=UI["card"], fg=UI["sub"],
                       font=(F, 10, "bold"), padx=22, pady=10, cursor="hand2")
        lbl.pack()
        bar = tk.Frame(holder, bg=UI["card"], height=3)
        bar.pack(fill="x")
        for wdg in (holder, lbl):
            wdg.bind("<Button-1>", lambda e, n=name: select_page(n))
        lbl.bind("<Enter>", lambda e, l=lbl, n=name: l.config(
            fg=UI["accent"] if nav_items[n][1]["bg"] != UI["accent"] else UI["accent"]))
        lbl.bind("<Leave>", lambda e, l=lbl, n=name: l.config(
            fg=UI["accent"] if nav_items[n][1]["bg"] == UI["accent"] else UI["sub"]))
        page = tk.Frame(content, bg=UI["bg"])
        pages[name] = page
        nav_items[name] = (lbl, bar)
        return page

    def card(parent, title=None, subtitle=None):
        outer = tk.Frame(parent, bg=UI["line"])
        inner = ttk.Frame(outer, style="Card.TFrame", padding=(14, 10))
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        if title:
            ttk.Label(inner, text=title, style="CardTitle.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(inner, text=subtitle, style="CardSub.TLabel",
                      wraplength=900, justify="left").pack(anchor="w", pady=(1, 6))
        return outer, inner

    # ───────── 페이지 1: 단건 분류 ─────────
    tab_one = add_page("단건 분류")

    c1o, c1 = card(tab_one, "과제 정보 입력")
    c1o.pack(fill="x", pady=(0, 6))
    grid = ttk.Frame(c1, style="Card.TFrame")
    grid.pack(fill="x")
    fields = {}
    heights = {"과제명": 1, "연구목표": 2, "연구내용": 4, "기대효과": 2}
    for i, name in enumerate(["과제명", "연구목표", "연구내용", "기대효과"]):
        ttk.Label(grid, text=name, style="Card.TLabel").grid(
            row=i, column=0, sticky="ne", padx=(0, 10), pady=3)
        t = tk.Text(grid, width=92, height=heights[name], wrap="word", font=(F, 10),
                    relief="flat", highlightthickness=1,
                    highlightbackground=UI["line"], highlightcolor=UI["accent"])
        t.grid(row=i, column=1, pady=3, sticky="we")
        fields[name] = t
    grid.columnconfigure(1, weight=1)

    c2o, c2 = card(tab_one, "분류항목 선택",
                   "선택된 항목에 대해서만 '유출 시 국가영향 수준'을 판단합니다.")
    c2o.pack(fill="x", pady=(0, 6))
    auto_var = tk.BooleanVar(value=True)
    item_vars, item_checks = {}, []

    def toggle_items():
        state = "disabled" if auto_var.get() else "normal"
        for cbx in item_checks:
            cbx.config(state=state)

    ttk.Checkbutton(c2, text="자동 선택 — 법적 기준 체크리스트 기반으로 AI가 항목 선택",
                    variable=auto_var, command=toggle_items).pack(anchor="w", pady=(0, 4))
    ig = ttk.Frame(c2, style="Card.TFrame")
    ig.pack(fill="x")
    for i, item in enumerate(IMPACT_ITEMS):
        var = tk.BooleanVar(value=False)
        item_vars[item] = var
        cbx = ttk.Checkbutton(ig, text=f"{i + 1}. {item}", variable=var)
        cbx.grid(row=i // 4, column=i % 4, sticky="w", padx=(0, 16), pady=1)
        item_checks.append(cbx)
    toggle_items()

    row1 = tk.Frame(tab_one, bg=UI["bg"])
    row1.pack(fill="x")
    btn_single = ttk.Button(row1, text="단건 분류 실행", style="Accent.TButton")
    btn_form = ttk.Button(row1, text="위원용 심의서 저장 (.docx)", state="disabled")
    btn_single.pack(side="left", padx=(0, 8))
    btn_form.pack(side="left")

    # ───────── 페이지 2: 대량 분류 ─────────
    tab_batch = add_page("대량 분류")

    b1o, b1 = card(tab_batch, "①  입력 양식 생성",
                   "작성안내 시트가 포함된 양식을 생성하고 '분류대상' 시트에 과제정보를 입력하세요."
                   "\n ※ 회색 예시 행은 자동 제외됩니다")
    b1o.pack(fill="x", pady=(0, 6))
    ttk.Button(b1, text="양식 생성 후 열기",
               command=lambda: create_template()).pack(anchor="w", pady=(2, 0))

    b2o, b2 = card(tab_batch, "②  대량 분류 실행",
                   "결과는 건별 즉시 기록되며, 에러 발생 혹은 중단 후 재실행하면 완료 건은 자동으로 건너뜁니다.")
    b2o.pack(fill="x", pady=(0, 6))
    opt = ttk.Frame(b2, style="Card.TFrame")
    opt.pack(fill="x", pady=(2, 8))
    ttk.Label(opt, text="동시 처리", style="Card.TLabel").pack(side="left")
    workers_var = tk.IntVar(value=CONFIG.get("max_workers", 1))
    ttk.Spinbox(opt, from_=1, to=8, width=4, textvariable=workers_var).pack(
        side="left", padx=(6, 18))
    forms_var = tk.BooleanVar(value=True)  # 기본: 심의서 함께 생성
    ttk.Checkbutton(opt, text="과제별 심의서(.docx) 함께 생성 — 1,000건 초과 시 심의서 생성 불가",
                    variable=forms_var).pack(side="left")
    btn_batch = ttk.Button(b2, text="양식 업로드 및 분류 시작", style="Accent.TButton")
    btn_batch.pack(anchor="w")

    b3o, b3 = card(tab_batch, "③  결과 확인",
                   "결과 엑셀에는 과제별 등급분류(안) 및 판단근거 등 요약 자료가 포함됩니다.")
    b3o.pack(fill="x")
    btn_result = ttk.Button(b3, text="최근 분류결과 열기", state="disabled")
    btn_result.pack(anchor="w", pady=(2, 0))

    # ───────── 페이지 3: 설정 ─────────
    tab_set = add_page("설정")

    s1o, s1 = card(tab_set, "LLM API 설정", "입력하신 API Key는 저장되지 않습니다. Key 관리에 각별히 유의해 주시기 바랍니다.")
    s1o.pack(fill="x", pady=(0, 6))
    sg = ttk.Frame(s1, style="Card.TFrame")
    sg.pack(fill="x")
    ttk.Label(sg, text="제공자", style="Card.TLabel").grid(row=0, column=0, sticky="e", padx=(0, 6), pady=3)
    provider_var = tk.StringVar(value=CONFIG["provider"])
    cb = ttk.Combobox(sg, textvariable=provider_var, state="readonly", width=14,
                      values=["openai", "claude", "gemini", "ollama", "lmstudio"])
    cb.grid(row=0, column=1, sticky="w", pady=3)
    ttk.Label(sg, text="API Key", style="Card.TLabel").grid(row=0, column=2, sticky="e", padx=(18, 6))
    key_var = tk.StringVar()
    key_entry = ttk.Entry(sg, textvariable=key_var, width=36, show="*")
    key_entry.grid(row=0, column=3, sticky="w")
    ttk.Label(sg, text="모델명", style="Card.TLabel").grid(row=1, column=0, sticky="e", padx=(0, 6), pady=3)
    model_var = tk.StringVar(value=CONFIG[CONFIG["provider"]]["model"])
    model_combo = ttk.Combobox(sg, textvariable=model_var, width=30, state="normal",
                               values=MODEL_OPTIONS.get(CONFIG["provider"], []))
    model_combo.grid(row=1, column=1, columnspan=2, sticky="w", pady=3)
    ttk.Label(sg, text="서버 주소(로컬 전용)", style="Card.TLabel").grid(
        row=2, column=0, sticky="e", padx=(0, 6), pady=3)
    url_var = tk.StringVar(value=CONFIG["ollama"]["base_url"])
    url_entry = ttk.Entry(sg, textvariable=url_var, width=32)
    url_entry.grid(row=2, column=1, columnspan=2, sticky="w", pady=3)
    local_lbl = ttk.Label(sg, text="", style="Ok.TLabel")
    local_lbl.grid(row=3, column=1, columnspan=3, sticky="w")

    s2o, s2 = card(tab_set, "AI 분류위원 구성", "각 위원은 독립 에이전트가 생성되어 다른 관점에서 평가합니다.")
    s2o.pack(fill="x", pady=(0, 6))
    panel_var = tk.IntVar(value=CONFIG.get("reviewer_panel", 3))
    ttk.Radiobutton(s2, text="위원 1명 — 기술분야 전문가",
                    value=1, variable=panel_var).pack(anchor="w")
    ttk.Radiobutton(s2, text="위원 3명 — 기술분야 전문가 · 연구보안·수출통제 전문가 · 기술사업화 전문가",
                    value=3, variable=panel_var).pack(anchor="w")

    s3o, s3 = card(tab_set, "기타")
    s3o.pack(fill="x")
    r3 = ttk.Frame(s3, style="Card.TFrame")
    r3.pack(fill="x", pady=(2, 0))
    ttk.Button(r3, text="※ 국가핵심기술, 첨단전략기술 등 고시 항목 보기",
               command=lambda: show_reference()).pack(side="left", padx=(0, 14))
    json_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(r3, text="단건 결과에 상세 로그(.json) 함께 표시",
                    variable=json_var).pack(side="left")

    select_page("단건 분류")

    LOCAL_PROVIDERS = ("ollama", "lmstudio")

    def update_badge():
        p = provider_var.get()
        is_local = p in LOCAL_PROVIDERS
        provider_badge.config(
            text=f"{p} · {model_var.get()}  ·  {'로컬 API' if is_local else '외부 API'}",
            bg=UI["okbg"] if is_local else "#26395F")

    def on_provider_change(_=None):
        p = provider_var.get()
        model_var.set(CONFIG[p]["model"])
        model_combo["values"] = MODEL_OPTIONS.get(p, [])
        key_var.set(CONFIG[p].get("api_key", ""))
        if p in LOCAL_PROVIDERS:
            url_var.set(CONFIG[p]["base_url"])
            key_entry.config(state="disabled")
            url_entry.config(state="normal")
            local_lbl.config(text="✓ 로컬 실행 — 과제정보가 외부로 전송되지 않습니다.")
        else:
            key_entry.config(state="normal")
            url_entry.config(state="disabled")
            local_lbl.config(text="")
        update_badge()
    cb.bind("<<ComboboxSelected>>", on_provider_change)
    model_combo.bind("<<ComboboxSelected>>", lambda e: update_badge())
    on_provider_change()

    def apply_config():
        p = provider_var.get()
        CONFIG["provider"] = p
        if key_var.get().strip():
            CONFIG[p]["api_key"] = key_var.get().strip()
        CONFIG[p]["model"] = model_var.get().strip()
        CONFIG["reviewer_panel"] = panel_var.get()
        if p in LOCAL_PROVIDERS:
            if url_var.get().strip():
                CONFIG[p]["base_url"] = url_var.get().strip()
        elif not CONFIG[p]["api_key"]:
            messagebox.showwarning("설정", "API Key가 비어 있습니다. 설정 탭을 확인하세요.")
        update_badge()

    # ══════════════ 결과 / 로그 (신축 영역) ══════════════
    lo = tk.Frame(root, bg=UI["line"])
    lo.grid(row=4, column=0, sticky="nsew", padx=12, pady=(2, 4))
    lc = ttk.Frame(lo, style="Card.TFrame", padding=(14, 10))
    lc.pack(fill="both", expand=True, padx=1, pady=1)
    lhead = ttk.Frame(lc, style="Card.TFrame")
    lhead.pack(fill="x")
    ttk.Label(lhead, text="결과 / 로그", style="CardTitle.TLabel").pack(side="left")
    ttk.Button(lhead, text="지우기", width=7,
               command=lambda: out_box.delete("1.0", "end")).pack(side="right")
    out_box = scrolledtext.ScrolledText(lc, wrap="word", font=(F, 10), relief="flat",
                                        highlightthickness=1, height=8,
                                        highlightbackground=UI["line"], bg="#FFFFFF")
    out_box.pack(fill="both", expand=True, pady=(6, 0))

    _MAX_LOG_LINES = 9000  # 대량 처리 시 로그 누적으로 GUI가 느려지는 것 방지

    def log(msg):
        out_box.insert("end", msg + "\n")
        try:
            if int(out_box.index("end-1c").split(".")[0]) > _MAX_LOG_LINES:
                out_box.delete("1.0", f"{_MAX_LOG_LINES // 3}.0")
        except (ValueError, tk.TclError):
            pass
        out_box.see("end")

    def log_threadsafe(msg):
        root.after(0, log, msg)

    # ══════════════ 상태바 — 상태 점 + 경과/잔여 예상 시간 ══════════════
    status = tk.Frame(root, bg=UI["bg"])
    status.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 8))
    dot = tk.Label(status, text="●", bg=UI["bg"], fg="#9AA3B2", font=(F, 10))
    dot.pack(side="left")
    status_lbl = tk.Label(status, text="대기 중", bg=UI["bg"], fg=UI["sub"], font=(F, 9))
    status_lbl.pack(side="left", padx=(4, 0))
    tk.Label(status, text="Powered by MIN", bg=UI["bg"], fg="#A9B0BD",
             font=(F, 9)).pack(side="right")

    def tick():
        """1초 주기 상태바 갱신 — 대량 분류는 잔여 예상, 단건은 경과 시간 표시."""
        if busy.is_set() and stat["t0"]:
            if stat["batch"]:
                status_lbl.config(text=stat["batch"])
            else:
                e = int(time.time() - stat["t0"])
                status_lbl.config(text=f"분류 중 · 경과 {e // 60}:{e % 60:02d}")
        root.after(1000, tick)
    tick()

    def set_busy(state, text="처리 중..."):
        busy.set() if state else busy.clear()
        s = "disabled" if state else "normal"
        btn_single.config(state=s)
        btn_batch.config(state=s)
        btn_form.config(state="disabled" if state or not last["res"] else "normal")
        if state:
            stat["t0"], stat["batch"] = time.time(), None
            dot.config(fg=UI["accent"])
            status_lbl.config(text=text)
        else:
            stat["t0"], stat["batch"] = None, None
            dot.config(fg="#9AA3B2")
            status_lbl.config(text="대기 중")

    # ══════════════ 동작 핸들러 ══════════════
    def create_template():
        p = make_template()
        log(f"양식 생성: {p} (작성안내 시트 참고, 회색 예시 행은 자동 제외)")
        if messagebox.askyesno("엑셀 양식",
                               f"양식이 생성되었습니다.\n{os.path.abspath(p)}\n\n지금 열어보시겠습니까?"):
            _open_file(p)

    def show_reference():
        win = tk.Toplevel(root)
        win.title("법령 고시 자료(분류 참조 데이터)")
        win.geometry("1100x1300")
        win.configure(bg=UI["bg"])
        tk.Label(win, text="프로그램에 내장되어 2단계 체크리스트·3단계 채점 시 AI 프롬프트에 제공되는 참조 자료입니다.\n"
                           "※ 고시 기술항목 및 사양은 개정될 수 있으니 정확한 사양은 최신 원문(국가법령정보센터 등)과 대조하세요.",
                 bg=UI["warnbg"], fg=UI["warn"], font=(F, 9), justify="left", anchor="w",
                 padx=12, pady=6).pack(fill="x", padx=10, pady=(10, 6))
        box = scrolledtext.ScrolledText(win, wrap="word", font=(F, 10), relief="flat",
                                        highlightthickness=1, highlightbackground=UI["line"])
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        lines = ["[출처]"]
        for s in REFERENCE_SOURCES_LIST:
            lines.append(f" · {s['title']} — {s['authority']} {s['notice_no']} "
                         f"({s['effective']}), {s['scope']}\n   {s['url']}")
        lines.append("\n" + build_reference_prompt(None))
        box.insert("1.0", "\n".join(lines))
        box.config(state="disabled")

    def run_single():
        if busy.is_set():
            return
        apply_config()
        task = {k: v.get("1.0", "end").strip() for k, v in fields.items()}
        if not task["과제명"]:
            messagebox.showwarning("입력", "과제명을 입력하세요.")
            select_page("단건 분류")
            return
        if auto_var.get():
            selected_override = None
        else:
            selected_override = [it for it, v in item_vars.items() if v.get()]
            if not selected_override:
                messagebox.showwarning(
                    "분류항목", "분류항목을 1개 이상 수동 선택하거나 '자동 선택'을 사용하세요.")
                return
        set_busy(True, f"단건 분류 중 — {task['과제명'][:24]}")
        panel = panel_var.get()
        log(f"\n=== {task['과제명']} 분류 시작 (위원 {panel}명"
            f"{', 항목 자동 선택' if selected_override is None else ', 항목 직접 선택'}) ===")

        def worker():
            try:
                llm = LLMClient(CONFIG)
                res = classify_one(llm, task, selected_override=selected_override)
                last["task"], last["res"] = task, res
                log_threadsafe(format_report(res))
                if json_var.get():
                    log_threadsafe("[상세 JSON]")
                    log_threadsafe(json.dumps(res, ensure_ascii=False, indent=2))
                log_threadsafe("→ '위원용 심의서 저장' 버튼으로 붙임2 양식(.docx)을 생성할 수 있습니다.")

                def reflect():  # AI 자동 선택 결과를 체크박스에 반영(참고 표시)
                    for it, v in item_vars.items():
                        v.set(it in res.get("선택항목", []))
                root.after(0, reflect)
            except Exception as e:
                log_threadsafe(f"[오류] {e}")
            finally:
                root.after(0, set_busy, False)
        threading.Thread(target=worker, daemon=True).start()

    def save_review_form():
        if not last["res"]:
            messagebox.showwarning("심의서", "먼저 단건 분류를 실행하세요.")
            return
        default = _safe_filename(last["task"].get("과제명", "심의서")) + "_심의서.docx"
        path = filedialog.asksaveasfilename(defaultextension=".docx", initialfile=default,
                                            filetypes=[("Word 문서", "*.docx")])
        if not path:
            return
        try:
            export_review_form_docx(last["task"], last["res"], path)
            log(f"위원용 심의서 저장 완료: {path}")
        except Exception as e:
            messagebox.showerror("심의서", str(e))

    def open_last_batch():
        if last_batch["path"] and os.path.exists(last_batch["path"]):
            _open_file(last_batch["path"])
        else:
            messagebox.showinfo("분류결과", "아직 생성된 분류결과 파일이 없습니다.")

    def run_batch():
        if busy.is_set():
            return
        apply_config()
        CONFIG["max_workers"] = max(1, min(8, int(workers_var.get() or 1)))
        f = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if not f:
            return
        set_busy(True, f"대량 분류 준비 중 (동시 처리 {CONFIG['max_workers']})")
        log(f"\n=== 엑셀 대량 분류: {f} (동시 처리 {CONFIG['max_workers']}) ===")

        def on_status(text):  # run_excel → 상태바(잔여 예상시간) — tick()이 표시
            stat["batch"] = text

        def worker():
            try:
                out = run_excel(f, progress_cb=log_threadsafe,
                                make_forms=forms_var.get(), status_cb=on_status)
                last_batch["path"] = out

                def done():
                    btn_result.config(state="normal")
                    if messagebox.askyesno("대량 분류 완료",
                                           f"분류가 완료되었습니다.\n{os.path.abspath(out)}\n\n"
                                           f"결과 파일을 지금 열어보시겠습니까?"):
                        _open_file(out)
                root.after(0, done)
            except Exception as e:
                log_threadsafe(f"[오류] {e}")
            finally:
                root.after(0, set_busy, False)
        threading.Thread(target=worker, daemon=True).start()

    btn_single.config(command=run_single)
    btn_form.config(command=save_review_form)
    btn_batch.config(command=run_batch)
    btn_result.config(command=open_last_batch)

    root.mainloop()


# =========================================================
if __name__ == "__main__":
    launch_gui()
    # 코드로 직접 실행:
    # make_template()
    # run_excel("분류대상_양식.xlsx")
