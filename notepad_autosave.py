#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Barcode Scanner → Notepad Writer (Global Capture)
바코드 스캐너에서 읽은 데이터를 메모장에 넣고 자동 저장하는 프로그램

- Low-level 키보드 훅으로 포커스 무관하게 바코드 캡처
- 타이밍 기반으로 스캐너 입력과 일반 키보드 구분
- 스캐너 입력은 다른 프로그램에 전달되지 않음 (억제)
- 메모장에 최신 바코드 한 줄만 남기고 자동 저장
- SendMessage로 메모장에만 저장 (다른 프로그램에 영향 없음)
"""

import ctypes
import ctypes.wintypes as wintypes
import time
import win32gui
import win32con
import json
import logging
import os
import sys

import tkinter as tk
from tkinter import messagebox

# ============================================================
# Win32 키보드 훅 상수 및 구조체
# ============================================================
user32 = ctypes.windll.user32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
HC_ACTION = 0
MAPVK_VK_TO_CHAR = 2
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_CAPITAL = 0x14

# 좌/우 구분 modifier 키
MODIFIER_VK_CODES = {
    VK_SHIFT, VK_CONTROL, VK_MENU, VK_CAPITAL,
    0xA0, 0xA1,  # L/R Shift
    0xA2, 0xA3,  # L/R Control
    0xA4, 0xA5,  # L/R Alt
}

HOOKPROC = ctypes.CFUNCTYPE(
    ctypes.c_long,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# ============================================================
# 키보드 훅 매니저
# ============================================================
class KeyboardHookManager:
    """Low-level 키보드 훅으로 바코드 스캐너 입력을 감지하고 억제"""

    def __init__(self, on_barcode_complete, key_interval_ms=50, flush_timeout_ms=100):
        self.on_barcode_complete = on_barcode_complete
        self.key_interval_ms = key_interval_ms
        self.flush_timeout_ms = flush_timeout_ms

        self.buffer = []
        self.last_key_time = 0.0
        self.in_burst = False
        self.pending_char = None

        self.hook_handle = None
        self._hook_proc = None  # GC 방지
        self.flush_after_id = None
        self.root = None

    def set_root(self, root):
        self.root = root

    def install(self):
        self._hook_proc = HOOKPROC(self._hook_callback)
        self.hook_handle = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc,
            None,
            0,
        )
        if not self.hook_handle:
            raise RuntimeError("키보드 훅 설치 실패")

    def uninstall(self):
        if self.hook_handle:
            user32.UnhookWindowsHookEx(self.hook_handle)
            self.hook_handle = None
        self._cancel_flush_timer()

    def _pass_through(self, nCode, wParam, lParam):
        return user32.CallNextHookExW(self.hook_handle, nCode, wParam, lParam)

    def _hook_callback(self, nCode, wParam, lParam):
        if nCode != HC_ACTION or wParam not in (WM_KEYDOWN, WM_SYSKEYDOWN):
            return self._pass_through(nCode, wParam, lParam)

        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk_code = kb.vkCode

        # Modifier 키는 항상 통과
        if vk_code in MODIFIER_VK_CODES:
            return self._pass_through(nCode, wParam, lParam)

        now = time.perf_counter()
        elapsed_ms = (now - self.last_key_time) * 1000 if self.last_key_time > 0 else 9999
        self.last_key_time = now

        # Enter + 버퍼 있음 → 바코드 완성
        if vk_code == VK_RETURN and (self.buffer or self.in_burst):
            barcode = ''.join(self.buffer)
            self.buffer.clear()
            self.in_burst = False
            self.pending_char = None
            self._cancel_flush_timer()
            if barcode and self.root:
                self.root.after(0, lambda b=barcode: self.on_barcode_complete(b))
            return 1  # Enter 억제

        char = self._vk_to_char(vk_code)

        # 이미 버스트 모드 → 계속 억제 및 누적
        if self.in_burst:
            if char:
                self.buffer.append(char)
            self._reset_flush_timer()
            return 1

        # 빠른 입력 감지 (이전 키와의 간격 < threshold)
        if elapsed_ms < self.key_interval_ms and self.pending_char:
            # 버스트 확인! pending_char(첫 글자) + 현재 글자 버퍼에 추가
            self.in_burst = True
            self.buffer.append(self.pending_char)
            if char:
                self.buffer.append(char)
            self.pending_char = None
            self._reset_flush_timer()
            return 1  # 두 번째 글자부터 억제

        # 느린 입력 → 일반 키보드로 판단, 통과
        # 현재 글자를 pending으로 기록 (다음 키가 빠르면 버스트 시작)
        self.pending_char = char
        return self._pass_through(nCode, wParam, lParam)

    def _vk_to_char(self, vk_code):
        char_code = user32.MapVirtualKeyW(vk_code, MAPVK_VK_TO_CHAR)
        if char_code > 0:
            return chr(char_code)
        return None

    def _reset_flush_timer(self):
        self._cancel_flush_timer()
        if self.root:
            self.flush_after_id = self.root.after(
                self.flush_timeout_ms, self._flush_buffer
            )

    def _cancel_flush_timer(self):
        if self.flush_after_id and self.root:
            self.root.after_cancel(self.flush_after_id)
            self.flush_after_id = None

    def _flush_buffer(self):
        """타임아웃: 버퍼를 바코드로 처리"""
        self.flush_after_id = None
        if self.buffer:
            barcode = ''.join(self.buffer)
            self.buffer.clear()
            self.in_burst = False
            self.pending_char = None
            self.on_barcode_complete(barcode)


# ============================================================
# 바코드 → 메모장 저장 클래스
# ============================================================
class BarcodeScanWriter:
    """바코드 데이터를 메모장에 쓰고 저장"""

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
            'scanner_key_interval_ms': 50,
            'barcode_flush_timeout_ms': 100,
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


# ============================================================
# 메인
# ============================================================
def main():
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

    # 상태 표시
    tk.Label(
        root,
        text="스캐너 입력 감지 중... (다른 프로그램 사용 가능)",
        anchor='w', fg='blue', font=('Arial', 10),
    ).pack(padx=14, pady=(12, 4), fill='x')

    last_scan_label = tk.Label(root, text="마지막 스캔: (없음)", anchor='w', fg='gray')
    last_scan_label.pack(padx=14, fill='x')

    status_label = tk.Label(root, text="상태: 스캔 대기 중...", anchor='w')
    status_label.pack(padx=14, fill='x')

    scan_count = [0]

    def on_barcode(barcode_text):
        scan_count[0] += 1
        success = scanner.process_barcode(barcode_text)
        last_scan_label.config(text=f"마지막 스캔: {barcode_text}", fg='black')
        if success:
            status_label.config(
                text=f"상태: 메모장에 저장 완료 (총 {scan_count[0]}회)", fg='green'
            )
        else:
            status_label.config(text="상태: 오류 발생 - 메모장을 확인하세요", fg='red')

    # 키보드 훅 설치
    hook_mgr = KeyboardHookManager(
        on_barcode_complete=on_barcode,
        key_interval_ms=scanner.config.get('scanner_key_interval_ms', 50),
        flush_timeout_ms=scanner.config.get('barcode_flush_timeout_ms', 100),
    )
    hook_mgr.set_root(root)
    hook_mgr.install()
    scanner.logger.info("키보드 훅 설치 완료 - 바코드 스캐너 감지 중")

    # 끝내기
    def on_exit():
        hook_mgr.uninstall()
        scanner.logger.info("프로그램 종료")
        root.destroy()

    exit_btn = tk.Button(root, text="끝내기", command=on_exit, width=20)
    exit_btn.pack(padx=14, pady=(8, 12))

    root.protocol("WM_DELETE_WINDOW", on_exit)
    root.mainloop()


if __name__ == '__main__':
    main()
