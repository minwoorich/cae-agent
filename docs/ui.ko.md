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
- 검증된 CAE 입력 파일 업로드
- 지정 보존 기간보다 오래된 안전한 정리 후보
- 실제 정리 결과, 실패 수와 감사 로그 경로

세션 메타데이터는 연결 가능성을 나타내는 로컬 기록입니다. 실제 Workbench 또는
Mechanical 응답을 보장하지 않으므로 CAE 작업을 시작할 때는 Codex가 기존
`status` 명령으로 연결을 다시 확인해야 합니다.

## 입력 파일 업로드

`CAE 입력 파일 선택` 영역에서 로컬 파일 하나를 선택하면 서버가 파일명,
확장자와 크기를 다시 검증한 뒤 `workspace/input`에 저장합니다. 브라우저의
파일 선택 제한은 안전 경계로 간주하지 않으며, 서버 검증을 통과하지 못한
파일은 저장하지 않습니다.

지원하는 형식은 다음과 같습니다.

- STEP: `.step`, `.stp`
- IGES: `.iges`, `.igs`
- SpaceClaim: `.scdoc`
- Workbench와 Mechanical: `.wbpj`, `.mechdat`
- 데이터와 작업 설명: `.csv`, `.json`, `.txt`

파일 하나의 최대 크기는 100 MiB입니다. 빈 파일, 실행 파일, 경로가 포함된
파일명, Windows 예약 이름과 같은 이름의 기존 입력 파일은 거부합니다. 기존
파일을 교체하거나 삭제하는 기능은 제공하지 않습니다.

업로드는 파일 보관만 수행합니다. SpaceClaim 가져오기, Workbench 프로젝트
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

현재 UI는 읽기 중심 대시보드와 원본 입력 파일 보관 기능을 제공합니다.
SpaceClaim 형상 생성, Mechanical 경계조건 변경과 해석 실행 버튼은 제공하지
않습니다. 모델 변경과 자연어 작업은 Codex를 통해 진행하고, 기존 Skill의 실행
승인 규칙을 그대로 적용합니다.
