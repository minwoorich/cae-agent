# Icepak AI 자동화

CAE Agent는 PyAEDT를 통해 Ansys Electronics Desktop의 Icepak 설계에 연결한다.
Workbench Mechanical 연결과는 별도 경로이며, 기존 `.aedt` 또는 `.aedtz`
프로젝트를 명시해야 한다.

## 설치

```powershell
python -m venv .venv-icepak
.\.venv-icepak\Scripts\python.exe -m pip install -e ".[icepak]"
```

Workbench gRPC와 PyAEDT의 의존성 충돌을 피하기 위해 Icepak은 전용
`.venv-icepak`에 설치한다.

## 상태 확인

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
- PyAEDT와 AEDT는 실제 연결 시점에만 필요하다.
- AI 프롬프트는 Desktop 직접 종료와 `release_desktop` 호출을 금지한다.
- 새 AEDT 프로세스가 필요할 때만 `--new-desktop`을 사용한다.
- 해석 실행과 기존 설계 변경은 사용자의 명시적인 승인을 받은 후 수행한다.
