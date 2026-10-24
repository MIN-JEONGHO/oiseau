# -*- coding: utf-8 -*-
"""
국외수혜정보 자동 통계산출 프로그램 (GUI)

사용법
  1) 연구자 raw 파일 선택 (연구자raw 시트가 있는 파일 또는 단독 파일)
  2) 과제 raw 파일 선택 (과제raw 시트가 있는 파일 또는 단독 파일)
     ※ 두 시트가 모두 들어있는 결합 파일이면 같은 파일을 두 번 선택해도 됨
  3) [통계 산출 실행] → 통계분석결과_날짜.xlsx 생성

매핑 규칙(기관별칭·민감국가·소속정규화)은 프로그램과 같은 폴더의
'매핑테이블.xlsx'에서 읽습니다. 새 별칭이 생기면 그 파일만 수정하세요.
"""
import os
import sys
import datetime
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from stat_engine import load_mappings, load_researcher_raw, load_project_raw, compute_stats
from report_builder import build_report


def app_dir():
    """exe로 패키징돼도 실행파일 위치를 기준으로 매핑테이블을 찾는다."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('국외지원사항 자동 통계산출')
        self.geometry('720x520')
        self.resizable(False, False)

        self.res_path = tk.StringVar()
        self.prj_path = tk.StringVar()
        self.map_path = tk.StringVar(value=os.path.join(app_dir(), '매핑테이블.xlsx'))
        self.out_dir = tk.StringVar(value=app_dir())

        pad = {'padx': 10, 'pady': 4}
        f = tk.Frame(self); f.pack(fill='x', **pad)
        tk.Label(f, text='국외지원사항 자동 통계산출', font=('맑은 고딕', 14, 'bold')).pack(anchor='w')
        tk.Label(f, text='raw 파일 2개를 업로드하면 통계분석 리포트(xlsx)를 자동 생성합니다.',
                 font=('맑은 고딕', 9), fg='#555').pack(anchor='w')

        self._file_row('① 연구자 raw 파일', self.res_path)
        self._file_row('② 과제 raw 파일', self.prj_path)
        self._file_row('③ 매핑테이블 (기관별칭·민감국가·소속정규화)', self.map_path)
        self._dir_row('④ 결과 저장 폴더', self.out_dir)

        tk.Button(self, text='통계 산출 실행', font=('맑은 고딕', 11, 'bold'),
                  bg='#2F5B95', fg='white', height=2, command=self.run).pack(fill='x', padx=10, pady=8)

        self.log = scrolledtext.ScrolledText(self, height=12, font=('맑은 고딕', 9), state='disabled')
        self.log.pack(fill='both', expand=True, padx=10, pady=(0, 10))

    def _file_row(self, label, var):
        f = tk.Frame(self); f.pack(fill='x', padx=10, pady=3)
        tk.Label(f, text=label, font=('맑은 고딕', 9, 'bold'), width=38, anchor='w').pack(side='left')
        tk.Entry(f, textvariable=var, font=('맑은 고딕', 9)).pack(side='left', fill='x', expand=True, padx=4)
        tk.Button(f, text='찾아보기', font=('맑은 고딕', 9),
                  command=lambda: self._pick(var)).pack(side='left')

    def _dir_row(self, label, var):
        f = tk.Frame(self); f.pack(fill='x', padx=10, pady=3)
        tk.Label(f, text=label, font=('맑은 고딕', 9, 'bold'), width=38, anchor='w').pack(side='left')
        tk.Entry(f, textvariable=var, font=('맑은 고딕', 9)).pack(side='left', fill='x', expand=True, padx=4)
        tk.Button(f, text='찾아보기', font=('맑은 고딕', 9),
                  command=lambda: self._pick_dir(var)).pack(side='left')

    def _pick(self, var):
        p = filedialog.askopenfilename(filetypes=[('Excel 파일', '*.xlsx *.xlsm *.xls')])
        if p:
            var.set(p)
            # 결합 파일 편의: 연구자 raw를 고르면 과제 raw도 같은 파일로 기본 설정
            if var is self.res_path and not self.prj_path.get():
                self.prj_path.set(p)

    def _pick_dir(self, var):
        p = filedialog.askdirectory()
        if p:
            var.set(p)

    def _log(self, msg):
        self.log.configure(state='normal')
        self.log.insert('end', msg + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')
        self.update()

    def run(self):
        try:
            if not self.res_path.get() or not self.prj_path.get():
                messagebox.showwarning('입력 확인', '연구자 raw / 과제 raw 파일을 모두 선택해 주세요.')
                return
            if not os.path.exists(self.map_path.get()):
                messagebox.showerror('매핑테이블 없음',
                                     f'매핑테이블 파일을 찾을 수 없습니다:\n{self.map_path.get()}\n\n'
                                     '프로그램과 같은 폴더에 "매핑테이블.xlsx"를 두거나 직접 지정해 주세요.')
                return

            self._log('▶ 매핑테이블 읽는 중...')
            org_alias, country_map, aff_norm = load_mappings(self.map_path.get())
            self._log(f'   기관별칭 {len(org_alias)}건 / 민감국가 {len(country_map)}건 / 소속정규화 {len(aff_norm)}건')

            self._log('▶ 연구자 raw 읽는 중...')
            res = load_researcher_raw(self.res_path.get())
            self._log(f'   {len(res):,}건 로드')

            self._log('▶ 과제 raw 읽는 중...')
            prj = load_project_raw(self.prj_path.get())
            self._log(f'   {len(prj):,}건 로드')

            self._log('▶ 통계 산출 중...')
            S = compute_stats(res, prj, org_alias, country_map, aff_norm)

            out = os.path.join(self.out_dir.get(),
                               f'통계분석결과_{datetime.datetime.now():%Y%m%d_%H%M}.xlsx')
            self._log('▶ 리포트 생성 중...')
            build_report(S, out)

            self._log(f'✔ 완료: {out}')
            self._log(f'   총 {S["총건수"]:,}건 / 연구자 {S["고유연구자수"]:,}명 / '
                      f'국가 {S["국가수"]}개 / 기관 {S["지원기관수"]:,}개 / '
                      f'보안우려 {S["보안"]["위험국가"] + S["보안"]["민감국가"]:,}건')
            if messagebox.askyesno('완료', f'통계 산출이 완료되었습니다.\n\n{out}\n\n지금 열어볼까요?'):
                os.startfile(out) if sys.platform == 'win32' else os.system(f'open "{out}"')
        except Exception:
            err = traceback.format_exc()
            self._log('✖ 오류 발생:\n' + err)
            messagebox.showerror('오류', '처리 중 오류가 발생했습니다. 하단 로그를 확인해 주세요.')


if __name__ == '__main__':
    # CLI 모드: python 국외수혜_통계산출.py 연구자.xlsx 과제.xlsx [출력.xlsx]
    if len(sys.argv) >= 3:
        org_alias, country_map, aff_norm = load_mappings(os.path.join(app_dir(), '매핑테이블.xlsx'))
        res = load_researcher_raw(sys.argv[1])
        prj = load_project_raw(sys.argv[2])
        S = compute_stats(res, prj, org_alias, country_map, aff_norm)
        out = sys.argv[3] if len(sys.argv) > 3 else f'통계분석결과_{datetime.datetime.now():%Y%m%d}.xlsx'
        build_report(S, out)
        print('완료:', out)
    else:
        App().mainloop()
