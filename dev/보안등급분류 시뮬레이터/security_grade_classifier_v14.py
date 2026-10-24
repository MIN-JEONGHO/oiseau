"""Native v14 application. Importing this module opens no window or connection.

All Tk operations run on the creating thread. Workers communicate through a
queue; clients receive frozen options and credentials supplied by the caller.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font, ttk
from zipfile import ZipFile

from credential_store import KeyManager
from v14_domain import DEFAULT_MODELS, ITEM_NAMES, TASK_COLUMNS, format_score, normalize_options, task_snapshot

VERSION = '14'
PROVIDERS = {'claude': 'Claude Sonnet 5.5', 'openai': 'OpenAI GPT-6 Luna',
             'ollama': 'Ollama', 'lmstudio': 'LM Studio'}
LOCAL_DEFAULTS = {'ollama': ('qwen2.5:14b', 'http://localhost:11434'),
                  'lmstudio': ('local-model', 'http://localhost:1234')}
BG, NAVY, INK, MUTED = '#F1F3F6', '#172E4D', '#202E40', '#53647A'


def _default_client(**kwargs):
    from llm_client_v14 import LLMClient
    return LLMClient(**kwargs)


def _classify(*args, **kwargs):
    from classification_v14 import classify_task
    return classify_task(*args, **kwargs)


def _batch(*args, **kwargs):
    from batch_v14 import run_excel
    return run_excel(*args, **kwargs)


def _documents(*args, **kwargs):
    from batch_v14 import regenerate_documents
    return regenerate_documents(*args, **kwargs)


def _persist_documents(*args, **kwargs):
    from batch_v14 import persist_regenerated_documents
    return persist_regenerated_documents(*args, **kwargs)


class ScrollFrame(ttk.Frame):
    """Two-axis scrolling keeps settings and long Korean labels reachable."""
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=BG, highlightthickness=0, borderwidth=0)
        vertical = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        horizontal = ttk.Scrollbar(self, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.body = ttk.Frame(self.canvas, padding=18)
        self.window = self.canvas.create_window(0, 0, anchor='nw', window=self.body)
        self.body.bind('<Configure>', self._resize)
        self.canvas.bind('<Configure>', self._resize)
        self.canvas.bind('<Enter>', lambda event: self.canvas.focus_set())
        self.canvas.bind('<MouseWheel>', lambda event: self.canvas.yview_scroll(-int(event.delta / 120), 'units'))

    def _resize(self, event=None):
        self.canvas.itemconfigure(self.window, width=max(self.canvas.winfo_width(), self.body.winfo_reqwidth()))
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))


class ClassifierApp:
    def __init__(self, root, *, key_manager=None, client_factory=None,
                 classify_func=None, batch_func=None, document_func=None, persist_documents_func=None):
        self.root = root
        self.key_manager = key_manager if key_manager is not None else KeyManager()
        self.client_factory = client_factory or _default_client
        self.classify_func = classify_func or _classify
        self.batch_func = batch_func or _batch
        self.document_func = document_func or _documents
        self.persist_documents_func = persist_documents_func or _persist_documents
        self.busy = False
        self.closed = False
        self.events = queue.Queue()
        self.cancel_event = threading.Event()
        self.result = None
        self.batch_report = None
        self.batch_results = []
        self.document_dir = ''
        self._poll_id = None
        self._selected_batch_index = None
        self.settings_controls = []
        self.readonly_controls = []
        self.input_controls = []
        self.provider_var = tk.StringVar(root, 'claude')
        self.provider_display_var = tk.StringVar(root, PROVIDERS['claude'])
        self.model_var = tk.StringVar(root, DEFAULT_MODELS['claude'])
        self.base_url_var = tk.StringVar(root, '')
        self.key_entry_var = tk.StringVar(root, '')
        self.key_status_var = tk.StringVar(root, '')
        self.method_var = tk.StringVar(root, 'impact')
        self.selection_var = tk.StringVar(root, 'auto')
        self.reviewers_var = tk.StringVar(root, '3개')
        self.strictness_var = tk.StringVar(root, '표준')
        self.status_var = tk.StringVar(root, '준비 · 입력과 설정을 확인한 뒤 시작하세요.')
        self.summary_var = tk.StringVar(root, '')
        self.input_path_var = tk.StringVar(root, '')
        self.output_path_var = tk.StringVar(root, '')
        self.resume_var = tk.BooleanVar(root, True)
        self.forms_var = tk.BooleanVar(root, True)
        self.workers_var = tk.StringVar(root, '3')
        self.item_vars = [tk.BooleanVar(root, index < 7) for index in range(8)]
        self.weight_vars = [tk.StringVar(root, '1.0') for _ in range(8)]
        self.root.title('연구보안 등급분류 시뮬레이터 v14')
        self.root.geometry('1120x820')
        self.root.minsize(720, 480)
        self.root.configure(background=BG)
        self._styles()
        self._build()
        self.on_provider_change()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self._poll_id = self.root.after(60, self.poll_events)

    def _styles(self):
        self.style = ttk.Style(self.root)
        self.style.theme_use('clam')
        self.style.configure('.', font=('맑은 고딕', 10), background=BG, foreground=INK)
        self.style.configure('TFrame', background=BG)
        self.style.configure('TLabel', background=BG, foreground=INK)
        self.style.configure('TLabelframe', background=BG, bordercolor='#D6DDE6')
        self.style.configure('TLabelframe.Label', font=('맑은 고딕', 11, 'bold'), foreground=NAVY)
        self.style.configure('TButton', padding=(12, 7))
        self.style.configure('Primary.TButton', background=NAVY, foreground='white')
        self.style.map('Primary.TButton', background=[('active', '#27486E'), ('disabled', '#B3BFCD')])
        self.style.configure('TNotebook.Tab', padding=(18, 9))
        self.style.configure('Card.TLabel', background='white', padding=10)
        self.style.configure('Header.TFrame', background=NAVY)
        self.style.configure('Header.TLabel', background=NAVY, foreground='white')
        self.style.configure('Title.TLabel', background=NAVY, foreground='white', font=('맑은 고딕', 19, 'bold'))

    def set_font_scale(self, scale):
        """Testable typography scaling, without changing the user's system DPI."""
        for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
            font.nametofont(name, root=self.root).configure(family='맑은 고딕', size=round(10 * scale))
        self.style.configure('.', font=('맑은 고딕', round(10 * scale)))
        self.style.configure('Title.TLabel', font=('맑은 고딕', round(19 * scale), 'bold'))
        self.style.configure('TLabelframe.Label', font=('맑은 고딕', round(11 * scale), 'bold'))

    def _build(self):
        self.root.rowconfigure(2, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.header = ttk.Frame(self.root, style='Header.TFrame', padding=(22, 16))
        self.header.grid(row=0, column=0, sticky='ew')
        ttk.Label(self.header, text='AI 에이전트 검토', style='Title.TLabel').pack(anchor='w')
        ttk.Label(self.header, textvariable=self.summary_var, style='Header.TLabel').pack(anchor='w', pady=(7, 0))
        ttk.Label(self.root, textvariable=self.status_var, padding=(22, 10), wraplength=1000).grid(row=1, column=0, sticky='ew')
        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=2, column=0, sticky='nsew', padx=16)
        self.single_scroll = ScrollFrame(self.notebook)
        self.batch_scroll = ScrollFrame(self.notebook)
        self.settings_scroll = ScrollFrame(self.notebook)
        self.results_scroll = ScrollFrame(self.notebook)
        for page, text in ((self.single_scroll, 'AI 에이전트 검토'), (self.batch_scroll, '엑셀 대량 처리'),
                           (self.settings_scroll, '설정'), (self.results_scroll, '검토 결과')):
            self.notebook.add(page, text=text)
        self._single_page(self.single_scroll.body)
        self._batch_page(self.batch_scroll.body)
        self._settings_page(self.settings_scroll.body)
        self._results_page(self.results_scroll.body)
        self.footer = ttk.Frame(self.root, padding=(16, 12))
        self.footer.grid(row=3, column=0, sticky='ew')
        self.footer.columnconfigure(0, weight=1)
        ttk.Label(self.footer, text='AI 참고 의견 · 최종 확정은 실제 심의위원회와 소관 기관', foreground=MUTED, wraplength=380).grid(row=0, column=0, sticky='w')
        self.cancel_button = ttk.Button(self.footer, text='대량 처리 중지', command=self.cancel_batch, state='disabled')
        self.cancel_button.grid(row=0, column=1, padx=8)
        self.run_button = ttk.Button(self.footer, text='AI 에이전트 검토 시작', style='Primary.TButton', command=self.start_current)
        self.run_button.grid(row=0, column=2)
        self.notebook.bind('<<NotebookTabChanged>>', self._tab_changed)

    def _section(self, parent, text):
        frame = ttk.LabelFrame(parent, text=text, padding=14)
        frame.pack(fill='x', pady=(0, 16))
        frame.columnconfigure(1, weight=1)
        return frame

    def _text(self, parent, height=3):
        holder = ttk.Frame(parent)
        text = tk.Text(holder, height=height, width=55, wrap='word', font=('맑은 고딕', 10),
                       background='white', foreground=INK, relief='solid', bd=1, padx=8, pady=7,
                       highlightthickness=0, undo=True)
        scroll = ttk.Scrollbar(holder, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        return holder, text

    def _single_page(self, parent):
        section = self._section(parent, '과제 요약')
        self.task_fields = {}
        for index, name in enumerate(TASK_COLUMNS + ('추가 검토정보',)):
            ttk.Label(section, text=name + (' *' if name == '과제명' else ''), width=14).grid(row=index, column=0, sticky='nw', pady=6)
            holder, text = self._text(section, 2 if index < 2 else 3)
            holder.grid(row=index, column=1, sticky='ew', pady=6)
            self.task_fields[name] = text
            self.input_controls.append(text)
        ttk.Label(parent, text='부처 세부기준은 설정에서 별도로 입력합니다. 입력한 과제 요약이 선택한 모델로 전달됩니다.',
                  foreground=MUTED, wraplength=760).pack(anchor='w')

    def _batch_page(self, parent):
        section = self._section(parent, '엑셀 파일')
        for row, label, variable, command in ((0, '입력 파일', self.input_path_var, self.choose_input),
                                               (1, '결과 파일', self.output_path_var, self.choose_output)):
            ttk.Label(section, text=label, width=12).grid(row=row, column=0, sticky='w', pady=6)
            entry = ttk.Entry(section, textvariable=variable, width=52)
            entry.grid(row=row, column=1, sticky='ew', pady=6)
            button = ttk.Button(section, text='찾아보기', command=command)
            button.grid(row=row, column=2, padx=(10, 0))
            self.input_controls.extend((entry, button))
        template = ttk.Button(section, text='입력 양식 저장', command=self.save_template)
        template.grid(row=2, column=1, sticky='w', pady=(10, 0))
        self.input_controls.append(template)
        section = self._section(parent, '처리 옵션')
        for row, text, var in ((0, '일치하는 완료 결과 재사용', self.resume_var), (1, 'HWPX 의견서 함께 생성', self.forms_var)):
            check = ttk.Checkbutton(section, text=text, variable=var)
            check.grid(row=row, column=0, columnspan=2, sticky='w', pady=5)
            self.input_controls.append(check)
        ttk.Label(section, text='동시 처리 수').grid(row=2, column=0, sticky='w', pady=8)
        workers = ttk.Spinbox(section, from_=1, to=8, width=6, textvariable=self.workers_var)
        workers.grid(row=2, column=1, sticky='w')
        self.input_controls.append(workers)
        self.batch_status_var = tk.StringVar(self.root, '처리 결과가 여기에 표시됩니다.')
        ttk.Label(parent, textvariable=self.batch_status_var, wraplength=780, justify='left').pack(anchor='w', pady=8)
        self.batch_list = ttk.Treeview(parent, columns=('status', 'grade', 'documents'), show='tree headings', height=8)
        for key, label in (('#0', '과제명'), ('status', '분류 상태'), ('grade', '참고 등급'), ('documents', '문서 상태')):
            self.batch_list.heading(key, text=label)
            self.batch_list.column(key, width=160 if key == '#0' else 120)
        self.batch_list.pack(fill='both', expand=True)
        self.batch_list.bind('<<TreeviewSelect>>', self.select_batch_result)

    def _settings_page(self, parent):
        section = self._section(parent, '모델 연결')
        ttk.Label(section, text='제공자').grid(row=0, column=0, sticky='w', pady=6)
        self.provider_combo = ttk.Combobox(section, textvariable=self.provider_display_var, values=tuple(PROVIDERS.values()), state='readonly', width=26)
        self.provider_combo.grid(row=0, column=1, sticky='w')
        self.provider_combo.bind('<<ComboboxSelected>>', self.on_provider_change)
        ttk.Label(section, text='모델').grid(row=1, column=0, sticky='w', pady=6)
        self.model_entry = ttk.Combobox(section, textvariable=self.model_var, width=36)
        self.model_entry.grid(row=1, column=1, sticky='ew')
        self.model_entry.bind('<KeyRelease>', lambda event: self._summary())
        self.model_entry.bind('<<ComboboxSelected>>', lambda event: self._summary())
        ttk.Label(section, text='로컬 서버 주소').grid(row=2, column=0, sticky='w', pady=6)
        self.url_entry = ttk.Entry(section, textvariable=self.base_url_var, width=36)
        self.url_entry.grid(row=2, column=1, sticky='ew')
        self.discover_button = ttk.Button(section, text='로컬 모델 찾기', command=self.discover_models)
        self.discover_button.grid(row=2, column=2, padx=8)
        ttk.Label(section, text='새 API 키').grid(row=3, column=0, sticky='w', pady=6)
        self.key_entry = ttk.Entry(section, textvariable=self.key_entry_var, show='•', width=36)
        self.key_entry.grid(row=3, column=1, sticky='ew')
        self.delete_button = ttk.Button(section, text='저장 키 삭제', command=self.delete_key)
        self.delete_button.grid(row=3, column=2, padx=8)
        ttk.Label(section, textvariable=self.key_status_var, wraplength=680, foreground=MUTED).grid(row=4, column=0, columnspan=3, sticky='w', pady=8)
        self.apply_button = ttk.Button(section, text='설정 적용 · 키 저장', command=self.apply_settings)
        self.apply_button.grid(row=5, column=1, sticky='w')
        self.settings_controls.extend((self.provider_combo, self.model_entry, self.url_entry,
                                       self.discover_button, self.key_entry, self.delete_button, self.apply_button))
        section = self._section(parent, '분류 방식과 AI 에이전트')
        for col, label, value in ((0, '국가영향 지표', 'impact'), (1, '체크리스트', 'checklist')):
            button = ttk.Radiobutton(section, text=label, variable=self.method_var, value=value, command=self.refresh_method)
            button.grid(row=0, column=col, sticky='w', pady=6)
            self.settings_controls.append(button)
        ttk.Label(section, text='AI 에이전트 수').grid(row=1, column=0, sticky='w', pady=8)
        reviewers = ttk.Combobox(section, textvariable=self.reviewers_var, values=('1개', '3개'), state='readonly', width=8)
        reviewers.grid(row=1, column=1, sticky='w')
        ttk.Label(section, text='마지막 의견 엄격도').grid(row=2, column=0, sticky='w', pady=8)
        strictness = ttk.Combobox(section, textvariable=self.strictness_var, values=('엄격', '표준', '관대'), state='readonly', width=8)
        strictness.grid(row=2, column=1, sticky='w')
        self.settings_controls.extend((reviewers, strictness))
        self.readonly_controls.extend((reviewers, strictness))
        ttk.Label(section, text='1개: AI 기술분야 전문가\n3개: AI 연구보안 전문가·AI 기술사업화 전문가 추가\n선택한 모델 하나가 각 역할을 독립적으로 검토합니다.',
                  foreground=MUTED, wraplength=700).grid(row=3, column=0, columnspan=2, sticky='w', pady=8)
        section = self._section(parent, '공통 검토항목 · 가중치')
        self.selection_controls = []
        for col, text, value in ((0, '자동 선택', 'auto'), (1, '직접 선택', 'manual')):
            button = ttk.Radiobutton(section, text=text, variable=self.selection_var, value=value, command=self.refresh_method)
            button.grid(row=0, column=col, sticky='w', pady=(0, 10))
            self.settings_controls.append(button)
            self.selection_controls.append(button)
        self.weight_note_var = tk.StringVar(self.root, '')
        ttk.Label(section, textvariable=self.weight_note_var, foreground=MUTED).grid(row=1, column=0, columnspan=3, sticky='w', pady=5)
        self.item_checks, self.weight_entries = [], []
        for index, name in enumerate(ITEM_NAMES):
            check = ttk.Checkbutton(section, text=f'{index + 1}. {name}', variable=self.item_vars[index], command=self.refresh_method)
            check.grid(row=index + 2, column=0, columnspan=2, sticky='w', pady=5)
            entry = ttk.Spinbox(section, from_=.8, to=1.2, increment=.1, textvariable=self.weight_vars[index], width=7)
            entry.grid(row=index + 2, column=2, sticky='e', padx=10)
            self.item_checks.append(check)
            self.weight_entries.append(entry)
            self.settings_controls.extend((check, entry))
        section = self._section(parent, '부처 세부기준 · 8번 항목')
        ttk.Label(section, text='실제 적용할 부처 정책과 판단 척도를 입력한 경우에만 8번 항목을 검토합니다.', wraplength=700).pack(anchor='w', pady=(0, 8))
        holder, self.policy_text = self._text(section, 5)
        holder.pack(fill='x')
        self.policy_text.bind('<KeyRelease>', self.refresh_method)
        self.settings_controls.append(self.policy_text)

    def _results_page(self, parent):
        cards = ttk.Frame(parent)
        cards.pack(fill='x', pady=(0, 14))
        self.card_vars = {}
        for index, (key, label) in enumerate((('status', '분류 상태'), ('grade', '참고 등급'), ('average', '종합평균'), ('documents', '문서 저장'))):
            box = ttk.Frame(cards, padding=8)
            box.grid(row=0, column=index, sticky='nsew', padx=3)
            cards.columnconfigure(index, weight=1)
            ttk.Label(box, text=label, foreground=MUTED).pack(anchor='w')
            variable = tk.StringVar(self.root, '—')
            ttk.Label(box, textvariable=variable, style='Card.TLabel').pack(fill='x', pady=(5, 0))
            self.card_vars[key] = variable
        self.discrepancy_var = tk.StringVar(self.root, '')
        ttk.Label(parent, textvariable=self.discrepancy_var, foreground='#895128', wraplength=780).pack(anchor='w', pady=6)
        self.detail_notebook = ttk.Notebook(parent)
        self.detail_notebook.pack(fill='both', expand=True)
        overview = ttk.Frame(self.detail_notebook)
        self.detail_notebook.add(overview, text='AI 종합 검토의견')
        holder, self.result_text = self._text(overview, 15)
        holder.pack(fill='both', expand=True)
        self.result_text.configure(state='disabled')
        actions = ttk.Frame(parent)
        actions.pack(fill='x', pady=(14, 0))
        self.export_button = ttk.Button(actions, text='HWPX 저장', style='Primary.TButton', command=self.export_documents, state='disabled')
        self.retry_button = ttk.Button(actions, text='문서 다시 저장', command=self.retry_documents, state='disabled')
        self.open_button = ttk.Button(actions, text='저장 폴더 열기', command=self.open_folder, state='disabled')
        for button in (self.export_button, self.retry_button, self.open_button):
            button.pack(side='left', padx=(0, 8))

    def _tab_changed(self, event=None):
        if not hasattr(self, 'run_button'):
            return
        batch = self.notebook.select() == str(self.batch_scroll)
        self.run_button.configure(text='엑셀 처리 시작' if batch else 'AI 에이전트 검토 시작')

    def _key_status(self, state):
        sources = {'session': '이번 실행 입력', 'saved': '보안 저장소', 'environment': '환경변수', 'missing': '키 없음'}
        stored = '저장됨' if state.stored else ('저장 확인 불가' if state.stored is None else '별도 저장 없음')
        self.key_status_var.set(f'{sources[state.source]} · {stored} · 인증 미확인' + (f'\n{state.warning}' if state.warning else ''))

    def on_provider_change(self, event=None):
        if self.busy:
            return
        if event is not None:
            selected = self.provider_display_var.get()
            for provider, label in PROVIDERS.items():
                if selected == label:
                    self.provider_var.set(provider)
                    break
        provider = self.provider_var.get()
        if provider not in PROVIDERS:
            return
        self.provider_display_var.set(PROVIDERS[provider])
        self.key_entry_var.set('')
        model, url = LOCAL_DEFAULTS.get(provider, (DEFAULT_MODELS[provider], ''))
        self.model_var.set(model)
        self.base_url_var.set(url)
        if provider in ('claude', 'openai'):
            self._key_status(self.key_manager.resolve(provider))
        else:
            self.key_status_var.set('로컬 연결 · 입력한 서버 주소에서 처리 · 모델 찾기를 눌러 목록을 확인하세요.')
        self.refresh_method()

    def _summary(self):
        method = '국가영향 지표' if self.method_var.get() == 'impact' else '체크리스트'
        self.summary_var.set(f'v14  |  {PROVIDERS.get(self.provider_var.get(), "")}  |  {self.model_var.get()}  |  {method}')

    def refresh_method(self, event=None):
        checklist = self.method_var.get() == 'checklist'
        policy = bool(self.policy_text.get('1.0', 'end').strip())
        manual = self.selection_var.get() == 'manual'
        if not policy:
            self.item_vars[7].set(False)
        if checklist:
            for index, var in enumerate(self.item_vars):
                var.set(index < 7 or policy)
        for index, (check, entry) in enumerate(zip(self.item_checks, self.weight_entries)):
            enabled = not self.busy and not checklist and manual and (index < 7 or policy)
            check.configure(state='normal' if enabled else 'disabled')
            entry.configure(state='normal' if not self.busy and not checklist and self.item_vars[index].get() and (index < 7 or policy) else 'disabled')
        for control in self.selection_controls:
            control.configure(state='disabled' if checklist or self.busy else 'normal')
        self.weight_note_var.set('체크리스트: 전 항목의 법적 해당성 검토 · 수치 해당 없음' if checklist else '가중치 0.8~1.2 · 선택 항목 평균 1.0 (자동 선택은 실제 선택 후 검증)')
        local = self.provider_var.get() in LOCAL_DEFAULTS
        if not self.busy:
            self.provider_combo.configure(state='readonly')
            self.model_entry.configure(state='normal' if local else 'readonly')
            self.url_entry.configure(state='normal' if local else 'disabled')
            self.discover_button.configure(state='normal' if local else 'disabled')
            self.key_entry.configure(state='disabled' if local else 'normal')
            self.delete_button.configure(state='disabled' if local else 'normal')
        self._summary()

    def apply_settings(self):
        if self.busy:
            return False
        provider = self.provider_var.get()
        if provider in ('claude', 'openai'):
            try:
                state = self.key_manager.apply(provider, self.key_entry_var.get())
            except Exception:
                self.status_var.set('새 키를 저장할 수 없습니다. 마스킹 표시 대신 새 API 키를 입력해 주세요.')
                return False
            finally:
                self.key_entry_var.set('')
            self._key_status(state)
        try:
            self.snapshot_options()
        except (ValueError, TypeError):
            self.status_var.set('설정을 확인해 주세요. 선택 항목·가중치 평균·에이전트 수·모델·서버 주소가 올바른지 확인하세요.')
            return False
        self.refresh_method()
        self.status_var.set('설정을 적용했습니다. 저장 여부와 API 인증 여부는 별개입니다.')
        return True

    def delete_key(self):
        if self.busy or self.provider_var.get() not in ('claude', 'openai'):
            return
        self.key_entry_var.set('')
        self._key_status(self.key_manager.delete(self.provider_var.get()))
        self.status_var.set('앱의 키 삭제를 처리했습니다. 제공자 계정에서 키가 폐기된 것은 아닙니다.')

    def snapshot_options(self, *, task=None, batch=False):
        method = self.method_var.get()
        raw = {'provider': self.provider_var.get(), 'model': self.model_var.get(), 'method': method,
               'num_reviewers': int(self.reviewers_var.get().removesuffix('개')), 'strictness': self.strictness_var.get(),
               'selection_mode': 'auto' if method == 'checklist' else self.selection_var.get(),
               'selected_items': [] if method == 'checklist' else [name for name, var in zip(ITEM_NAMES, self.item_vars) if var.get()],
               'weights': {} if method == 'checklist' else {name: var.get() for name, var, selected in zip(ITEM_NAMES, self.weight_vars, self.item_vars) if selected.get()},
               'ministry_policy': self.policy_text.get('1.0', 'end').strip(),
               'local_base_url': self.base_url_var.get().strip()}
        return normalize_options(raw, ministry_policy_context=(task or {}).get('부처 세부기준', ''), allow_row_policy=batch)

    def _prepare(self, *, task=None, batch=False):
        if not self.apply_settings():
            return None
        options = self.snapshot_options(task=task, batch=batch)
        key = None
        if options.provider in ('claude', 'openai'):
            state = self.key_manager.resolve(options.provider)
            self._key_status(state)
            if not state.has_key:
                self.status_var.set('선택한 제공자의 새 API 키를 입력하고 적용해 주세요.')
                self.notebook.select(self.settings_scroll)
                return None
            key = state.key
        client_factory = self.client_factory
        # This closure captures immutable options and a private key; it is never
        # serialized. Worker code never reads a Tk variable or widget.
        def create_client():
            return client_factory(provider=options.provider, api_key=key, model=options.model,
                                  base_url=options.local_base_url or None)
        return options, create_client

    def start_current(self):
        if self.notebook.select() == str(self.batch_scroll):
            self.start_batch()
        else:
            self.start_single()

    def _set_busy(self, busy):
        self.busy = busy
        for control in self.settings_controls + self.input_controls:
            control.configure(state='disabled' if busy else 'normal')
        for control in (self.run_button, self.export_button, self.retry_button):
            control.configure(state='disabled' if busy else 'normal')
        if not busy:
            for control in self.readonly_controls:
                control.configure(state='readonly')
            for control in (self.export_button, self.retry_button):
                control.configure(state='normal' if self.result is not None else 'disabled')
            self.refresh_method()

    def _launch(self, kind, work):
        if self.busy:
            return False
        self._set_busy(True)
        self.status_var.set('처리 중 · 실행 시작 시의 입력과 설정을 사용합니다.')
        events = self.events
        def worker():
            try:
                payload = work()
                events.put((kind, payload))
            except Exception:
                # SDK/OS exception strings may contain headers or credentials.
                events.put(('error', (kind, '처리하지 못했습니다. 인증·모델 접근 권한·연결·입출력 경로를 확인한 뒤 다시 시도해 주세요.')))
        threading.Thread(target=worker, name=f'v14-{kind}', daemon=True).start()
        return True

    def start_single(self):
        if self.busy:
            return
        try:
            task = task_snapshot({name: text.get('1.0', 'end').strip() for name, text in self.task_fields.items()})
            prepared = self._prepare(task=task)
        except (ValueError, TypeError):
            self.status_var.set('과제명을 입력하고 분류 설정을 확인해 주세요.')
            return
        if prepared is None:
            return
        options, factory = prepared
        classify = self.classify_func
        events = self.events
        self.result = None
        self._selected_batch_index = None
        self.document_dir = ''
        self.open_button.configure(state='disabled')
        self._launch('single', lambda: classify(task, options, factory(),
                     progress_callback=lambda text: events.put(('progress', text))))

    def start_batch(self):
        if self.busy:
            return
        try:
            input_path, output_path = self.input_path_var.get().strip(), self.output_path_var.get().strip()
            if not input_path or not output_path:
                self.status_var.set('입력 엑셀과 결과 저장 경로를 선택해 주세요.')
                return
            workers = int(self.workers_var.get())
            if workers not in range(1, 9):
                raise ValueError()
            prepared = self._prepare(batch=True)
        except (ValueError, TypeError):
            self.status_var.set('설정과 동시 처리 수(1~8)를 확인해 주세요.')
            return
        if prepared is None:
            return
        options, factory = prepared
        resume, forms = self.resume_var.get(), self.forms_var.get()
        batch_func = self.batch_func
        events = self.events
        self.cancel_event = threading.Event()
        cancel = self.cancel_event
        self.cancel_button.configure(state='normal')
        self._launch('batch', lambda: batch_func(input_path, output_path, options, factory,
                     resume=resume, workers=workers, make_forms=forms, cancel_event=cancel,
                     progress_cb=lambda text: events.put(('progress', text)),
                     status_cb=lambda text: events.put(('progress', text))))

    def cancel_batch(self):
        if self.busy:
            self.cancel_event.set()
            self.status_var.set('중지 요청 · 새 과제 시작을 멈춥니다. 진행 중인 작업과 저장이 끝날 때까지 기다려 주세요.')
            self.cancel_button.configure(state='disabled')

    def discover_models(self):
        if self.busy or self.provider_var.get() not in LOCAL_DEFAULTS:
            return
        try:
            options = self.snapshot_options()
        except (ValueError, TypeError):
            self.status_var.set('로컬 모델과 서버 주소를 확인해 주세요.')
            return
        factory = self.client_factory
        self._launch('models', lambda: factory(provider=options.provider, api_key=None, model=options.model,
                     base_url=options.local_base_url or None).discover_models())

    def poll_events(self):
        if self.closed:
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'progress':
                    # Engine progress is a fixed stage label, never raw transport.
                    self.status_var.set(str(payload))
                    continue
                self._set_busy(False)
                self.cancel_button.configure(state='disabled')
                if kind == 'single':
                    self.result = payload
                    self.render_result(payload)
                    self.notebook.select(self.results_scroll)
                    self.status_var.set(f'AI 에이전트 검토 종료 · {payload["status"]} · 문서 {payload["documents"]["status"]} · 감사기록 미사용')
                elif kind == 'documents':
                    self.result = payload
                    self.render_result(payload)
                    documents = payload['documents']
                    completed = sum(f['status'] == '완료' for f in documents['files'])
                    self.status_var.set(f'문서 저장 {documents["status"]} · 성공 {completed}/{documents["expected_files"]} · 분류 결과 보존')
                    self.open_button.configure(state='normal' if self.document_dir else 'disabled')
                elif kind == 'batch_documents':
                    self.render_batch(payload['report'])
                    self.result = payload['result']
                    self._selected_batch_index = next((index for index, result in enumerate(self.batch_results)
                                                      if result['task_fingerprint'] == self.result['task_fingerprint']), None)
                    self.render_result(self.result)
                    documents = self.result['documents']
                    completed = sum(f['status'] == '완료' for f in documents['files'])
                    persistence = payload['persistence']
                    message = (f'문서 생성 {documents["status"]} · 성공 {completed}/{documents["expected_files"]} · '
                               f'결과 기록 {persistence["status"]} (중간 저장 {persistence["checkpoint"]}, '
                               f'엑셀 {persistence["workbook"]}, 감사 {persistence["audit"]})')
                    if persistence['warnings']:
                        message += '\n' + '\n'.join(persistence['warnings'])
                    self.status_var.set(message)
                    self._replace_text(self.result_text, self.result_text.get('1.0', 'end').rstrip() + '\n\n' + message)
                    self.open_button.configure(state='normal' if self.document_dir else 'disabled')
                elif kind == 'batch':
                    self.render_batch(payload)
                elif kind == 'models':
                    self.model_entry.configure(values=tuple(payload))
                    if payload:
                        self.model_var.set(payload[0])
                    self._summary()
                    self.status_var.set(f'로컬 모델 {len(payload)}개를 확인했습니다. 사용할 모델을 선택하세요.')
                elif kind == 'template':
                    self.status_var.set('입력 양식을 저장했습니다.')
                elif kind == 'error':
                    operation, message = payload
                    self.status_var.set(message)
                    if operation == 'single':
                        self.card_vars['status'].set('오류')
                        self.card_vars['grade'].set('미확정')
                        self.card_vars['average'].set('미산출')
                        self.card_vars['documents'].set('미생성')
                        self.discrepancy_var.set('')
                        self._replace_text(self.result_text, message)
                        for tab in self.detail_notebook.tabs()[1:]:
                            widget = self.detail_notebook.nametowidget(tab)
                            self.detail_notebook.forget(tab)
                            widget.destroy()
                        self.notebook.select(self.results_scroll)
        except queue.Empty:
            pass
        self._poll_id = self.root.after(60, self.poll_events)

    def render_result(self, result):
        self.card_vars['status'].set(result['status'])
        self.card_vars['grade'].set(result.get('final_grade') or '미확정')
        self.card_vars['average'].set('해당 없음' if result['method'] == 'checklist' else
                                      ('미산출' if result.get('overall_avg') is None else format_score(result['overall_avg'])))
        documents = result['documents']
        completed = sum(f.get('status') == '완료' for f in documents.get('files', []))
        self.card_vars['documents'].set(f'{documents["status"]} {completed}/{documents["expected_files"]}')
        mismatch = result.get('rule_grade') and result.get('final_grade') and result['rule_grade'] != result['final_grade']
        self.discrepancy_var.set('점수 구간 참고 등급과 AI 종합 검토의견이 다릅니다. 근거를 검토하세요.' if mismatch else '')
        lines = [result['task_name'], 'AI 에이전트 검토 · 최종 확정 등급 아님', '', 'AI 종합 검토의견', result.get('rationale', ''),
                 '', '토론사항', result.get('discussion_points', '')]
        if result.get('candidate', {}).get('reason'):
            lines += ['', '후보 검토', result['candidate']['reason']]
        if result['status'] == '후보제외':
            lines += ['일반 우선 검토 안내 · 평가 완료 등급 아님']
        lines += ['', '검토 필요 사유'] + (result.get('unresolved_reasons') or ['없음'])
        lines += ['', '문서 저장 오류'] + (documents.get('errors') or ['없음'])
        self._replace_text(self.result_text, '\n'.join(lines))
        for tab in self.detail_notebook.tabs()[1:]:
            widget = self.detail_notebook.nametowidget(tab)
            self.detail_notebook.forget(tab)
            widget.destroy()
        for index, reviewer in enumerate(result.get('reviewers', [])):
            page = ttk.Frame(self.detail_notebook)
            self.detail_notebook.add(page, text=f'에이전트 {index + 1} 검토의견')
            holder, text = self._text(page, 15)
            holder.pack(fill='both', expand=True)
            lines = ['에이전트별 검토의견', reviewer['persona'], f'상태: {reviewer["status"]}', f'참고 등급: {reviewer.get("grade") or "미확정"}',
                     f'신뢰도: {reviewer.get("confidence") or "미산출"}',
                     '국가영향 점수: ' + ('해당 없음' if result['method'] == 'checklist' else
                                        ('미산출' if reviewer.get('reviewer_score') is None else format_score(reviewer['reviewer_score']))),
                     '', reviewer.get('rationale', ''), '', '토론사항', reviewer.get('discussion_points', '')]
            for item in reviewer.get('item_reviews', []):
                score = reviewer.get('scores', {}).get(item['item'])
                weight = result.get('weights', {}).get(item['item'])
                lines += ['', f'{item["item"]}: {item["level"]}' + (f' · 점수 {score} · 가중치 {weight}' if score is not None else ''),
                          item.get('note', ''), ' / '.join(item.get('law_refs', []))]
            lines += ['', '검토 필요 사유'] + reviewer.get('unresolved_reasons', [])
            self._replace_text(text, '\n'.join(lines))
        self.export_button.configure(state='disabled' if self.busy else 'normal')
        self.retry_button.configure(state='disabled' if self.busy else 'normal')

    @staticmethod
    def _replace_text(widget, value):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value)
        widget.configure(state='disabled')

    def render_batch(self, report):
        self.batch_report = report
        self.batch_results = report['results']
        self._selected_batch_index = None
        counts = report['counts']
        lines = [f'{report["status"]} · 정상 {counts["완료"]} / 검토필요 {counts["검토필요"]} / 후보제외 {counts["후보제외"]} / 오류 {counts["오류"]}',
                 f'문서 성공 {counts["documents_completed"]}/{counts["documents_expected"]} · 실패 {counts["documents_failed"]} · 누락 {counts["documents_missing"]}',
                 f'감사기록: {report.get("audit_status", "미확인")} · 재사용 {report.get("reused_count", 0)}건',
                 '입력 집계: ' + ' / '.join(f'{ {"blank": "빈 과제명", "example": "예시", "duplicate": "중복"}.get(k, k)} {v}' for k, v in report.get('input_counts', {}).items()),
                 '결과: ' + str(report.get('output_path', ''))]
        lines += report.get('warnings', [])
        self.batch_status_var.set('\n'.join(lines))
        self.status_var.set(lines[0] + ' · 문서 누락 ' + str(counts['documents_missing']) + ' · 감사기록 ' + str(report.get('audit_status', '미확인')))
        self._fill_batch_list()

    def _fill_batch_list(self):
        for item in self.batch_list.get_children():
            self.batch_list.delete(item)
        for index, result in enumerate(self.batch_results):
            self.batch_list.insert('', 'end', iid=str(index), text=result['task_name'],
                                   values=(result['status'], result.get('final_grade') or '미확정', result['documents']['status']))

    def select_batch_result(self, event=None):
        selected = self.batch_list.selection()
        if not selected or self.busy:
            return
        self._selected_batch_index = int(selected[0])
        self.result = self.batch_results[self._selected_batch_index]
        self.document_dir = str((self.batch_report or {}).get('documents_dir') or '')
        saved_paths = [entry['path'] for entry in self.result['documents']['files'] if entry['status'] == '완료']
        if saved_paths:
            self.document_dir = str(Path(saved_paths[0]).parent)
        self.render_result(self.result)
        self.notebook.select(self.results_scroll)
        self.open_button.configure(state='normal' if self.document_dir else 'disabled')

    def export_documents(self):
        if self.busy or self.result is None:
            return
        folder = filedialog.askdirectory(parent=self.root, title='HWPX 저장 폴더 선택')
        if not folder:
            return
        self.document_dir = folder
        self._save_documents(folder)

    def retry_documents(self):
        if self.busy or self.result is None:
            return
        if not self.document_dir:
            self.export_documents()
            return
        self._save_documents(self.document_dir)

    def _save_documents(self, folder):
        saved = copy.deepcopy(self.result)
        document_func = self.document_func
        if self._selected_batch_index is None or self.batch_report is None:
            self._launch('documents', lambda: document_func(saved, folder))
            return
        report = copy.deepcopy(self.batch_report)
        persist_func = self.persist_documents_func
        def regenerate_and_persist():
            generated = document_func(copy.deepcopy(saved), folder)
            try:
                return persist_func(report, saved, generated)
            except Exception:
                # A metadata error must not hide successfully generated files.
                warning = '문서는 생성했지만 결과 기록 갱신에 실패했습니다. 생성 문서와 이전 결과 기록을 각각 확인하세요.'
                report.setdefault('warnings', []).append(warning)
                persistence = {'status': '실패', 'checkpoint': '미시도', 'workbook': '미시도',
                               'audit': '미시도', 'warnings': [warning]}
                report['document_persistence'] = persistence
                preserved = copy.deepcopy(saved)
                preserved['documents'] = copy.deepcopy(generated['documents'])
                return {'result': preserved, 'report': report, 'persistence': persistence}
        self._launch('batch_documents', regenerate_and_persist)

    def open_folder(self):
        if self.document_dir and Path(self.document_dir).is_dir():
            try:
                os.startfile(self.document_dir)
            except OSError:
                self.status_var.set('저장 폴더를 열지 못했습니다. 결과에 표시된 경로를 확인해 주세요.')

    def choose_input(self):
        if not self.busy:
            path = filedialog.askopenfilename(parent=self.root, title='입력 엑셀 선택', filetypes=[('Excel', '*.xlsx')])
            if path:
                self.input_path_var.set(path)

    def choose_output(self):
        if not self.busy:
            path = filedialog.asksaveasfilename(parent=self.root, title='결과 엑셀 저장', defaultextension='.xlsx', filetypes=[('Excel', '*.xlsx')])
            if path:
                self.output_path_var.set(path)

    def save_template(self):
        if self.busy:
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='입력 양식 저장', initialfile='분류대상_양식_v14.xlsx',
                                          defaultextension='.xlsx', filetypes=[('Excel', '*.xlsx')])
        if not path:
            return
        def save():
            from batch_v14 import make_template
            return make_template(path)
        self._launch('template', save)

    def close(self):
        if self.closed:
            return
        if self.busy:
            self.cancel_event.set()
            self.cancel_button.configure(state='disabled')
            self.status_var.set('종료 대기 · 새 대량 작업을 멈춥니다. 진행 중인 모델 요청과 저장은 즉시 중단할 수 없습니다. 처리 종료 후 다시 닫아 주세요.')
            return
        self.closed = True
        self.cancel_event.set()
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
        self.key_entry_var.set('')
        self.root.destroy()


def self_check(report_path):
    """Frozen-executable bootstrap check: withdrawn root and isolated fake store.

    This does not authenticate, read environment keys, use the native credential
    store, or claim a foreground/DPI visual review.
    """
    class FakeStore:
        def __init__(self):
            self.keys = {}
        def get(self, provider):
            return self.keys.get(provider)
        def set(self, provider, key):
            self.keys[provider] = key
        def delete(self, provider):
            self.keys.pop(provider, None)
    root = None
    report = {'version': VERSION, 'models': dict(DEFAULT_MODELS), 'status': 'failed',
              'network_used': False, 'native_credentials_used': False, 'visible_window': False}
    try:
        from hwpx_writer import TEMPLATE_DIR
        templates = [Path(TEMPLATE_DIR) / name for name in ('reviewer_opinion.hwpx', 'committee_summary.hwpx')]
        report['templates'] = []
        for template in templates:
            entry = {'path': str(template), 'exists': template.is_file(), 'zip_valid': False}
            if entry['exists']:
                with ZipFile(template) as archive:
                    names = set(archive.namelist())
                    entry['zip_valid'] = archive.testzip() is None and {'mimetype', 'Contents/content.hpf', 'Contents/section0.xml'} <= names
            report['templates'].append(entry)
        report['sdk_modules'] = {}
        for module_name in ('anthropic', 'openai'):
            try:
                module = __import__(module_name)
                report['sdk_modules'][module_name] = {'imported': True, 'version': str(getattr(module, '__version__', 'unknown'))}
            except ImportError:
                report['sdk_modules'][module_name] = {'imported': False}
        root = tk.Tk()
        root.withdraw()
        app = ClassifierApp(root, key_manager=KeyManager(FakeStore(), {}),
                            client_factory=lambda **kwargs: None)
        root.update_idletasks()
        report['root_state'] = root.state()
        report['window_title'] = root.title()
        report['tk_version'] = str(root.tk.call('info', 'patchlevel'))
        templates_ok = all(t['exists'] and t['zip_valid'] for t in report['templates'])
        sdk_ok = not getattr(sys, 'frozen', False) or all(s['imported'] for s in report['sdk_modules'].values())
        report['status'] = 'passed' if templates_ok and sdk_ok and root.state() == 'withdrawn' and 'v14' in root.title() else 'failed'
        app.close()
        root = None
    except Exception:
        report['error'] = 'v14 오프라인 초기화 확인 실패'
    finally:
        if root is not None:
            root.destroy()
    target = Path(report_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, target)
    return 0 if report['status'] == 'passed' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description='연구보안 등급분류 시뮬레이터 v14')
    parser.add_argument('--self-check', metavar='REPORT_JSON')
    args = parser.parse_args(argv)
    if args.self_check:
        return self_check(args.self_check)
    root = tk.Tk()
    ClassifierApp(root)
    root.mainloop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
