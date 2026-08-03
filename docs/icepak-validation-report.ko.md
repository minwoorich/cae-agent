# Icepak AI 통합 검증 보고서

검증일: 2026-08-03

## 결론

CAE Agent의 Icepak 설치 감지, 버전 선택, 프로젝트 생성 경로 보호와 세션 종료
처리는 단위·회귀 테스트를 통과했다. Windows Smart App Control 해제와 ASCII
컴퓨터명 적용 후 AEDT Student 2025 R2의 실제 프로젝트 생성, 메시와 정상상태
TemperatureOnly 해석 및 온도 결과 추출까지 완료했다.

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
- Native ScriptEnv를 사용한 실제 Icepak 프로젝트 생성
- 10 W 구리 블록의 정상상태 TemperatureOnly 해석
- 메시와 온도 필드 요약 추출
- 전체 테스트: 159 passed, 2 skipped

스킵 2건은 현재 Windows 계정의 심볼릭 링크 생성 권한에 관한 테스트이며 Icepak과
관련이 없다.

## 실제 실행 결과

초기에는 Smart App Control이 서명되지 않은 AEDT 자동화 DLL을 차단했다. 기능을
해제한 뒤 Native `ScriptEnv.Initialize` 연결과 프로젝트 저장이 성공했다. 이후
Icepak Mesher는 한글 Windows 컴퓨터명을 HPC 머신 이름으로 전달할 때 시작되지
않았다. 컴퓨터명을 `MINWOO`로 변경하고 재부팅한 뒤 동일 해석이 정상 완료됐다.

최종 검증 모델과 결과는 다음과 같다.

- 프로젝트: `workspace/generated/icepak_minimal_20260803.aedt`
- 형상: 20 × 20 × 10 mm 구리 블록
- 발열: 총 10 W
- 외부 열전달계수: 10 W/m²·K, 기준온도 `AmbientTemp`
- 메시: 노드 7,488, 면 1,722, 셀 4,410
- 솔버 상태: `Normal Completion`
- 블록 온도: 최저 599.102 °C, 최고 599.272 °C, 평균 599.211 °C

온도가 높은 것은 작은 블록에 10 W를 가하고 낮은 자연대류 수준의 열전달계수만
사용한 의도적인 스모크 조건 때문이다. 실제 제품 설계의 허용 온도를 뜻하지 않는다.

## 주의 사항

PyAEDT 1.3의 새 세션 시작은 이 Student 빌드에서 WNUA 및 insecure 모드 모두
타임아웃됐다. 실제 검증은 Ansys 설치본의 CPython과 Native ScriptEnv를 사용했다.
향후 CAE Agent에는 Student 2025 R2용 Native 백엔드를 정식 실행 경로로 통합해야
한다.

## 판정

- CAE Agent 코드 및 모의 통합 검증: 통과
- 실제 AEDT 프로세스 시작: 통과
- 실제 Native AEDT 세션 연결: 통과
- 실제 Icepak 최소 열해석: 통과
- 실제 PyAEDT 1.3 세션 연결: 호환성 문제로 실패, Native 경로로 대체
