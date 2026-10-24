# EnerTri V4.1 变更记录

发布日期：2026-08-05

## Added

- Alembic 迁移框架、V4.0 基线迁移和 V4.1 增量迁移。
- `workspace_tasks`、`workspace_files`、`task_files`、`task_events`、`audit_logs`、`ai_usage_records`、`knowledge_documents`、`knowledge_chunks`、`simulation_artifacts`。
- 论文解析、PPT 生成、视频分析和仿真输入包生成异步任务处理器。
- 任务中心、文件管理和管理员审计/迁移页面。
- 文件 SHA-256、重复检测、随机存储名、保密等级、外部 AI 开关和自动清理。
- 六类角色和基于权限点的接口控制。
- 用户角色管理、迁移状态和审计日志 API。

## Changed

- 版本由 4.0.0 升级为 4.1.0。
- 数据库结构修改以 Alembic revision 为唯一正式入口。
- Docker 后端先迁移后启动。
- 旧 `student` 角色迁移为 `learning_user`；旧 `assistant_jobs` 保留用于 V4.0 接口兼容。
- 外部 AI、商业仿真和工艺审批接口改为权限点校验。
- 论文解析、PPTX、视频分析与仿真输入包前端入口接入统一任务中心。

## Compatibility

- 保留 V4.0 同步科研、焊接、遥测和仿真输入包接口。
- V4.0 34 项离线回归矩阵全部通过。
- 旧数据库可自动标记 `v4_0_baseline` 后增量升级，不要求清空业务数据。

## Known boundaries

- 当前后台执行器使用进程内线程池，适合 V4.1 基础验收和单机部署；后续高并发视频/仿真任务应替换为 Redis + Celery/RQ 或独立调度服务。
- 任务取消采用协作式取消，正在执行的第三方阻塞调用需要后续增加进程级终止与超时隔离。
- 知识文档/分块和仿真成果表已建模，完整检索、向量化与商业求解器成果采集将在后续阶段接入。
