from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _v(composition: dict[str, float], element: str) -> float:
    for key, value in composition.items():
        if key.strip().casefold() == element.casefold():
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def carbon_equivalent_iiw(composition: dict[str, float]) -> float:
    c = _v(composition, "C")
    mn = _v(composition, "Mn")
    cr, mo, v = _v(composition, "Cr"), _v(composition, "Mo"), _v(composition, "V")
    ni, cu = _v(composition, "Ni"), _v(composition, "Cu")
    return round(c + mn / 6 + (cr + mo + v) / 5 + (ni + cu) / 15, 4)


def pcm(composition: dict[str, float]) -> float:
    c = _v(composition, "C")
    si, mn, cu = _v(composition, "Si"), _v(composition, "Mn"), _v(composition, "Cu")
    ni, cr, mo, v, b = _v(composition, "Ni"), _v(composition, "Cr"), _v(composition, "Mo"), _v(composition, "V"), _v(composition, "B")
    return round(c + si / 30 + mn / 20 + cu / 20 + ni / 60 + cr / 20 + mo / 15 + v / 10 + 5 * b, 4)


ELEMENT_EFFECTS: dict[str, dict[str, str]] = {
    "C": {"benefit": "提高强度、硬度和淬透性。", "risk": "增大冷裂纹、硬化组织和韧性下降风险。", "welding": "控制热输入、氢含量与预热；高碳材料通常需要更严格的工艺评定。"},
    "Mn": {"benefit": "固溶强化并与硫形成 MnS，改善热裂敏感性。", "risk": "含量过高会增加淬透性和硬化倾向。", "welding": "结合碳当量评估；注意焊材 Mn 含量与稀释。"},
    "Si": {"benefit": "脱氧并提高强度，改善熔池流动。", "risk": "过高可能降低韧性并影响镀层钢焊接。", "welding": "关注焊缝脱氧、飞溅与表面氧化。"},
    "Cr": {"benefit": "提高淬透性、耐磨性和耐蚀性。", "risk": "促进硬化组织；不锈钢中需关注 σ 相和晶间腐蚀。", "welding": "低合金钢注意预热；不锈钢控制层间温度和热输入。"},
    "Ni": {"benefit": "提高低温韧性和耐蚀性，稳定奥氏体。", "risk": "某些高 Ni 焊缝存在热裂纹敏感性。", "welding": "用于低温钢和异种钢焊材设计，需控制杂质元素。"},
    "Mo": {"benefit": "提高高温强度、耐点蚀性与淬透性。", "risk": "增加硬化和冷裂倾向。", "welding": "Cr-Mo 钢通常需要预热、后热或焊后热处理。"},
    "V": {"benefit": "析出强化、细化晶粒。", "risk": "提高淬透性，热影响区可能硬化。", "welding": "控制冷却速度，并按材料规范决定预热和 PWHT。"},
    "Nb": {"benefit": "细化晶粒并析出强化；不锈钢中稳定碳。", "risk": "高热输入可能导致粗化或局部脆化。", "welding": "微合金钢宜控制热输入和层间温度。"},
    "Ti": {"benefit": "固氮、细化晶粒和形成稳定碳氮化物。", "risk": "夹杂控制不佳时影响韧性。", "welding": "保护气体和焊材洁净度重要。"},
    "Al": {"benefit": "强脱氧并固氮。", "risk": "氧化物夹杂可能降低韧性。", "welding": "铝合金需彻底清除氧化膜；钢中关注夹杂。"},
    "Cu": {"benefit": "提高耐大气腐蚀性和部分强化效果。", "risk": "高含量可能增加热裂倾向。", "welding": "控制稀释和热输入，异种材料时选择合适过渡焊材。"},
    "B": {"benefit": "微量即可显著提高淬透性。", "risk": "对冷裂敏感性影响显著，且有效含量控制窗口窄。", "welding": "应采用 Pcm 评估并严格控制预热、氢和冷却速度。"},
    "S": {"benefit": "改善部分钢种切削性。", "risk": "形成低熔点共晶，增加热裂纹和夹杂风险。", "welding": "采用低 S 焊材、合理 Mn/S 比和适当焊道形状。"},
    "P": {"benefit": "可提高耐候性和强度。", "risk": "偏析并降低韧性，增加凝固裂纹风险。", "welding": "限制母材和焊材 P 含量，避免过大稀释与深窄焊缝。"},
    "N": {"benefit": "强化奥氏体并提高部分不锈钢耐蚀性。", "risk": "可能引起气孔、时效和氮化物析出。", "welding": "控制保护气体、弧长和熔池暴露。"},
}


def analyze_elements(composition: dict[str, float]) -> list[dict[str, Any]]:
    rows = []
    for raw, value in composition.items():
        key = raw.strip()
        canonical = next((name for name in ELEMENT_EFFECTS if name.casefold() == key.casefold()), key)
        effect = ELEMENT_EFFECTS.get(canonical, {"benefit": "需结合具体合金体系判断。", "risk": "数据库暂无该元素的通用规则。", "welding": "建议查阅材料标准和焊接工艺评定资料。"})
        rows.append({"element": canonical, "content_percent": float(value), **effect})
    return rows


def _steel_risk(ce: float, thickness_mm: float, hydrogen_level: str) -> tuple[str, int]:
    score = 0
    if ce < 0.35:
        score += 0
    elif ce < 0.45:
        score += 1
    elif ce < 0.55:
        score += 2
    else:
        score += 3
    if thickness_mm >= 50:
        score += 2
    elif thickness_mm >= 25:
        score += 1
    if hydrogen_level.lower() in {"high", "高", "unknown", "未知"}:
        score += 1
    labels = ["较低", "中等", "较高", "很高", "很高", "很高"]
    return labels[min(score, len(labels) - 1)], score


def _preheat_range(ce: float, thickness_mm: float, hydrogen_level: str) -> tuple[int | None, int | None]:
    risk, score = _steel_risk(ce, thickness_mm, hydrogen_level)
    if score <= 0:
        return None, None
    base = 50 + max(0, score - 1) * 35
    if thickness_mm >= 50:
        base += 25
    return int(base), int(min(base + 50, 300))


def assess_weldability(payload: dict[str, Any]) -> dict[str, Any]:
    composition = {str(k): float(v) for k, v in (payload.get("composition") or {}).items()}
    thickness = float(payload.get("thickness_mm") or 0)
    group = str(payload.get("material_group") or "carbon_low_alloy_steel")
    hydrogen = str(payload.get("hydrogen_level") or "low")
    result: dict[str, Any] = {
        "material_name": payload.get("material_name") or "未命名材料",
        "material_group": group,
        "thickness_mm": thickness,
        "composition": composition,
        "limitations": ["本结果是前期工艺筛选，不替代材料标准、WPS/PQR、焊接性试验和责任工程师批准。"],
    }
    if group in {"carbon_low_alloy_steel", "steel", "low_alloy_steel"}:
        ce = carbon_equivalent_iiw(composition)
        p_cm = pcm(composition)
        risk, score = _steel_risk(ce, thickness, hydrogen)
        preheat = _preheat_range(ce, thickness, hydrogen)
        issues = []
        if ce >= 0.45 or p_cm >= 0.25:
            issues.extend(["热影响区硬化", "氢致冷裂纹", "焊后延迟裂纹"])
        if _v(composition, "C") >= 0.22:
            issues.append("接头塑韧性下降和淬硬倾向")
        if _v(composition, "S") >= 0.035 or _v(composition, "P") >= 0.035:
            issues.append("凝固裂纹或偏析敏感性增大")
        if thickness >= 40:
            issues.append("高拘束和层状撕裂风险需评估")
        result.update({
            "carbon_equivalent_iiw": ce,
            "pcm": p_cm,
            "weldability": "良好" if score == 0 else "一般" if score <= 2 else "较差",
            "cold_cracking_risk": risk,
            "possible_problems": list(dict.fromkeys(issues)) or ["常规条件下主要关注热输入、变形和氢控制"],
            "preheat_celsius": {"min": preheat[0], "max": preheat[1]},
            "mechanical_property_outlook": "随碳当量和冷却速度升高，强度/硬度可能上升，但冲击韧性和塑性可能下降。",
        })
    elif group in {"stainless_steel", "stainless"}:
        cr_eq = _v(composition, "Cr") + _v(composition, "Mo") + 1.5 * _v(composition, "Si") + 0.5 * _v(composition, "Nb")
        ni_eq = _v(composition, "Ni") + 30 * _v(composition, "C") + 0.5 * _v(composition, "Mn") + 30 * _v(composition, "N")
        result.update({
            "chromium_equivalent": round(cr_eq, 3),
            "nickel_equivalent": round(ni_eq, 3),
            "weldability": "需结合不锈钢组织类型判断",
            "possible_problems": ["凝固热裂纹", "晶间腐蚀/敏化", "σ 相或脆性相析出", "铁素体数不合适"],
            "preheat_celsius": {"min": None, "max": None},
            "mechanical_property_outlook": "低热输入有助于控制敏化和变形，但需保证熔合；层间温度通常需要限制。",
        })
    elif group in {"aluminum", "aluminum_alloy"}:
        result.update({
            "weldability": "取决于合金系列和热处理状态",
            "possible_problems": ["氢气孔", "热裂纹", "氧化膜导致未熔合", "软化区和强度损失", "变形"],
            "preheat_celsius": {"min": None, "max": 120 if thickness >= 12 else None},
            "mechanical_property_outlook": "可热处理强化铝合金焊接接头常在热影响区软化，强度低于母材。",
        })
    else:
        result.update({
            "weldability": "规则库覆盖不足",
            "possible_problems": ["需依据材料牌号、相图、物理性能和适用标准进行专项评估"],
            "preheat_celsius": {"min": None, "max": None},
            "mechanical_property_outlook": "暂无可靠规则结论。",
        })
    return result


def process_plan(payload: dict[str, Any]) -> dict[str, Any]:
    assessment = assess_weldability(payload)
    group = assessment["material_group"]
    thickness = float(payload.get("thickness_mm") or 0)
    joint = str(payload.get("joint_type") or "butt")
    position = str(payload.get("position") or "flat")
    preheat = assessment.get("preheat_celsius") or {}
    if group in {"carbon_low_alloy_steel", "steel", "low_alloy_steel"}:
        if thickness <= 6:
            process, current, voltage, speed = "GMAW/MAG 或 GTAW", "90–180 A", "18–25 V", "250–600 mm/min"
            groove = "I 形对接；装配间隙约 1–2 mm（需按标准确认）"
        elif thickness <= 20:
            process, current, voltage, speed = "MAG/FCAW；根焊可采用 GTAW", "160–300 A", "22–32 V", "180–450 mm/min"
            groove = "单 V 形坡口，角度约 50–70°，钝边与间隙按工艺评定确定"
        else:
            process, current, voltage, speed = "FCAW/SAW；根部可采用 GTAW/MAG", "220–650 A（随方法变化）", "25–38 V", "150–600 mm/min"
            groove = "双 V 或 U 形坡口以降低填充量和变形"
        filler = "低氢型、强度匹配或略低匹配焊材；具体牌号按母材强度级别与服役温度选择"
        interpass = "约 100–250 °C，最终以材料规范和 WPS 为准"
    elif group in {"stainless_steel", "stainless"}:
        process, current, voltage, speed = "GTAW 根焊 + GMAW/FCAW 填充，或全 GTAW", "60–220 A", "10–30 V（随方法变化）", "100–450 mm/min"
        groove = "薄板 I 形；中厚板 V/U 形，控制间隙并实施背面保护"
        filler = "按母材成分选用匹配或超合金化不锈钢焊材；异种钢可选 309L 类过渡焊材"
        interpass = "通常限制在约 150 °C 以下；双相钢等需按专用规范控制"
    elif group in {"aluminum", "aluminum_alloy"}:
        process, current, voltage, speed = "AC GTAW（薄板）或脉冲 GMAW（中厚板）", "70–300 A", "14–28 V", "250–1000 mm/min"
        groove = "薄板 I 形；中厚板 V 形，焊前机械/化学清除氧化膜"
        filler = "按母材系列、裂纹敏感性、强度和耐蚀性在 4xxx/5xxx 系焊丝中选择"
        interpass = "通常不宜过高；避免长时间高温导致软化和变形"
    else:
        process, current, voltage, speed = "需专项选定", "待工艺评定", "待工艺评定", "待工艺评定"
        groove, filler, interpass = "按结构和标准设计", "按母材和服役条件选择", "按材料规范控制"
    return {
        "assessment": assessment,
        "preliminary_wps": {
            "joint_type": joint,
            "position": position,
            "recommended_process": process,
            "current_range": current,
            "voltage_range": voltage,
            "travel_speed_range": speed,
            "groove": groove,
            "filler_principle": filler,
            "preheat_celsius": preheat,
            "interpass_temperature": interpass,
            "postheat_pwht": "当高碳当量、高拘束、厚板、Cr-Mo 钢或法规要求时，评估消氢后热和 PWHT。",
            "shielding_and_cleaning": "采用匹配保护气体；清除油、水、锈、氧化膜并控制焊材烘干和保温。",
        },
        "predicted_joint_performance": assessment.get("mechanical_property_outlook"),
        "validation": ["必须通过 WPS/PQR、试板力学性能、硬度和必要的无损检测确认。"],
    }


FILLER_RULES = [
    (("q235", "q355", "a36", "s355"), "碳钢/低合金钢", ["ER70S-6（实心焊丝）", "E7018（低氢焊条）", "E71T-1 类药芯焊丝"], "常用强度匹配，工艺成熟；低温或高拘束结构应优先低氢并核对冲击韧性。"),
    (("304", "304l"), "奥氏体不锈钢", ["ER308L / E308L", "异种钢时可考虑 ER309L / E309L"], "低碳焊材有利于降低晶间腐蚀风险，异种钢需提高 Cr/Ni 储备。"),
    (("316", "316l"), "含 Mo 奥氏体不锈钢", ["ER316L / E316L"], "匹配 Mo 含量以保持耐点蚀性能。"),
    (("duplex", "2205", "s31803", "s32205"), "双相不锈钢", ["ER2209 / E2209"], "焊材通常提高 Ni 以保证焊缝奥氏体/铁素体平衡。"),
    (("6061", "6063", "6xxx"), "6xxx 系铝合金", ["ER4043/4047", "ER5356（需结合服役温度和阳极氧化要求）"], "4xxx 系通常降低热裂敏感性；5xxx 系可获得不同强度和外观，但高温服役有额外限制。"),
    (("5083", "5086", "5xxx"), "5xxx 系铝镁合金", ["ER5183", "ER5356", "ER5556"], "保持 Mg 合金化和强度；需核对高温服役及应力腐蚀要求。"),
]


def select_filler(payload: dict[str, Any]) -> dict[str, Any]:
    material = " ".join(str(payload.get(k) or "") for k in ("material_name", "base_material", "material_group")).casefold()
    matches = []
    for aliases, family, fillers, reason in FILLER_RULES:
        if any(alias in material for alias in aliases):
            matches.append({"material_family": family, "candidate_fillers": fillers, "reason": reason})
    if not matches:
        group = str(payload.get("material_group") or "").casefold()
        if "stainless" in group:
            matches.append({"material_family": "不锈钢", "candidate_fillers": ["先按母材 Cr-Ni-Mo 成分匹配；异种钢评估 309L/312 类焊材"], "reason": "需要材料牌号和服役介质才能确定具体牌号。"})
        elif "aluminum" in group:
            matches.append({"material_family": "铝合金", "candidate_fillers": ["依据 AWS D1.2/制造商选材表在 4xxx 或 5xxx 系中筛选"], "reason": "铝焊丝选择受裂纹、强度、颜色、腐蚀和服役温度共同影响。"})
        else:
            matches.append({"material_family": "钢或其他材料", "candidate_fillers": ["按母材最低抗拉/屈服强度、冲击韧性、成分、热处理和服役环境选取匹配或低匹配焊材"], "reason": "输入信息不足，不能可靠给出唯一牌号。"})
    return {
        "base_material": payload.get("material_name") or payload.get("base_material"),
        "recommendations": matches,
        "checks": ["核对适用标准体系（GB/T、AWS、ISO、EN 等）", "核对焊接位置、保护气体/焊剂、热处理状态和服役温度", "最终通过 WPS/PQR 和焊材厂家数据确认"],
    }


DEFECT_LIBRARY: dict[str, dict[str, list[str]]] = {
    "气孔": {"causes": ["母材/焊丝表面油水锈", "保护气体流量或纯度异常", "弧长过长或风扰", "铝合金氢含量和氧化膜"], "solutions": ["彻底清洁并干燥", "检查气路泄漏、流量和喷嘴", "缩短弧长并防风", "控制焊材储存和层间清理"]},
    "裂纹": {"causes": ["高碳当量和淬硬组织", "扩散氢与高拘束", "焊缝成分/形状导致凝固裂纹", "收弧坑未填满"], "solutions": ["采用低氢工艺、预热和缓冷", "降低拘束并优化焊接顺序", "调整焊材成分和焊道宽深比", "填满弧坑并采用引弧/熄弧板"]},
    "咬边": {"causes": ["电流/电压过高", "焊速过快", "焊枪角度不当", "摆动在坡口边缘停留不足"], "solutions": ["降低参数或焊速", "调整焊枪角度和弧长", "在两侧适当停顿", "优化焊道层次"]},
    "夹渣": {"causes": ["层间清渣不彻底", "坡口角度小或焊道布置不合理", "热输入不足", "焊枪角度推动熔渣进入前方"], "solutions": ["彻底清理每道焊缝", "增大操作空间并优化层道", "提高熔池流动与热输入", "调整运条方向"]},
    "未熔合": {"causes": ["热输入不足或焊速过快", "坡口侧壁氧化/污染", "焊枪指向不当", "熔池过大遮蔽电弧"], "solutions": ["提高有效热输入或降低焊速", "清理侧壁", "使电弧直接作用于待熔区域", "采用较小焊道和合理摆动"]},
    "未焊透": {"causes": ["根部间隙过小/钝边过大", "电流不足", "焊条/焊丝直径过大", "根部位置偏离"], "solutions": ["调整坡口和装配", "提高根焊电流或选用合适工艺", "减小焊材直径", "保证根部可达性与枪位"]},
}


def analyze_defect(payload: dict[str, Any]) -> dict[str, Any]:
    defect = str(payload.get("defect_type") or "未知缺陷").strip()
    entry = next((value for key, value in DEFECT_LIBRARY.items() if key in defect or defect in key), None)
    if not entry:
        entry = {"causes": ["输入缺陷类型不在基础规则库中，需要结合宏观照片、NDT、参数曲线和断口进一步判断"], "solutions": ["补充缺陷位置、方向、尺寸、出现频率和过程参数", "开展针对性复验和工艺评定"]}
    return {
        "defect_type": defect,
        "observations": payload.get("observations") or "",
        "likely_causes": entry["causes"],
        "corrective_actions": entry["solutions"],
        "verification": ["按适用验收标准确认缺陷性质和允许等级", "通过复验焊、NDT 和必要的金相/断口分析验证根因"],
    }
