# CAE Agent

[![Windows CI](https://github.com/minwoorich/cae-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/minwoorich/cae-agent/actions/workflows/ci.yml)

CAE Agent는 사용자가 자연어로 요청한 CAE 작업을 Codex가 이해하고, Ansys
Workbench·SpaceClaim·Mechanical에서 실행할 수 있는 스크립트로 작성·수정하는
Windows용 오픈소스 도구입니다.

일반 사용자는 Python 파일을 직접 고칠 필요가 없습니다. 로컬 웹 UI에서 모델
파일을 첨부하고 “이 STEP 파일을 해석에 적합하게 단순화해줘”처럼 요청하면
Codex가 작업 계획과 진행 상태를 보여주고 CAE 작업을 수행합니다. PowerShell
명령은 최초 설치, 서버 실행과 문제 진단에만 주로 사용합니다.

> 현재 버전은 공개 알파입니다. 우선 지원 환경은 **Windows + Ansys 2026
> R1(V261) + Codex CLI**입니다. 중요한 원본 모델은 별도로 백업하고, 자동화
> 결과를 검토한 뒤 설계 또는 해석 의사결정에 사용하세요.

## 할 수 있는 일

- Codex와 자연어로 대화하며 SpaceClaim·Mechanical 작업 계획 수립
- STEP, IGES, SpaceClaim, Workbench, Mechanical 모델과 이미지·데이터 첨부
- SpaceClaim 형상 생성, 가져오기, 검사 및 단순화 스크립트 작성·실행
- Mechanical 재료, 접촉, 메시, 경계조건, 결과 항목과 해석 스크립트 작성·실행
- Workbench 프로젝트와 세션 준비, 연결 상태 확인
- 실패 로그를 Codex에 전달해 제한된 횟수 안에서 스크립트 수정 및 재시도
- 생성 스크립트, 로그와 결과를 작업공간에 분리 보관
- 확인 모드와 YOLO 모드로 실행 승인 방식 선택

CAE Agent가 Ansys 자체를 대신하거나 라이선스를 제공하는 것은 아닙니다.
SpaceClaim 또는 Mechanical을 실제로 실행하려면 해당 제품과 유효한 Ansys
라이선스가 설치되어 있어야 합니다.

## 처음 사용하는 사람을 위한 전체 흐름

```text
필수 프로그램 설치
    → 저장소 내려받기
    → setup.ps1로 가상환경 준비
    → doctor로 설치 상태 확인
    → 로컬 UI 실행
    → 파일 첨부 및 자연어 요청
    → 계획·진행 상태 확인
    → Ansys 실행 결과 검토
```

### 1. 준비할 프로그램

| 프로그램 | 용도 | 없으면 어떻게 되나요? |
|---|---|---|
| Python 3.11 이상 | CAE Agent와 UI 실행 | 설치 스크립트가 중단됩니다. |
| Git | 저장소 다운로드와 업데이트 | Git으로 설치·업데이트할 수 없습니다. |
| Codex CLI | 자연어 요청 해석과 스크립트 작성 | UI의 AI 채팅 기능을 사용할 수 없습니다. |
| Ansys 2026 R1 | Workbench, SpaceClaim, Mechanical 실행 | 스크립트 작성은 가능하지만 실제 CAE 실행은 불가능합니다. |
| Ansys 라이선스 | 제품 실행 권한 | 제품 시작 또는 해석 단계에서 라이선스 오류가 발생합니다. |

Python, Codex CLI와 Ansys는 CAE Agent가 몰래 설치하거나 로그인하지 않습니다.
Codex CLI는 [OpenAI 공식 설치 안내](https://developers.openai.com/codex/cli)를
따라 설치하고, 터미널에서 `codex`를 한 번 실행해 로그인하세요.

### 2. 저장소 내려받기

PowerShell을 열고 원하는 위치에서 다음 명령을 실행합니다.

```powershell
git clone https://github.com/minwoorich/cae-agent.git
cd cae-agent
```

ZIP으로 내려받았다면 압축을 푼 뒤 PowerShell에서 해당 폴더로 이동해도 됩니다.

### 3. CAE Agent와 UI 설치

저장소 루트에서 다음 명령을 실행합니다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1 -WithAnsys -WithUI
```

설치 스크립트는 저장소 안에 `.venv` 가상환경을 만들고 필요한 Python 패키지를
설치합니다. 기존 가상환경과 `cae-agent.toml`은 덮어쓰지 않으며, 비밀번호나
API 토큰을 요구하지 않습니다.

설치 마지막에 `doctor`가 실행됩니다. `FAIL`이 표시되면 실패 항목의 안내를
먼저 해결하세요. Ansys가 없는 PC에서도 UI와 일부 진단 기능은 설치할 수 있지만
실제 모델링과 해석은 실행할 수 없습니다.

### 4. UI 실행

```powershell
.\.venv\Scripts\cae-agent.exe ui
```

브라우저가 자동으로 열리지 않으면 다음 주소를 직접 여세요.

<http://127.0.0.1:8765>

이 PowerShell 창이 UI 서버입니다. 창을 닫거나 `Ctrl+C`를 누르면 서버도
종료됩니다. 다시 시작하려면 같은 `cae-agent.exe ui` 명령을 실행하면 됩니다.
UI는 외부 인터넷에 공개되지 않고 현재 PC의 `127.0.0.1`에만 열립니다.

### 5. UI에서 첫 작업 수행

1. 상단 연결 메뉴에서 **Codex 연결 상태**와 **Workbench 연결 상태**를
   확인합니다.
2. 채팅 입력창의 `+` 버튼으로 STEP, SCDOC, WBPJ, MECHDAT 또는 참고 이미지를
   첨부합니다.
3. 사용 목적, 단위, 반드시 보존할 형상과 원하는 결과를 자연어로 입력합니다.
4. `Enter`로 전송합니다. 줄바꿈은 `Shift+Enter`를 사용합니다.
5. 응답의 작업 과정에서 스크립트 작성, 명령 실행과 오류 수정 상태를 확인합니다.
6. 작업 완료 후 `workspace/results`와 채팅의 결과 안내를 검토합니다.

예를 들어 다음처럼 요청할 수 있습니다.

> 첨부한 `package.step`을 열고 해석에 불필요한 작은 필렛과 구멍을 찾아줘.
> 원본은 수정하지 말고, 제거할 항목을 먼저 설명한 다음 단순화한 사본을 만들어줘.

> 현재 Workbench 시스템의 Mechanical에 실리콘과 구리 재료를 지정하고,
> 발열량 15 W와 바닥면 25 °C 조건으로 정상상태 열해석을 준비해줘. 해석을
> 실행하기 전 적용할 조건을 요약해줘.

좋은 요청에는 다음 정보가 포함됩니다.

- 작업 대상 파일 또는 Workbench 시스템
- 모델의 실제 용도와 목표
- mm, W, °C 같은 단위
- 변경해도 되는 부분과 반드시 보존할 부분
- 원하는 출력 파일 및 확인할 결과

### 6. 승인 모드 선택

- **확인 모드**: 모델 변경, 해석 실행, 덮어쓰기와 삭제처럼 영향이 큰 작업을
  사용자에게 확인합니다. 처음 사용하거나 중요한 모델을 다룰 때 권장합니다.
- **YOLO 모드**: 현재 브라우저 세션에서 실행 승인을 자동 처리합니다. 반복
  시험에는 편하지만 Ansys 실행과 파일 변경이 연속으로 진행될 수 있습니다.

YOLO 모드에서도 제품 소스, 업로드 원본, 로그와 기존 결과처럼 보호된 경로는
직접 수정할 수 없습니다. 브라우저를 새로고침하거나 다시 접속하면 확인 모드로
돌아갑니다.

## 파일은 어디에 저장되나요?

모든 사용자 작업 파일은 기본적으로 저장소의 `workspace` 아래에 분리됩니다.

| 폴더 | 내용 | 자동 정리 여부 |
|---|---|---|
| `workspace/input` | UI로 올린 원본 모델·이미지·데이터 | 자동 삭제하지 않음 |
| `workspace/generated` | Codex가 작성한 SpaceClaim·Mechanical 스크립트와 작업 사본 | 오래된 파일 정리 가능 |
| `workspace/results` | Workbench 프로젝트, 해석 결과와 최종 산출물 | 자동 삭제하지 않음 |
| `workspace/logs` | 실행 기록, 오류와 승인 감사 로그 | 오래된 파일 정리 가능 |
| `workspace/.runtime` | 현재 세션 연결 정보와 임시 상태 | 종료된 오래된 항목만 정리 가능 |

같은 이름의 입력 파일을 다시 올리면 즉시 덮어쓰지 않고 교체 확인 창을
표시합니다. `workspace/input`의 원본을 직접 편집하지 않고, 변경 작업은
`workspace/generated`의 사본에서 수행하는 것이 기본 원칙입니다.

## Codex 연결과 Workbench 연결의 차이

- **Codex 연결**은 자연어 요청을 읽고 스크립트를 작성할 AI 세션이 준비됐다는
  의미입니다.
- **Workbench 연결**은 실행 중인 로컬 Ansys Workbench 세션에 실제로 ping이
  성공했다는 의미입니다.

Codex만 연결된 경우 계획과 스크립트 작성은 가능하지만 Workbench 작업은 실행할
수 없습니다. Workbench만 연결되고 Codex가 없으면 이미 작성된 CLI 스크립트는
실행할 수 있지만 자연어 채팅은 사용할 수 없습니다.

왼쪽 메뉴로 이동했다가 채팅으로 돌아오는 것은 같은 페이지 안의 이동이므로
대화와 응답 생성이 유지됩니다. 브라우저 새로고침, 탭 닫기 또는 UI 서버
재시작은 현재 메모리 기반 채팅 세션을 종료합니다.

## 문제가 생겼을 때

먼저 다음 진단을 실행하세요.

```powershell
.\.venv\Scripts\cae-agent.exe doctor
.\.venv\Scripts\cae-agent.exe workbench status
```

- UI 주소가 열리지 않으면 UI 서버 PowerShell 창이 실행 중인지 확인합니다.
- Codex가 미연결이면 `codex` 설치와 로그인 상태를 확인합니다.
- Workbench가 미연결이면 Workbench가 실행 중인지 확인하고 세션을 다시
  시작합니다.
- Ansys 라이선스 오류가 발생하면 모든 Ansys 프로그램을 정상 종료한 뒤
  라이선스 서버 설정과 사용 가능한 라이선스를 확인합니다.
- 오류가 반복되면 `workspace/logs`의 최신 로그를 보존합니다.

자세한 증상별 해결 방법은 [문제 해결 가이드](docs/troubleshooting.ko.md)를
참고하세요.

## 상세 문서

- [일반 사용자 시작 가이드](docs/getting-started.ko.md)
- [UI 전체 사용 설명서](docs/ui.ko.md)
- [Codex를 자연어 인터페이스로 사용하는 방법](docs/codex-first.ko.md)
- [프로젝트 폴더와 코드 구조](docs/project-structure.ko.md)
- [파일 역할과 수정·보호 정책](docs/file-policy.ko.md)
- [문제 해결 가이드](docs/troubleshooting.ko.md)
- [UI 정보 구조와 디자인 시스템](docs/ui-design.ko.md)
- [전력반도체 열해석 예제](examples/power-semiconductor-thermal/README.md)
- [변경 이력](CHANGELOG.md)
- [v0.1.0 릴리스 노트](docs/releases/v0.1.0.ko.md)

## 고급 사용자용 CLI

UI 없이 환경 상태를 확인하거나 기존 스크립트를 직접 실행할 수도 있습니다.

```powershell
# 환경 진단
.\.venv\Scripts\cae-agent.exe doctor

# Workbench 세션 시작 및 상태 확인
.\.venv\Scripts\cae-agent.exe workbench start
.\.venv\Scripts\cae-agent.exe workbench status

# 기존 Workbench 시스템에서 SpaceClaim 스크립트 실행
.\.venv\Scripts\cae-agent.exe spaceclaim run .\geometry.py --system-name SYS

# Mechanical 연결 및 스크립트 실행
.\.venv\Scripts\cae-agent.exe mechanical --system-name SYS connect
.\.venv\Scripts\cae-agent.exe mechanical --system-name SYS run-script .\setup.py

# 작업공간 용량과 정리 후보 확인
.\.venv\Scripts\cae-agent.exe workspace status
.\.venv\Scripts\cae-agent.exe workspace clean --older-than 30
```

`--clear`, `--overwrite`, `workspace clean --approve`는 기존 모델 또는 파일에
영향을 줄 수 있으므로 의미를 확인한 뒤 사용하세요. 전체 명령과 실행 순서는
[일반 사용자 시작 가이드](docs/getting-started.ko.md)에 설명되어 있습니다.

## 개발 참여

개발 도구까지 설치하려면 다음을 실행합니다.

```powershell
.\setup.ps1 -WithAnsys -WithUI -WithDev
.\.venv\Scripts\python.exe -m pytest
```

코드 식별자와 공개 CLI 옵션은 Python 관례에 따라 영어를 사용합니다. 주석과
docstring은 구현 의도, Ansys 제약과 오류 처리 배경을 알 수 있도록 자세한
한국어로 작성합니다. 기능을 수정하기 전
[프로젝트 구조 문서](docs/project-structure.ko.md)와
[파일 수정 정책](docs/file-policy.ko.md)을 먼저 확인하세요.

## 프로젝트 상태와 라이선스

현재 버전 `0.1.0`은 첫 공개 알파 단계입니다. 특정 모델에 대한 해석 정확도,
Ansys 버전 간 스크립트 호환성과 자동 단순화 결과는 사용자가 검증해야 합니다.

이 프로젝트는 [MIT 라이선스](LICENSE)로 배포됩니다.
