# CAE Agent 프로젝트 구조

이 문서는 저장소를 내려받은 일반 사용자에게 파일이 어디에 저장되는지
설명하고, 개발자에게는 기능별 소스 코드의 책임과 수정 경계를 안내합니다.

일반 사용자는 대부분 `workspace`와 `cae-agent.toml`만 확인하면 됩니다.
`src`, `.agents`, `tests`와 `.github`는 프로그램을 개발하거나 배포할 때 사용하는
파일이므로 UI 작업을 위해 직접 수정할 필요가 없습니다.

## 저장소 전체 구조

```text
cae-agent/
├── .agents/
│   └── skills/cae-agent/       # Codex가 CAE 작업 규칙을 이해하는 저장소 Skill
├── .github/
│   └── workflows/              # GitHub Actions 자동 테스트 설정
├── docs/                       # 설치, UI, 구조와 문제 해결 문서
├── examples/                   # 재현 가능한 CAE 사용 예제
├── src/
│   └── cae_agent/              # 실제 CAE Agent Python 패키지
├── tests/                      # 기능 및 안전 정책 자동 테스트
├── workspace/                  # 사용자 입력, 생성물, 결과와 실행 기록
├── AGENTS.md                   # 저장소에서 Codex가 따라야 할 작업 규칙
├── cae-agent.example.toml      # 배포용 설정 예시
├── cae-agent.toml              # 설치 후 만드는 사용자 로컬 설정
├── pyproject.toml              # Python 패키지와 선택 의존성 정의
├── setup.ps1                   # Windows 설치 및 가상환경 준비 스크립트
├── README.md                   # 프로젝트 첫 화면과 일반 사용 안내
├── CHANGELOG.md                # 버전별 변경 이력
└── LICENSE                     # MIT 라이선스
```

설치 후 생성되는 `.venv`, `cae-agent.toml`과 실행 중 만들어지는 일부 파일은
Git에 올리지 않는 로컬 전용 항목입니다.

## 일반 사용자가 주로 다루는 파일

### `cae-agent.toml`

Ansys 버전, Workbench 연결 포트, Codex 제공자와 작업공간 위치를 설정합니다.
기본 설정은 `cae-agent.example.toml`에서 복사됩니다.

비밀번호, GitHub 토큰, OpenAI API 키 또는 Ansys 라이선스 정보는 이 파일에
저장하지 않습니다. Codex는 로컬 Codex CLI의 기존 로그인 상태를 사용합니다.

### `workspace/input`

UI에서 첨부한 원본 모델, 이미지와 데이터가 저장됩니다. 원본 보존 영역이므로
Codex와 자동 정리 기능이 직접 수정하거나 삭제하지 않습니다.

같은 파일명을 다시 업로드하면 사용자 확인 후에만 교체됩니다. 원본 모델을
변경해야 하는 작업은 먼저 `generated`에 사본을 만든 다음 그 사본에서
수행합니다.

### `workspace/generated`

Codex가 작성한 SpaceClaim·Mechanical Python 스크립트, JSON 메타데이터와
변경 작업용 모델 사본이 저장됩니다. AI가 쓰기 작업을 수행할 수 있는 기본
영역입니다.

작업을 반복하면 파일이 누적될 수 있습니다. 필요 없는 오래된 생성물은
`workspace clean` 미리보기로 대상을 확인한 뒤 정리할 수 있습니다.

### `workspace/results`

사용자가 보존해야 하는 Workbench 프로젝트, 해석 결과와 최종 산출물을
저장합니다. 자동 정리 대상이 아니며 AI가 기존 결과를 임의로 덮어쓰지 않습니다.

### `workspace/logs`

명령 실행 기록, 오류, Codex 승인과 업로드 교체 감사 로그가 저장됩니다.
작업이 실패했을 때 가장 먼저 확인할 폴더입니다. 오래된 로그는 정리 대상으로
선택할 수 있지만 오류를 문의하기 전에는 관련 로그를 보존하는 것이 좋습니다.

### `workspace/.runtime`

Workbench·Mechanical 연결 정보와 Codex 임시 실행 상태가 저장됩니다. 모델이나
해석 결과가 아니라 현재 세션을 찾기 위한 메타데이터입니다.

프로그램이 실행 중일 때 이 폴더를 직접 삭제하면 연결 상태가 어긋날 수 있습니다.
Workbench와 UI를 정상 종료한 뒤 정리 명령을 사용하세요.

## Python 패키지 구조

```text
src/cae_agent/
├── core/
│   ├── config.py               # TOML 설정 읽기와 값 검증
│   ├── doctor.py               # Python, Codex, Ansys 환경 진단
│   └── workspace.py            # 작업공간 생성, 상태와 안전한 정리
├── ansys/
│   ├── workbench.py            # Workbench 프로세스와 브리지 세션 제어
│   ├── project.py              # Workbench 프로젝트 생성 및 보호
│   ├── spaceclaim.py           # SpaceClaim 스크립트 준비와 실행
│   └── mechanical.py           # Mechanical 연결, 상태와 스크립트 실행
├── agent/
│   ├── attachments.py          # 채팅 첨부 분류와 검증
│   ├── chat.py                 # 대화 상태와 CAE 요청 처리
│   ├── codex_app_server.py     # Codex App Server JSONL 통신
│   ├── repair.py               # 실패 정보 기반 스크립트 수정·재시도
│   └── providers/              # Codex 등 AI 제공자별 어댑터
├── security/
│   ├── approval.py             # 실행·삭제 승인 범위와 감사 기록
│   └── write_policy.py         # AI가 수정할 수 있는 경로 제한
├── ui/
│   ├── dashboard.py            # 페이지 구성과 UI 서버 진입점
│   ├── chat.py                 # 스트리밍 채팅과 진행 상태
│   ├── files.py                # 업로드, 교체와 파일 요약
│   ├── session_menu.py         # 연결 상태와 승인 모드 메뉴
│   └── styles.py               # 레이아웃, 색상과 반응형 스타일
├── cli.py                      # `cae-agent` 명령행 진입점
├── __main__.py                 # `python -m cae_agent` 진입점
└── __init__.py                 # 패키지 버전과 최소 공개 정보
```

## 관심사별 책임과 의존 방향

```text
사용자
  ├── UI ─────┐
  └── CLI ────┴──> agent ──> ansys ──> core
                       └────> security
```

- `core`는 특정 화면이나 AI 제공자에 의존하지 않는 공통 기반입니다.
- `ansys`는 Workbench, SpaceClaim과 Mechanical의 외부 프로세스·세션을
  제어합니다.
- `agent`는 자연어 요청, 첨부, Codex 통신과 오류 복구 흐름을 담당합니다.
- `security`는 승인 여부와 파일 쓰기 가능 영역을 판단합니다.
- `ui`는 정보를 표시하고 사용자 입력을 받으며, 실제 CAE 로직은 다른
  패키지의 공개 함수를 호출합니다.
- `cli.py`는 명령을 해석해 각 패키지로 전달하는 얇은 진입점입니다.

하위 기반 계층인 `core`가 `ui`를 불러오는 식의 역방향 의존은 만들지 않습니다.
UI 없이 재사용해야 하는 기능은 `ui`가 아니라 `core`, `ansys` 또는 `agent`에
둡니다.

## 수정해도 되는 영역과 보호 영역

| 영역 | 일반 사용자 직접 수정 | Codex UI 쓰기 | 설명 |
|---|---:|---:|---|
| `workspace/input` | 원칙적으로 하지 않음 | 차단 | 업로드 원본 보존 |
| `workspace/generated` | 가능 | 허용 | 생성 스크립트와 작업 사본 |
| `workspace/results` | 결과 관리만 권장 | 기존 파일 변경 차단 | 최종 산출물 보존 |
| `workspace/logs` | 열람 가능 | 기존 로그 변경 차단 | 오류 및 감사 기록 |
| `workspace/.runtime` | 수정 금지 | 차단 | 실행 중 세션 상태 |
| `src`, `tests`, `.agents` | 개발자만 수정 | 배포 UI에서 차단 | 제품 코드와 정책 |
| `docs`, `README.md` | 개발·문서 기여 시 가능 | 배포 UI에서 차단 | 사용자 문서 |

UI에서 Codex는 작업공간을 기준으로 실행되며 일반적인 파일 쓰기는
`workspace/generated` 내부로 제한됩니다. YOLO 모드를 켜도 이 경로 경계는
해제되지 않습니다. 자세한 판정 규칙은 [파일 수정 정책](file-policy.ko.md)을
참고하세요.

## 개발자가 새 기능을 추가할 때

1. 기능의 책임과 가장 가까운 패키지를 선택합니다.
2. UI 이벤트 안에 Ansys 제어 코드를 직접 작성하지 않고 공개 함수로
   분리합니다.
3. 원본 입력, 기존 결과와 작업공간 밖 경로가 보호되는지 테스트합니다.
4. 외부 프로세스 실패와 라이선스 오류가 사용자에게 한국어로 설명되는지
   확인합니다.
5. 구현 의도와 Ansys 버전 제약을 자세한 한국어 주석 및 docstring으로
   기록합니다.
6. `tests`에 정상 흐름과 실패·보호 경계 테스트를 추가합니다.

공개 import는 다음처럼 역할이 드러나는 경로를 사용합니다.

```python
from cae_agent.core.config import load_config
from cae_agent.ansys.mechanical import run_mechanical
from cae_agent.agent.providers import CodexProvider
from cae_agent.ui import launch_ui
```

기존의 간단한 코드 계층 설명은
[아키텍처 문서](architecture.ko.md)에서도 확인할 수 있습니다.
