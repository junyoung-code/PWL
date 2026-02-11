#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notepad Auto-Save with Barcode Support
메모장 자동 저장 + 바코드 최신 것만 추출

- 메모장 변경사항 자동 저장
- 바코드 감지 및 최신 것만 파일 저장
- Raw Input API로 바코드 스캐너 장치 식별
- 키보드 훅으로 스캐너 입력만 억제 (일반 키보드 영향 없음)
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
import ctypes
from ctypes import wintypes, POINTER, Structure, CFUNCTYPE, c_long, c_int, byref
import threading
import tkinter as tk
from tkinter import messagebox

# UI Automation
import uiautomation as auto

# ============================================================
# Win32 상수
# ============================================================
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_INPUT = 0x00FF
WM_DESTROY = 0x0002
VK_RETURN = 0x0D
VK_SHIFT = 0x10
MAPVK_VK_TO_CHAR = 2

# Raw Input 상수
RIDEV_INPUTSINK = 0x00000100
RIM_TYPEKEYBOARD = 1
RID_INPUT = 0x10000003
RI_KEY_BREAK = 1

# LLKHF_INJECTED - SendInput 등으로 주입된 키 식별
LLKHF_INJECTED = 0x10


# ============================================================
# ctypes 구조체
# ============================================================
class KBDLLHOOKSTRUCT(Structure):
    _fields_ = [
        ('vkCode', wintypes.DWORD),
        ('scanCode', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', POINTER(ctypes.c_ulong)),
    ]


HOOKPROC = CFUNCTYPE(c_long, c_int, wintypes.WPARAM, wintypes.LPARAM)


class RAWINPUTDEVICE(Structure):
    _fields_ = [
        ('usUsagePage', wintypes.USHORT),
        ('usUsage', wintypes.USHORT),
        ('dwFlags', wintypes.DWORD),
        ('hwndTarget', wintypes.HWND),
    ]


class RAWINPUTHEADER(Structure):
    _fields_ = [
        ('dwType', wintypes.DWORD),
        ('dwSize', wintypes.DWORD),
        ('hDevice', wintypes.HANDLE),
        ('wParam', wintypes.WPARAM),
    ]


class RAWKEYBOARD(Structure):
    _fields_ = [
        ('MakeCode', wintypes.USHORT),
        ('Flags', wintypes.USHORT),
        ('Reserved', wintypes.USHORT),
        ('VKey', wintypes.USHORT),
        ('Message', wintypes.UINT),
        ('ExtraInformation', wintypes.ULONG),
    ]


class RAWINPUT(Structure):
    _fields_ = [
        ('header', RAWINPUTHEADER),
        ('keyboard', RAWKEYBOARD),
    ]


class RAWINPUTDEVICELIST(Structure):
    _fields_ = [
        ('hDevice', wintypes.HANDLE),
        ('dwType', wintypes.DWORD),
    ]


class WNDCLASSEXW(Structure):
    _fields_ = [
        ('cbSize', wintypes.UINT),
        ('style', wintypes.UINT),
        ('lpfnWndProc', ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)),
        ('cbClsExtra', ctypes.c_int),
        ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE),
        ('hIcon', wintypes.HANDLE),
        ('hCursor', wintypes.HANDLE),
        ('hbrBackground', wintypes.HANDLE),
        ('lpszMenuName', wintypes.LPCWSTR),
        ('lpszClassName', wintypes.LPCWSTR),
        ('hIconSm', wintypes.HANDLE),
    ]


WNDPROC_TYPE = ctypes.WINFUNCTYPE(
    ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)

# API 함수 프로토타입
user32.GetRawInputData.restype = wintypes.UINT
user32.GetRawInputData.argtypes = [
    wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
    POINTER(wintypes.UINT), wintypes.UINT
]

user32.GetRawInputDeviceList.restype = wintypes.UINT
user32.GetRawInputDeviceList.argtypes = [
    ctypes.c_void_p, POINTER(wintypes.UINT), wintypes.UINT
]

user32.RegisterRawInputDevices.restype = wintypes.BOOL
user32.RegisterRawInputDevices.argtypes = [
    POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT
]

user32.DefWindowProcW.restype = ctypes.c_long
user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
]


# ============================================================
# BarcodeInterceptor - Raw Input + Keyboard Hook
# ============================================================
class BarcodeInterceptor:
    """
    Raw Input API로 바코드 스캐너 장치를 식별하고,
    키보드 훅으로 스캐너 입력만 억제하여 메모장에 전달.
    일반 키보드는 영향 없음.
    """

    def __init__(self, on_barcode_callback, logger):
        self.on_barcode = on_barcode_callback
        self.logger = logger

        # 바코드 버퍼
        self.buffer = []

        # 훅 관련
        self.hook_id = None
        self._hook_proc_ref = None
        self.running = False
        self._thread_id = None

        # Raw Input 관련
        self._msg_hwnd = None
        self._wndproc_ref = None
        self._scanner_device = None  # 식별된 스캐너 장치 핸들
        self._is_scanner_key = False  # WM_INPUT에서 설정, 훅에서 읽음
        self._identifying = True  # 스캐너 식별 모드
        self._known_devices = set()  # 시작 시 존재하는 키보드 장치

    def start(self):
        """별도 스레드에서 Raw Input + 키보드 훅 시작"""
        self.running = True
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def stop(self):
        """정리 및 종료"""
        self.running = False
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT

    def _enumerate_keyboard_devices(self):
        """현재 연결된 키보드 장치 목록 조회"""
        num_devices = wintypes.UINT(0)
        user32.GetRawInputDeviceList(
            None, byref(num_devices), ctypes.sizeof(RAWINPUTDEVICELIST)
        )
        if num_devices.value == 0:
            return

        devices = (RAWINPUTDEVICELIST * num_devices.value)()
        user32.GetRawInputDeviceList(
            devices, byref(num_devices), ctypes.sizeof(RAWINPUTDEVICELIST)
        )

        for dev in devices:
            if dev.dwType == RIM_TYPEKEYBOARD:
                self._known_devices.add(dev.hDevice)

        self.logger.info(f"[Raw Input] 기존 키보드 장치 {len(self._known_devices)}개 감지")

    def _create_message_window(self):
        """WM_INPUT을 수신할 메시지 전용 윈도우 생성"""
        hInstance = kernel32.GetModuleHandleW(None)
        class_name = "BarcodeRawInputWindow"

        self._wndproc_ref = WNDPROC_TYPE(self._wndproc)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc_ref
        wc.hInstance = hInstance
        wc.lpszClassName = class_name

        atom = user32.RegisterClassExW(byref(wc))
        if not atom:
            self.logger.error(f"[Raw Input] RegisterClassExW 실패: {ctypes.GetLastError()}")
            return False

        HWND_MESSAGE = -3
        self._msg_hwnd = user32.CreateWindowExW(
            0, class_name, "BarcodeRawInput", 0,
            0, 0, 0, 0,
            HWND_MESSAGE, None, hInstance, None
        )

        if not self._msg_hwnd:
            self.logger.error(f"[Raw Input] CreateWindowExW 실패: {ctypes.GetLastError()}")
            return False

        self.logger.info("[Raw Input] 메시지 윈도우 생성 완료")
        return True

    def _register_raw_input(self):
        """Raw Input으로 키보드 장치 수신 등록"""
        rid = RAWINPUTDEVICE()
        rid.usUsagePage = 0x01  # Generic Desktop
        rid.usUsage = 0x06  # Keyboard
        rid.dwFlags = RIDEV_INPUTSINK  # 포커스 없어도 수신
        rid.hwndTarget = self._msg_hwnd

        result = user32.RegisterRawInputDevices(
            byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE)
        )
        if not result:
            self.logger.error(f"[Raw Input] RegisterRawInputDevices 실패: {ctypes.GetLastError()}")
            return False

        self.logger.info("[Raw Input] 키보드 Raw Input 등록 완료 (RIDEV_INPUTSINK)")
        return True

    def _wndproc(self, hwnd, msg, wParam, lParam):
        """윈도우 프로시저 - WM_INPUT 처리"""
        if msg == WM_INPUT:
            self._handle_raw_input(lParam)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wParam, lParam)

    def _handle_raw_input(self, lParam):
        """WM_INPUT 메시지에서 장치 정보 추출"""
        dwSize = wintypes.UINT(0)
        user32.GetRawInputData(
            lParam, RID_INPUT, None, byref(dwSize),
            ctypes.sizeof(RAWINPUTHEADER)
        )

        if dwSize.value == 0:
            return

        buf = ctypes.create_string_buffer(dwSize.value)
        result = user32.GetRawInputData(
            lParam, RID_INPUT, buf, byref(dwSize),
            ctypes.sizeof(RAWINPUTHEADER)
        )

        if result == 0xFFFFFFFF:  # (UINT)-1
            return

        raw = ctypes.cast(buf, POINTER(RAWINPUT)).contents

        if raw.header.dwType != RIM_TYPEKEYBOARD:
            return

        hDevice = raw.header.hDevice

        # 스캐너 식별 모드: 기존에 없던 새 장치 = 스캐너
        if self._identifying and hDevice and hDevice not in self._known_devices:
            self._scanner_device = hDevice
            self._identifying = False
            self.logger.info(f"[Raw Input] 바코드 스캐너 식별 완료! (장치 핸들: {hDevice})")

        # 스캐너 장치 여부 플래그 설정 (훅에서 읽음)
        if hDevice == self._scanner_device:
            self._is_scanner_key = True
        else:
            self._is_scanner_key = False

    def _hook_callback(self, nCode, wParam, lParam):
        """저수준 키보드 훅 콜백 - 스캐너 입력만 억제"""
        try:
            if nCode < 0:
                return user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

            kb = ctypes.cast(lParam, POINTER(KBDLLHOOKSTRUCT)).contents

            # 주입된 키(SendInput 등)는 무시
            if kb.flags & LLKHF_INJECTED:
                return user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

            # 스캐너 입력인지 확인
            if self._is_scanner_key and self._scanner_device:
                vk_code = kb.vkCode

                if wParam == WM_KEYDOWN or wParam == WM_SYSKEYDOWN:
                    if vk_code == VK_RETURN:
                        # Enter → 바코드 완성
                        if len(self.buffer) > 0:
                            barcode = ''.join(self.buffer)
                            self.buffer.clear()
                            self.logger.info(f"[인터셉터] 바코드 완성: '{barcode}'")
                            threading.Thread(
                                target=self.on_barcode, args=(barcode,), daemon=True
                            ).start()
                        return 1  # Enter 억제

                    elif vk_code == VK_SHIFT:
                        # Shift 키는 버퍼에 추가하지 않지만 억제
                        return 1

                    else:
                        # MapVirtualKeyW로 문자 변환 (ToUnicode 대신 - 키보드 상태 오염 없음)
                        char_code = user32.MapVirtualKeyW(vk_code, MAPVK_VK_TO_CHAR)
                        if char_code > 0:
                            self.buffer.append(chr(char_code))
                        return 1  # 억제

                elif wParam == WM_KEYUP or wParam == WM_SYSKEYUP:
                    return 1  # key up도 억제

            # 일반 키보드 → 통과
            return user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

        except Exception:
            return user32.CallNextHookEx(self.hook_id, nCode, wParam, lParam)

    def _run(self):
        """훅 스레드 메인 루프"""
        self._thread_id = kernel32.GetCurrentThreadId()

        # 1. 메시지 윈도우 생성
        if not self._create_message_window():
            self.logger.error("[인터셉터] 메시지 윈도우 생성 실패 - 인터셉터 비활성화")
            return

        # 2. Raw Input 등록
        if not self._register_raw_input():
            self.logger.error("[인터셉터] Raw Input 등록 실패 - 인터셉터 비활성화")
            return

        # 3. 기존 키보드 장치 목록 기록
        self._enumerate_keyboard_devices()

        # 4. 키보드 훅 설치
        self._hook_proc_ref = HOOKPROC(self._hook_callback)
        self.hook_id = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._hook_proc_ref, None, 0
        )

        if not self.hook_id:
            self.logger.error(f"[인터셉터] 키보드 훅 설치 실패: {ctypes.GetLastError()}")
            return

        self.logger.info("[인터셉터] 키보드 훅 설치 완료")
        self.logger.info("[인터셉터] 바코드 스캐너를 한번 스캔하세요 (장치 식별용)")

        # 5. 메시지 루프
        msg = wintypes.MSG()
        while self.running:
            result = user32.GetMessageW(byref(msg), None, 0, 0)
            if result <= 0:
                break
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))

        # 정리
        if self.hook_id:
            user32.UnhookWindowsHookEx(self.hook_id)
            self.hook_id = None
        if self._msg_hwnd:
            user32.DestroyWindow(self._msg_hwnd)
            self._msg_hwnd = None

        self.logger.info("[인터셉터] 종료 완료")


# ============================================================
# 메인 클래스
# ============================================================
class NotepadAutoSave:
    """메모장 자동 저장 + 바코드 처리 클래스"""

    def __init__(self, config_file='config.json'):
        self.config = self.load_config(config_file)
        self.setup_logging()

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
        self.logger.info("Notepad Auto-Save (UI Automation + Raw Input 바코드 인터셉터)")
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
        """바코드 인터셉터로부터 바코드를 수신했을 때"""
        self.logger.info(f"[인터셉터 → 메모장] 바코드 수신: '{barcode}'")

        notepad_windows = self.find_notepad_windows()
        if not notepad_windows:
            self.logger.warning("[인터셉터] 메모장이 열려있지 않습니다. 파일에만 저장합니다.")
            self.save_barcode_to_file(barcode)
            return

        hwnd = notepad_windows[0]

        if self.set_notepad_text(hwnd, barcode):
            self.logger.info(f"[인터셉터] 메모장에 바코드 쓰기 성공: '{barcode}'")
            time.sleep(0.1)
            self.send_save_command(hwnd)
            self.save_barcode_to_file(barcode)
            self.last_barcode = barcode
            self.last_content = barcode
        else:
            self.logger.error(f"[인터셉터] 메모장에 바코드 쓰기 실패: '{barcode}'")
            self.save_barcode_to_file(barcode)

    def load_config(self, config_file):
        """설정 파일 로드"""
        default_config = {
            'check_interval': 5,
            'enable_logging': True,
            'log_file': 'autosave.log',
            'barcode_output_file': 'barcode_latest.txt',
            'enable_barcode_feature': True,
            'enable_barcode_interceptor': True
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
        """줄바꿈 문자를 \n으로 통일"""
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
                        lines = [l for l in text.split('\n') if l.strip()]
                        self.logger.info(f"[TextPattern] 텍스트 읽기 성공 (길이: {len(text)}, 유효줄수: {len(lines)})")
                        return text
            except Exception as e:
                self.logger.info(f"[TextPattern] 실패: {e}")

            try:
                vp = edit_control.GetValuePattern()
                if vp:
                    text = vp.Value
                    if text:
                        text = self.normalize_line_endings(text)
                        self.logger.info(f"[ValuePattern] 텍스트 읽기 성공 (길이: {len(text)})")
                        return text
            except Exception as e:
                self.logger.info(f"[ValuePattern] 실패: {e}")

            try:
                edit_hwnd = win32gui.FindWindowEx(hwnd, 0, "Edit", None)
                if edit_hwnd:
                    length = win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)
                    if length > 0:
                        buffer = ctypes.create_unicode_buffer(length + 1)
                        win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXT, length + 1, buffer)
                        text = buffer.value
                        self.logger.info(f"[WM_GETTEXT] 폴백 성공 (길이: {len(text)})")
                        return text
            except Exception as e:
                self.logger.info(f"[WM_GETTEXT] 폴백 실패: {e}")

            self.logger.warning("모든 텍스트 읽기 방식 실패")
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
        "- 바코드 스캐너 자동 감지 (Raw Input)\n"
        "- 스캐너 입력만 차단하여 메모장에 전달\n\n"
        "방식: UI Automation + Raw Input API"
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

    label = tk.Label(
        ui,
        text="메모장 자동 저장이 실행 중입니다.\n"
             "바코드 스캐너 입력을 자동 감지합니다.\n"
             "(첫 스캔 시 스캐너 장치 자동 식별)\n\n"
             "끝내려면 아래 버튼을 누르세요.",
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

        notepad_windows = autosaver.find_notepad_windows()
        if notepad_windows:
            for hwnd in notepad_windows:
                title = autosaver.get_window_title(hwnd)

                if autosaver.has_unsaved_changes(hwnd):
                    autosaver.logger.info(f"변경사항 감지: '{title}'")
                    if autosaver.send_save_command(hwnd):
                        autosaver.logger.info(f"자동 저장 완료: '{title}'")

                autosaver.process_notepad_content(hwnd)

        ui.after(int(check_interval * 1000), tick)

    tick()
    ui.mainloop()


if __name__ == '__main__':
    main()
