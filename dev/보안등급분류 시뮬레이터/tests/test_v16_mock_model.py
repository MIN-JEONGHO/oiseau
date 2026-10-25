"""Offline tests for the input-based v16 mock model; synthetic tasks only.

Every task here is invented test text (no real project content). The installed
catalogue bundle is used read-only; no network, key or real model is involved.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'tools'))

import v16_domain as d
import classification_v16 as engine
import notice_review_v16 as nr
from notice_catalogue_v16 import load_catalogue
import v16_mock_model as mm


CATALOGUE = load_catalogue()
_, BY_ID = nr._preflight(CATALOGUE)
OPTIONS = {'method': 'impact', 'num_reviewers': 3}

# Auto-judged core clauses (no unsupported leaf) used for targeted tasks, and a
# core clause whose only leaf is unsupported (cannot resolve without it).
TARGET_CLAUSES = ('core:item:029', 'core:item:068')
UNSUPPORTED_CLAUSE = 'core:item:035'

GENERIC_GOAL = (
    '지역 공공도서관의 열람 기록과 이용자 설문을 묶어 서비스 개선 방향을 찾는 연구이다. '
    '도서관 운영 담당자와 이용자 사이의 소통 방식을 정리하고, 계절별 이용 흐름을 살펴 '
    '프로그램 편성에 반영할 수 있는 기준을 마련한다.\n'
    '- 이용자 의견을 주제별로 나누어 정리하는 절차 마련\n'
    '- 운영 담당자 면담 결과를 서비스 개선 과제로 연결\n'
    '- 계절별 이용 흐름을 해마다 같은 방식으로 기록하는 양식 마련')
GENERIC_CONTENT = (
    '1차년도에는 열람 기록 정리 방식과 설문 문항을 마련하고, 시범 도서관 세 곳에서 '
    '이용자 의견을 모은다. 모은 의견은 주제별로 묶어 운영 담당자와 함께 검토한다.\n'
    '2차년도에는 시범 결과를 바탕으로 프로그램 편성 기준을 다듬고, 다른 지역 도서관에 '
    '적용할 수 있도록 안내서를 만든다. 안내서에는 의견 수렴 절차, 면담 진행 방법, '
    '결과 공유 방식을 담는다.\n'
    '3차년도에는 안내서를 여러 도서관에서 써 보고 고칠 점을 모아 최종본을 낸다. '
    '이 과정에서 이용자 만족도 변화를 해마다 같은 문항으로 살핀다.\n'
    '○ 열람 기록 정리 방식 마련\n'
    '○ 설문 문항 개발과 시범 운영\n'
    '○ 운영 담당자 면담과 결과 정리\n'
    '○ 프로그램 편성 기준과 안내서 작성\n'
    '○ 여러 도서관 시범 적용과 최종본 발간')
GENERIC_EFFECT = (
    '도서관 이용자의 의견이 서비스 편성에 꾸준히 반영되는 운영 방식이 자리 잡는다. '
    '운영 담당자는 같은 기준으로 해마다 이용 흐름을 비교할 수 있고, 지역 주민은 '
    '필요한 프로그램을 더 쉽게 찾을 수 있다. 안내서는 다른 공공시설의 의견 수렴에도 '
    '참고 자료로 쓰일 수 있다.')


def generic_task(name):
    task = {'세부사업명': '[모의] 생활연구 지원사업', '과제명': name,
            '연구목표': GENERIC_GOAL, '연구내용': GENERIC_CONTENT, '기대효과': GENERIC_EFFECT}
    filler = ('\n이용자 의견과 운영 기록을 함께 살펴 다음 해 편성에 반영하는 순서를 정리한다.')
    while sum(len(task[k]) for k in d.TASK_COLUMNS) < 1600:
        task['연구내용'] += filler
    return task


def spec_lines(clause):
    """Spec 4.4: one line per distinct condition subject (point value, condition unit)."""
    lines, seen = [], set()
    for leaf in d.condition_leaves(clause['condition']):
        if leaf['type'] == 'unsupported' or leaf['subject'] in seen:
            continue
        seen.add(leaf['subject'])
        lines.append(f"{leaf['subject']} {leaf['threshold']}{leaf['unit']}" if leaf['type'] == 'numeric'
                     else leaf['subject'])
    return lines


def targeted_task(clause_id):
    clause = BY_ID[clause_id]
    title = re.sub(r'\s+', ' ', clause['title']).strip()
    lines = '\n'.join(spec_lines(clause))
    return {'세부사업명': '[모의] 산업기술 고도화사업', '과제명': f'[모의] {clause_id} 대상 합성 과제',
            '연구목표': f'{title}을 확보한다.\n시험 장비와 공정 조건을 정리한다.',
            '연구내용': '시제품을 만들고 시험 결과를 정리한다.\n- 단계별 시험 절차 마련',
            '기대효과': '관련 산업의 시험 기반을 넓힌다.',
            '현재 기술사양': lines, '개발목표 사양': lines}


class Base(unittest.TestCase):
    def classify(self, task, client=None, options=OPTIONS):
        client = mm.MockModel() if client is None else client
        result = engine.classify_task(task, options, client, catalogue=CATALOGUE)
        opts = d.normalize_options(dict(options) | {'catalogue_fingerprint': CATALOGUE.fingerprint},
                                   ministry_policy_context=task.get('부처 세부기준', ''))
        self.assertIs(d.validate_result(result, opts, task), result)
        self.assertNotEqual(result['status'], '오류')
        self.assertNotEqual(result['notice_review']['status'], 'error')
        return result, client

    @staticmethod
    def candidates(result):
        return [cid for entry in result['notice_review']['families'] for cid in entry['candidate_ids']]


class EndToEndTests(Base):
    def test_generic_realistic_task_has_no_candidates_and_complete_notice(self):
        task = generic_task('[모의] 도서관 이용 흐름 정리 연구')
        self.assertGreaterEqual(sum(len(task[k]) for k in d.TASK_COLUMNS), 1600)
        result, _ = self.classify(task)
        self.assertEqual(self.candidates(result), [])
        self.assertEqual(result['notice_review']['comparisons'], [])
        self.assertEqual(result['notice_review']['status'], 'complete')
        self.assertIn(result['status'], ('완료', '후보제외'))

    def test_some_generic_task_is_graded(self):
        graded = []
        for index in range(8):
            result, _ = self.classify(generic_task(f'[모의] 도서관 이용 흐름 정리 연구 {index}'))
            self.assertEqual(self.candidates(result), [])
            self.assertEqual(result['notice_review']['status'], 'complete')
            if result['status'] == '완료':
                self.assertIn(result['final_grade'], d.GRADES)
                self.assertEqual(result['final_grade'], result['rule_grade'])
                graded.append(result['final_grade'])
            else:
                self.assertEqual(result['status'], '후보제외')
        self.assertTrue(graded)

    def test_targeted_auto_core_clause_reaches_grade(self):
        for clause_id in TARGET_CLAUSES:
            with self.subTest(clause_id=clause_id):
                result, _ = self.classify(targeted_task(clause_id))
                notice = result['notice_review']
                self.assertEqual(self.candidates(result), [clause_id])
                self.assertEqual(notice['status'], 'complete')
                self.assertGreaterEqual(len(notice['comparisons']), 1)
                comparison = notice['comparisons'][0]
                self.assertIn(3, comparison['affected_items'])
                self.assertIn(comparison['current_assessment'], ('satisfied', 'not_satisfied'))
                self.assertIn(comparison['target_assessment'], ('satisfied', 'not_satisfied'))
                self.assertEqual(result['status'], '완료')
                self.assertTrue(result['candidate']['is_candidate'])
                self.assertEqual(result['candidate']['uncertainty'], '')
                self.assertIn(result['final_grade'], d.GRADES)
                core = result['criteria'][2]
                self.assertIn(core['level'], ('해당', '일부'))
                self.assertTrue(core['law_refs'])
                self.assertEqual(json.loads(core['matched_reference']),
                                 [dict(comparison_id=comparison['comparison_id'], source_id=comparison['source_id'])])
                for reviewer in result['reviewers']:
                    self.assertEqual(reviewer['unresolved_reasons'], [])

    def test_unsupported_leaf_clause_needs_review(self):
        result, _ = self.classify(targeted_task(UNSUPPORTED_CLAUSE))
        self.assertEqual(self.candidates(result), [UNSUPPORTED_CLAUSE])
        comparison = result['notice_review']['comparisons'][0]
        self.assertEqual(comparison['current_assessment'], 'insufficient_info')
        self.assertEqual(result['notice_review']['status'], 'needs_info')
        self.assertEqual(result['status'], '검토필요')
        self.assertIsNone(result['final_grade'])

    def test_same_input_gives_identical_result(self):
        task = targeted_task(TARGET_CLAUSES[1])
        first, _ = self.classify(task)
        second, _ = self.classify(task)
        self.assertEqual(json.dumps(first, ensure_ascii=False, sort_keys=True),
                         json.dumps(second, ensure_ascii=False, sort_keys=True))

    def test_grades_vary_across_task_names(self):
        grades = set()
        for index in range(12):
            result, _ = self.classify(generic_task(f'[모의] 등급 분산 확인 과제 {index}'))
            if result['status'] == '완료':
                grades.add(result['final_grade'])
        self.assertGreaterEqual(len(grades), 2)

    def test_excel_markers_facts_match_cleaned_snapshot(self):
        task = generic_task('[모의] 줄바꿈 표시 확인 과제')
        task['연구내용'] = ('시험 설비 출력 20 kW로 운전한다._x000D_\n측정 간격 5 ms로 기록한다._x000D_'
                          '_x000D_\n_x000D_\n- 시료 무게 3 kg 기준으로 비교한다.\n') + task['연구내용']
        task['현재 기술사양'] = '_x000D_\n장비 길이 2 m_x000D_\n장비 무게 40 kg'
        task['개발목표 사양'] = '장비 무게 30 kg_x000D_\n'
        result, _ = self.classify(task)
        snapshot = d.task_snapshot(task)
        facts = result['notice_review']['facts']
        self.assertTrue(facts)
        self.assertTrue(any(f['source_field'] == '연구내용' for f in facts))
        for fact in facts:
            self.assertEqual(snapshot[fact['source_field']][fact['start']:fact['end']], fact['quote'])
            self.assertIs(d.validate_fact(fact, snapshot), fact)
            if fact['source_field'] == '현재 기술사양':
                self.assertEqual(fact['basis'], 'current')
            if fact['source_field'] == '개발목표 사양':
                self.assertEqual(fact['basis'], 'target')
        self.assertLessEqual(len(facts), 12)


class PartialContextTests(Base):
    def test_24000_request_size_answers_every_header_clause(self):
        task = generic_task('[모의] 조각 요청 확인 과제')
        client = mm.MockModel()
        with mock.patch.object(nr, 'DEFAULT_CHUNK_CHARS', 24000):
            result, _ = self.classify(task, client)
        partial = [entry for entry in client.call_log() if entry['partial']]
        self.assertTrue(partial)
        self.assertTrue(all(entry['phase'] == 'screen' for entry in partial))
        self.assertIn(result['status'], ('검토필요', '후보제외', '완료'))

    def test_hand_made_fragments_get_a_decision_for_every_header_clause(self):
        task = targeted_task(TARGET_CLAUSES[0])
        snapshot = d.task_snapshot(task)
        indexes = [nr._screen_index(c) for c in BY_ID.values()
                   if c['family'] == 'core' and c['field'] != '공통정의·주석']
        payload = dict(phase='screen', family='core', task_segments=nr._segments(snapshot, 100000),
                       facts=[], screening_scope='whole_unit_catalogue_index', completeness='x', clauses=indexes)
        client = mm.MockModel()
        packets = nr._requests(payload, 6000)
        self.assertGreater(len(packets), 1)
        for packet in packets:
            self.assertTrue(packet['partial_context'])
            response = client.ask_json(nr._SYSTEM, json.dumps(packet, ensure_ascii=False))
            ids = [entry['clause_id'] for entry in response['decisions']]
            self.assertEqual(sorted(ids), sorted(c['clause_id'] for c in packet['clauses']))
            for entry in response['decisions']:
                self.assertIs(type(entry['candidate']), bool)
                self.assertTrue(entry['reason'].strip())
        compare = dict(phase='compare', task_segments=nr._segments(snapshot, 100000), facts=[],
                       clause=BY_ID[TARGET_CLAUSES[0]], references=[], review_items=[], has_target_information=True,
                       response='x')
        for packet in nr._requests(compare, 2048):
            response = client.ask_json(nr._SYSTEM, json.dumps(packet, ensure_ascii=False))
            nr._comparison_response(deepcopy(response), BY_ID[TARGET_CLAUSES[0]], [], snapshot)


class ModelUnitTests(unittest.TestCase):
    def screen(self, text, clause_ids):
        snapshot = d.task_snapshot({'과제명': '[모의] 낱말 확인', '연구내용': text})
        payload = dict(phase='screen', family='core', task_segments=nr._segments(snapshot, 100000), facts=[],
                       screening_scope='whole_unit_catalogue_index', completeness='x',
                       clauses=[nr._screen_index(BY_ID[c]) for c in clause_ids])
        response = mm.MockModel().ask_json(nr._SYSTEM, json.dumps(payload, ensure_ascii=False))
        self.assertEqual([e['clause_id'] for e in response['decisions']], list(clause_ids))
        self.assertTrue(all(e['reason'].strip() for e in response['decisions']))
        return {e['clause_id'] for e in response['decisions'] if e['candidate']}

    def test_screen_tokenizer_rules(self):
        every = [c['clause_id'] for c in BY_ID.values() if c['field'] != '공통정의·주석']
        prose = ('본 과제는 차세대 고성능 소재를 개발하고 데이터 기반 소프트웨어로 공정을 제어한다. '
                 '스마트 시스템 장치를 위한 설계 기술과 반도체 디스플레이 정보통신 3차원 이상의 이하급 '
                 '제조 원문 통제기준 해당하는 해당되는 가능한 적용되는 제외 주석 공통정의 이중용도품목 군용물자목록.')
        self.assertEqual(self.screen(prose, every), set())
        title = BY_ID['core:item:027']['title']
        self.assertEqual(self.screen('이번 과제는 ' + title + '을 다룬다.', ['core:item:027', 'core:item:029']),
                         {'core:item:027'})
        # Whitespace inside the title does not matter.
        self.assertEqual(self.screen(re.sub(r'\s+', '', title), ['core:item:027']), {'core:item:027'})
        # A distinctive clause word (3+ chars, not common) is enough.
        self.assertEqual(self.screen('다축복합가공 장비 기록', ['core:item:067', 'core:item:068']), {'core:item:067'})
        # Particle-ending clause words (고속철도차량의) and short Latin words are dropped.
        self.assertEqual(self.screen('고속철도차량의 운영', ['core:item:026', 'core:item:027']), set())
        self.assertEqual(self.screen('SoC LTE', ['core:item:006', 'core:item:051']), set())
        self.assertEqual(mm.tokens('바이오의약품을 개발하고 OLED용 DDI 21uF ML1 ML10 128단'),
                         ['OLED용', '21uF', 'ML10', '128단'])

    def test_facts_phase_offsets_basis_and_validation(self):
        task = {'과제명': '[모의] 근거 확인', '연구목표': '_x000D_\n목표 출력 50 kW 달성_x000D_\n세부 목표 정리',
                '연구내용': '현재 출력 20 kW 수준이다. 주기 5 ms로 측정한다.\n출력은 높다.',
                '현재 기술사양': '- 장비 길이 2 m\n장비 무게 40 kg', '개발목표 사양': '장비 무게 30 kg\n시험 조건 정리'}
        snapshot = d.task_snapshot(task)
        client = mm.MockModel()
        found = []
        for segment in nr._segments(snapshot, 100000):
            payload = dict(phase='facts', segment=segment, instruction='x', fact_fields=[])
            response = client.ask_json(nr._SYSTEM, json.dumps(payload, ensure_ascii=False))
            self.assertEqual(set(response), {'facts'})
            for fact in response['facts']:
                self.assertEqual(fact['source_field'], segment['source_field'])
                self.assertTrue(segment['start'] <= fact['start'] < fact['end'] <= segment['end'])
                self.assertEqual(snapshot[fact['source_field']][fact['start']:fact['end']], fact['quote'])
                self.assertEqual(nr._checked_fact(fact, snapshot), fact)
                found.append(fact)
        by_field = {}
        for fact in found:
            by_field.setdefault(fact['source_field'], []).append(fact)
        # The last line of a field touches the segment end and is left to compare.
        self.assertEqual([f['quote'] for f in by_field['현재 기술사양']], ['장비 길이 2 m'])
        self.assertEqual([f['basis'] for f in by_field['현재 기술사양']], ['current'])
        self.assertEqual([f['basis'] for f in by_field['개발목표 사양']], ['target'])
        self.assertEqual(by_field['연구목표'][0]['basis'], 'target')
        self.assertEqual(by_field['연구내용'][0]['basis'], 'current')
        self.assertEqual(len({f['fact_id'] for f in found}), len(found))
        again = mm.MockModel()
        segment = nr._segments(snapshot, 100000)[0]
        payload = json.dumps(dict(phase='facts', segment=segment, instruction='x', fact_fields=[]), ensure_ascii=False)
        self.assertEqual(client.ask_json('s', payload), again.ask_json('s', payload))

    def test_segment_edge_facts_are_not_guessed(self):
        text = '장비 무게 40 kg\n장비 길이 2 m'
        snapshot = d.task_snapshot({'과제명': '[모의] 경계', '연구내용': text + 'm 정도'})
        segment = dict(source_field='연구내용', start=0, end=len(text), text=text)
        response = mm.MockModel().ask_json('s', json.dumps(dict(phase='facts', segment=segment), ensure_ascii=False))
        self.assertEqual([f['quote'] for f in response['facts']], ['장비 무게 40 kg'])
        for fact in response['facts']:
            nr._checked_fact(fact, snapshot)

    def test_attributes_log_and_source_rules(self):
        client = mm.MockModel()
        self.assertEqual((client.provider, client.model), ('claude', 'claude-sonnet-5-5'))
        self.assertEqual((client.provider, client.model), (d.RunOptions().provider, d.RunOptions().model))
        snapshot = d.task_snapshot({'과제명': '[모의] 기록 확인'})
        segment = nr._segments(snapshot, 100000)[0]
        user = json.dumps(dict(phase='facts', segment=segment), ensure_ascii=False)
        response = client.ask_json('system', user)
        log = client.call_log()
        self.assertEqual(len(log), 1)
        entry = log[0]
        self.assertEqual(entry['phase'], 'facts')
        self.assertEqual(entry['prompt_chars'], len(user))
        self.assertEqual(entry['system_chars'], len('system'))
        self.assertEqual(entry['response_chars'], len(json.dumps(response, ensure_ascii=False)))
        self.assertIsInstance(entry['timestamp'], float)
        self.assertEqual(entry['task_name'], '[모의] 기록 확인')
        log[0]['phase'] = 'changed'
        self.assertEqual(client.call_log()[0]['phase'], 'facts')
        source = Path(mm.__file__).read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'(?<![\w.])hash\(', source))
        self.assertIsNone(re.search(r'^\s*(?:import|from)\s+(?:socket|urllib|http|requests|anthropic|openai|test_)', source, re.M))
        self.assertIn('sha256', source)


if __name__ == '__main__':
    unittest.main()
