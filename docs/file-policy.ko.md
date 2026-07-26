# CAE Agent 파일 역할과 수정 정책

공개 배포판의 UI는 설치된 CAE Agent 프로그램과 사용자별 CAE 작업 파일을
분리합니다. 자연어 요청으로 생성되는 코드는 프로그램 소스가 아니라 작업공간의
자동화 스크립트이며, 허용된 폴더 밖의 파일 변경 요청은 자동으로 거절됩니다.

## 설치·개발 파일

다음 항목은 CAE Agent 자체를 구성하므로 배포 UI에서 수정하지 않습니다.

- `src/cae_agent`: UI, 승인 정책과 Ansys 실행기
- `tests`: 프로그램 회귀 테스트
- `docs`, `README.md`: 제품 문서
- `.agents`, `.github`: Codex Skill과 GitHub 자동화
- `pyproject.toml`, `setup.ps1`, 설정 예제: 설치와 패키지 구성

이 파일은 GitHub 기여자가 별도의 개발 환경에서 이슈와 PR을 통해 변경합니다.
일반 사용자의 모델 생성·단순화·해석 요청은 이 영역을 수정할 이유가 없습니다.

## 사용자 작업공간

| 경로 | 역할 | UI의 Codex 직접 수정 |
|---|---|---|
| `workspace/input` | 업로드한 원본 모델과 데이터 | 금지 |
| `workspace/generated` | 작업별 SpaceClaim·Mechanical 스크립트 | 허용 |
| `workspace/results` | 새 모델, Workbench 프로젝트와 해석 결과 | 직접 수정 금지 |
| `workspace/logs` | 감사 기록과 실행 로그 | 직접 수정 금지 |
| `workspace/.runtime` | 로컬 세션과 임시 프로토콜 파일 | 직접 수정 금지 |

`input` 교체는 UI의 파일명·크기·경로 검증과 경고 모달을 통과한 경우에만
수행합니다. `results`는 사용자가 승인한 CAE 실행기와 서비스 계층이 새 결과를
저장하는 위치이며 Codex가 일반 파일 편집으로 결과를 조작하지 않습니다.

## 승인과 경로 검사

UI의 Codex App Server는 저장소 루트가 아니라 설정된 `workspace`를 현재
디렉터리로 사용합니다. 기본 샌드박스는 계속 읽기 전용입니다.

파일 변경 요청은 다음 조건을 모두 만족할 때만 자동 승인합니다.

1. App Server가 구체적인 변경 루트를 제공해야 합니다.
2. 정규화된 경로가 실제 `workspace/generated` 또는 그 하위여야 합니다.
3. `..`을 통한 경로 탈출이 없어야 합니다.
4. 작업공간부터 대상까지 심볼릭 링크가 없어야 합니다.

대상이 불명확하거나 `input`, `results`, `logs`, `.runtime`, 저장소 소스 또는
작업공간 밖이면 승인 카드로 우회시키지 않고 정책으로 거절합니다. 생성된
스크립트를 SpaceClaim이나 Mechanical에서 실제 실행하는 작업은 파일 위치와
관계없이 기존처럼 사용자 승인을 요구합니다.
