# Icepak AI 자동화

현재 로컬 실제 실행 검증 결과는 [Icepak AI 통합 검증 보고서](icepak-validation-report.ko.md)에
정리되어 있다.

CAE Agent는 PyAEDT와 AEDT Native ScriptEnv 두 백엔드를 제공한다. PyAEDT는
기존 Icepak 설계 객체를 고수준 API로 제어하고, Native는 PyAEDT 세션 생성이
로컬 보안 정책에서 멈추는 경우 설치본의 내장 CPython과 DesktopPlugin을 직접
사용한다. 두 경로 모두 Workbench Mechanical 연결과는 별개다.

## 설치

```powershell
python -m venv .venv-icepak
.\.venv-icepak\Scripts\python.exe -m pip install -e ".[icepak]"
```

Workbench gRPC와 PyAEDT의 의존성 충돌을 피하기 위해 Icepak은 전용
`.venv-icepak`에 설치한다.

## 상태 확인

먼저 로컬에 설치된 AEDT 버전을 확인할 수 있다. 별도 버전을 지정하지 않으면
CAE Agent가 일반 버전을 우선하고, 없으면 Student 버전 중 가장 최신 설치를 선택한다.

```powershell
.\.venv-icepak\Scripts\cae-agent.exe icepak installations
```

## 새 프로젝트 생성

새 프로젝트는 원본 입력과 섞이지 않도록 `workspace/generated` 아래에만 만든다.
확장자는 `.aedt`여야 하며 같은 파일이 이미 있으면 덮어쓰지 않고 중단한다.

```powershell
.\.venv-icepak\Scripts\cae-agent.exe icepak `
  --student-version `
  create-project --output workspace/generated/icepak_minimal.aedt
```

프로젝트가 이미 있으면 다음 명령으로 연결 상태를 확인한다.

```powershell
cae-agent icepak --project workspace/input/thermal.aedt status
```

특정 설계나 Student 버전을 사용할 때는 다음 옵션을 추가한다.

```powershell
.\.venv-icepak\Scripts\cae-agent.exe icepak `
  --project workspace/input/thermal.aedt `
  --design IcepakDesign1 `
  --student-version `
  --aedt-version 2025.2 `
  status
```

## 스크립트 실행

스크립트에는 연결된 PyAEDT 애플리케이션이 `icepak`과 `app` 변수로 제공된다.
`result` 변수에 값을 대입하면 구조화된 실행 결과에 포함된다. 원본 스크립트는
변경하지 않고 `workspace/generated/icepak`에 실행 사본을 만든다.

```powershell
cae-agent icepak `
  --project workspace/input/thermal.aedt `
  run-script workspace/input/set_heat_source.py
```

### Native ScriptEnv 백엔드

Native 스크립트에는 AEDT가 제공하는 `oDesktop`이 주입된다. 새 프로젝트 생성,
기존 프로젝트 열기와 해석은 AEDT Scripting API로 명시해야 하며, 결과 요약은
`result` 변수에 저장한다. 이 백엔드는 `--project`가 필수가 아니므로 새 프로젝트
생성 스크립트에도 사용할 수 있다.

```powershell
.\.venv-icepak\Scripts\cae-agent.exe icepak `
  --student-version `
  --aedt-version 2025.2 `
  run-script --backend native --timeout 120 workspace/input/native_probe.py
```

실행기는 설치 경로에서 `ansysedtsv.exe`, 내장 CPython과 `DesktopPlugin`을
검증하고 localhost 임시 포트에 새 AEDT를 시작한다. 원본은 보존하며 실행 사본과
고정 래퍼는 `workspace/generated/icepak/native/<run-id>`에 남긴다. 내장 Python의
종료 코드뿐 아니라 `CAE_NATIVE_RESULT` 성공 마커도 확인한 뒤 자신이 시작한 AEDT
프로세스만 종료한다. `ANSYSEM_ROOT###` 설치 환경 변수를 우선 사용하므로 Native
실행 자체에는 PyAEDT 패키지가 필요하지 않다.

AEDT 2025 R2에서 `CreateBox`를 사용할 때는 GUI 녹화 결과의 모든 속성을 그대로
전달하지 않는다. `UDMId`, `IsMaterialEditable`, `UseMaterialAppearance`,
`IsLightweight`가 포함된 확장 속성 묶음은 Native gRPC에서 `0x80020009`를
발생시킬 수 있다. `native_box_attributes(name, material)`이 반환하는 `Name`,
`MaterialValue`, `SolveInside` 최소 묶음으로 형상을 생성하고 색상·투명도는 생성
후 별도 속성 변경으로 적용한다. 또한 빈 신규 프로젝트에는 존재하지 않는
`Setup1`을 무조건 삭제하지 말고, 설정 목록을 확인한 뒤에만 삭제한다.

## AI 스크립트 생성

```powershell
cae-agent generate `
  --target icepak `
  --prompt "PCB 부품에 25 W 열원을 지정하고 설정 상태를 result에 기록해"
```

AI 생성은 코드를 작성하고 검증된 사본으로 저장하는 단계다. 실제 프로젝트 변경과
해석 실행은 생성 스크립트를 검토한 뒤 `icepak run-script`로 별도 실행한다.

## 안전 경계

- 프로젝트 경로는 기존 `.aedt` 또는 `.aedtz` 파일이어야 한다.
- 새 프로젝트 생성 위치는 `workspace/generated` 내부로 제한되며 기존 파일을 덮어쓰지 않는다.
- 자동 감지가 맞지 않는 경우에만 `--aedt-version`과 `--student-version`을 명시한다.
- PyAEDT와 AEDT는 실제 연결 시점에만 필요하다.
- AI 프롬프트는 Desktop 직접 종료와 `release_desktop` 호출을 금지한다.
- 새 AEDT 프로세스가 필요할 때만 `--new-desktop`을 사용한다.
- Native 백엔드는 ASCII 컴퓨터 이름이 필요하며, 조건이 맞지 않으면 AEDT를 시작하기 전에 중단한다.
- Native 스크립트에서는 `ScriptEnv.Initialize`와 `ScriptEnv.Shutdown`을 직접 호출하지 않는다.
- 해석 실행과 기존 설계 변경은 사용자의 명시적인 승인을 받은 후 수행한다.
