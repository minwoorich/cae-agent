# CAE Agent 로컬 대시보드

CAE Agent UI는 Codex 자연어 인터페이스를 대체하지 않습니다. Codex가 CAE
작업을 조정하는 동안 환경, 세션, 작업공간, 정리 후보와 결과 파일을 한 화면에서
확인하는 localhost 전용 상태·승인 대시보드입니다.

화면의 정보 구조, 색상, 상태 표현과 후속 기능 확장 규칙은
[UI 디자인 시스템](ui-design.ko.md)에 정리되어 있습니다.

## 설치

```powershell
.\setup.ps1 -WithAnsys -WithUI
```

개발 의존성까지 함께 설치하려면 다음을 사용합니다.

```powershell
.\setup.ps1 -WithAnsys -WithUI -WithDev
```

수동 설치도 가능합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ui]"
```

NiceGUI는 선택 의존성이므로 `.[ui]`를 설치하지 않아도 doctor, Workbench,
SpaceClaim, Mechanical과 Codex-first CLI는 계속 사용할 수 있습니다.

## 실행

```powershell
.\.venv\Scripts\cae-agent.exe ui
```

기본 브라우저가 열리지 않게 하거나 포트를 변경할 수 있습니다.

```powershell
.\.venv\Scripts\cae-agent.exe ui --no-browser --port 8876
```

UI는 항상 `127.0.0.1`에만 바인딩됩니다. 현재 버전은 외부 네트워크 주소를
지정하는 옵션을 제공하지 않습니다.

## 표시 내용

- 왼쪽 내비게이션으로 분리된 개요, 입력 파일, 로그·결과와 유지관리
- 실제 연결 전 사용자 흐름을 검증하는 모의 스트리밍 대화
- localhost 전용 실행과 UI 버전을 보여주는 상단 상태 바
- Python, Git, Codex와 Ansys 환경 진단
- Workbench와 Mechanical 세션 메타데이터 존재 여부
- `input`, `generated`, `logs`, `results`, `.runtime`의 파일 수와 용량
- 최근 로그 및 결과 파일 이름
- 검증된 CAE 입력 파일 업로드
- 지정 보존 기간보다 오래된 안전한 정리 후보
- 실제 정리 결과, 실패 수와 감사 로그 경로

개요 화면의 `입력 파일 업로드` 버튼을 누르면 입력 파일 화면으로 이동합니다.
`대화` 화면은 아직 실제 Codex 연결 전이며 `MOCK MODE`로 표시됩니다.

세션 메타데이터는 연결 가능성을 나타내는 로컬 기록입니다. 실제 Workbench 또는
Mechanical 응답을 보장하지 않으므로 CAE 작업을 시작할 때는 Codex가 기존
`status` 명령으로 연결을 다시 확인해야 합니다.

## 모의 스트리밍 대화

대화 화면은 실제 Codex App Server를 연결하기 전에 다음 사용자 흐름을
검증합니다.

- 사용자, CAE Agent, 시스템과 오류 메시지의 구분
- 현재 UI 세션에서 선택한 입력 파일 첨부 칩
- 응답 텍스트가 여러 조각으로 도착하는 스트리밍 표시
- 응답 중 중복 전송 차단
- 진행 중인 응답 중지
- 마지막 사용자 요청과 첨부 파일로 다시 시도
- 명령, 스크립트와 로그를 위한 접이식 상세 카드

현재 응답에는 `CAE Agent · 모의 응답`과 `MOCK MODE`가 명확하게 표시됩니다.
이 화면에서 메시지를 전송해도 Codex CLI, Workbench, SpaceClaim 또는
Mechanical을 실행하지 않습니다. 모의 응답의 상세 카드에서도 외부 명령 실행,
Ansys 명령 실행과 모델 변경이 없음을 확인할 수 있습니다.

선택한 파일을 실제 Codex 요청으로 전달하고 응답 이벤트를 받는 기능은 #44
Codex App Server 대화 어댑터에서 연결합니다. 따라서 현재 모의 대화에서
표시되는 답변을 실제 CAE 검토 결과로 사용하면 안 됩니다.

## 입력 파일 업로드

`CAE 입력 파일 선택 또는 드래그앤드롭` 영역에 파일을 끌어놓거나 선택하면
서버가 파일명, 확장자와 크기를 다시 검증한 뒤 `workspace/input`에 저장합니다.
한 번에 최대 10개, 전체 500 MiB까지 선택할 수 있고 개별 파일은 100 MiB를
넘을 수 없습니다. 브라우저의 파일 선택 제한은 안전 경계로 간주하지 않으며,
서버 검증을 통과하지 못한 파일은 저장하지 않습니다.

지원하는 형식은 다음과 같습니다.

- STEP: `.step`, `.stp`
- IGES: `.iges`, `.igs`
- SpaceClaim: `.scdoc`
- Workbench와 Mechanical: `.wbpj`, `.mechdat`
- 데이터와 작업 설명: `.csv`, `.json`, `.txt`

파일 하나의 최대 크기는 100 MiB입니다. 빈 파일, 실행 파일, 경로가 포함된
파일명, Windows 예약 이름과 같은 이름의 기존 입력 파일은 거부합니다. 기존
파일을 교체하거나 삭제하는 기능은 제공하지 않습니다.

업로드한 파일은 입력 파일 라이브러리에 최근 수정 순서로 표시됩니다. 목록에는
파일명, 확장자, 크기, 저장 시각과 현재 사용 상태가 포함됩니다. 파일 행의
체크박스를 선택하면 `채팅 첨부 준비` 영역에 첨부 칩이 나타납니다. 이 선택은
현재 브라우저 UI 세션에만 유지되며, #43 채팅 화면이 구현되기 전에는 Codex로
자동 전송되지 않습니다.

업로드와 첨부 선택은 파일 보관과 작업 대상 준비만 수행합니다. SpaceClaim 가져오기, Workbench 프로젝트
열기 또는 Mechanical 해석을 자동으로 시작하지 않습니다. 업로드가 끝나면
Codex에 다음처럼 별도로 요청하세요.

> 방금 업로드한 `package.step`을 검토하고 SpaceClaim에서 가져오기 전에
> 변경될 내용을 설명해줘.

## 정리 승인

`정리 후보 미리보기`는 `workspace clean`의 dry-run만 실행합니다. 이 단계에서는
파일을 삭제하지 않습니다. 후보가 있는 경우에만 별도 확인 대화상자가 열리며,
`삭제 승인` 버튼을 눌러야 실제 정리가 실행됩니다.

자동 정리 대상은 오래된 `generated`, `logs`, `.runtime/codex` 파일로
제한됩니다. 다음 항목은 UI에서도 자동 삭제할 수 없습니다.

- `workspace/input`
- `workspace/results`
- Workbench와 Mechanical runtime
- 심볼릭 링크
- 작업공간 밖으로 해석되는 경로

실행 중이거나 종료가 확인되지 않은 세션 메타데이터가 있으면 실제 정리가
차단됩니다. 세션 파일을 강제로 삭제하지 말고 Workbench와 Mechanical을 정상
종료한 뒤 다시 확인하세요.

## 현재 범위

현재 UI는 읽기 중심 대시보드, 원본 입력 파일 보관과 모의 대화 기능을 제공합니다.
SpaceClaim 형상 생성, Mechanical 경계조건 변경과 해석 실행 버튼은 제공하지
않습니다. 모델 변경과 자연어 작업은 Codex를 통해 진행하고, 기존 Skill의 실행
승인 규칙을 그대로 적용합니다.
