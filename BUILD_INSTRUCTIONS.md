# 독립 실행 파일(.exe) 빌드 가이드

Python이 설치되지 않은 Windows PC에서도 실행 가능한 `.exe` 파일을 만드는 방법입니다.

## 📋 사전 요구사항

**Windows PC가 필요합니다** (가상머신도 가능)
- Python 3.7 이상 설치
- 인터넷 연결 (라이브러리 다운로드용)

## 🚀 빌드 방법

### 방법 1: 자동 빌드 (추천) ⭐

Windows에서 배치 파일을 더블클릭하면 자동으로 빌드됩니다:

#### 옵션 A: 백그라운드 실행 버전
```
build_exe.bat 더블클릭
```
- 콘솔 창이 표시되지 않음
- 백그라운드에서 조용히 실행
- 일반 사용자용

#### 옵션 B: 콘솔 표시 버전
```
build_exe_console.bat 더블클릭
```
- 콘솔 창이 표시됨
- 로그를 실시간으로 확인 가능
- 개발자/디버깅용

### 방법 2: 수동 빌드

Windows 명령 프롬프트(cmd)에서:

```cmd
# 1. 필수 패키지 설치
pip install -r requirements.txt

# 2. 빌드 실행 (백그라운드 버전)
pyinstaller --onefile --noconsole --name "NotepadAutoSave" --add-data "config.json;." notepad_autosave.py

# 또는 콘솔 버전
pyinstaller --onefile --console --name "NotepadAutoSave_Console" --add-data "config.json;." notepad_autosave.py

# 3. 설정 파일 복사
copy config.json dist\config.json
```

## 📦 빌드 결과물

빌드가 완료되면 `dist` 폴더에 다음 파일이 생성됩니다:

```
dist/
├── NotepadAutoSave.exe         (또는 NotepadAutoSave_Console.exe)
├── config.json
└── autosave.log                (실행 후 생성됨)
```

## 💾 배포 방법

### Python이 없는 PC에서 실행하기

1. **`dist` 폴더 전체를 복사**
   - USB, 이메일, 클라우드 등으로 전송

2. **Windows PC에서 실행**
   ```
   NotepadAutoSave.exe 더블클릭
   ```
   
3. **끝!** Python 설치 없이 바로 실행됩니다 ✅

### 주의사항

> [!IMPORTANT]
> - `config.json` 파일도 함께 복사해야 합니다
> - `.exe` 파일만 단독으로는 기본 설정으로 실행됩니다
> - 설정을 변경하려면 `config.json`을 같은 폴더에 두세요

## 🔧 빌드 옵션 설명

| 옵션 | 설명 |
|------|------|
| `--onefile` | 단일 .exe 파일로 패키징 |
| `--noconsole` | 콘솔 창 숨김 (백그라운드 실행) |
| `--console` | 콘솔 창 표시 (로그 확인용) |
| `--name` | 생성될 .exe 파일 이름 |
| `--add-data` | 추가 파일 포함 (config.json) |

## 📊 파일 크기

- **예상 크기**: 약 10-15 MB
- Python 인터프리터와 모든 라이브러리가 포함되어 있기 때문에 크기가 큽니다

## ❓ 문제 해결

### "Python is not installed" 오류
```bash
# Python 설치 확인
python --version

# PATH에 추가되지 않은 경우, Python 재설치 시 "Add Python to PATH" 체크
```

### "PyInstaller not found" 오류
```bash
pip install pyinstaller
```

### 빌드는 성공했지만 실행 안 됨
- `build_exe_console.bat`으로 콘솔 버전을 빌드하여 에러 메시지 확인
- `autosave.log` 파일 확인

### Windows Defender 경고
- PyInstaller로 만든 .exe는 서명이 없어 경고가 뜰 수 있습니다
- "추가 정보" → "실행" 클릭하여 실행 가능
- 안전한 프로그램이지만, 보안 소프트웨어가 의심하는 것입니다

## 🎯 macOS에서 Windows용 .exe 빌드하기

macOS에서는 직접 .exe를 만들 수 없습니다. 다음 방법을 사용하세요:

### 1. Windows 가상머신 사용
- UTM, Parallels, VirtualBox 등
- 가상머신에서 Windows 실행 후 빌드

### 2. GitHub Actions 사용 (고급)
- GitHub에 코드 업로드
- GitHub Actions에서 Windows 환경 자동 빌드
- 필요하시면 설정 파일을 만들어드릴 수 있습니다

## ✅ 빌드 완료 체크리스트

- [ ] Python 설치 확인
- [ ] `pip install -r requirements.txt` 실행
- [ ] `build_exe.bat` 또는 `build_exe_console.bat` 실행
- [ ] `dist` 폴더에 `.exe` 파일 생성 확인
- [ ] `config.json` 파일이 `dist` 폴더에 있는지 확인
- [ ] `.exe` 파일 테스트 (메모장 열고 자동 저장 확인)

---

**빌드하시다가 문제가 있으면 언제든 질문해주세요!** 🙂
