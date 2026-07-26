# 변경 이력

이 문서는 CAE Agent의 사용자에게 영향을 주는 주요 변경 사항을 기록합니다.
버전은 [Semantic Versioning](https://semver.org/) 형식을 따릅니다.

## [0.1.0] - 2026-07-25

첫 공개 알파 버전입니다. Windows와 Ansys 2026 R1(V261)을 최초 지원
대상으로 하며, Codex CLI를 첫 AI 제공자로 사용합니다.

### 추가

- Python 3.11~3.14에서 실행되는 `cae-agent` 명령줄 인터페이스
- Python, 가상환경, Codex CLI와 Ansys 설치 상태를 확인하는 `doctor`
- TOML 설정과 격리된 작업공간 관리
- Workbench 시작·상태 확인·저널 실행·정상 종료
- SpaceClaim 및 Mechanical 스크립트 실행과 결과 보존
- 빈 Steady-State Thermal 프로젝트 생성
- Codex CLI 기반 SpaceClaim·Mechanical 스크립트 생성
- 명시적 실행 승인과 최대 재시도 횟수를 적용한 제한적 자동 수정
- 전력반도체 열해석용 재현 가능한 V261 예제
- 반복 실행 가능한 Windows 설치 스크립트와 Windows CI
- 한국어 시작 가이드, 문제 해결 가이드와 안전한 버그 보고 양식
- dry-run, 세션 보호와 명시적 승인을 적용한 작업공간 상태·정리 명령
- 환경·세션·작업공간과 정리 승인을 표시하는 선택형 localhost NiceGUI 대시보드
- 기존 입력을 덮어쓰지 않는 localhost 대시보드 CAE 파일 업로드
- 개요·입력 파일·로그와 결과·유지관리로 분리한 반응형 엔지니어링 UI

### 안전 제약

- AI 생성 코드는 `--approve-execution` 없이는 Ansys에서 실행되지 않습니다.
- Codex에는 읽기 전용 샌드박스를 사용하며 Ansys 제어권을 직접 제공하지 않습니다.
- 토큰, API 키와 라이선스 정보는 설정·로그·배포 파일에 저장하지 않습니다.
- `--clear`와 `--overwrite`는 사용자가 명시한 경우에만 적용됩니다.
- 자동 수정은 설정된 재시도 횟수 안에서만 동작하며 성공을 보장하지 않습니다.

### 검증 범위

- GitHub Actions에서 Windows와 Python 3.11~3.14 단위 테스트를 수행합니다.
- wheel과 source distribution을 만들고 깨끗한 환경에서 wheel을 설치합니다.
- Ansys 및 Codex가 필요한 실제 CAE 통합 검증은 GitHub-hosted runner에서
  수행하지 않습니다.
- SpaceClaim 자동 수정 흐름과 공식 열해석 예제는 로컬 Ansys Student
  2026 R1(V261) 환경에서 검증했습니다.

[0.1.0]: https://github.com/minwoorich/cae-agent/releases/tag/v0.1.0
