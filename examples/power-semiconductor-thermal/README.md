# 전력반도체 정상상태 열해석 공식 예제

이 예제는 빈 Workbench 세션에서 단일 SiC die 패키지의 7개 적층 형상을 만들고,
100 W 발열과 baseplate 바닥 25°C 조건으로 정상상태 열해석을 수행합니다.

## 요구사항

- Windows
- Ansys 2026 R1(V261), SpaceClaim 및 Mechanical 사용 가능 라이선스
- Python 3.11 이상
- CAE Agent의 `ansys` 선택 의존성

```powershell
python -m pip install -e ".[ansys]"
```

## 모델

| 바디 | 재료 | 두께 |
|---|---|---:|
| `Baseplate_Cu` | 구리 | 3.00 mm |
| `Substrate_Attach_Solder` | SAC305 | 0.15 mm |
| `DBC_Bottom_Copper` | 구리 | 0.30 mm |
| `DBC_Ceramic_AlN` | AlN | 0.63 mm |
| `DBC_Top_Copper` | 구리 | 0.30 mm |
| `Die_Attach_Solder` | SAC305 | 0.10 mm |
| `SiC_Die_Heat_Source` | 4H-SiC | 0.20 mm |

해석 입력은 die 총 발열 100 W, baseplate 바닥 25°C, 전역 메시 크기 1 mm입니다.
이는 냉각 시스템 전체가 아니라 패키지 자체의 기준 열저항을 확인하는 이상화된
조건입니다.

## 실행 순서

아래 명령은 저장소 루트에서 실행합니다. 첫 번째 명령은 Workbench 브리지를
포그라운드에서 유지하므로 별도 PowerShell 터미널을 열어 나머지를 실행합니다.

```powershell
$example = ".\examples\power-semiconductor-thermal"
$config = "$example\cae-agent.toml"

cae-agent doctor
cae-agent workbench --file $config start
```

두 번째 터미널:

```powershell
$example = ".\examples\power-semiconductor-thermal"
$config = "$example\cae-agent.toml"

cae-agent workbench --file $config create-project `
  --output .\results\power-semiconductor.wbpj

cae-agent workbench --file $config run-script `
  "$example\workbench\define_materials.wbjn"

cae-agent spaceclaim --file $config run `
  "$example\geometry\power_semiconductor.py" `
  --system-name "SYS"

cae-agent mechanical --file $config --system-name "SYS" connect

cae-agent mechanical --file $config --system-name "SYS" run-script `
  "$example\mechanical\setup_analysis.py"

cae-agent mechanical --file $config --system-name "SYS" run-script `
  "$example\mechanical\solve_and_summarize.py"

cae-agent workbench --file $config stop
```

각 Mechanical 명령은 CAE Agent 실행 메타데이터와 Mechanical 반환 문자열을
함께 JSON으로 출력합니다. 마지막 명령의 `return_value` 문자열을 JSON으로
해석하면 `expected/result.schema.json`의 해석 결과 구조를 얻습니다.

## 성공 판정

- SpaceClaim 바디가 7개이며 모든 필수 이름이 존재해야 합니다.
- Mechanical solver 상태가 오류 없이 완료되어야 합니다.
- node와 element 개수는 각각 1 이상이어야 합니다.
- 최대온도는 25°C보다 높아야 합니다.
- 계산된 기준 열저항은 0 K/W보다 커야 합니다.

메시 생성기와 Ansys 패치 버전에 따라 절점 수와 결과값에 차이가 생길 수 있으므로
현재 단계에서는 특정 온도값을 동일성 기준으로 사용하지 않습니다. 실제 V261
통합 실행을 완료한 뒤 기준값과 허용 오차를 별도 기록합니다.
