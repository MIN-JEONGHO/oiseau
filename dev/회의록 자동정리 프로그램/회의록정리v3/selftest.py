# -*- coding: utf-8 -*-
"""
API 키 없이 돌려보는 자체 점검.

  python selftest.py

가짜 요약 결과로 template.hwpx 를 채워 보고, 만들어진 파일의 표 구조가
의도대로(기관 수 x 항목 수) 나왔는지 확인한다. 한글에서 열어 보기 전에
구조가 깨지지 않았는지 빠르게 보기 위한 용도.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from lxml import etree

import hwpx_writer as HW
from hwpx_writer import Document, fill_hwpx
from stt import Segment, Transcript
from summarizer import Attendee, InstitutionSummary, Summary, SummaryItem

HERE = Path(__file__).resolve().parent


def sample() -> tuple[Document, list[Attendee]]:
    attendees = [
        Attendee("홍길동", "과학기술정보통신부", "사무관"),
        Attendee("김철수", "한국연구재단", "팀장"),
        Attendee("이영희", "한국연구재단", "선임연구원"),
        Attendee("박민수", "KISTEP", "연구위원"),
    ]
    summary = Summary(
        title="연구윤리 제도개선 실무",
        agenda="연구부정행위 검증 절차 개선, 기관별 자체규정 정비 현황 점검",
        institutions=[
            InstitutionSummary("과학기술정보통신부", [
                SummaryItem("제도 개선", "연구윤리 확보 지침 개정안을 연내 확정할 계획임."),
                SummaryItem("자료 제출", "기관별 자체규정 정비 현황을 10월까지 제출 요청함."),
                SummaryItem("예산", "검증 지원 예산은 내년도 본예산에 반영을 검토 중임."),
            ]),
            InstitutionSummary("한국연구재단", [
                SummaryItem("검증 절차", "제보 접수 후 예비조사 착수까지 평균 21일이 소요되어\n"
                                      "기간 단축이 필요하다는 의견임."),
                SummaryItem("애로사항", "전담 인력이 2명에 불과해 사건 적체가 발생하고 있음."),
            ]),
            InstitutionSummary("KISTEP", [
                SummaryItem("실태조사", "2026년 연구윤리 실태조사 문항을 개편할 예정임."),
            ]),
        ],
        implications="검증 절차의 기간 단축과 전담 인력 확충이 동시에 필요함.",
        feedback_plan="10월 중 기관별 정비 현황을 취합하고, 11월 실무협의회에서 개정안을 논의함.",
    )
    tr = Transcript(engine="selftest", has_diarization=True, duration=180.0)
    lines = [
        ("홍길동", "안녕하십니까. 과기정통부 홍길동입니다. 오늘 회의를 시작하겠습니다."),
        ("홍길동", "연구윤리 확보 지침 개정안은 연내 확정을 목표로 하고 있습니다."),
        ("김철수", "재단에서는 제보 접수 후 예비조사 착수까지 평균 21일이 걸립니다."),
        ("이영희", "전담 인력이 두 명뿐이라 사건이 쌓이고 있는 상황입니다."),
        ("박민수", "내년 실태조사 문항을 개편하려고 준비 중입니다."),
    ]
    for i, (spk, text) in enumerate(lines):
        tr.segments.append(Segment(i, i * 30.0, i * 30.0 + 28.0, text, spk))

    doc = Document(
        summary=summary, attendees=attendees,
        meeting_date="2026-09-04",
        when_where="’26. 9. 4.(금) 14:00 / KISTEP 3층 중회의실",
        transcript=tr, attach_transcript=True,
    )
    return doc, attendees


def inspect(path: Path) -> None:
    q = lambda t: f"{{{HW.HP}}}{t}"  # noqa: E731
    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read(HW.SECTION))
    tbl = HW._find_summary_table(root)
    trs = tbl.findall(q("tr"))
    print(f"  기관별 요약 표: rowCnt={tbl.get('rowCnt')} (실제 {len(trs)}행), "
          f"colCnt={tbl.get('colCnt')}")
    for ri, tr in enumerate(trs):
        cells = HW._cells(tr)
        desc = []
        for tc in cells:
            a, s = HW._addr(tc), HW._span(tc)
            txt = " / ".join(x.strip() for x in tc.itertext() if x.strip())[:40]
            desc.append(f"c{a.get('colAddr')}(span{s.get('rowSpan')}) {txt!r}")
        assert all(int(HW._addr(tc).get("rowAddr")) == ri for tc in cells), \
            f"{ri}행 rowAddr 불일치"
        print(f"    row{ri:<2} " + " | ".join(desc))

    body = "".join(t.text or "" for t in root.iter(q("t")))
    for ph in (HW.PH_TITLE, HW.PH_AGENDA, HW.PH_ATTEND, HW.PH_WHEN_WHERE,
               HW.PH_IMPLICATION, HW.PH_FEEDBACK, HW.PH_TRANSCRIPT):
        assert ph not in body, f"자리표시자가 남아 있음: {ph!r}"
    print("  자리표시자 치환: 모두 완료")
    n = sum(1 for p in root.iter(q("p")) if _text(p).startswith("   -  ("))
    print(f"  회의록 원문 문단: {n}줄")


def _text(p) -> str:
    return "".join(t.text or "" for t in p.iter(f"{{{HW.HP}}}t"))


def main() -> int:
    tpl = HERE / "template.hwpx"
    if not tpl.exists():
        print(f"[실패] 양식이 없습니다: {tpl}")
        return 1
    out = HERE / "_selftest_결과.hwpx"
    doc, _ = sample()

    print("1) hwpx 생성")
    fill_hwpx(tpl, out, doc)
    print(f"   -> {out.name} ({out.stat().st_size:,} bytes)")

    print("2) 구조 확인")
    inspect(out)

    print("3) 전사문 텍스트 저장")
    txt = HW.write_transcript_txt(HERE / "_selftest_전사문.txt", doc.transcript, doc.summary.title)
    print(f"   -> {Path(txt).name}")

    print("\n점검 통과. 한글에서 _selftest_결과.hwpx 를 열어 표가 정상인지 확인해 주세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
