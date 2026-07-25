# -*- coding: utf-8 -*-
"""메시와 정상상태 열해석을 실행하고 핵심 결과를 JSON 문자열로 반환한다."""

import json

analysis = Model.Analyses[0]
solution = analysis.Solution

# 메시 생성과 해석을 분리 호출하여 실패 단계가 Mechanical 로그에 명확히 남도록
# 한다. Solve(True)는 해석 완료까지 기다린 후 다음 결과 평가 단계로 진행한다.
Model.Mesh.GenerateMesh()
solution.Solve(True)
solution.EvaluateAllResults()

temperature_result = None
heat_flux_result = None
for child in solution.Children:
    if child.Name == "Temperature":
        temperature_result = child
    elif child.Name == "Total Heat Flux":
        heat_flux_result = child

if temperature_result is None:
    raise Exception("Temperature result object was not found.")

mesh_data = ExtAPI.DataModel.MeshDataByName("Global")
temperature_max_c = float(str(temperature_result.Maximum).split()[0])
base_temperature_c = 25.0
die_power_w = 100.0

summary = {
    "status": str(solution.Status),
    "node_count": mesh_data.Nodes.Count,
    "element_count": mesh_data.Elements.Count,
    "temperature_min": str(temperature_result.Minimum),
    "temperature_max": str(temperature_result.Maximum),
    "temperature_average": str(temperature_result.Average),
    "die_power_w": die_power_w,
    "base_temperature_c": base_temperature_c,
    "baseline_rth_k_per_w": (
        temperature_max_c - base_temperature_c
    ) / die_power_w,
}
if heat_flux_result is not None:
    summary["heat_flux_max"] = str(heat_flux_result.Maximum)

json.dumps(summary)
