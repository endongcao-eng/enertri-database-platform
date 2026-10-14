> 网页试用部署准备版（2026-09-10）：请优先阅读 [架构审查](review/ARCHITECTURE_REVIEW.md)、[部署手册](deploy/DEPLOYMENT.md)、[Railway 部署](deploy/RAILWAY_DEPLOYMENT.md) 和 [本次验证](review/VALIDATION.md)。当前尚未通过公网放行门槛；

# EnerTri 科研与焊接智能平台 V4.7

当前数据库目标 revision：`v4_7_space_energy_literature`。

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

## 文献与论文知识系统

### 多来源文献适配

`publication_service.py` 提供统一 Provider 协议：

- `search_publications()`
- `get_publication()`
- `get_citations()`
- `get_references()`
- `get_author()`
- `get_fulltext_link()`

当前实现空间能源平台、OpenAlex 与 Crossref。论文目录以空间能源平台为主库，EnerTri 通过后端代理实时读取；空间能源后端不可用时，目录 API 返回不可用状态，不回退到 EnerTri 本地的旧论文记录。PostgreSQL 中的 `space_energy_literatures` 表按主库 `literatures` 字段结构建立为读穿镜像，只在主库请求成功后更新。科研成长计划仍可使用 EnerTri 原有的 `publications` 外部检索记录。

Railway 和 Docker 部署使用 `SPACE_ENERGY_API_BASE_URL` 指定空间能源平台的 API 根地址，默认示例为 `https://114514191981061285174648.dpdns.org`。EnerTri 后端会调用 `/api/literatures` 与 `/api/search`；访问者仍需先登录 EnerTri。论文库每 15 秒检查主库连通状态，检测到主库离线后清空页面中的目录结果。用户上传的 PDF/DOCX、逐页解析结果和证据索引继续保存在 EnerTri 的知识库中。

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

表格识别会同时尝试 PDF 绘制线、文本对齐和混合版式策略，并以 pdfplumber 作为补充，按页面位置、表格内容和识别质量去重；表格标题按其在页面中的垂直位置匹配，避免同一页多个表格全部绑定到第一个标题。结构化结果会保存表格数量和覆盖页码诊断，便于对照原文核验。原文仍保留在文件卷时，论文详情页可以点击“重新解析”应用新的识别策略。

### 能源动力相关性过滤

论文检索在 OpenAlex、Crossref 和空间能源主库结果合并前增加领域相关性筛选。查询会识别空间、能源、氢能、燃料电池、电池、太阳能、热管理、推进、流体、材料、焊接等概念组；结果必须同时满足查询概念和至少一个能源动力工程概念，返回结果附带相关度分数。这样“空间 能源”不会把只含“空间”一词、但属于茶文化等其他学科的论文带入结果。

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


