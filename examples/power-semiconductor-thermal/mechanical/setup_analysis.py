# -*- coding: utf-8 -*-
"""7개 패키지 바디에 재료, 발열, 기준온도, 메시와 결과 항목을 설정한다."""

import json

DIE_POWER_W = 100.0
BASE_TEMPERATURE_C = 25.0
GLOBAL_MESH_SIZE_MM = 1.0
DIE_VOLUME_M3 = 10e-3 * 10e-3 * 0.2e-3
HEAT_GENERATION_W_M3 = DIE_POWER_W / DIE_VOLUME_M3

MATERIAL_MAP = {
    "Baseplate_Cu": "Cu_Pure_Thermal",
    "Substrate_Attach_Solder": "Solder_SAC305_Thermal",
    "DBC_Bottom_Copper": "Cu_Pure_Thermal",
    "DBC_Ceramic_AlN": "AlN_Ceramic_Thermal",
    "DBC_Top_Copper": "Cu_Pure_Thermal",
    "Die_Attach_Solder": "Solder_SAC305_Thermal",
    "SiC_Die_Heat_Source": "SiC_4H_Thermal",
}

Model.RefreshMaterials()


def short_name(tree_name):
    """Mechanical 트리의 경로 접두사를 제거하고 실제 바디 이름만 반환한다."""
    return tree_name.split("\\")[-1]


def all_bodies():
    """Geometry 트리를 재귀 순회하여 모든 Body 객체를 수집한다."""
    bodies = []

    def visit(node):
        for child in node.Children:
            if child.GetType().Name == "Body":
                bodies.append(child)
            visit(child)

    visit(Model.Geometry)
    return bodies


def geometry_selection(ids):
    """Mechanical 하중 위치에 사용할 GeometryEntities 선택을 만든다."""
    selection = ExtAPI.SelectionManager.CreateSelectionInfo(
        SelectionTypeEnum.GeometryEntities
    )
    selection.Ids = ids
    return selection


def find_child(parent, name):
    """반복 실행 시 같은 이름의 하중이나 결과를 재사용한다."""
    for child in parent.Children:
        if child.Name == name:
            return child
    return None


bodies = all_bodies()
body_by_name = {}
for body in bodies:
    name = short_name(body.Name)
    body_by_name[name] = body
    if name in MATERIAL_MAP:
        body.Material = MATERIAL_MAP[name]

missing = [name for name in MATERIAL_MAP if name not in body_by_name]
if missing:
    raise Exception("Missing required bodies: " + ", ".join(missing))

analysis = Model.Analyses[0]
die_body = body_by_name["SiC_Die_Heat_Source"]
baseplate_body = body_by_name["Baseplate_Cu"]
die_selection = geometry_selection([die_body.GetGeoBody().Id])

# 바닥면은 baseplate 면 중심의 Z 좌표가 최소인 면으로 찾는다. 면 ID는 형상
# 재생성 시 달라질 수 있으므로 고정 ID를 코드에 기록하지 않는다.
base_faces = list(baseplate_body.GetGeoBody().Faces)
minimum_z = min(face.Centroid[2] for face in base_faces)
bottom_faces = [
    face
    for face in base_faces
    if abs(face.Centroid[2] - minimum_z) < 1.0e-9
]
if not bottom_faces:
    raise Exception("The baseplate bottom face could not be identified.")
bottom_selection = geometry_selection([face.Id for face in bottom_faces])

heat = find_child(analysis, "Die Heat Generation - 100 W")
if heat is None:
    heat = analysis.AddInternalHeatGeneration()
    heat.Name = "Die Heat Generation - 100 W"
heat.Location = die_selection
heat.Magnitude.Output.DiscreteValues = [
    Quantity(str(HEAT_GENERATION_W_M3) + " [W m^-3]")
]

temperature = find_child(analysis, "Baseplate Bottom - 25 C")
if temperature is None:
    temperature = analysis.AddTemperature()
    temperature.Name = "Baseplate Bottom - 25 C"
temperature.Location = bottom_selection
temperature.Magnitude.Output.DiscreteValues = [Quantity("25 [C]")]

Model.Mesh.ElementSize = Quantity("1 [mm]")
solution = analysis.Solution
if find_child(solution, "Temperature") is None:
    result = solution.AddTemperature()
    result.Name = "Temperature"
if find_child(solution, "Total Heat Flux") is None:
    result = solution.AddTotalHeatFlux()
    result.Name = "Total Heat Flux"

json.dumps({
    "status": "analysis_configured",
    "body_count": len(bodies),
    "bottom_face_ids": [face.Id for face in bottom_faces],
    "die_power_w": DIE_POWER_W,
    "base_temperature_c": BASE_TEMPERATURE_C,
    "mesh_size_mm": GLOBAL_MESH_SIZE_MM,
})
