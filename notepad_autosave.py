#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Barcode Scanner → Notepad Writer
바코드 스캐너에서 읽은 데이터를 메모장에 넣고 자동 저장하는 프로그램

- 바코드 스캐너 입력을 프로그램 창에서 캡처
- 메모장에 최신 바코드 한 줄만 남기고 이전 데이터 삭제
- SendMessage로 메모장에만 저장 (다른 프로그램에 영향 없음)
"""

import win32gui
import win32con
import json
import logging
import os
import sys

import tkinter as tk
from tkinter import messagebox


class BarcodeScanWriter:
    """바코드 스캐너 캡처 + 메모장 저장 클래스"""

    def __init__(self, config_file='config.json'):
        self.config = self.load_config(config_file)
        self.setup_logging()
        self.logger.info("=" * 50)
        self.logger.info("Barcode Scanner Writer Started")
        self.logger.info("=" * 50)

    def load_config(self, config_file):
        default_config = {
            'enable_logging': True,
            'log_file': 'autosave.log',
            'barcode_timeout_ms': 500,
        }

        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return {**default_config, **config}
            except Exception as e:
                print(f"설정 파일 로드 오류: {e}")
                print("기본 설정을 사용합니다.")

        return default_config

    def setup_logging(self):
        if self.config['enable_logging']:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler(self.config['log_file'], encoding='utf-8'),
                    logging.StreamHandler(sys.stdout)
                ]
            )
        else:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(levelname)s - %(message)s',
                handlers=[logging.StreamHandler(sys.stdout)]
            )

        self.logger = logging.getLogger(__name__)

    def find_notepad_windows(self):
        """열려있는 메모장 창 찾기"""
        notepad_windows = []

        def enum_callback(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                class_name = win32gui.GetClassName(hwnd)
                if class_name == 'Notepad':
                    results.append(hwnd)
            return True

        win32gui.EnumWindows(enum_callback, notepad_windows)
        return notepad_windows

    def find_notepad_edit_control(self, notepad_hwnd):
        """메모장의 Edit 자식 컨트롤 찾기"""
        edit_hwnd = win32gui.FindWindowEx(notepad_hwnd, 0, 'Edit', None)
        if not edit_hwnd:
            # Windows 11 새 메모장 대비
            edit_hwnd = win32gui.FindWindowEx(notepad_hwnd, 0, 'RichEditD2DPT', None)
        return edit_hwnd

    def get_save_menu_id(self, notepad_hwnd):
        """메모장의 '저장' 메뉴 ID를 동적으로 찾기"""
        menu_bar = win32gui.GetMenu(notepad_hwnd)
        if not menu_bar:
            return None
        file_menu = win32gui.GetSubMenu(menu_bar, 0)
        if not file_menu:
            return None
        # Save는 보통 File 메뉴의 인덱스 2~4 위치
        for index in [2, 3, 4]:
            menu_id = win32gui.GetMenuItemID(file_menu, index)
            if menu_id > 0:
                return menu_id
        return None

    def write_to_notepad(self, notepad_hwnd, barcode_text):
        """메모장의 Edit 컨트롤에 바코드 텍스트 쓰기 (기존 내용 전부 교체)"""
        edit_hwnd = self.find_notepad_edit_control(notepad_hwnd)
        if not edit_hwnd:
            self.logger.error("메모장 Edit 컨트롤을 찾을 수 없습니다")
            return False

        win32gui.SendMessage(edit_hwnd, win32con.WM_SETTEXT, 0, barcode_text)
        return True

    def save_notepad(self, notepad_hwnd):
        """메모장에 SendMessage로 저장 명령 전송 (메모장에만 영향)"""
        save_id = self.get_save_menu_id(notepad_hwnd)
        if save_id:
            win32gui.SendMessage(notepad_hwnd, win32con.WM_COMMAND, save_id, 0)
            return True
        else:
            self.logger.error("저장 메뉴 ID를 찾을 수 없습니다")
            return False

    def process_barcode(self, barcode_text):
        """바코드 처리: 메모장 찾기 → 텍스트 쓰기 → 저장"""
        barcode_text = barcode_text.strip()
        if not barcode_text:
            return False

        notepad_windows = self.find_notepad_windows()
        if not notepad_windows:
            self.logger.error("열린 메모장 창이 없습니다")
            return False

        notepad_hwnd = notepad_windows[0]

        if not self.write_to_notepad(notepad_hwnd, barcode_text):
            return False

        if not self.save_notepad(notepad_hwnd):
            return False

        self.logger.info(f"바코드 저장 완료: '{barcode_text}'")
        return True


def main():
    """메인 함수"""

    # 시작 확인창
    init_root = tk.Tk()
    init_root.withdraw()

    start = messagebox.askyesno("Barcode Scanner", "바코드 스캐너 프로그램을 시작하겠습니까?")
    init_root.destroy()
    if not start:
        return

    scanner = BarcodeScanWriter()

    # 메인 UI
    root = tk.Tk()
    root.title("Barcode Scanner (실행 중)")
    root.attributes('-topmost', True)
    root.resizable(False, False)

    # 바코드 입력 필드
    tk.Label(root, text="바코드 입력:", anchor='w').pack(padx=14, pady=(12, 2), fill='x')

    barcode_var = tk.StringVar()
    entry = tk.Entry(root, textvariable=barcode_var, font=('Arial', 16), width=30)
    entry.pack(padx=14, pady=(0, 8))
    entry.focus_set()

    # 상태 표시
    last_scan_label = tk.Label(root, text="마지막 스캔: (없음)", anchor='w', fg='gray')
    last_scan_label.pack(padx=14, fill='x')

    status_label = tk.Label(root, text="상태: 스캔 대기 중...", anchor='w')
    status_label.pack(padx=14, fill='x')

    timeout_id = [None]

    def do_process():
        """바코드 처리 실행"""
        timeout_id[0] = None
        text = barcode_var.get().strip()
        if not text:
            return

        success = scanner.process_barcode(text)
        last_scan_label.config(text=f"마지막 스캔: {text}", fg='black')

        if success:
            status_label.config(text="상태: 메모장에 저장 완료", fg='green')
        else:
            status_label.config(text="상태: 오류 발생 - 메모장을 확인하세요", fg='red')

        barcode_var.set('')
        entry.focus_set()

    def on_enter(event):
        """Enter 키 → 즉시 바코드 처리"""
        if timeout_id[0]:
            root.after_cancel(timeout_id[0])
            timeout_id[0] = None
        do_process()

    def on_key_release(event):
        """키 입력마다 타임아웃 리셋 (Enter 없는 스캐너 대비)"""
        if event.keysym == 'Return':
            return
        if timeout_id[0]:
            root.after_cancel(timeout_id[0])
        timeout_ms = scanner.config.get('barcode_timeout_ms', 500)
        timeout_id[0] = root.after(timeout_ms, do_process)

    entry.bind('<Return>', on_enter)
    entry.bind('<KeyRelease>', on_key_release)

    # 창 포커스 시 Entry에 포커스 복구
    root.bind('<FocusIn>', lambda e: entry.focus_set())

    # 끝내기 버튼
    def on_exit():
        root.destroy()

    exit_btn = tk.Button(root, text="끝내기", command=on_exit, width=20)
    exit_btn.pack(padx=14, pady=(8, 12))

    root.protocol("WM_DELETE_WINDOW", on_exit)
    root.mainloop()


if __name__ == '__main__':
    main()
