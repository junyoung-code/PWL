#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notepad Auto-Save with Barcode Support
메모장 자동 저장 + 바코드 최신 것만 추출

- 메모장 변경사항 자동 저장
- 바코드 감지 및 최신 것만 파일 저장
- 바코드 스캐너 입력 인터셉트 (어떤 창에서든 메모장으로 리다이렉트)
- UI Automation 방식 (Windows 11 완전 호환)
"""

import win32gui
import win32con
import time
import json
import logging
from datetime import datetime
import os
import sys
import subprocess
import ctypes
from ctypes import wintypes, POINTER, Structure, CFUNCTYPE, c_long, c_int, byref
import threading
import tkinter as tk
from tkinter import messagebox

# UI Automation
import uiautomation as auto

# ============================================================
# 키보드 훅 상수 및 구조체
# ============================================================
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
VK_RETURN = 0x0D

user32 = ctypes.windll.user32


class KBDLLHOOKSTRUCT(Structure):
    _fields_ = [
        ('vkCode', wintypes.DWORD),
        ('scanCode', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', POINTER(ctypes.c_ulong)),
    ]


HOOKPROC = CFUNCTYPE(c_long, c_int, wintypes.WPARAM, wintypes.LPARAM)


class BarcodeInterceptor:
    """
    키보드 훅으로 바코드 스캐너 입력을 감지하여 메모장으로 리다이렉트

    바코드 스캐너는 매우 빠른 속도로 문자를 입력 (< 50ms/키)
    → 일반 타이핑과 구별하여, 바코드 입력만 차단 후 메모장에 전송
    """

    SPEED_THRESHOLD_MS = 50   # 바코드 스캐너 속도 기준 (ms)
    MIN_BARCODE_LEN = 3       # 최소 바코드 길이
    BUFFER_TIMEOUT_S = 0.15   # 버퍼 타임아웃 (초)

    def __init__(self, on_barcode_callback, logger):
        self.on_barcode = on_barcode_callback
        self.logger = logger
        self.buffer = []
        self.buffer_times = []
        self.suppressing = False
        self.hook_id = None
        self._proc_ref = None
        self.running = False
        self._timer = None
        self._lock = threading.Lock()
        self._thread_id = None

    def start(self):
        """별도 스레드에서 키보드 훅 시작"""
        self.running = True
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def stop(self):
        """키보드 훅 해제"""
        self.running = False
        if self._timer:
            self._timer.cancel()
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(
                self._thread_id, 0x0012, 0, 0  # WM_QUIT
            )

    def _vk_to_char(self, vk_code, scan_code):
        """Virtual Key 코드를 문자로 변환"""
        keyboard_state = (ctypes.c_ubyte * 256)()
        user32.GetKeyboardState(keyboard_state)
        buf = (ctypes.c_wchar * 4)()
        result = user32.ToUnicode(vk_code, scan_code, keyboard_state, buf, 4, 0)
        if result > 0:
            return buf[0]
        return None

    def _is_fast(self, current_time):
        """이전 키와의 시간 간격이 빠른지 확인"""
        if not self.buffer_times:
            return False
        delta = current_time - self.buffer_times[-1]
        return 0 < delta < self.SPEED_THRESHOLD_MS

    def _start_timeout(self):
        """타임아웃 타이머 (재)시작"""
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.BUFFER_TIMEOUT_S, self._on_timeout)
        self._timer.daemon = True
        self._timer.start()

    def _on_timeout(self):
        """타임아웃: 바코드가 아니었으므로 억제된 키 재생"""
        with self._lock:
            if self.suppressing and self.buffer:
                self.logger.info(f"[인터셉터] 타임아웃 - 버퍼 재생 ({len(self.buffer)}자)")
                self._replay_buffer()
            self.buffer.clear()
            self.buffer_times.clear()
            self.suppressing = False

    def _replay_buffer(self):
        """억제했던 키를 원래 창에 재생"""
        INPUT_KEYBOARD = 1
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002

        class KEYBDINPUT(Structure):
            _fields_ = [
                ('wVk', wintypes.WORD),
                ('wScan', wintypes.WORD),
                ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD),
                ('dwExtraInfo', POINTER(ctypes.c_ulong)),
            ]

        class INPUT(Structure):
            _fields_ = [
                ('type', wintypes.DWORD),
                ('ki', KEYBDINPUT),
                ('padding', ctypes.c_ubyte * 8),
            ]

        for char in self.buffer:
            # Key down
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki.wScan = ord(char)
            inp.ki.dwFlags = KEYEVENTF_UNICODE
            user32.SendInput(1, byref(inp), ctypes.sizeof(INPUT))
            # Key up
            inp2 = INPUT()
            inp2.type = INPUT_KEYBOARD
            inp2.ki.wScan = ord(char)
            inp2.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            user32.SendInput(1, byref(inp2), ctypes.sizeof(INPUT))

    def _hook_callback(self, nCode, wParam, lParam):
        """저수준 키보드 훅 콜백"""
        if nCode < 0 or wParam != WM_KEYDOWN:
            return user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

        kb = ctypes.cast(lParam, POINTER(KBDLLHOOKSTRUCT)).contents
        vk_code = kb.vkCode
        current_time = kb.time

        # 우리가 재생한 키는 무시 (dwExtraInfo로 구분 불가하므로 flags 확인)
        # LLKHF_INJECTED = 0x10
        if kb.flags & 0x10:
            return user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

        # Enter 키
        if vk_code == VK_RETURN:
            with self._lock:
                if self._timer:
                    self._timer.cancel()
                if len(self.buffer) >= self.MIN_BARCODE_LEN and self.suppressing:
                    # 바코드 완성!
                    barcode = ''.join(self.buffer)
                    self.buffer.clear()
                    self.buffer_times.clear()
                    self.suppressing = False
                    self.logger.info(f"[인터셉터] 바코드 감지: '{barcode}'")
                    threading.Thread(
                        target=self.on_barcode, args=(barcode,), daemon=True
                    ).start()
                    return 1  # Enter 억제
                else:
                    # 바코드 아님 - 버퍼 비우기
                    self.buffer.clear()
                    self.buffer_times.clear()
                    self.suppressing = False
                    return user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

        # 문자 변환
        char = self._vk_to_char(vk_code, kb.scanCode)
        if not char or not char.isprintable():
            return user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

        with self._lock:
            is_fast = self._is_fast(current_time)

            if is_fast:
                # 빠른 입력 - 바코드 가능성
                self.buffer.append(char)
                self.buffer_times.append(current_time)
                if len(self.buffer) >= 2:
                    self.suppressing = True
                self._start_timeout()
                if self.suppressing:
                    return 1  # 억제
            else:
                # 느린 입력 - 일반 타이핑
                if self.suppressing and self.buffer:
                    # 이전에 억제 중이었으나 바코드 아님 → 재생
                    self._replay_buffer()
                self.buffer.clear()
                self.buffer_times.clear()
                self.suppressing = False
                self.buffer.append(char)
                self.buffer_times.append(current_time)
                self._start_timeout()

        return user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

    def _run(self):
        """훅 스레드 메인 루프"""
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        self._proc_ref = HOOKPROC(self._hook_callback)
        self.hook_id = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._proc_ref, None, 0
        )

        if not self.hook_id:
            self.logger.error(f"키보드 훅 설치 실패 (에러: {ctypes.GetLastError()})")
            return

        self.logger.info("키보드 훅 설치 완료 - 바코드 스캐너 입력 감지 대기 중")

        # 메시지 펌프 (훅이 작동하려면 필요)
        msg = wintypes.MSG()
        while self.running:
            result = user32.GetMessageW(byref(msg), None, 0, 0)
            if result <= 0:
                break
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))

        if self.hook_id:
            user32.UnhookWindowsHookEx(self.hook_id)
            self.hook_id = None
        self.logger.info("키보드 훅 해제 완료")


# ============================================================
# 메인 클래스
# ============================================================
class NotepadAutoSave:
    """메모장 자동 저장 + 바코드 처리 클래스"""

    def __init__(self, config_file='config.json'):
        self.config = self.load_config(config_file)
        self.setup_logging()

        # 타겟 메모장 파일
        self.target_notepad_file = self.config.get('target_notepad_file', '')

        # 바코드 처리용 변수
        self.last_content = ""
        self.last_barcode = ""
        self.barcode_output_file = self.config.get('barcode_output_file', 'barcode_latest.txt')

        # 루프 제어
        self.stop_requested = False

        # UIA 메모장 컨트롤 캐시
        self._uia_edit_cache = {}

        # 바코드 인터셉터
        self.interceptor = None
        if self.config.get('enable_barcode_interceptor', True):
            self.interceptor = BarcodeInterceptor(
                on_barcode_callback=self.on_barcode_intercepted,
                logger=self.logger
            )

        self.logger.info("=" * 60)
        self.logger.info("Notepad Auto-Save (UI Automation + 바코드 인터셉터)")
        if self.target_notepad_file:
            self.logger.info(f"타겟 메모장 파일: {self.target_notepad_file}")
        self.logger.info("=" * 60)

    def start_interceptor(self):
        """바코드 인터셉터 시작"""
        if self.interceptor:
            self.interceptor.start()

    def request_stop(self):
        """외부(UI)에서 종료 요청할 때 호출"""
        self.stop_requested = True
        if self.interceptor:
            self.interceptor.stop()
        self.logger.info("종료 요청을 받았습니다. 프로그램을 종료합니다...")

    def on_barcode_intercepted(self, barcode):
        """바코드 인터셉터로부터 바코드를 수신했을 때 (별도 스레드에서 호출됨)"""
        self.logger.info(f"[인터셉터 → 메모장] 바코드 수신: '{barcode}'")

        # 메모장 확보
        notepad_windows = self.ensure_notepad_running()
        if not notepad_windows:
            self.logger.error("[인터셉터] 메모장을 찾을 수 없습니다")
            return

        hwnd = notepad_windows[0]

        # 메모장에 바코드 쓰기
        if self.set_notepad_text(hwnd, barcode):
            self.logger.info(f"[인터셉터] 메모장에 바코드 쓰기 성공: '{barcode}'")
            time.sleep(0.1)
            self.send_save_command(hwnd)
            self.save_barcode_to_file(barcode)
            self.last_barcode = barcode
            self.last_content = barcode
        else:
            self.logger.error(f"[인터셉터] 메모장에 바코드 쓰기 실패: '{barcode}'")

    def load_config(self, config_file):
        """설정 파일 로드"""
        default_config = {
            'check_interval': 5,
            'enable_logging': True,
            'log_file': 'autosave.log',
            'barcode_output_file': 'barcode_latest.txt',
            'enable_barcode_feature': True,
            'enable_barcode_interceptor': True,
            'target_notepad_file': 'AA.txt'
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
        """로깅 설정"""
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
        """열려있는 모든 메모장 창 찾기 (최소화 상태 포함)"""
        notepad_windows = []

        def enum_callback(hwnd, results):
            class_name = win32gui.GetClassName(hwnd)
            if class_name == 'Notepad':
                results.append(hwnd)
            return True

        win32gui.EnumWindows(enum_callback, notepad_windows)
        return notepad_windows

    def find_target_notepad(self):
        """타겟 파일이 열린 메모장 창 찾기"""
        if not self.target_notepad_file:
            return self.find_notepad_windows()

        all_windows = self.find_notepad_windows()
        target_name = self.target_notepad_file.lower()

        for hwnd in all_windows:
            title = self.get_window_title(hwnd).lower()
            # 메모장 타이틀: "AA.txt - 메모장" 또는 "*AA.txt - 메모장"
            if target_name in title:
                return [hwnd]

        return []

    def get_target_file_path(self):
        """타겟 파일의 절대 경로 반환"""
        if not self.target_notepad_file:
            return None
        # exe 실행 경로 기준으로 절대 경로 생성
        if os.path.isabs(self.target_notepad_file):
            return self.target_notepad_file
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        return os.path.join(base_dir, self.target_notepad_file)

    def ensure_notepad_running(self):
        """타겟 메모장이 실행 중이 아니면 자동으로 실행"""
        notepad_windows = self.find_target_notepad()
        if not notepad_windows:
            target_path = self.get_target_file_path()
            if target_path:
                # 타겟 파일이 없으면 생성
                if not os.path.exists(target_path):
                    try:
                        with open(target_path, 'w', encoding='utf-8') as f:
                            f.write('')
                        self.logger.info(f"타겟 파일 생성: {target_path}")
                    except Exception as e:
                        self.logger.error(f"타겟 파일 생성 실패: {e}")

                self.logger.info(f"타겟 메모장({self.target_notepad_file})이 실행 중이 아닙니다. 자동으로 실행합니다...")
                cmd = ['notepad.exe', target_path]
            else:
                self.logger.info("메모장이 실행 중이 아닙니다. 자동으로 실행합니다...")
                cmd = ['notepad.exe']

            try:
                subprocess.Popen(cmd)
                for _ in range(20):
                    time.sleep(0.3)
                    notepad_windows = self.find_target_notepad()
                    if notepad_windows:
                        self.logger.info(f"메모장 자동 실행 완료: {self.target_notepad_file or '새 파일'}")
                        return notepad_windows
                self.logger.warning("메모장 자동 실행 후 창을 찾지 못함")
            except Exception as e:
                self.logger.error(f"메모장 자동 실행 실패: {e}")
        return notepad_windows

    def get_window_title(self, hwnd):
        """윈도우 타이틀 가져오기"""
        try:
            return win32gui.GetWindowText(hwnd)
        except Exception:
            return ""

    def has_unsaved_changes(self, hwnd):
        """저장되지 않은 변경사항이 있는지 확인"""
        title = self.get_window_title(hwnd)
        return title.startswith('*')

    def get_uia_edit_control(self, hwnd):
        """UI Automation으로 메모장의 편집 컨트롤 찾기"""
        if hwnd in self._uia_edit_cache:
            try:
                cached = self._uia_edit_cache[hwnd]
                _ = cached.Name
                return cached
            except Exception:
                del self._uia_edit_cache[hwnd]

        try:
            notepad_control = auto.ControlFromHandle(hwnd)
            if not notepad_control:
                self.logger.error("UIA: 메모장 윈도우 컨트롤을 찾을 수 없음")
                return None

            edit_control = notepad_control.DocumentControl()
            if edit_control and edit_control.Exists(maxSearchSeconds=1):
                self.logger.info("UIA: DocumentControl 발견")
                self._uia_edit_cache[hwnd] = edit_control
                return edit_control

            edit_control = notepad_control.EditControl()
            if edit_control and edit_control.Exists(maxSearchSeconds=1):
                self.logger.info("UIA: EditControl 발견")
                self._uia_edit_cache[hwnd] = edit_control
                return edit_control

            self.logger.error("UIA: 편집 컨트롤을 찾을 수 없음")
            return None

        except Exception as e:
            self.logger.error(f"UIA 편집 컨트롤 검색 오류: {e}")
            return None

    def normalize_line_endings(self, text):
        """줄바꿈 문자를 \\n으로 통일"""
        text = text.replace('\r\n', '\n')
        text = text.replace('\r', '\n')
        return text

    def get_notepad_text(self, hwnd):
        """UI Automation으로 메모장 텍스트 읽기"""
        try:
            edit_control = self.get_uia_edit_control(hwnd)
            if not edit_control:
                return ""

            try:
                tp = edit_control.GetTextPattern()
                if tp:
                    text = tp.DocumentRange.GetText(-1)
                    if text:
                        text = self.normalize_line_endings(text)
                        return text
            except Exception:
                pass

            try:
                vp = edit_control.GetValuePattern()
                if vp:
                    text = vp.Value
                    if text:
                        return self.normalize_line_endings(text)
            except Exception:
                pass

            try:
                edit_hwnd = win32gui.FindWindowEx(hwnd, 0, "Edit", None)
                if edit_hwnd:
                    length = win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)
                    if length > 0:
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXT, length + 1, buffer)
                        return buffer.value
            except Exception:
                pass

            return ""

        except Exception as e:
            self.logger.error(f"get_notepad_text 오류: {e}", exc_info=True)
            return ""

    def set_notepad_text(self, hwnd, text):
        """UI Automation으로 메모장 텍스트 설정"""
        try:
            edit_control = self.get_uia_edit_control(hwnd)
            if not edit_control:
                return False

            try:
                vp = edit_control.GetValuePattern()
                if vp:
                    vp.SetValue(text)
                    self.logger.info(f"[ValuePattern] 텍스트 설정 성공: '{text[:50]}'")
                    return True
            except Exception as e:
                self.logger.info(f"[ValuePattern] SetValue 실패: {e}")

            try:
                tp = edit_control.GetTextPattern()
                if tp:
                    tp.DocumentRange.Select()
                    time.sleep(0.05)
                    vp = edit_control.GetValuePattern()
                    if vp:
                        vp.SetValue(text)
                        self.logger.info(f"[TextPattern+ValuePattern] 텍스트 설정 성공: '{text[:50]}'")
                        return True
            except Exception as e:
                self.logger.info(f"[TextPattern+ValuePattern] 실패: {e}")

            try:
                edit_control.SetFocus()
                time.sleep(0.05)
                edit_control.SendKeys('{Ctrl}a')
                time.sleep(0.05)
                edit_control.SendKeys(text, interval=0)
                self.logger.info(f"[SendKeys] 텍스트 설정 성공: '{text[:50]}'")
                return True
            except Exception as e:
                self.logger.info(f"[SendKeys] 실패: {e}")

            try:
                edit_hwnd = win32gui.FindWindowEx(hwnd, 0, "Edit", None)
                if edit_hwnd:
                    win32gui.SendMessage(edit_hwnd, win32con.WM_SETTEXT, 0, text)
                    self.logger.info(f"[WM_SETTEXT] 폴백 성공: '{text[:50]}'")
                    return True
            except Exception as e:
                self.logger.info(f"[WM_SETTEXT] 폴백 실패: {e}")

            self.logger.error("모든 텍스트 설정 방식 실패")
            return False

        except Exception as e:
            self.logger.error(f"set_notepad_text 오류: {e}", exc_info=True)
            return False

    def extract_latest_barcode(self, text):
        """텍스트에서 최신 바코드 추출 (마지막 비어있지 않은 줄)"""
        lines = text.strip().split('\n')
        for line in reversed(lines):
            line = line.strip()
            if line:
                return line
        return None

    def save_barcode_to_file(self, barcode):
        """바코드를 별도 파일에 저장 (최신 것만)"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(self.barcode_output_file, 'w', encoding='utf-8') as f:
                f.write(f"최근 스캔 시간: {timestamp}\n")
                f.write(f"바코드: {barcode}\n")
            self.logger.info(f"바코드 저장 완료: {barcode} -> {self.barcode_output_file}")
        except Exception as e:
            self.logger.error(f"바코드 파일 저장 오류: {e}")

    def send_save_command(self, hwnd):
        """메모장 창에 직접 저장 명령 전송"""
        try:
            WM_COMMAND = 0x0111
            IDFILE_SAVE = 3
            win32gui.SendMessage(hwnd, WM_COMMAND, IDFILE_SAVE, 0)
            return True
        except Exception as e:
            self.logger.error(f"저장 명령 전송 오류: {e}")
            return False

    def process_notepad_content(self, hwnd):
        """메모장 내용 처리 (바코드 추출 및 메모장 업데이트)"""
        if not self.config.get('enable_barcode_feature', True):
            return

        current_text = self.get_notepad_text(hwnd)

        if not current_text.strip():
            return

        if current_text == self.last_content:
            return

        latest_barcode = self.extract_latest_barcode(current_text)
        if not latest_barcode:
            return

        lines = [l for l in current_text.strip().split('\n') if l.strip()]
        line_count = len(lines)

        # 무한 루프 방지: 유효한 줄이 1줄이고 그게 최신 바코드면 스킵
        if line_count <= 1 and current_text.strip() == latest_barcode.strip():
            self.last_content = current_text
            self.last_barcode = latest_barcode
            return

        self.logger.info(f"[모니터] 여러 줄 감지 ({line_count}줄). 마지막 줄만 남기기: '{latest_barcode}'")

        if self.set_notepad_text(hwnd, latest_barcode):
            time.sleep(0.1)
            self.send_save_command(hwnd)
            self.save_barcode_to_file(latest_barcode)
            self.last_barcode = latest_barcode
            self.last_content = latest_barcode
        else:
            self.last_content = current_text
            self.last_barcode = latest_barcode


def main():
    """메인 함수"""

    root = tk.Tk()
    root.withdraw()

    start = messagebox.askyesno(
        "Notepad Auto-Save",
        "메모장 자동 저장 프로그램을 시작하시겠습니까?\n\n"
        "기능:\n"
        "- 메모장 자동 저장\n"
        "- 바코드 스캐너 입력 자동 감지\n"
        "- 어떤 창에서든 바코드 → 메모장(AA.txt)으로 전송\n\n"
        "방식: UI Automation + 키보드 훅"
    )
    if not start:
        return

    autosaver = NotepadAutoSave()

    # 바코드 인터셉터 시작
    autosaver.start_interceptor()

    # 종료 버튼이 있는 작은 창
    ui = tk.Tk()
    ui.title("Notepad Auto-Save (실행 중)")
    ui.resizable(False, False)

    target_file = autosaver.target_notepad_file or "(모든 메모장)"
    label = tk.Label(
        ui,
        text=f"메모장 자동 저장이 실행 중입니다.\n"
             f"타겟 파일: {target_file}\n"
             f"바코드 스캐너 입력을 자동 감지합니다.\n"
             f"(어떤 창에서든 {target_file}으로 전송)\n\n"
             f"끝내려면 아래 버튼을 누르세요.",
        justify=tk.LEFT
    )
    label.pack(padx=20, pady=15)

    def on_exit():
        autosaver.request_stop()
        ui.destroy()

    exit_btn = tk.Button(ui, text="끝내기", command=on_exit, width=20)
    exit_btn.pack(padx=20, pady=(0, 15))

    ui.protocol("WM_DELETE_WINDOW", on_exit)

    def tick():
        if autosaver.stop_requested:
            return

        check_interval = autosaver.config['check_interval']

        notepad_windows = autosaver.ensure_notepad_running()
        if notepad_windows:
            # 타겟 메모장만 처리 (find_target_notepad가 이미 필터링함)
            hwnd = notepad_windows[0]
            title = autosaver.get_window_title(hwnd)

            if autosaver.has_unsaved_changes(hwnd):
                autosaver.logger.info(f"변경사항 감지: '{title}'")
                if autosaver.send_save_command(hwnd):
                    autosaver.logger.info(f"자동 저장 완료: '{title}'")

            # 메모장 직접 입력 감지 (인터셉터와 병행)
            autosaver.process_notepad_content(hwnd)

        ui.after(int(check_interval * 1000), tick)

    tick()
    ui.mainloop()


if __name__ == '__main__':
    main()
