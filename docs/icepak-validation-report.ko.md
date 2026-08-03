# Icepak AI 통합 검증 보고서

검증일: 2026-08-03

## 결론

CAE Agent의 Icepak 설치 감지, 버전 선택, 프로젝트 생성 경로 보호, 스크립트 실행
준비와 AEDT 세션 종료 처리는 단위·회귀 테스트를 통과했다. 그러나 이 PC의 실제
AEDT Student 2025 R2 연결은 Windows Application Control 정책이 AEDT 자동화 DLL을
차단하여 완료되지 않았다. 이 차단은 Icepak 모델이나 해석 조건을 만들기 전에
발생하므로 형상 또는 메시 문제와는 무관하다.

## 검증 환경

- Windows, Python 3.13 및 Python 3.14
- PyAEDT 1.3.0
- AEDT Student 2025 R2
- CAE Agent 전용 가상환경

## 통과 항목

- 설치된 AEDT Student 2025 R2 자동 감지
- 명시 버전과 설치 버전의 선택 규칙
- `workspace/generated` 밖의 새 프로젝트 생성 차단
- 기존 `.aedt` 파일 덮어쓰기 차단
- Icepak 상태·스크립트 실행 인자와 결과 직렬화
- CAE Agent가 시작한 새 AEDT 세션의 정상 종료 요청
- 전체 테스트: 159 passed, 2 skipped

스킵 2건은 현재 Windows 계정의 심볼릭 링크 생성 권한에 관한 테스트이며 Icepak과
관련이 없다.

## 실제 실행 결과

Python 3.13과 3.14에서 각각 새 Icepak 프로젝트 생성을 시도했다. AEDT 실행 파일은
시작되었지만 gRPC 세션이 준비되지 않아 연결이 타임아웃되었다. Windows Code
Integrity 이벤트 3033/3077은 AEDT의 `Ansys.Ansoft.CoreCOMScripting.dll`이 기업
서명 수준을 충족하지 못해 차단되었다고 기록했다. Python 3.13 환경의 콘솔 실행
파일도 같은 정책에 의해 차단되어 `python -m cae_agent` 방식으로 재검증했지만 AEDT
자동화 DLL 차단은 동일했다. 테스트가 만든 잔류 AEDT/Python 프로세스는 종료했다.

## 실제 최소 열해석을 완료하기 위한 외부 조치

조직의 Windows 보안 관리자 또는 IT 담당자가 설치된 Ansys 배포본과 해당 자동화
DLL을 신뢰하도록 Application Control 정책을 수정하거나, 허용된 Ansys 설치본을
제공해야 한다. 정책을 임의로 비활성화하거나 우회해서는 안 된다. 정책 반영 후에는
다음 순서로 다시 검증한다.

1. 빈 Icepak 프로젝트 생성 및 저장
2. 단순 블록과 공기 영역 생성
3. 고체 발열과 외기 경계조건 지정
4. 정상상태 해석 실행
5. 최고 온도, 수렴 상태와 프로젝트 저장 여부 확인

## 판정

- CAE Agent 코드 및 모의 통합 검증: 통과
- 실제 AEDT 프로세스 시작: 통과
- 실제 PyAEDT 세션 연결: 외부 보안 정책으로 차단
- 실제 Icepak 최소 열해석: 세션 연결 차단으로 미실행
