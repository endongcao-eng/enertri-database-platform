> 网页试用部署准备版（2026-09-10）：请优先阅读 [架构审查](review/ARCHITECTURE_REVIEW.md)、[部署手册](deploy/DEPLOYMENT.md)、[Railway 部署](deploy/RAILWAY_DEPLOYMENT.md) 和 [本次验证](review/VALIDATION.md)。当前尚未通过公网放行门槛；下文原版本说明保留作历史参考，演示账号仅用于开发环境。

# EnerTri 科研与焊接智能平台 V4.7

当前数据库目标 revision：`v4_7_dynamic_development_loop`。

## 科研成长执行闭环

```text
目标知识/能力缺口
          ↓
课程 + 专业书 + 内部论文知识库 + 科研实践 + 可参与项目
          ↓
个人执行路线图（计划中 / 进行中 / 已完成 / 跳过）
          ↓
完成标准资源 → 低可信待核验证据
          ↓
教师核验 → 高可信个人证据
          ↓
个人科研画像重算 → 目标匹配快照 → 下一轮路线
```

## 核心架构

```text
Browser / API Client
        ↓
Gunicorn + FastAPI Web (可多 Worker)
        ↓ 仅创建 queued 任务
PostgreSQL workspace_tasks
        ↓ 原子抢占 / 租约 / 心跳
Independent Task Worker
        ↓
PDF / OCR / Tables / Vector / QA / Artifacts
```

Web Worker 不再创建 `ThreadPoolExecutor`，也不再在启动时执行任务恢复、默认数据初始化或迁移审计。Docker Compose 使用一次性 `init` 服务完成迁移与初始化，长任务由独立 `worker` 服务消费数据库队列。

## 阻断项修复

### 1. 多 Gunicorn Worker 与异步执行器冲突

- 移除 Web 进程内线程池。
- `workspace_tasks` 新增 `worker_id`、`attempt_count`、`heartbeat_at`、`lease_expires_at`、`last_claimed_at`、`timeout_seconds`。
- PostgreSQL Worker 通过事务和 `FOR UPDATE SKIP LOCKED` 原子抢占 `queued` 任务。
- 只有租约过期的 `running` 任务才会被恢复为失败；其他 Worker 正在执行的任务不会被误判。
- `queued` 任务本身即数据库队列，不依赖 Web 重启时“重新提交”。
- `bootstrap.py` 统一迁移、默认数据、过期租约恢复、清理与迁移审计，避免多个 Web Worker 重复执行。

### 2. system_admin 保护

- 普通管理员不能修改已有 `system_admin`，包括降级、停用和其他属性变更。
- 只有 `system_admin` 能授予 `system_admin`。
- 最后一个有效 `system_admin` 不能被降级或停用。
- 高权限账户变更要求 `confirmation=<目标用户名>` 二次确认。
- 高权限变更写入 `security.privileged_user.updated` 专用审计事件。

### 3. 权限点真正落地到接口

新增/落实：

- `task.own.cancel`
- `task.other.manage`
- `file.other.download`
- `user.role.manage`
- `data.export`

`task.other.view` 只代表查看权限，不再隐含重试或取消；审稿专家可查看他人任务，但默认不能重试、取消或下载他人文件。

### 4. 内容级文件安全校验

上传不再只看扩展名。V4.2 同时检查扩展名、检测 MIME、魔数和格式解析：

- PDF：魔数 + pypdf 可打开/可读页数。
- DOCX/PPTX/XLSX/ZIP：ZIP 结构、CRC、路径穿越、条目数、压缩比、OOXML 必需条目。
- 图片：Pillow `verify()` 与尺寸读取。
- 视频：ffprobe 必须成功并识别真实 video stream。
- JSON/XML/文本：执行解析或编码验证。

无法解析的文件进入 `quarantine/`，文件解析状态和相关任务状态均为 `failed`。

### 5. 严格旧库 baseline 识别

对“非空且没有 alembic_version”的数据库，系统会检查关键表、字段、类型族、约束、索引和新版本特征字段，并输出结构差异报告。不完全匹配时拒绝自动 stamp。生产旧库首次升级还需要人工备份/核验并显式设置：

```env
V4_BASELINE_CONFIRM=I_HAVE_VERIFIED_V4_0_BACKUP
```

## 文献与论文知识系统

### 多来源文献适配

`publication_service.py` 提供统一 Provider 协议：

- `search_publications()`
- `get_publication()`
- `get_citations()`
- `get_references()`
- `get_author()`
- `get_fulltext_link()`

当前实现 OpenAlex 与 Crossref。主文献统一保存 DOI、标题、作者、机构、摘要、关键词、期刊、年份、引用量、开放获取状态和更新时间；`publication_sources` 保存来源 provenance 与原始 payload。

### 文献去重

按以下优先级匹配：

1. DOI 完全一致；
2. 标准化标题一致；
3. 标题 + 第一作者相似；
4. 年份和期刊辅助判断。

多个来源命中同一论文时只保留一条 `publications` 主记录，并追加来源记录。

### PDF 论文解析流水线

```text
文件校验
→ 文本层检测 / 逐页解析
→ OCR 兜底
→ 标题 / 摘要 / 章节
→ 表格
→ 图片 / 图注
→ 参考文献
→ 按章节和物理页分块
→ 本地向量化
→ 结构化阅读
```

数据模型包含 `knowledge_bases`、`knowledge_documents`、`knowledge_pages`、`knowledge_tables`、`knowledge_figures`、`knowledge_chunks`。关键事实与问答证据保存物理页码、章节与原文片段。

默认向量是无外部依赖的确定性本地哈希向量，用于保证离线 V4.2 可完整运行；向量已与证据模型解耦，后续可替换为 pgvector + embedding service。

### 五级知识库

- 个人知识库 `personal`
- 课题组知识库 `group`
- 项目知识库 `project`
- 企业知识库 `enterprise`
- 公共术语知识库 `public_terms`

可配置团队检索、AI 使用、导出、保留原文；论文还保留保密等级和是否允许外部 AI。

### 论文问答

`POST /api/knowledge/documents/{id}/qa` 基于已解析证据检索。中文问题会扩展为对应英文检索意图，答案返回：

- 简洁答案；
- 置信度；
- PDF 物理页码；
- 章节；
- 原文 excerpt；
- 相关度；
- `#page=N` 原文定位链接。

已验证的问题包括“激光功率是多少？”、“最高抗拉强度对应哪组参数？”、“使用了什么母材？”、“作者如何解释气孔形成？”。

## 启动方式

### Docker Compose 本地版

```bash
docker compose -f docker-compose.local.yml up -d --build

如果 Docker Desktop 在 `apt-get update/install` 阶段长时间超时，可在项目根目录创建 `.env` 并加入：

```env
APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
```

随后执行 `docker compose -f docker-compose.local.yml build --no-cache --progress=plain backend` 获取完整构建日志，再执行 `docker compose -f docker-compose.local.yml up -d`。V4.2 后端镜像固定为 `python:3.12-slim-bookworm`，并为 APT 设置了重试和超时。
```

启动拓扑：`db → init → backend + worker → caddy`。

访问：

```text
平台：http://127.0.0.1:8080
API 文档：http://127.0.0.1:8080/api/docs
```

### 非 Docker 开发

```bash
cd backend
cp .env.example .env
python scripts/bootstrap.py
```

分别启动 Web 与 Worker：

```bash
uvicorn app.main:app --reload
python scripts/task_worker.py
```

生产环境必须保持：

```env
TASK_EXECUTION_MODE=database_worker
```

`TASK_EXECUTION_MODE=inline` 仅用于自动化测试。


