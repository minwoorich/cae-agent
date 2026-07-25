# SpaceClaim V261 스크립트 규칙

새 SpaceClaim 스크립트에는 UTF-8 선언과 API 버전을 명시한다.

```python
# -*- coding: utf-8 -*-
# Python Script, API Version = V261
```

## 검증된 형상 패턴

- 길이는 `MM(60)`처럼 `MM` 함수로 명시한다.
- 점은 `Point.Create(x, y, z)`로 생성한다.
- 독립 직육면체는 `BlockBody.Create(minimum, maximum,
  ExtrudeType.ForceIndependent, None)` 패턴을 우선한다.
- 생성 바디는 반환값의 `CreatedBodies[0]`에서 얻는다.
- V261의 생성 바디 이름은 `body.Name = "이름"`으로 지정한다.
- 문서 변경을 확정해야 할 때 `Window.ActiveWindow.Document.Save()`를 호출한다.

저장소의 실제 검증 예제는
`examples/power-semiconductor-thermal/geometry/power_semiconductor.py`에 있다.
새 API를 추측하기 전에 이 예제와 기존 성공 스크립트를 우선 재사용한다.

## 안전 규칙

- 기존 형상을 삭제하는 코드를 스크립트 안에 숨기지 않는다.
- 바디 이름은 이후 Mechanical 재료 할당과 연결될 수 있으므로 임의 변경하지 않는다.
- 입력 치수는 양수, 포함 관계와 적층 순서를 실행 전에 검증한다.
- 실패 시 기존 스크립트를 덮어쓰지 않고 수정본을 새 파일로 저장한다.
