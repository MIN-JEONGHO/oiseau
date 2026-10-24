# -*- coding: utf-8 -*-
"""공공데이터 등록 사전검토 프로그램 — 파일데이터 · OPEN API."""
__version__ = "3.0.0"
CRITERIA_VERSION = "26.2. 배포 매뉴얼 기준"
RELEASE_DATE = "2026-08-03"
AUTHOR = "MIN"

#: 검토 영역. 안내 매뉴얼이 파일데이터용과 OPEN API 용으로 나뉘어 있어
#: 조항 번호가 서로 겹치므로, 결과·픽스·리포트 모두 이 값으로 갈라 본다.
DOMAIN_FILE = "file"
DOMAIN_API = "api"
DOMAIN_LABEL = {DOMAIN_FILE: "파일데이터", DOMAIN_API: "OPEN API"}
