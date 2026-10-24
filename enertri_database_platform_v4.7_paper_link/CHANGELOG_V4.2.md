# EnerTri V4.2 Changelog

发布日期：2026-08-07

## 阻断项修复

- 移除 Web 进程内 `ThreadPoolExecutor`。任务改由独立数据库 Worker 原子抢占，支持 `worker_id`、尝试次数、心跳、租约、最后抢占时间和任务超时。
- Web 启动不再执行任务恢复、默认数据初始化或迁移审计；新增一次性 `scripts/bootstrap.py`，Docker Compose 拆分为 `init`、`backend`、`worker`。
- `running` 任务仅在租约过期后判定中断；`queued` 任务由 Worker 持续抢占，不因 Web 重启永久滞留。
- 已有 `system_admin` 账户只允许系统管理员修改；最后一个有效系统管理员不可降级/停用；高权限修改要求用户名二次确认并写专用审计事件。
- 权限点在接口层落地：`task.own.cancel`、`task.other.manage`、`file.other.download`、`user.role.manage`、`data.export`。查看他人任务不再隐含重试/取消权限。
- 上传改为扩展名 + MIME + 魔数 + 专用解析器复合校验。PDF、OOXML/ZIP、图片、视频均执行内容级验证；无效文件进入隔离区并标记 `failed`。
- 旧数据库 baseline 识别改为结构指纹校验，输出字段/类型/约束/索引差异；不完全匹配拒绝 stamp；生产首次旧库升级要求显式确认参数。

## 文献与论文知识系统

- 新增统一文献适配协议与 OpenAlex/Crossref 适配器。
- 新增跨来源文献标准化和去重，保留每个来源的 provenance。
- 新增知识库模型：个人、课题组、项目、企业、公共术语；支持团队检索、AI 使用、导出、保留原文策略。
- 新增 PDF 论文流水线：验证、文本层/逐页解析、OCR 兜底、章节、表格、图片/图注、参考文献、分块、向量化、结构化阅读。
- 新增页码级证据模型：页面、章节、表格、图片、分块与自动结论均可回溯原文。
- 新增论文问答 API 与界面，答案返回页码、章节、原文片段和相关度，支持点击证据定位 PDF 页面。

## 前端验收页

- 多来源文献检索及跨源去重状态。
- 五级知识库及数据使用策略。
- PDF 原文与结构化结果并排阅读。
- 表格提取结果。
- 论文问答与页码证据定位。
- 任务中心显示 Worker、尝试次数、超时；文件中心显示声明 MIME/检测 MIME 与下载权限。

## Docker build hotfix (2026-08-07)

- Pin backend base image from mutable `python:3.12-slim` to `python:3.12-slim-bookworm`.
- Add APT retry/timeout policy and optional `APT_MIRROR` / `APT_SECURITY_MIRROR` build arguments.
- Remove unnecessary runtime `build-essential` and `curl` packages to reduce APT download size and build time.
- Explicitly install `tesseract-ocr-eng` for the default `OCR_LANG=eng` configuration.
- `init` / `backend` / `worker` now share the same tagged backend image/build definition in Compose.
- Add `.env.docker.example` with official-mirror and mainland-China mirror examples.
