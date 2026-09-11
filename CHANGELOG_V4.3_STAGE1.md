# EnerTri V4.3 Stage 1 Changelog

发布日期：2026-08-28

## 目标

第一阶段把 V4.2 的“术语 + 文献 + 论文证据知识系统”向科研人才能力分析底座扩展，先统一定义：课程、专业书、项目任务分别覆盖哪些知识点，以及这些知识点和实践能够贡献哪些科研能力。

本阶段刻意不直接计算“学生能力分”。个人成绩、项目独立完成度、导师评价、成果质量和时效等证据留到第二阶段。

## 数据模型

新增 7 张表：

- `knowledge_nodes`
- `knowledge_relations`
- `capabilities`
- `capability_knowledge_links`
- `learning_resources`
- `resource_knowledge_links`
- `resource_capability_links`

`knowledge_nodes.linked_term_id` 可以直接绑定现有 `terms` 词条，使原术语库成为知识体系标准化命名基础。

## 标准关系

知识点之间支持：

- `prerequisite`：先修
- `part_of`：组成
- `related`：相关
- `enables`：使能

能力与知识支持：

- `requires`：能力核心要求
- `supports`：能力支撑知识

课程/专业书/项目任务到知识和能力的映射同时保存：等级、权重、证据强度和备注，后续个人证据计算可以继续复用。

## API

新增 `/api/capability-standards/*`：

- `GET /overview`
- `GET /knowledge-nodes`
- `GET /capabilities`
- `GET /resources`
- `GET /resources/{id}`
- `GET /graph`
- `POST /simulate`
- 管理员创建知识点、能力、资源、知识关系及三类映射关系接口

普通登录用户可读取标准库和执行映射演算；维护动作仍需要管理员权限。

## 前端

顶部导航新增“能力标准库”。页面包括：

1. 第一阶段标准化主链路；
2. 课程、专业书和项目任务列表；
3. 可多选的标准映射演算；
4. 按领域组织的知识体系节点与先修关系；
5. 科研能力标准及其知识要求；
6. 映射结果的来源证据路径。

## 默认演示标准

当前种子数据包含：

- 15 个知识节点；
- 8 个科研能力节点；
- 6 个课程/专业书/项目任务；
- 64 条关系和映射。

演示覆盖传热、微纳热科学、数值方法、Python 科研计算、机器学习、科研方法与焊接工程。

## 实际运行验收

- fresh migration 至 `v4_3_capability_standard_library`：通过；
- V4.3 Stage 1 tests：2/2 通过；
- V4.2 foundation/blocker regression：5/5 通过；
- V4 smoke matrix：1/1 通过；
- Python compile：通过；
- JavaScript syntax：通过；
- 浏览器实际渲染：通过，console error 0；
- 运行 API 版本：`4.3.0`。

实际选择“传热学 + Micro/Nanoscale Heat Transfer + 微纳热输运数值模拟任务”时，映射结果包括：

- 知识：微纳尺度传热 87.1、Python 科学计算 74.4、声子输运 71.3；
- 能力：传热理论分析 79.7、Python 科研计算 77.1、数值建模与求解 73.6。

这些值是标准映射强度，不是个人能力评分。
