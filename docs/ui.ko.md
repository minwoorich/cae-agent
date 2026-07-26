# CAE Agent 로컬 대시보드

CAE Agent UI는 Codex 자연어 인터페이스를 대체하지 않습니다. Codex가 CAE
작업을 조정하는 동안 환경, 세션, 작업공간, 정리 후보와 결과 파일을 한 화면에서
확인하는 localhost 전용 상태·승인 대시보드입니다.

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

- Python, Git, Codex와 Ansys 환경 진단
- Workbench와 Mechanical 세션 메타데이터 존재 여부
- `input`, `generated`, `logs`, `results`, `.runtime`의 파일 수와 용량
- 최근 로그 및 결과 파일 이름
- 지정 보존 기간보다 오래된 안전한 정리 후보
- 실제 정리 결과, 실패 수와 감사 로그 경로

세션 메타데이터는 연결 가능성을 나타내는 로컬 기록입니다. 실제 Workbench 또는
Mechanical 응답을 보장하지 않으므로 CAE 작업을 시작할 때는 Codex가 기존
`status` 명령으로 연결을 다시 확인해야 합니다.

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

첫 UI는 읽기 중심 대시보드입니다. SpaceClaim 형상 생성, Mechanical 경계조건
변경과 해석 실행 버튼은 제공하지 않습니다. 모델 변경과 자연어 작업은 Codex를
통해 진행하고, 기존 Skill의 실행 승인 규칙을 그대로 적용합니다.
