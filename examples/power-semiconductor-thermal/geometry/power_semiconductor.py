# -*- coding: utf-8 -*-
# Python Script, API Version = V261
"""단일 SiC die 전력반도체 패키지의 7개 열전달 바디를 생성한다.

각 층을 독립 솔리드로 유지해야 Mechanical에서 서로 다른 열전도 재료를 할당할
수 있다. 바디 이름은 mechanical/setup_analysis.py의 MATERIAL_MAP과 연결되므로
두 파일을 변경할 때 반드시 이름을 함께 갱신해야 한다.
"""


# 모든 평면 치수와 두께는 SpaceClaim의 MM 함수를 사용해 SI 단위 변환을
# 명시한다. 적층은 baseplate의 바닥인 전역 Z=0에서 위쪽으로 진행한다.
BASEPLATE_LENGTH = MM(60)
BASEPLATE_WIDTH = MM(40)
SUBSTRATE_LENGTH = MM(40)
SUBSTRATE_WIDTH = MM(30)
TOP_COPPER_LENGTH = MM(36)
TOP_COPPER_WIDTH = MM(26)
DIE_LENGTH = MM(10)
DIE_WIDTH = MM(10)

BASEPLATE_THICKNESS = MM(3.00)
SUBSTRATE_ATTACH_THICKNESS = MM(0.15)
BOTTOM_COPPER_THICKNESS = MM(0.30)
CERAMIC_THICKNESS = MM(0.63)
TOP_COPPER_THICKNESS = MM(0.30)
DIE_ATTACH_THICKNESS = MM(0.10)
DIE_THICKNESS = MM(0.20)


def create_centered_layer(length, width, bottom, thickness, name):
    """전역 원점을 중심으로 하는 독립 직육면체 바디 한 층을 생성한다."""
    minimum = Point.Create(-length / 2, -width / 2, bottom)
    maximum = Point.Create(
        length / 2,
        width / 2,
        bottom + thickness,
    )
    result = BlockBody.Create(
        minimum,
        maximum,
        ExtrudeType.ForceIndependent,
        None,
    )
    body = result.CreatedBodies[0]
    body.SetName(name)
    return body


def validate_dimensions():
    """잘못된 치수로 겹치거나 역전된 적층을 만들기 전에 입력을 검사한다."""
    positive_values = [
        BASEPLATE_LENGTH,
        BASEPLATE_WIDTH,
        SUBSTRATE_LENGTH,
        SUBSTRATE_WIDTH,
        TOP_COPPER_LENGTH,
        TOP_COPPER_WIDTH,
        DIE_LENGTH,
        DIE_WIDTH,
        BASEPLATE_THICKNESS,
        SUBSTRATE_ATTACH_THICKNESS,
        BOTTOM_COPPER_THICKNESS,
        CERAMIC_THICKNESS,
        TOP_COPPER_THICKNESS,
        DIE_ATTACH_THICKNESS,
        DIE_THICKNESS,
    ]
    if any(value <= MM(0) for value in positive_values):
        raise Exception("All dimensions and thicknesses must be positive.")
    if SUBSTRATE_LENGTH > BASEPLATE_LENGTH:
        raise Exception("Substrate length exceeds the baseplate.")
    if SUBSTRATE_WIDTH > BASEPLATE_WIDTH:
        raise Exception("Substrate width exceeds the baseplate.")
    if TOP_COPPER_LENGTH > SUBSTRATE_LENGTH:
        raise Exception("Top copper length exceeds the substrate.")
    if TOP_COPPER_WIDTH > SUBSTRATE_WIDTH:
        raise Exception("Top copper width exceeds the substrate.")
    if DIE_LENGTH > TOP_COPPER_LENGTH or DIE_WIDTH > TOP_COPPER_WIDTH:
        raise Exception("SiC die exceeds the top copper area.")


validate_dimensions()

layers = [
    (
        BASEPLATE_LENGTH,
        BASEPLATE_WIDTH,
        BASEPLATE_THICKNESS,
        "Baseplate_Cu",
    ),
    (
        SUBSTRATE_LENGTH,
        SUBSTRATE_WIDTH,
        SUBSTRATE_ATTACH_THICKNESS,
        "Substrate_Attach_Solder",
    ),
    (
        SUBSTRATE_LENGTH,
        SUBSTRATE_WIDTH,
        BOTTOM_COPPER_THICKNESS,
        "DBC_Bottom_Copper",
    ),
    (
        SUBSTRATE_LENGTH,
        SUBSTRATE_WIDTH,
        CERAMIC_THICKNESS,
        "DBC_Ceramic_AlN",
    ),
    (
        TOP_COPPER_LENGTH,
        TOP_COPPER_WIDTH,
        TOP_COPPER_THICKNESS,
        "DBC_Top_Copper",
    ),
    (
        DIE_LENGTH,
        DIE_WIDTH,
        DIE_ATTACH_THICKNESS,
        "Die_Attach_Solder",
    ),
    (
        DIE_LENGTH,
        DIE_WIDTH,
        DIE_THICKNESS,
        "SiC_Die_Heat_Source",
    ),
]

z_bottom = MM(0)
for length, width, thickness, body_name in layers:
    create_centered_layer(
        length,
        width,
        z_bottom,
        thickness,
        body_name,
    )
    z_bottom += thickness

# 명시적 저장을 호출하면 Workbench로 Geometry를 전달하기 전에 문서 변경 상태가
# 확정된다. 최종 프로젝트 저장은 CAE Agent가 생성한 Workbench 저널이 담당한다.
Window.ActiveWindow.Document.Save()
