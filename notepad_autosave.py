#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notepad Auto-Save with Barcode Support
메모장 자동 저장 + 바코드 최신 것만 추출

- 메모장 변경사항 자동 저장
- 바코드 감지 및 최신 것만 파일 저장
- 완전 자동 모드 (확인 불필요)
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
import tkinter as tk
from tkinter import messagebox

# UI Automation
import uiautomation as auto


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

        self.logger.info("=" * 60)
        self.logger.info("Notepad Auto-Save (UI Automation 방식)")
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
        """열려있는 모든 메모장 창 찾기 (최소화 상태 포함)"""
        notepad_windows = []

        def enum_callback(hwnd, results):
            class_name = win32gui.GetClassName(hwnd)
            if class_name == 'Notepad':
                results.append(hwnd)
            return True

        win32gui.EnumWindows(enum_callback, notepad_windows)
        return notepad_windows

    def ensure_notepad_running(self):
        """메모장이 실행 중이 아니면 자동으로 실행"""
        notepad_windows = self.find_notepad_windows()
        if not notepad_windows:
            self.logger.info("메모장이 실행 중이 아닙니다. 자동으로 실행합니다...")
            try:
                subprocess.Popen(['notepad.exe'])
                # 메모장이 완전히 열릴 때까지 대기
                for _ in range(20):
                    time.sleep(0.3)
                    notepad_windows = self.find_notepad_windows()
                    if notepad_windows:
                        self.logger.info("메모장 자동 실행 완료")
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
        # 캐시에 있으면 유효성 확인 후 반환
        if hwnd in self._uia_edit_cache:
            try:
                cached = self._uia_edit_cache[hwnd]
                # 컨트롤이 아직 유효한지 간단히 확인
                _ = cached.Name
                return cached
            except Exception:
                del self._uia_edit_cache[hwnd]

        try:
            # hwnd로 UIA 윈도우 컨트롤 찾기
            notepad_control = auto.ControlFromHandle(hwnd)
            if not notepad_control:
                self.logger.error("UIA: 메모장 윈도우 컨트롤을 찾을 수 없음")
                return None

            # 방법 1: DocumentControl 찾기 (Windows 11 메모장)
            edit_control = notepad_control.DocumentControl()
            if edit_control and edit_control.Exists(maxSearchSeconds=1):
                self.logger.info(f"UIA: DocumentControl 발견")
                self._uia_edit_cache[hwnd] = edit_control
                return edit_control

            # 방법 2: EditControl 찾기 (Windows 10 메모장)
            edit_control = notepad_control.EditControl()
            if edit_control and edit_control.Exists(maxSearchSeconds=1):
                self.logger.info(f"UIA: EditControl 발견")
                self._uia_edit_cache[hwnd] = edit_control
                return edit_control

            self.logger.error("UIA: 편집 컨트롤을 찾을 수 없음")
            return None

        except Exception as e:
            self.logger.error(f"UIA 편집 컨트롤 검색 오류: {e}")
            return None

    def normalize_line_endings(self, text):
        """줄바꿈 문자를 \n으로 통일 (Windows 11 UIA는 \r만 사용할 수 있음)"""
        # \r\n → \n 먼저 처리, 그 다음 남은 \r → \n
        text = text.replace('\r\n', '\n')
        text = text.replace('\r', '\n')
        return text

    def get_notepad_text(self, hwnd):
        """UI Automation으로 메모장 텍스트 읽기"""
        try:
            edit_control = self.get_uia_edit_control(hwnd)
            if not edit_control:
                return ""

            # 방법 1: TextPattern 사용 (멀티라인 텍스트에 가장 정확)
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

            # 방법 2: ValuePattern 사용 (단일 라인 또는 간단한 텍스트)
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

            # 방법 3: WM_GETTEXT 폴백 (Win32 - Windows 10)
            try:
                edit_hwnd = win32gui.FindWindowEx(hwnd, 0, "Edit", None)
                if edit_hwnd:
                    import ctypes
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

            # 방법 1: ValuePattern 사용
            try:
                vp = edit_control.GetValuePattern()
                if vp:
                    vp.SetValue(text)
                    self.logger.info(f"[ValuePattern] 텍스트 설정 성공: '{text[:50]}'")
                    return True
            except Exception as e:
                self.logger.info(f"[ValuePattern] SetValue 실패: {e}")

            # 방법 2: TextPattern으로 전체 선택 후 ValuePattern으로 설정
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

            # 방법 3: SendKeys로 전체 선택 후 텍스트 입력
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

            # 방법 4: Win32 WM_SETTEXT 폴백 (Windows 10)
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
        self.logger.info(f"[디버그] 현재 메모장 내용 (길이: {len(current_text)}): '{current_text[:100]}'")

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

        if latest_barcode:
            self.logger.info(f"바코드 감지: '{latest_barcode}'")

            # 줄 수 확인
            lines = [l for l in current_text.strip().split('\n') if l.strip()]
            line_count = len(lines)
            self.logger.info(f"[디버그] 유효한 줄 수: {line_count}, 텍스트 stripped 길이: {len(current_text.strip())}, 바코드 길이: {len(latest_barcode.strip())}")

            # 무한 루프 방지: 유효한 줄이 1줄이고 그게 최신 바코드면 스킵
            if line_count <= 1 and current_text.strip() == latest_barcode.strip():
                self.logger.info(f"[디버그] 이미 마지막 줄만 남아있습니다. 스킵합니다.")
                self.last_content = current_text
                self.last_barcode = latest_barcode
                return

            self.logger.info(f"[디버그] 여러 줄 감지됨. 마지막 줄만 남기기 시작...")

            # 메모장 내용을 최신 바코드만 남기고 삭제
            if self.set_notepad_text(hwnd, latest_barcode):
                self.logger.info(f"메모장 내용 업데이트 성공: '{latest_barcode}'만 남김")

                # 강제 저장
                time.sleep(0.1)
                if self.send_save_command(hwnd):
                    self.logger.info(f"메모장 저장 완료")

                # 별도 파일에도 저장
                self.save_barcode_to_file(latest_barcode)

                self.last_barcode = latest_barcode
                self.last_content = latest_barcode
            else:
                self.logger.error(f"텍스트 설정 실패! 무한 루프 방지를 위해 last_content 업데이트")
                self.last_content = current_text
                self.last_barcode = latest_barcode
        else:
            self.logger.warning(f"[디버그] 바코드를 추출할 수 없습니다.")


def main():
    """메인 함수"""

    # 시작 확인창
    root = tk.Tk()
    root.withdraw()

    start = messagebox.askyesno(
        "Notepad Auto-Save",
        "메모장 자동 저장 프로그램을 시작하시겠습니까?\n\n"
        "기능:\n"
        "- 메모장 자동 저장\n"
        "- 바코드 최신 것만 추출 (자동)\n\n"
        "방식: UI Automation (클립보드 사용 안 함)"
    )
    if not start:
        return

    # 프로그램 실행
    autosaver = NotepadAutoSave()

    # 종료 버튼이 있는 작은 창
    ui = tk.Tk()
    ui.title("Notepad Auto-Save (실행 중)")
    ui.resizable(False, False)

    label = tk.Label(
        ui,
        text="메모장 자동 저장이 실행 중입니다.\n"
             "바코드 기능도 활성화되었습니다.\n"
             "(UI Automation 방식)\n\n"
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

    # UI 이벤트 루프와 자동 저장 루프 통합
    def tick():
        if autosaver.stop_requested:
            return

        check_interval = autosaver.config['check_interval']

        notepad_windows = autosaver.ensure_notepad_running()
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
                autosaver.process_notepad_content(hwnd)

        # 다음 실행 예약
        ui.after(int(check_interval * 1000), tick)

    tick()
    ui.mainloop()


if __name__ == '__main__':
    main()
