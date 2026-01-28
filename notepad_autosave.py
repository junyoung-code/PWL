#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notepad Auto-Save Program
메모장의 변화를 감지하여 자동으로 저장하는 프로그램

이 프로그램은 Windows 메모장 창을 모니터링하고,
저장되지 않은 변경사항이 있을 때 자동으로 Ctrl+S를 전송하여 저장합니다.
"""

import win32gui
import win32con
import win32api
import time
import json
import logging
from datetime import datetime
import os
import sys


class NotepadAutoSave:
    """메모장 자동 저장 클래스"""
    
    def __init__(self, config_file='config.json'):
        """
        초기화
        
        Args:
            config_file: 설정 파일 경로
        """
        self.config = self.load_config(config_file)
        self.setup_logging()
        self.logger.info("=" * 50)
        self.logger.info("Notepad Auto-Save Program Started")
        self.logger.info("=" * 50)
        
    def load_config(self, config_file):
        """
        설정 파일 로드
        
        Args:
            config_file: 설정 파일 경로
            
        Returns:
            dict: 설정 사전
        """
        default_config = {
            'check_interval': 5,
            'enable_logging': True,
            'log_file': 'autosave.log'
        }
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 기본값과 병합
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
        """
        열려있는 모든 메모장 창 찾기
        
        Returns:
            list: 메모장 창 핸들 리스트
        """
        notepad_windows = []
        
        def enum_callback(hwnd, results):
            """윈도우 열거 콜백"""
            if win32gui.IsWindowVisible(hwnd):
                class_name = win32gui.GetClassName(hwnd)
                # 메모장의 클래스 이름은 'Notepad'
                if class_name == 'Notepad':
                    results.append(hwnd)
            return True
        
        win32gui.EnumWindows(enum_callback, notepad_windows)
        return notepad_windows
    
    def get_window_title(self, hwnd):
        """
        윈도우 타이틀 가져오기
        
        Args:
            hwnd: 윈도우 핸들
            
        Returns:
            str: 윈도우 타이틀
        """
        try:
            return win32gui.GetWindowText(hwnd)
        except Exception:
            return ""
    
    def has_unsaved_changes(self, hwnd):
        """
        저장되지 않은 변경사항이 있는지 확인
        메모장은 변경사항이 있을 때 타이틀에 '*'를 표시함
        
        Args:
            hwnd: 윈도우 핸들
            
        Returns:
            bool: 저장되지 않은 변경사항 여부
        """
        title = self.get_window_title(hwnd)
        # 타이틀이 '*'로 시작하면 저장되지 않은 변경사항이 있음
        return title.startswith('*')
    
    def send_save_command(self, hwnd):
        """
        Ctrl+S 키 조합을 창에 전송하여 저장
        
        Args:
            hwnd: 윈도우 핸들
        """
        try:
            # 윈도우를 포그라운드로 가져오기 (선택사항, 백그라운드에서도 작동 가능)
            # win32gui.SetForegroundWindow(hwnd)
            # time.sleep(0.1)
            
            # Ctrl+S 전송 (WM_KEYDOWN과 WM_KEYUP 사용)
            # VK_CONTROL = 0x11, VK_S = 0x53
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
    
    def monitor_loop(self):
        """메인 모니터링 루프"""
        check_interval = self.config['check_interval']
        self.logger.info(f"모니터링 시작 (체크 주기: {check_interval}초)")
        
        try:
            while True:
                # 메모장 창 찾기
                notepad_windows = self.find_notepad_windows()
                
                if notepad_windows:
                    self.logger.debug(f"발견된 메모장 창: {len(notepad_windows)}개")
                    
                    for hwnd in notepad_windows:
                        title = self.get_window_title(hwnd)
                        
                        # 저장되지 않은 변경사항 확인
                        if self.has_unsaved_changes(hwnd):
                            self.logger.info(f"변경사항 감지: '{title}'")
                            
                            # 자동 저장 실행
                            if self.send_save_command(hwnd):
                                self.logger.info(f"자동 저장 완료: '{title}'")
                            else:
                                self.logger.warning(f"자동 저장 실패: '{title}'")
                
                # 대기
                time.sleep(check_interval)
                
        except KeyboardInterrupt:
            self.logger.info("\n프로그램 종료 (Ctrl+C)")
        except Exception as e:
            self.logger.error(f"모니터링 오류: {e}", exc_info=True)


def main():
    """메인 함수"""
    print("=" * 50)
    print("Windows 메모장 자동 저장 프로그램")
    print("=" * 50)
    print("이 프로그램은 메모장의 변경사항을 감지하여")
    print("자동으로 파일을 저장합니다.")
    print("종료하려면 Ctrl+C를 누르세요.")
    print("=" * 50)
    print()
    
    # 프로그램 실행
    autosaver = NotepadAutoSave()
    autosaver.monitor_loop()


if __name__ == '__main__':
    main()
