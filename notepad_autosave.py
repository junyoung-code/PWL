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
        return win32gui.FindWindowEx(hwnd, 0, "Edit", None)

    def get_notepad_text(self, edit_hwnd):
        """메모장 텍스트 읽기"""
        try:
            length = win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)
            if length == 0:
                return ""

            import ctypes
            buffer = ctypes.create_unicode_buffer(length + 1)
            win32gui.SendMessage(edit_hwnd, win32con.WM_GETTEXT, length + 1, buffer)
            return buffer.value
        except Exception as e:
            return ""

    def set_notepad_text(self, hwnd, edit_hwnd, text):
        """메모장 텍스트 설정 (Edit 컨트롤 직접 제어 - 가장 안정적)"""
        try:
            # EM_SETSEL: 전체 텍스트 선택 (0, -1)
            EM_SETSEL = 0x00B1
            EM_REPLACESEL = 0x00C2

            # 1. 전체 텍스트 선택
            win32gui.SendMessage(edit_hwnd, EM_SETSEL, 0, -1)

            # 2. 선택된 텍스트를 새 텍스트로 교체
            win32gui.SendMessage(edit_hwnd, EM_REPLACESEL, True, text)

            return True
        except Exception as e:
            self.logger.error(f"텍스트 설정 오류: {e}")
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
        """Ctrl+S 키 조합을 창에 전송하여 저장"""
        try:
            VK_CONTROL = win32con.VK_CONTROL
            VK_S = ord('S')

            # Ctrl 키 누름
            win32api.keybd_event(VK_CONTROL, 0, 0, 0)
            time.sleep(0.05)

            # S 키 누름
            win32api.keybd_event(VK_S, 0, 0, 0)
            time.sleep(0.05)

            # S 키 뗌
            win32api.keybd_event(VK_S, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.05)

            # Ctrl 키 뗌
            win32api.keybd_event(VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)

            return True
        except Exception as e:
            self.logger.error(f"저장 명령 전송 오류: {e}")
            return False

    def process_notepad_content(self, hwnd, edit_hwnd):
        """메모장 내용 처리 (바코드 추출 및 메모장 업데이트)"""
        if not self.config.get('enable_barcode_feature', True):
            return

        current_text = self.get_notepad_text(edit_hwnd)

        # 메모장 내용이 변경되었고, 비어있지 않으면 처리
        if current_text != self.last_content and current_text.strip():
            # 최신 바코드 추출
            latest_barcode = self.extract_latest_barcode(current_text)

            # 바코드가 추출되면 항상 처리 (같은 내용이어도!)
            if latest_barcode:
                self.logger.info(f"바코드 감지: {latest_barcode}")

                # 1. 메모장 내용을 최신 바코드만 남기고 삭제 (클립보드 방식)
                if self.set_notepad_text(hwnd, edit_hwnd, latest_barcode):
                    self.logger.info(f"메모장 내용 업데이트: {latest_barcode}만 남김")

                    # 강제 저장 (내용 변경 후)
                    time.sleep(0.1)
                    if self.send_save_command(hwnd):
                        self.logger.info(f"메모장 저장 완료")

                # 2. 별도 파일에도 저장 (같은 내용이어도 타임스탬프 업데이트)
                self.save_barcode_to_file(latest_barcode)

                self.last_barcode = latest_barcode
                self.last_content = latest_barcode  # 업데이트된 내용으로 변경

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
