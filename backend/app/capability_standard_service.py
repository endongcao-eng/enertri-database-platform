from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import (
    Capability,
    CapabilityKnowledgeLink,
    KnowledgeNode,
    KnowledgeRelation,
    LearningResource,
    ResourceCapabilityLink,
    ResourceKnowledgeLink,
    Term,
)

LEVEL_RUBRIC = {
    "1": "了解核心概念，可识别术语与基本问题",
    "2": "可在指导下完成基础分析或操作",
    "3": "可独立完成常规科研任务",
    "4": "可处理复杂问题并选择合适方法",
    "5": "可设计方案、综合判断并指导他人",
}

KNOWLEDGE_SEED = [
    ("K-MATH-PDE", "偏微分方程", "Partial Differential Equations", "数学基础", "theory", "连续介质、传热与多物理场模型常用的数学基础。"),
    ("K-HEAT-CONDUCTION", "热传导", "Heat Conduction", "传热学", "theory", "稳态与非稳态热传导、热阻与导热微分方程。"),
    ("K-HEAT-CONVECTION", "对流换热", "Convective Heat Transfer", "传热学", "theory", "流动边界层、换热系数与对流传热分析。"),
    ("K-MAT-THERMO", "材料热物性", "Thermophysical Properties of Materials", "材料与能源", "concept", "导热系数、比热、热扩散率等温度相关物性。"),
    ("K-MICRO-HEAT", "微纳尺度传热", "Micro/Nanoscale Heat Transfer", "微纳热科学", "theory", "特征尺度接近载流子平均自由程时的非傅里叶传热。"),
    ("K-PHONON", "声子输运", "Phonon Transport", "微纳热科学", "theory", "晶格振动、散射机制与声子主导热输运。"),
    ("K-NUM-FDM", "有限差分法", "Finite Difference Method", "数值方法", "method", "以离散差分近似微分算子的数值求解方法。"),
    ("K-NUM-FEM", "有限元法", "Finite Element Method", "数值方法", "method", "复杂几何与多物理场问题的离散求解方法。"),
    ("K-PROG-PY", "Python 科学计算", "Scientific Computing with Python", "科研计算", "tool", "NumPy、SciPy、Pandas 与可复现实验脚本。"),
    ("K-SIM-COMSOL", "COMSOL 多物理场", "COMSOL Multiphysics", "科研计算", "tool", "多物理场建模、网格、求解器设置与结果后处理。"),
    ("K-DATA-ANALYSIS", "科研数据分析", "Research Data Analysis", "科研方法", "method", "数据清洗、拟合、可视化、不确定度与误差分析。"),
    ("K-RESEARCH-LIT", "科研文献方法", "Research Literature Methods", "科研方法", "practice", "检索、筛选、证据阅读、研究空白识别与文献综述。"),
    ("K-ML-BASE", "机器学习基础", "Machine Learning Fundamentals", "人工智能", "method", "监督学习、特征工程、训练验证与模型评估。"),
    ("K-WELD-LASER", "激光焊接", "Laser Welding", "焊接工程", "theory", "激光热源、熔池与小孔模式焊接基础。"),
    ("K-WELD-DEFECT", "焊接缺陷与气孔", "Welding Defects and Porosity", "焊接工程", "concept", "焊接气孔、未熔合等缺陷形成机理与检测分析。"),
    ("K-STAT-PHYS", "统计物理", "Statistical Physics", "物理基础", "theory", "从微观统计规律理解宏观热学与输运现象。"),
    ("K-MD", "分子动力学", "Molecular Dynamics", "计算材料", "method", "基于原子相互作用势进行微观动力学模拟与输运性质计算。"),
    ("K-DL", "深度学习基础", "Deep Learning Fundamentals", "人工智能", "method", "神经网络、优化、正则化与深度模型训练评估基础。"),
    ("K-GNN", "图神经网络", "Graph Neural Networks", "人工智能", "method", "面向图结构与材料结构数据的消息传递和表示学习方法。"),
    ("K-CHIP-THERM", "芯片热管理", "Chip Thermal Management", "电子热科学", "practice", "芯片封装、热点、界面热阻与多尺度热管理方法。"),
]

CAPABILITY_SEED = [
    ("C-HEAT-THEORY", "传热理论分析", "Heat-transfer Theoretical Analysis", "theory", "建立热过程物理假设并进行理论分析。"),
    ("C-NUM-MODEL", "数值建模与求解", "Numerical Modeling and Solving", "methodology", "把科研问题转化为可计算模型并选择数值方法。"),
    ("C-PYTHON", "Python 科研计算", "Python for Research Computing", "computation", "独立编写科研计算、数据处理与可复现脚本。"),
    ("C-COMSOL", "多物理场仿真", "Multiphysics Simulation", "computation", "使用多物理场软件完成模型、网格、求解与结果验证。"),
    ("C-DATA", "科研数据分析", "Research Data Analysis", "research", "对实验或仿真数据进行清洗、拟合、误差分析和解释。"),
    ("C-LITERATURE", "文献调研与证据综合", "Literature Review and Evidence Synthesis", "research", "完成系统检索、证据提取、观点比较和研究空白识别。"),
    ("C-ML-RESEARCH", "科研机器学习", "Machine Learning for Research", "computation", "将机器学习用于科研数据建模并正确评估泛化性能。"),
    ("C-WELD-PROCESS", "焊接工艺与缺陷分析", "Welding Process and Defect Analysis", "experiment", "结合工艺参数、组织和缺陷证据分析焊接问题。"),
]

RESOURCE_SEED = [
    ("R-COURSE-HEAT", "course", "传热学", "Heat Transfer", "能源动力/机械", "课程", "传热理论核心课程，覆盖导热、对流与基础热物性。"),
    ("R-COURSE-NUM", "course", "数值分析与工程计算", "Numerical Analysis for Engineering", "工科基础", "课程", "从微分方程离散到常见数值方法和工程计算。"),
    ("R-BOOK-MICRO", "book", "Micro/Nanoscale Heat Transfer", "专业书籍", "微纳热科学", "专业书", "用于建立微纳尺度传热、声子输运与材料热物性的系统知识。"),
    ("R-COURSE-ML", "course", "机器学习基础", "Machine Learning Fundamentals", "人工智能", "课程", "科研机器学习所需的监督学习、验证与数据处理基础。"),
    ("R-TASK-MICRO", "project_task", "微纳热输运数值模拟任务", "Micro/Nanoscale Heat Transport Simulation Task", "微纳热科学", "科研项目任务", "查阅文献、建立微纳热输运模型、编写求解程序并完成数据解释。"),
    ("R-TASK-WELD", "project_task", "激光焊接气孔机理分析任务", "Laser-welding Porosity Mechanism Analysis Task", "焊接工程", "科研项目任务", "结合论文证据、工艺参数和数据结果分析气孔形成机制。"),
    ("R-TASK-ML-THERMO", "project_task", "材料热物性机器学习预测任务", "ML Prediction of Material Thermophysical Properties", "材料与人工智能", "科研项目任务", "构建材料热物性数据集，完成特征处理、机器学习建模、交叉验证与结果解释。"),
    ("R-COURSE-STAT", "course", "统计物理与输运基础", "Statistical Physics and Transport", "物理基础", "课程", "为声子输运、分子动力学和非平衡热输运建立统计物理基础。"),
    ("R-COURSE-MD", "course", "分子动力学模拟方法", "Molecular Dynamics Simulation", "计算材料", "课程", "覆盖原子模型、势函数、积分算法、平衡与输运性质计算。"),
    ("R-COURSE-DL", "course", "深度学习与 PyTorch 科研实践", "Deep Learning with PyTorch for Research", "人工智能", "课程", "从神经网络基础到科研数据建模、训练验证与可复现实验。"),
    ("R-BOOK-GNN", "book", "Graph Representation Learning", "图表示学习专业书", "人工智能", "专业书", "系统学习图表示、消息传递神经网络与图结构数据建模。"),
    ("R-COURSE-CHIP", "course", "芯片热管理与电子封装热设计", "Chip Thermal Management", "电子热科学", "课程", "覆盖芯片热点、封装热阻、界面热传导和热设计方法。"),
    ("R-TASK-GNN-THERMO", "project_task", "图神经网络材料热导率预测任务", "GNN Thermal Conductivity Prediction", "材料与人工智能", "科研项目任务", "使用材料结构图数据训练 GNN，预测热导率并结合传热机理解释结果。"),
    ("R-TASK-CHIP", "project_task", "芯片热点与封装热阻数值分析任务", "Chip Hotspot and Package Thermal Resistance Simulation", "电子热科学", "科研项目任务", "建立芯片热点与封装多层热阻模型，完成数值求解、参数分析与热设计建议。"),
]

KNOWLEDGE_RELATIONS = [
    ("K-MATH-PDE", "K-NUM-FDM", "prerequisite", 0.9, "理解微分方程有助于掌握差分离散。"),
    ("K-MATH-PDE", "K-NUM-FEM", "prerequisite", 0.9, "有限元弱形式与场方程建立依赖微分方程基础。"),
    ("K-HEAT-CONDUCTION", "K-MICRO-HEAT", "prerequisite", 1.0, "微纳传热需要先理解经典傅里叶传热。"),
    ("K-MAT-THERMO", "K-MICRO-HEAT", "prerequisite", 0.7, "尺度效应分析依赖材料热物性。"),
    ("K-PHONON", "K-MICRO-HEAT", "part_of", 0.9, "声子输运是微纳尺度传热的重要组成。"),
    ("K-PROG-PY", "K-ML-BASE", "prerequisite", 0.8, "科研机器学习通常需要 Python 数据与模型实现基础。"),
    ("K-DATA-ANALYSIS", "K-ML-BASE", "prerequisite", 0.7, "可靠机器学习依赖数据处理与评估意识。"),
    ("K-NUM-FEM", "K-SIM-COMSOL", "prerequisite", 0.8, "理解有限元有助于正确使用多物理场软件。"),
    ("K-WELD-LASER", "K-WELD-DEFECT", "enables", 0.8, "焊接过程机理是缺陷解释的基础。"),
    ("K-STAT-PHYS", "K-PHONON", "prerequisite", 0.9, "统计物理为声子分布与输运提供基础。"),
    ("K-STAT-PHYS", "K-MD", "prerequisite", 0.8, "统计系综和热涨落概念是分子动力学的重要基础。"),
    ("K-ML-BASE", "K-DL", "prerequisite", 0.9, "深度学习建立在监督学习、优化和模型评估基础之上。"),
    ("K-DL", "K-GNN", "prerequisite", 0.9, "图神经网络需要神经网络与反向传播基础。"),
    ("K-MAT-THERMO", "K-CHIP-THERM", "prerequisite", 0.7, "芯片热管理需要理解材料和界面的热物性。"),
    ("K-HEAT-CONDUCTION", "K-CHIP-THERM", "prerequisite", 0.9, "芯片热设计以多层导热与热阻网络为基础。"),
]

CAP_KNOWLEDGE_LINKS = [
    ("C-HEAT-THEORY", "K-HEAT-CONDUCTION", "requires", 4.0, 1.0),
    ("C-HEAT-THEORY", "K-HEAT-CONVECTION", "requires", 3.0, 0.8),
    ("C-HEAT-THEORY", "K-MAT-THERMO", "supports", 3.0, 0.6),
    ("C-HEAT-THEORY", "K-MICRO-HEAT", "supports", 3.0, 0.8),
    ("C-NUM-MODEL", "K-MATH-PDE", "requires", 3.0, 0.8),
    ("C-NUM-MODEL", "K-NUM-FDM", "supports", 3.0, 0.8),
    ("C-NUM-MODEL", "K-NUM-FEM", "supports", 3.0, 0.8),
    ("C-PYTHON", "K-PROG-PY", "requires", 4.0, 1.0),
    ("C-COMSOL", "K-SIM-COMSOL", "requires", 4.0, 1.0),
    ("C-COMSOL", "K-NUM-FEM", "supports", 3.0, 0.7),
    ("C-DATA", "K-DATA-ANALYSIS", "requires", 4.0, 1.0),
    ("C-DATA", "K-PROG-PY", "supports", 2.0, 0.4),
    ("C-LITERATURE", "K-RESEARCH-LIT", "requires", 4.0, 1.0),
    ("C-ML-RESEARCH", "K-ML-BASE", "requires", 4.0, 1.0),
    ("C-ML-RESEARCH", "K-DATA-ANALYSIS", "requires", 3.0, 0.7),
    ("C-ML-RESEARCH", "K-PROG-PY", "supports", 3.0, 0.7),
    ("C-WELD-PROCESS", "K-WELD-LASER", "requires", 3.0, 0.8),
    ("C-WELD-PROCESS", "K-WELD-DEFECT", "requires", 4.0, 1.0),
    ("C-WELD-PROCESS", "K-DATA-ANALYSIS", "supports", 2.0, 0.4),
    ("C-ML-RESEARCH", "K-DL", "supports", 3.5, 0.8),
    ("C-ML-RESEARCH", "K-GNN", "supports", 3.5, 0.8),
    ("C-HEAT-THEORY", "K-STAT-PHYS", "supports", 2.5, 0.5),
    ("C-NUM-MODEL", "K-MD", "supports", 3.0, 0.7),
    ("C-HEAT-THEORY", "K-CHIP-THERM", "supports", 3.0, 0.7),
]

RESOURCE_KNOWLEDGE_LINKS = [
    ("R-COURSE-HEAT", "K-HEAT-CONDUCTION", 4.2, 1.0, 0.68),
    ("R-COURSE-HEAT", "K-HEAT-CONVECTION", 4.0, 1.0, 0.68),
    ("R-COURSE-HEAT", "K-MAT-THERMO", 2.4, 0.7, 0.60),
    ("R-COURSE-NUM", "K-MATH-PDE", 3.2, 0.8, 0.65),
    ("R-COURSE-NUM", "K-NUM-FDM", 4.1, 1.0, 0.68),
    ("R-COURSE-NUM", "K-NUM-FEM", 3.0, 0.8, 0.60),
    ("R-BOOK-MICRO", "K-HEAT-CONDUCTION", 3.0, 0.6, 0.42),
    ("R-BOOK-MICRO", "K-MICRO-HEAT", 4.5, 1.0, 0.48),
    ("R-BOOK-MICRO", "K-PHONON", 4.0, 0.9, 0.46),
    ("R-BOOK-MICRO", "K-MAT-THERMO", 3.0, 0.6, 0.40),
    ("R-COURSE-ML", "K-PROG-PY", 3.0, 0.6, 0.60),
    ("R-COURSE-ML", "K-DATA-ANALYSIS", 3.1, 0.8, 0.64),
    ("R-COURSE-ML", "K-ML-BASE", 4.2, 1.0, 0.70),
    ("R-TASK-MICRO", "K-RESEARCH-LIT", 3.2, 0.7, 0.88),
    ("R-TASK-MICRO", "K-MICRO-HEAT", 4.2, 1.0, 0.92),
    ("R-TASK-MICRO", "K-PHONON", 3.6, 0.9, 0.88),
    ("R-TASK-MICRO", "K-NUM-FDM", 3.4, 0.8, 0.86),
    ("R-TASK-MICRO", "K-PROG-PY", 4.0, 1.0, 0.93),
    ("R-TASK-MICRO", "K-DATA-ANALYSIS", 3.4, 0.8, 0.90),
    ("R-TASK-WELD", "K-RESEARCH-LIT", 3.4, 0.8, 0.90),
    ("R-TASK-WELD", "K-WELD-LASER", 3.8, 0.9, 0.90),
    ("R-TASK-WELD", "K-WELD-DEFECT", 4.2, 1.0, 0.94),
    ("R-TASK-WELD", "K-DATA-ANALYSIS", 3.2, 0.7, 0.88),
    ("R-TASK-ML-THERMO", "K-MAT-THERMO", 3.2, 0.7, 0.88),
    ("R-TASK-ML-THERMO", "K-ML-BASE", 4.4, 1.0, 0.95),
    ("R-TASK-ML-THERMO", "K-PROG-PY", 4.1, 0.9, 0.94),
    ("R-TASK-ML-THERMO", "K-DATA-ANALYSIS", 4.3, 1.0, 0.95),
    ("R-TASK-ML-THERMO", "K-RESEARCH-LIT", 2.8, 0.6, 0.86),
    ("R-COURSE-STAT", "K-STAT-PHYS", 4.4, 1.0, 0.70),
    ("R-COURSE-STAT", "K-PHONON", 2.5, 0.5, 0.55),
    ("R-COURSE-MD", "K-MD", 4.4, 1.0, 0.72),
    ("R-COURSE-MD", "K-STAT-PHYS", 2.8, 0.5, 0.58),
    ("R-COURSE-MD", "K-PROG-PY", 2.4, 0.4, 0.55),
    ("R-COURSE-DL", "K-DL", 4.5, 1.0, 0.74),
    ("R-COURSE-DL", "K-ML-BASE", 3.7, 0.8, 0.70),
    ("R-COURSE-DL", "K-PROG-PY", 3.5, 0.7, 0.68),
    ("R-BOOK-GNN", "K-GNN", 4.2, 1.0, 0.48),
    ("R-BOOK-GNN", "K-DL", 3.2, 0.6, 0.44),
    ("R-COURSE-CHIP", "K-CHIP-THERM", 4.5, 1.0, 0.72),
    ("R-COURSE-CHIP", "K-HEAT-CONDUCTION", 3.2, 0.6, 0.62),
    ("R-COURSE-CHIP", "K-MAT-THERMO", 3.4, 0.7, 0.64),
    ("R-TASK-GNN-THERMO", "K-GNN", 4.5, 1.0, 0.96),
    ("R-TASK-GNN-THERMO", "K-DL", 4.1, 0.8, 0.94),
    ("R-TASK-GNN-THERMO", "K-MAT-THERMO", 3.3, 0.7, 0.90),
    ("R-TASK-GNN-THERMO", "K-PROG-PY", 4.0, 0.8, 0.93),
    ("R-TASK-GNN-THERMO", "K-DATA-ANALYSIS", 3.8, 0.8, 0.92),
    ("R-TASK-CHIP", "K-CHIP-THERM", 4.6, 1.0, 0.95),
    ("R-TASK-CHIP", "K-HEAT-CONDUCTION", 4.0, 0.8, 0.92),
    ("R-TASK-CHIP", "K-MAT-THERMO", 3.8, 0.8, 0.90),
    ("R-TASK-CHIP", "K-NUM-FEM", 3.5, 0.7, 0.88),
    ("R-TASK-CHIP", "K-DATA-ANALYSIS", 3.2, 0.6, 0.88),
]

RESOURCE_CAPABILITY_LINKS = [
    ("R-COURSE-HEAT", "C-HEAT-THEORY", 3.5, 1.0, 0.65),
    ("R-COURSE-NUM", "C-NUM-MODEL", 3.4, 1.0, 0.66),
    ("R-BOOK-MICRO", "C-HEAT-THEORY", 3.0, 0.8, 0.42),
    ("R-COURSE-ML", "C-ML-RESEARCH", 3.0, 0.9, 0.66),
    ("R-COURSE-ML", "C-DATA", 2.6, 0.6, 0.60),
    ("R-TASK-MICRO", "C-HEAT-THEORY", 3.7, 0.8, 0.90),
    ("R-TASK-MICRO", "C-NUM-MODEL", 4.0, 1.0, 0.92),
    ("R-TASK-MICRO", "C-PYTHON", 4.1, 1.0, 0.94),
    ("R-TASK-MICRO", "C-DATA", 3.4, 0.8, 0.90),
    ("R-TASK-MICRO", "C-LITERATURE", 3.0, 0.7, 0.88),
    ("R-TASK-WELD", "C-WELD-PROCESS", 4.2, 1.0, 0.94),
    ("R-TASK-WELD", "C-DATA", 3.2, 0.7, 0.88),
    ("R-TASK-WELD", "C-LITERATURE", 3.2, 0.7, 0.90),
    ("R-TASK-ML-THERMO", "C-ML-RESEARCH", 4.5, 1.0, 0.96),
    ("R-TASK-ML-THERMO", "C-PYTHON", 3.8, 0.8, 0.92),
    ("R-TASK-ML-THERMO", "C-DATA", 4.2, 1.0, 0.95),
    ("R-TASK-ML-THERMO", "C-LITERATURE", 2.8, 0.6, 0.86),
    ("R-COURSE-STAT", "C-HEAT-THEORY", 2.5, 0.45, 0.55),
    ("R-COURSE-MD", "C-NUM-MODEL", 3.1, 0.7, 0.66),
    ("R-COURSE-DL", "C-ML-RESEARCH", 3.5, 0.9, 0.70),
    ("R-COURSE-DL", "C-PYTHON", 2.8, 0.5, 0.64),
    ("R-BOOK-GNN", "C-ML-RESEARCH", 3.0, 0.7, 0.44),
    ("R-COURSE-CHIP", "C-HEAT-THEORY", 3.5, 0.8, 0.68),
    ("R-TASK-GNN-THERMO", "C-ML-RESEARCH", 4.7, 1.0, 0.97),
    ("R-TASK-GNN-THERMO", "C-PYTHON", 4.0, 0.8, 0.93),
    ("R-TASK-GNN-THERMO", "C-DATA", 4.0, 0.8, 0.93),
    ("R-TASK-GNN-THERMO", "C-LITERATURE", 2.8, 0.5, 0.86),
    ("R-TASK-CHIP", "C-HEAT-THEORY", 4.2, 1.0, 0.94),
    ("R-TASK-CHIP", "C-NUM-MODEL", 3.8, 0.9, 0.92),
    ("R-TASK-CHIP", "C-COMSOL", 3.2, 0.6, 0.88),
    ("R-TASK-CHIP", "C-DATA", 3.0, 0.5, 0.86),
]


def _term_match(db: Session, zh: str, en: str | None) -> int | None:
    conditions = [Term.zh == zh]
    if en:
        conditions.append(Term.en == en)
    term = db.scalar(select(Term).where(or_(*conditions)).limit(1))
    return term.id if term else None


def seed_capability_standards(db: Session) -> dict[str, int]:
    nodes: dict[str, KnowledgeNode] = {}
    for code, zh, en, domain, node_type, desc in KNOWLEDGE_SEED:
        item = db.scalar(select(KnowledgeNode).where(KnowledgeNode.code == code))
        if not item:
            item = KnowledgeNode(
                code=code, name_zh=zh, name_en=en, domain=domain, node_type=node_type,
                description=desc, linked_term_id=_term_match(db, zh, en), level_scale=5, status="active",
            )
            db.add(item); db.flush()
        nodes[code] = item

    capabilities: dict[str, Capability] = {}
    rubric_json = json.dumps(LEVEL_RUBRIC, ensure_ascii=False)
    for code, zh, en, category, desc in CAPABILITY_SEED:
        item = db.scalar(select(Capability).where(Capability.code == code))
        if not item:
            item = Capability(code=code, name_zh=zh, name_en=en, category=category, description=desc, level_scale=5, rubric_json=rubric_json, status="active")
            db.add(item); db.flush()
        capabilities[code] = item

    resources: dict[str, LearningResource] = {}
    for code, resource_type, title, subtitle, discipline, provider, desc in RESOURCE_SEED:
        item = db.scalar(select(LearningResource).where(LearningResource.code == code))
        if not item:
            item = LearningResource(
                code=code, resource_type=resource_type, title=title, subtitle=subtitle,
                discipline=discipline, provider=provider, description=desc,
                metadata_json=json.dumps({"seed": "v4.3-stage1"}, ensure_ascii=False), status="active",
            )
            db.add(item); db.flush()
        resources[code] = item

    for source, target, relation_type, weight, rationale in KNOWLEDGE_RELATIONS:
        exists = db.scalar(select(KnowledgeRelation).where(
            KnowledgeRelation.source_node_id == nodes[source].id,
            KnowledgeRelation.target_node_id == nodes[target].id,
            KnowledgeRelation.relation_type == relation_type,
        ))
        if not exists:
            db.add(KnowledgeRelation(source_node_id=nodes[source].id, target_node_id=nodes[target].id, relation_type=relation_type, weight=weight, rationale=rationale))

    for cap_code, node_code, relation_type, required_level, weight in CAP_KNOWLEDGE_LINKS:
        exists = db.scalar(select(CapabilityKnowledgeLink).where(
            CapabilityKnowledgeLink.capability_id == capabilities[cap_code].id,
            CapabilityKnowledgeLink.knowledge_node_id == nodes[node_code].id,
            CapabilityKnowledgeLink.relation_type == relation_type,
        ))
        if not exists:
            db.add(CapabilityKnowledgeLink(
                capability_id=capabilities[cap_code].id, knowledge_node_id=nodes[node_code].id,
                relation_type=relation_type, required_level=required_level, weight=weight,
            ))

    for res_code, node_code, level, weight, evidence in RESOURCE_KNOWLEDGE_LINKS:
        exists = db.scalar(select(ResourceKnowledgeLink).where(
            ResourceKnowledgeLink.resource_id == resources[res_code].id,
            ResourceKnowledgeLink.knowledge_node_id == nodes[node_code].id,
        ))
        if not exists:
            db.add(ResourceKnowledgeLink(
                resource_id=resources[res_code].id, knowledge_node_id=nodes[node_code].id,
                coverage_level=level, weight=weight, evidence_strength=evidence,
            ))

    for res_code, cap_code, level, weight, evidence in RESOURCE_CAPABILITY_LINKS:
        exists = db.scalar(select(ResourceCapabilityLink).where(
            ResourceCapabilityLink.resource_id == resources[res_code].id,
            ResourceCapabilityLink.capability_id == capabilities[cap_code].id,
        ))
        if not exists:
            db.add(ResourceCapabilityLink(
                resource_id=resources[res_code].id, capability_id=capabilities[cap_code].id,
                contribution_level=level, weight=weight, evidence_strength=evidence,
            ))

    db.commit()
    return {
        "knowledge_nodes": len(nodes),
        "capabilities": len(capabilities),
        "resources": len(resources),
    }


def to_float(value: Decimal | float | int | None) -> float:
    return float(value or 0)
