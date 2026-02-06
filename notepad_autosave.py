#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notepad Auto-Save with Barcode Support
메모장 자동 저장 + 바코드 최신 것만 추출

- 메모장 변경사항 자동 저장
- 바코드 감지 및 최신 것만 파일 저장
- 완전 자동 모드 (확인 불필요)
- 백그라운드 처리 (방해 최소)
"""

import win32gui
import win32con
import win32api
import win32clipboard
import time
import json
import logging
from datetime import datetime
import os
import sys
import tkinter as tk
from tkinter import messagebox


class NotepadAutoSave:
    """메모장 자동 저장 + 바코드 처리 클래스"""

    def __init__(self, config_file='config.json'):
        """
        초기화

        Args:
            config_file: 설정 파일 경로
        """
        self.config = self.load_config(config_file)
        self.setup_logging()

        # 바코드 처리용 변수
        self.last_content = ""
        self.last_barcode = ""
        self.barcode_output_file = self.config.get('barcode_output_file', 'barcode_latest.txt')

        # 루프 제어
        self.stop_requested = False

        self.logger.info("=" * 60)
        self.logger.info("Notepad Auto-Save with Barcode Support Started")
        self.logger.info("=" * 60)

    def request_stop(self):
        """외부(UI)에서 종료 요청할 때 호출"""
        self.stop_requested = True
        self.logger.info("종료 요청을 받았습니다. 프로그램을 종료합니다...")

    def load_config(self, config_file):
        """설정 파일 로드"""
        default_config = {
            'check_interval': 5,
            'enable_logging': True,
            'log_file': 'autosave.log',
            'barcode_output_file': 'barcode_latest.txt',
            'enable_barcode_feature': True
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
        """열려있는 모든 메모장 창 찾기"""
        notepad_windows = []

        def enum_callback(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
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

    def get_edit_control(self, hwnd):
        """메모장의 편집 컨트롤 찾기"""
        edit_hwnd = win32gui.FindWindowEx(hwnd, 0, "Edit", None)

        if not edit_hwnd:
            # Edit 컨트롤을 찾지 못하면 모든 자식 윈도우 검색
            self.logger.warning(f"Edit 컨트롤을 직접 찾지 못함. 자식 윈도우 검색 중...")

            def enum_child_callback(child_hwnd, results):
                class_name = win32gui.GetClassName(child_hwnd)
                self.logger.info(f"  자식 윈도우 발견: {class_name}")
                # Windows 10, 11 메모장의 다양한 편집 컨트롤 지원
                if class_name.lower() in ['edit', 'richedit', 'richedit20w', 'richedit50w',
                                           'richeditd2dpt', 'notepadtextbox']:
                    results.append(child_hwnd)
                    self.logger.info(f"  → 편집 컨트롤로 인식: {class_name}")
                return True

            child_windows = []
            win32gui.EnumChildWindows(hwnd, enum_child_callback, child_windows)

            if child_windows:
                edit_hwnd = child_windows[0]
                self.logger.info(f"Edit 컨트롤 찾음: {win32gui.GetClassName(edit_hwnd)}")
            else:
                self.logger.error(f"Edit 컨트롤을 찾을 수 없음!")

        return edit_hwnd

    def open_clipboard_with_retry(self, max_retries=5, delay=0.2):
        """클립보드를 재시도 로직과 함께 열기"""
        for attempt in range(max_retries):
            try:
                win32clipboard.OpenClipboard()
                return True
            except Exception as e:
                if attempt < max_retries - 1:
                    self.logger.warning(f"클립보드 열기 실패 (시도 {attempt + 1}/{max_retries}): {e}")
                    time.sleep(delay * (attempt + 1))  # 지수 백오프
                else:
                    self.logger.error(f"클립보드 열기 최종 실패: {e}")
                    return False
        return False

    def get_notepad_text(self, hwnd, edit_hwnd):
        """메모장 텍스트 읽기 (클립보드 방식 - Windows 11 호환)"""
        try:
            # 방법 1: WM_GETTEXT 시도 (Windows 10 메모장용)
            length = win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)

            if length > 0:
                import ctypes
                buffer = ctypes.create_unicode_buffer(length + 1)
                result = win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXT, length + 1, buffer)
                if result > 0:
                    text = buffer.value
                    self.logger.debug(f"WM_GETTEXT 성공: '{text[:50]}'")
                    return text

            # 방법 2: 클립보드 사용 (Windows 11 메모장용)
            self.logger.info(f"클립보드 방식으로 텍스트 읽기 시도...")

            # 메모장 창 활성화 (키보드 이벤트가 올바른 창으로 가도록)
            try:
                win32gui.SetForegroundWindow(hwnd)
                win32gui.SetFocus(edit_hwnd)
                time.sleep(0.2)  # 창 활성화 대기
                self.logger.info("메모장 창 활성화 완료")
            except Exception as e:
                self.logger.warning(f"창 활성화 실패: {e}")

            # 현재 클립보드 백업
            old_clipboard = ""
            try:
                if self.open_clipboard_with_retry():
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        old_clipboard = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    win32clipboard.CloseClipboard()
                time.sleep(0.1)  # 클립보드 해제 대기
            except Exception as e:
                self.logger.warning(f"클립보드 백업 실패: {e}")

            # Ctrl+A로 전체 선택
            VK_CONTROL = win32con.VK_CONTROL
            VK_A = ord('A')
            VK_C = ord('C')

            win32api.keybd_event(VK_CONTROL, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_A, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_A, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.15)

            # Ctrl+C로 복사
            win32api.keybd_event(VK_CONTROL, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_C, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_C, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.2)  # 복사 완료 대기

            # 클립보드에서 읽기
            text = ""
            try:
                if self.open_clipboard_with_retry():
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    win32clipboard.CloseClipboard()
                    self.logger.info(f"클립보드에서 텍스트 읽기 성공: '{text[:50]}'")
                time.sleep(0.1)  # 클립보드 해제 대기
            except Exception as e:
                self.logger.error(f"클립보드 읽기 오류: {e}")
                try:
                    win32clipboard.CloseClipboard()
                except:
                    pass

            # 원래 클립보드 복원
            if old_clipboard:
                try:
                    time.sleep(0.2)  # 복원 전 충분한 대기
                    if self.open_clipboard_with_retry():
                        win32clipboard.EmptyClipboard()
                        win32clipboard.SetClipboardText(old_clipboard, win32con.CF_UNICODETEXT)
                        win32clipboard.CloseClipboard()
                    time.sleep(0.1)
                except Exception as e:
                    self.logger.warning(f"클립보드 복원 실패: {e}")

            return text

        except Exception as e:
            self.logger.error(f"get_notepad_text 오류: {e}", exc_info=True)
            return ""

    def set_notepad_text(self, hwnd, edit_hwnd, text):
        """메모장 텍스트 설정 (클립보드 방식 - Windows 11 호환)"""
        try:
            self.logger.info(f"클립보드 방식으로 텍스트 설정: '{text[:50]}'")

            # 1. 메모장 창 활성화 (키보드 이벤트가 올바른 창으로 가도록)
            try:
                win32gui.SetForegroundWindow(hwnd)
                win32gui.SetFocus(edit_hwnd)
                time.sleep(0.3)  # 창 활성화 대기
                self.logger.info("메모장 창 활성화 완료")
            except Exception as e:
                self.logger.warning(f"창 활성화 실패: {e}")

            # 2. 클립보드가 완전히 해제될 때까지 대기
            time.sleep(0.3)

            # 3. 클립보드에 텍스트 복사
            if not self.open_clipboard_with_retry():
                self.logger.error("클립보드를 열 수 없습니다")
                return False

            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                self.logger.info("클립보드에 텍스트 설정 완료")
                time.sleep(0.2)  # 클립보드 해제 대기
            except Exception as e:
                self.logger.error(f"클립보드 설정 오류: {e}")
                try:
                    win32clipboard.CloseClipboard()
                except:
                    pass
                return False

            # 4. Ctrl+A로 전체 선택
            VK_CONTROL = win32con.VK_CONTROL
            VK_A = ord('A')
            VK_V = ord('V')

            win32api.keybd_event(VK_CONTROL, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_A, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_A, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.15)

            # 5. Ctrl+V로 붙여넣기
            win32api.keybd_event(VK_CONTROL, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_V, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_V, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.05)
            win32api.keybd_event(VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.3)  # 붙여넣기 완료 대기

            self.logger.info(f"텍스트 설정 완료")
            return True

        except Exception as e:
            self.logger.error(f"set_notepad_text 오류: {e}", exc_info=True)
            return False

    def extract_latest_barcode(self, text):
        """텍스트에서 최신 바코드 추출 (8자리 이상 숫자 또는 모든 텍스트)"""
        lines = text.strip().split('\n')

        for line in reversed(lines):
            line = line.strip()
            # 8자리 이상 숫자 우선, 없으면 마지막 줄 반환
            if line:
                # 숫자 8자리 이상이면 바코드
                if line.isdigit() and len(line) >= 8:
                    return line
                # 숫자가 아니어도 마지막 줄이면 반환
                elif line:
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
        """메모장 창에 직접 저장 명령 전송 (다른 프로그램에 영향 없음)"""
        try:
            # WM_COMMAND with IDFILE_SAVE (메모장의 저장 명령)
            # 메뉴 ID: File > Save = 3 (0x0003)
            WM_COMMAND = 0x0111
            IDFILE_SAVE = 3

            # 메모장 창에만 저장 명령 전송 (다른 프로그램에 영향 없음)
            win32gui.SendMessage(hwnd, WM_COMMAND, IDFILE_SAVE, 0)

            return True
        except Exception as e:
            self.logger.error(f"저장 명령 전송 오류: {e}")
            return False

    def process_notepad_content(self, hwnd, edit_hwnd):
        """메모장 내용 처리 (바코드 추출 및 메모장 업데이트)"""
        if not self.config.get('enable_barcode_feature', True):
            self.logger.info("바코드 기능이 비활성화되어 있습니다.")
            return

        if not edit_hwnd:
            self.logger.error("Edit 컨트롤이 없습니다!")
            return

        current_text = self.get_notepad_text(hwnd, edit_hwnd)
        self.logger.info(f"[디버그] 현재 메모장 내용 (길이: {len(current_text)}): '{current_text[:100]}'")
        self.logger.info(f"[디버그] 이전 내용 (길이: {len(self.last_content)}): '{self.last_content[:100] if self.last_content else 'None'}'")

        # 메모장 내용이 비어있으면 스킵
        if not current_text.strip():
            self.logger.info("[디버그] 메모장이 비어있습니다. 처리 건너뜀")
            return

        # 메모장 내용이 변경되었는지 확인
        if current_text == self.last_content:
            self.logger.info("[디버그] 내용이 이전과 동일합니다. 처리 건너뜀")
            return

        self.logger.info("[디버그] 내용이 변경되었습니다! 바코드 추출 시작")

        # 최신 바코드 추출
        latest_barcode = self.extract_latest_barcode(current_text)
        self.logger.info(f"[디버그] 추출된 바코드: '{latest_barcode}'")

        # 바코드가 추출되면 항상 처리 (같은 내용이어도!)
        if latest_barcode:
            self.logger.info(f"✓ 바코드 감지: '{latest_barcode}'")

            # 무한 루프 방지: 이미 한 줄만 있고 그게 최신 바코드면 스킵
            if current_text.strip() == latest_barcode.strip():
                self.logger.info(f"[디버그] 이미 마지막 줄만 남아있습니다. 스킵합니다.")
                self.last_content = current_text
                self.last_barcode = latest_barcode
                return

            self.logger.info(f"[디버그] 여러 줄 감지됨. 마지막 줄만 남기기 시작...")

            # 1. 메모장 내용을 최신 바코드만 남기고 삭제
            if self.set_notepad_text(hwnd, edit_hwnd, latest_barcode):
                self.logger.info(f"✓ 메모장 내용 업데이트 성공: '{latest_barcode}'만 남김")

                # 강제 저장 (내용 변경 후)
                time.sleep(0.1)
                if self.send_save_command(hwnd):
                    self.logger.info(f"✓ 메모장 저장 완료")

                # 2. 별도 파일에도 저장 (같은 내용이어도 타임스탬프 업데이트)
                self.save_barcode_to_file(latest_barcode)

                self.last_barcode = latest_barcode
                self.last_content = latest_barcode  # 업데이트된 내용으로 변경
            else:
                # 텍스트 설정 실패 시 무한 루프 방지
                self.logger.error(f"✗ 텍스트 설정 실패! 무한 루프 방지를 위해 last_content 업데이트")
                self.last_content = current_text
                self.last_barcode = latest_barcode
        else:
            self.logger.warning(f"[디버그] 바코드를 추출할 수 없습니다.")

    def monitor_loop(self):
        """메인 모니터링 루프"""
        check_interval = self.config['check_interval']
        barcode_enabled = self.config.get('enable_barcode_feature', True)

        self.logger.info(f"모니터링 시작 (체크 주기: {check_interval}초)")
        if barcode_enabled:
            self.logger.info(f"바코드 기능: 활성화 (저장 위치: {self.barcode_output_file})")
        else:
            self.logger.info(f"바코드 기능: 비활성화")

        try:
            while not self.stop_requested:
                notepad_windows = self.find_notepad_windows()

                if notepad_windows:
                    self.logger.debug(f"발견된 메모장 창: {len(notepad_windows)}개")

                    for hwnd in notepad_windows:
                        title = self.get_window_title(hwnd)

                        # 1. 자동 저장 처리
                        if self.has_unsaved_changes(hwnd):
                            self.logger.info(f"변경사항 감지: '{title}'")

                            if self.send_save_command(hwnd):
                                self.logger.info(f"자동 저장 완료: '{title}'")
                            else:
                                self.logger.warning(f"자동 저장 실패: '{title}'")

                        # 2. 바코드 처리
                        edit_hwnd = self.get_edit_control(hwnd)
                        if edit_hwnd:
                            self.process_notepad_content(hwnd, edit_hwnd)

                time.sleep(check_interval)

            self.logger.info("모니터링 루프 종료 완료")

        except KeyboardInterrupt:
            self.logger.info("\n프로그램 종료 (Ctrl+C)")
        except Exception as e:
            self.logger.error(f"모니터링 오류: {e}", exc_info=True)


def main():
    """메인 함수"""

    # 시작 확인창
    root = tk.Tk()
    root.withdraw()

    start = messagebox.askyesno(
        "Notepad Auto-Save",
        "메모장 자동 저장 프로그램을 시작하시겠습니까?\n\n"
        "기능:\n"
        "✅ 메모장 자동 저장\n"
        "✅ 바코드 최신 것만 추출 (자동)"
    )
    if not start:
        return

    # 프로그램 실행
    autosaver = NotepadAutoSave()

    # 종료 버튼이 있는 작은 창
    ui = tk.Tk()
    ui.title("Noㅇtepad Auto-Save (실행 중)")
    ui.resizable(False, False)

    label = tk.Label(
        ui,
        text="메모장 자동 저장이 실행 중입니다.\n"
             "바코드 기능도 활성화되었습니다.\n\n"
             "끝내려면 아래 버튼을 누르세요.",
        justify=tk.LEFT
    )
    label.pack(padx=20, pady=15)

    def on_exit():
        autosaver.request_stop()
        ui.destroy()

    exit_btn = tk.Button(ui, text="끝내기", command=on_exit, width=20)
    exit_btn.pack(padx=20, pady=(0, 15))

    # 창 X를 눌러도 동일하게 종료
    ui.protocol("WM_DELETE_WINDOW", on_exit)

    # UI 이벤트 루프와 자동 저장 루프 통합
    def tick():
        if autosaver.stop_requested:
            return

        check_interval = autosaver.config['check_interval']

        notepad_windows = autosaver.find_notepad_windows()
        if notepad_windows:
            for hwnd in notepad_windows:
                title = autosaver.get_window_title(hwnd)

                # 자동 저장
                if autosaver.has_unsaved_changes(hwnd):
                    autosaver.logger.info(f"변경사항 감지: '{title}'")
                    if autosaver.send_save_command(hwnd):
                        autosaver.logger.info(f"자동 저장 완료: '{title}'")
                    else:
                        autosaver.logger.warning(f"자동 저장 실패: '{title}'")

                # 바코드 처리
                edit_hwnd = autosaver.get_edit_control(hwnd)
                if edit_hwnd:
                    autosaver.process_notepad_content(hwnd, edit_hwnd)

        # 다음 실행 예약
        ui.after(int(check_interval * 1000), tick)

    tick()
    ui.mainloop()


if __name__ == '__main__':
    main()
