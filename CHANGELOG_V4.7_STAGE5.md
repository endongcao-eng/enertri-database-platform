# EnerTri V4.7 Stage 5

## 目标

把 V4.6 的“目标 → 缺口 → 推荐”推进为“计划 → 执行 → 证据 → 核验 → 画像重算”的动态科研成长闭环。

## 数据库

- Alembic revision：`v4_7_dynamic_development_loop`。
- 新增 `development_plan_items`：课程、书籍、科研任务、论文、科研项目五类执行项。
- 新增 `development_snapshots`：保存目标匹配基线、完成节点后的匹配/能力/知识/证据可信度快照。

## 后端

- 新增 `/api/development-execution/goals/{goal_id}/recommendations`。
- 新增 `/api/development-execution/goals/{goal_id}/roadmap/generate`。
- 新增 `/api/development-execution/goals/{goal_id}/roadmap`。
- 新增 `PATCH /api/development-execution/items/{item_id}`。
- 五类资源统一进入一条路线：课程、专业书、内部论文知识库、科研实践、可参与项目。
- 完成标准课程/书籍/科研任务时自动生成 `student_evidence` 待核验证据。
- V4.7 自动完成记录在未核验前使用 0.35 的较低可信系数；教师核验后才升级为高可信证据。
- 继续保留 V4.6 缺口解释和先修关系，不允许“完成按钮”直接写入能力分。

## 前端

- 新增“成长执行闭环”入口。
- 显示路线执行进度、当前目标匹配、待核验证据数量、相对基线变化。
- 按阶段展示五类执行项，并支持开始、完成和完成后证据提示。
- 展示成长快照，便于老师观察“做了什么以后，知识/能力发生了什么变化”。

## 实际验收

演示学生“芯片热管理与微纳热输运成长目标”：

- 路线项：10 个；五类资源均有覆盖。
- 完成项：`芯片热管理与电子封装热设计`。
- 路线执行进度：0% → 10%。
- 待核验证据：1 → 2。
- 快照：1 → 2。
- 目标匹配：76.5% → 80.6%（临时变化）。
- 证据可信度：80.7% → 72.1%，明确反映新增证据尚未核验。
- 浏览器渲染验收：console/page errors = 0。

## 回归

- V4.1/V4.2 foundation：5/5。
- V4.3：2/2。
- V4.4：3/3。
- V4.5：3/3。
- V4.6：3/3。
- V4.7：3/3。
- Smoke Matrix：1/1。
