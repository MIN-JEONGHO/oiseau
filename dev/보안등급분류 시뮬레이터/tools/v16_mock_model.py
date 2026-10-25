"""Input-based deterministic mock JSON model for offline v16 checks.

Public contract:
    MockModel().ask_json(system_prompt, user_prompt, temperature=None) -> dict
    MockModel.provider / MockModel.model == 'claude' / 'claude-sonnet-5-5'
    MockModel().call_log() -> list of {phase, partial, system_chars, prompt_chars,
                                       response_chars, timestamp, task_name}
    tokens(text) -> distinctive clause words used by the screen phase

The reply depends only on the prompt text (no network, key, SDK or randomness);
task-level choices use sha256 of the task name, never the salted built-in
hash function. One client
is meant per task, so its call log describes that task's calls.

Notice phases (user_prompt JSON with ``phase``):
* facts: number+unit facts inside the received segment only. Offsets are those
  of the cleaned field; basis comes from notice_review_v16._checked_fact and
  every fact is pre-checked with v16_domain.validate_fact. A quote touching an
  edge of the segment is skipped (the text beyond it is unknown), and at most
  MAX_SEGMENT_FACTS facts are returned so the screen context stays small.
* screen: every supplied clause gets a decision with a non-empty reason. A
  clause is a candidate only on a distinctive match: its whole title (spaces
  ignored) or one of its distinctive words (see tokens) occurs in the task text.
  Fragment requests (partial_context) answer every header clause from the
  strings present in that fragment and never fail.
* compare: for each distinct leaf subject, current and target facts are taken
  from the lines of '현재 기술사양' / '개발목표 사양' that carry the subject
  ('<subject> <value><unit>' for numeric leaves, the subject phrase itself for
  qualitative leaves). Qualitative leaves get {current,target} assessments with
  fact IDs; numeric leaves are left to Python. affected_items: core [3],
  dual_use/military [4], advanced [2].

Classification stages (``stage``): candidate is true with empty uncertainty
whenever the notice review has candidates, otherwise decided by the task-name
digest. Criteria, reviewers and summary pass the v16 validators: no 판단곤란,
law_refs on every 해당/일부, matched_reference equal to the comparison links,
no expert-review flag, reviewer notice comments for every comparison, and a
final grade equal to the rule grade. Scores follow the task-name digest so that
different tasks reach different grades.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import time

_PROJECT = Path(__file__).resolve().parents[1]
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

import notice_review_v16 as nr  # noqa: E402
import v16_domain as d  # noqa: E402


PROVIDER = 'claude'
MODEL = 'claude-sonnet-5-5'
MAX_SEGMENT_FACTS = 6
_SPEC_BASIS = {'현재 기술사양': 'current', '개발목표 사양': 'target'}

# Common words never make a clause a candidate on their own (spec 4.5 list plus
# generic research vocabulary that appears in most task descriptions).
STOP_WORDS = frozenset("""
기술 설계 제조 공정 원문 통제기준 이상 이하 이상의 이하급 시스템 장치 해당하는 해당되는
위한 가능한 적용되는 제외 이중용도품목 공통정의 주석 군용물자목록 반도체 정보통신 디스플레이 3차원
고성능 차세대 데이터 소프트웨어 스마트 친환경 초고속 고정밀 고강도 고품질 고효율 고용량 고에너지밀도
플랫폼 인공지능 딥러닝 엔지니어링 프로그램 신뢰성 연료전지 자율주행 바이오 모바일 자동차 이동형
산업용 발전용 대규모 중대형 초소형 대구경 핵심기자재 통합제어관리 통합통제 신호처리 무선장치 통신장비
시스템기술 공정기술 제조기술 설계기술 검사기술 소자기술 평가기술 구동기술 자동제어 연동제어 안전제어
정도관리 상황인식 고부가가치 해양시스템 해양구조물 해양플랜트 고온 저온 저압 고압 극저온
이차전지 배터리 웨이퍼 원자력 이동통신 우주항공 사이버보안 모빌리티
application system display driver processor mode true stage narrow
""".split())
_PARTICLE_ENDINGS = ('은', '는', '을', '를', '의', '에', '에서', '으로', '로', '와', '과', '및', '이', '가',
                     '도', '만', '하고', '하는', '하며', '하여', '한', '된', '되는', '인', '적', '에게',
                     '까지', '부터')
_TOKEN = re.compile(r'[가-힣A-Za-z0-9]+')
_HANGUL = re.compile(r'[가-힣]')
_NUMBER = re.compile(r'(?<![A-Za-z0-9_.,+\-−])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d,.]\d)')
_UNIT_KEYS = sorted(d._UNITS, key=len, reverse=True)
_BULLET = re.compile(r'[\s\-–•·○◦▪●■□*]+')
_SENTENCE_END = re.compile(r'[;。!?]|\.(?=\s)')


def _digest(*parts):
    return hashlib.sha256('\x1f'.join(str(part) for part in parts).encode('utf-8')).digest()


def _compact(text):
    return re.sub(r'\s+', '', text).casefold()


def tokens(text):
    """Distinctive clause words: 3+ characters, not common, no particle ending.

    Words without Hangul shorter than four characters, pure numbers and words
    ending in a particle/ending (e.g. ~의, ~을, ~하고) are dropped.
    """
    out = []
    for token in _TOKEN.findall(text):
        if len(token) < 3 or token.isdigit() or token.casefold() in STOP_WORDS:
            continue
        if not _HANGUL.search(token):
            if len(token) < 4:
                continue
        elif _HANGUL.match(token[-1]) and token.endswith(_PARTICLE_ENDINGS):
            continue
        if token not in out:
            out.append(token)
    return out


def _match(title, code, text):
    """Return a reason for a distinctive match, or None."""
    whole = _compact(title)
    if whole and whole in _compact(text):
        return '조항 제목 전체가 과제 글에 있습니다.'
    folded = text.casefold()
    for token in tokens(title + ' ' + code):
        if token.casefold() in folded:
            return f"조항의 고유 낱말 '{token}'이(가) 과제 글에 있습니다."
    return None


def _fact_id(field, start, end, subject):
    return 'f-' + hashlib.sha256(f'{field}\x1f{start}\x1f{end}\x1f{subject}'.encode('utf-8')).hexdigest()[:16]


def _fact(field, start, end, quote, subject, value_text, number, unit):
    return dict(fact_id=_fact_id(field, start, end, subject), basis=_SPEC_BASIS.get(field, 'unspecified'),
                subject=subject, value_text=value_text, number=number, unit=unit,
                source_field=field, start=start, end=end, quote=quote)


def _checked(fact, snapshot):
    try:
        checked = nr._checked_fact(fact, snapshot)
        d.validate_fact(checked, snapshot)
        return checked
    except Exception:
        return None


def _unit_at(text, position):
    """The longest declared unit written at ``position`` (spaces allowed before)."""
    while position < len(text) and text[position] == ' ':
        position += 1
    for unit in _UNIT_KEYS:
        end = position + len(unit)
        if text.startswith(unit, position) and not (end < len(text) and re.match(r'[A-Za-z0-9/]', text[end])):
            return unit, end
    return None, None


def _sentence(text, position):
    """(start, end) of the sentence around ``position`` inside one line."""
    line_start = text.rfind('\n', 0, position) + 1
    line_end = text.find('\n', position)
    line_end = len(text) if line_end < 0 else line_end
    start = line_start
    for match in _SENTENCE_END.finditer(text, line_start, position):
        start = match.end()
    end = line_end
    match = _SENTENCE_END.search(text, position, line_end)
    if match is not None:
        end = match.end() if match.group() in '.。!?' else match.start()
    bullet = _BULLET.match(text, start)
    if bullet is not None and bullet.end() <= position:
        start = bullet.end()
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _segment_facts(segment):
    field, offset, text = segment['source_field'], segment['start'], segment['text']
    # The validator reads the whole field; outside the segment nothing is known,
    # so it sees blanks there and quotes touching an edge are skipped.
    snapshot = {field: ' ' * offset + text}
    facts, used = [], set()
    for token in _NUMBER.finditer(text):
        if len(facts) >= MAX_SEGMENT_FACTS:
            break
        unit, unit_end = _unit_at(text, token.end())
        if unit is None:
            continue
        start, end = _sentence(text, token.start())
        if (start, end) in used or (start == 0 and offset > 0) or not text[end:].strip() or len(text) - end < 8:
            continue
        prefix = text[start:token.start()].strip().rstrip(':=').strip()
        words = prefix.split()
        if not words or not re.search(r'[가-힣A-Za-z]', words[-1]):
            continue
        subject = prefix if field in _SPEC_BASIS else ' '.join(words[-3:])
        fact = _fact(field, offset + start, offset + end, text[start:end], subject,
                     text[token.start():unit_end], token.group().replace(',', ''), unit)
        checked = _checked(fact, snapshot)
        if checked is not None:
            used.add((start, end))
            facts.append(checked)
    return facts


def _fields(segments):
    """Rebuild the cleaned task fields from complete request segments."""
    buffers = {}
    for segment in segments:
        buffer = buffers.setdefault(segment['source_field'], [])
        if len(buffer) < segment['end']:
            buffer.extend([''] * (segment['end'] - len(buffer)))
        buffer[segment['start']:segment['start'] + len(segment['text'])] = list(segment['text'])
    snapshot = {column: '' for column in d.TASK_COLUMNS + d.OPTIONAL_TASK_COLUMNS}
    snapshot.update({field: ''.join(buffer) for field, buffer in buffers.items()})
    return snapshot


def _lines(text):
    position = 0
    for line in text.split('\n'):
        bullet = _BULLET.match(line)
        start = bullet.end() if bullet is not None else 0
        content = line[start:].rstrip()
        if content:
            yield position + start, content
        position += len(line) + 1


def _spec_fact(leaf, field, snapshot):
    """The fact for one leaf subject on its own line of a specification field."""
    subject = leaf['subject']
    for start, content in _lines(snapshot[field]):
        if leaf['type'] == 'numeric':
            if not content.startswith(subject):
                continue
            rest = content[len(subject):]
            lead = re.match(r'[\s:=]*', rest).end()
            token = _NUMBER.match(rest, lead)
            if lead == 0 or token is None:
                continue
            unit_text = rest[token.end():].strip().split()
            if not unit_text:
                continue
            unit = unit_text[0]
            unit_end = rest.index(unit, token.end()) + len(unit)
            begin = len(subject) + token.start()
            fact = _fact(field, start, start + len(content), content, subject,
                         content[begin:len(subject) + unit_end], token.group().replace(',', ''), unit)
        else:
            if _compact(subject) not in _compact(content):
                continue
            fact = _fact(field, start, start + len(content), content, subject,
                         subject if subject in content else content, None, None)
        checked = _checked(fact, snapshot)
        if checked is not None:
            return checked
    return None


def _affected(family):
    return [3] if family == 'core' else [4] if family in ('dual_use', 'military') else [2]


def _paths(parts):
    """Complete strings of a fragment, keyed by JSON pointer."""
    pieces = {}
    for record in parts:
        if isinstance(record, dict) and isinstance(record.get('text'), str):
            pieces.setdefault(record['path'], []).append(record)
    complete, partial_text = {}, []
    for path, records in pieces.items():
        records.sort(key=lambda r: r.get('start', 0))
        joined = ''.join(r['text'] for r in records)
        partial_text.append((path, joined))
        if records[0].get('start') == 0 and len(joined) == records[0].get('total'):
            complete[path] = joined
    return complete, partial_text


class MockModel:
    """Deterministic stand-in for the pinned v16 JSON client (one per task)."""

    provider = PROVIDER
    model = MODEL

    def __init__(self):
        self._calls = []

    def call_log(self):
        return deepcopy(self._calls)

    def ask_json(self, system_prompt, user_prompt, temperature=None):
        data = json.loads(user_prompt)
        if not isinstance(data, dict):
            raise ValueError('지원하지 않는 요청입니다.')
        name = None
        if 'phase' in data:
            phase = data['phase']
            if data.get('partial_context'):
                response = self._fragment(data)
            elif phase == 'facts':
                segment = data['segment']
                if segment['source_field'] == '과제명' and segment['start'] == 0:
                    name = segment['text']
                response = dict(facts=_segment_facts(segment))
            elif phase == 'screen':
                name = _fields(data['task_segments'])['과제명'] or None
                response = self._screen(data)
            elif phase == 'compare':
                name = _fields(data['task_segments'])['과제명'] or None
                response = self._compare(data)
            else:
                raise ValueError('지원하지 않는 요청 단계입니다.')
        elif 'stage' in data:
            phase = data['stage']
            name = data['task']['과제명']
            response = self._classify(data)
        else:
            raise ValueError('지원하지 않는 요청입니다.')
        self._calls.append(dict(phase=phase, partial=bool(data.get('partial_context')),
                                system_chars=len(system_prompt), prompt_chars=len(user_prompt),
                                response_chars=len(json.dumps(response, ensure_ascii=False)),
                                timestamp=time.time(), task_name=name))
        return response

    # Notice phases -----------------------------------------------------------

    def _screen(self, data):
        text = '\n'.join(segment['text'] for segment in data['task_segments'])
        decisions = []
        for clause in data['clauses']:
            reason = _match(clause.get('title', ''), clause.get('code', ''), text)
            decisions.append(dict(clause_id=clause['clause_id'], candidate=reason is not None,
                                  reason=reason or '과제 글에 조항 제목이나 고유 낱말이 없습니다.'))
        return dict(decisions=decisions)

    def _fragment(self, data):
        complete, pieces = _paths(data.get('parts', []))
        if data['phase'] == 'compare':
            return dict(facts=[], conditions=[], affected_items=_affected(data['clause']['family']),
                        rationale='조각 요청이라 전체 조건을 판단하지 않았습니다.')
        text = '\n'.join(value for path, value in pieces if re.fullmatch(r'/task_segments/\d+/text', path))
        decisions = []
        for index, clause in enumerate(data['clauses']):
            title = complete.get(f'/clauses/{index}/title')
            code = complete.get(f'/clauses/{index}/code', '')
            reason = _match(title, code, text) if title is not None and text else None
            decisions.append(dict(clause_id=clause['clause_id'], candidate=reason is not None,
                                  reason=reason or '이 조각에서 뚜렷한 일치를 찾지 못했습니다.'))
        return dict(decisions=decisions)

    def _compare(self, data):
        clause = data['clause']
        snapshot = _fields(data['task_segments'])
        existing = data.get('facts', [])
        facts, conditions, found = [], [], {}
        leaves = [leaf for leaf in d.condition_leaves(clause['condition']) if leaf['type'] != 'unsupported']
        for leaf in leaves:
            for field, basis in _SPEC_BASIS.items():
                key = (leaf['subject'], basis)
                if key in found:
                    continue
                fact = _spec_fact(leaf, field, snapshot)
                if fact is not None:
                    same = next((f for f in existing if {k: v for k, v in f.items() if k != 'fact_id'}
                                 == {k: v for k, v in fact.items() if k != 'fact_id'}), None)
                    if same is not None:
                        fact = same
                    elif all(f['fact_id'] != fact['fact_id'] for f in facts):
                        facts.append(fact)
                found[key] = fact
        for leaf in leaves:
            if leaf['type'] != 'qualitative':
                continue
            for basis in ('current', 'target'):
                fact = found.get((leaf['subject'], basis))
                conditions.append(dict(predicate_id=leaf['predicate_id'], basis=basis,
                    fact_ids=[fact['fact_id']] if fact else [],
                    assessment='satisfied' if fact else 'insufficient_info',
                    reason='사양 줄에 조건 주제 문구가 그대로 있습니다.' if fact else '사양 줄에서 조건 주제 문구를 찾지 못했습니다.'))
        return dict(facts=facts, conditions=conditions, affected_items=_affected(clause['family']),
                    rationale='현재·목표 사양 줄의 조건 주제를 원문 조건과 대조했습니다.')

    # Classification stages ---------------------------------------------------

    @staticmethod
    def _bucket(name):
        return _digest('grade', name)[0] % 3

    def _bucket_grade(self, name):
        return d.GRADES[self._bucket(name)]

    def _score(self, name, reviewer_id, item):
        bucket = self._bucket(name)
        return 5 if bucket == 0 else 4 if bucket == 1 else 1 + _digest('score', name, reviewer_id, item)[0] % 3

    @staticmethod
    def _chosen(name, comparisons):
        indexes = {i for c in comparisons for i in c['affected_items'] if 1 <= i <= 7}
        count = 1 + _digest('count', name)[0] % 2
        indexes |= {1 + _digest('item', name, k)[0] % 7 for k in range(count)}
        return {i: '일부' if _digest('level', name, i)[0] % 4 == 0 else '해당' for i in sorted(indexes)}

    def _classify(self, data):
        stage, name = data['stage'], data['task']['과제명']
        notice = data['notice_review']
        comparisons = notice['comparisons']
        if stage == 'candidate':
            if comparisons or any(entry['candidate_ids'] for entry in notice['families']):
                return dict(is_candidate=True, reason='고시 대조 후보 조항이 있어 등급분류 대상으로 검토합니다.', uncertainty='')
            chosen = _digest('candidate', name)[0] % 5 != 0
            return dict(is_candidate=chosen, uncertainty='',
                        reason='과제 내용상 등급분류 검토 대상입니다.' if chosen else '과제 내용상 보호가 필요한 기술 요소가 없습니다.')
        if stage == 'criteria':
            chosen = self._chosen(name, comparisons)
            criteria = []
            for index, criterion in enumerate(d.CRITERIA, 1):
                level = chosen.get(index, '미해당')
                refs = (list(criterion['security_refs']) if level == '해당'
                        else list(criterion['sensitive_refs']) if level == '일부' else [])
                links = [dict(comparison_id=c['comparison_id'], source_id=c['source_id'])
                         for c in comparisons if index in c['affected_items']]
                criteria.append(dict(item=criterion['name'], level=level, law_refs=refs,
                                     note='합성 과제의 사실과 유출 영향을 검토했습니다.',
                                     matched_reference=json.dumps(links, ensure_ascii=False) if links else '',
                                     needs_expert_review=False))
            return dict(criteria=criteria)
        if stage == 'reviewer':
            reviewer_id, selected = data['reviewer_id'], data['selected_items']
            impact = data['method'] == 'impact'
            scores = {item: self._score(name, reviewer_id, item) for item in selected} if impact else {}
            grade = (d.rule_grade(d.calculate_reviewer_score(scores, selected, data['weights']))
                     if impact else self._bucket_grade(name))
            return dict(item_reviews=[dict(item=c['item'], level=c['level'], note=c['note'], law_refs=list(c['law_refs']))
                                      for c in data['criteria']],
                        scores=scores, grade=grade, confidence='보통',
                        rationale=data['persona'] + '의 독립 보호 필요성 검토', discussion_points='역할별 논의사항',
                        unresolved_reasons=[],
                        notice_comments=[dict(comparison_id=c['comparison_id'], comment=data['persona'] + '의 고시 대조 의견')
                                         for c in comparisons])
        if stage == 'summary':
            return dict(final_grade=data['rule_grade'] or self._bucket_grade(name), confidence='보통',
                        rationale='법정의와 유출 영향, 보호 필요성을 종합했습니다.',
                        discussion_points='역할별 의견 차이를 검토했습니다.', unresolved_reasons=[])
        raise ValueError('지원하지 않는 분류 단계입니다.')
