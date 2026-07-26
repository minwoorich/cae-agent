# CAE Agent 코드 구조

CAE Agent의 구현 코드는 역할이 다른 기능이 한 폴더에 섞이지 않도록 관심사별
패키지로 나눕니다. 새 기능을 추가할 때는 아래 책임과 가장 가까운 폴더를
선택합니다.

```text
src/cae_agent/
├── core/               # 설정, 환경 진단, 작업공간처럼 모든 기능이 공유하는 기반 코드
├── ansys/              # Workbench, SpaceClaim, Mechanical 실행 및 프로젝트 제어
├── agent/              # 자연어 대화, 첨부 처리, Codex 연동과 자동 복구
│   └── providers/      # Codex 등 AI 실행 제공자별 구현
├── security/           # 명령 승인과 파일 쓰기 범위 제한
├── ui/                 # 대시보드, 채팅, 파일 화면과 공통 스타일
├── cli.py              # 명령행 인터페이스와 각 기능의 진입점
├── __main__.py         # `python -m cae_agent` 실행 진입점
└── __init__.py         # 패키지 버전처럼 최상위에 필요한 최소 공개 정보
```

## 폴더별 책임

- `core`는 특정 UI나 Ansys 제품에 의존하지 않는 공통 기반 기능만 포함합니다.
- `ansys`는 CAE 제품을 찾고 실행하거나 프로젝트와 해석 모델을 다루는 코드를
  포함합니다.
- `agent`는 사용자 요청을 해석하고 AI 제공자를 호출하며, 생성된 작업을
  실행·복구하는 흐름을 담당합니다.
- `security`는 자동 실행이 허용되는 범위와 보호해야 할 소스 파일을 판정합니다.
- `ui`는 화면 표시와 사용자 상호작용만 담당하고, 실제 CAE 처리는 다른
  패키지의 공개 함수를 호출합니다.

## 의존 방향

순환 참조를 피하기 위해 일반적으로 다음 방향으로만 의존합니다.

```text
CLI / UI
   ├── agent ──> ansys
   ├── ansys ──> core
   └── security
```

하위 기반 패키지인 `core`는 `ui`나 `agent`를 import하지 않습니다. 화면에서만
필요한 코드는 `ui`에 두고, UI 없이도 재사용할 CAE 로직은 `ansys` 또는
`agent`에 둡니다.

## 공개 import 경로

외부 코드와 테스트는 파일의 새 위치를 명시하는 경로를 사용합니다.

```python
from cae_agent.core.config import load_config
from cae_agent.ansys.mechanical import run_mechanical
from cae_agent.agent.providers import CodexProvider
from cae_agent.ui import launch_ui
```

`cae_agent.ui`처럼 패키지의 `__init__.py`가 명시적으로 다시 공개하는 API는
짧은 경로를 사용할 수 있습니다. 내부 구현 파일을 옮길 때는 이 공개 API를
최소한으로 유지해 패키지 경계를 분명하게 관리합니다.
