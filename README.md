> 网页试用部署准备版（2026-09-10）：请优先阅读 [架构审查](review/ARCHITECTURE_REVIEW.md)、[部署手册](deploy/DEPLOYMENT.md)、[Railway 部署](deploy/RAILWAY_DEPLOYMENT.md) 和 [本次验证](review/VALIDATION.md)。当前尚未通过公网放行门槛；下文原版本说明保留作历史参考，演示账号仅用于开发环境。

# EnerTri 科研与焊接智能平台 V4.7 · 第五阶段

EnerTri V4.7 第五阶段把 V4.6 的“目标 → 缺口 → 推荐”继续推进为可执行、可追踪、可回流的科研成长闭环。课程、专业书、论文知识库、科研实践和可参与项目进入同一条个人路线图；完成标准学习资源后系统只生成低可信待核验证据，教师核验后才升级为高可信证据，并回流 V4.4 个人科研画像重新计算目标匹配。

当前数据库目标 revision：`v4_7_dynamic_development_loop`。

## V4.7 第五阶段：科研成长执行闭环

```text
V4.6 目标知识/能力缺口
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

第五阶段新增：

- `development_plan_items`：保存目标下的课程、书籍、科研任务、论文和科研项目执行项、阶段、优先级、状态与进度；
- `development_snapshots`：保存目标匹配基线与每次完成动作后的能力/知识准备度快照；
- `/api/development-execution/goals/{id}/recommendations`：统一输出五类推荐；
- `/api/development-execution/goals/{id}/roadmap`：读取动态成长路线；
- `/api/development-execution/goals/{id}/roadmap/generate`：把推荐固化为可执行路线；
- `/api/development-execution/items/{id}`：更新开始、进度、完成或跳过状态；
- 标准资源完成时自动生成 `student_evidence` 待核验记录，但 V4.7 自动记录仅按较低可信权重参与临时画像，避免“点完成 = 直接获得高能力分”；
- 内部论文推荐只从系统已有 `publications`/演示文献目录匹配，不伪造外部论文事实；外部最新论文仍应走 V4.2 文献检索模块；
- 前端新增“成长执行闭环”入口，展示五类路线、执行进度、待核验证据、目标匹配变化和成长快照。

实际验收中，演示学生“芯片热管理与微纳热输运成长目标”生成 10 个路线项，五类资源全部覆盖。完成“芯片热管理与电子封装热设计”后：路线进度从 0% → 10%，待核验证据从 1 → 2，成长快照从 1 → 2；目标匹配由 76.5% 临时变化为 80.6%，同时证据可信度从 80.7% 降至 72.1%，明确提示该提升仍等待教师核验。

## V4.6 第四阶段：学生选课 / 成长路径与教师新方向差距分析

V4.6 将 V4.5 项目需求模型抽象为统一“目标能力模型”。学生输入目标科研方向后，系统从个人画像反推知识/能力缺口，并按缺口闭合程度、标准证据强度和先修知识准备度排序课程、专业书与科研实践；教师输入新课题方向后，可同时得到自身知识缺口、学习资源、论文检索主题，以及能够补足当前短板的学生。

新增 `development_goals`，以及 `/api/development-planning/*` 目标预览、保存、分析接口；前端入口为“成长与方向规划”。


## V4.5 第三阶段：项目需求能力模型与科研人才智能匹配

```text
项目名称 / 项目说明
        ↓
能力要求 + 知识要求 + 等级 + 权重 + 关键项
        ↓
V4.4 学生证据画像逐项对齐
        ↓
个人匹配 / 缺口解释 / 证据可信度
        ↓
2–4 人互补团队推荐 + 职责建议
```

第三阶段新增：

- `research_projects`：科研项目需求；
- `project_capability_requirements`：项目能力要求；
- `project_knowledge_requirements`：项目明确知识要求；
- `/api/project-matching/draft-requirements`：从课题文本生成可解释需求草案，返回命中关键词；
- `/api/project-matching/projects/{id}/matches`：按项目要求与个人证据画像计算候选学生；
- `/api/project-matching/projects/{id}/teams`：按每项要求由团队最合适成员承担的方式推荐互补团队；
- 前端新增“项目人才匹配”，展示项目模型、候选排序、逐项满足率、主要缺口、证据可信度和团队职责；
- 完整候选排名仅教师/管理员侧可见，普通学生不能横向读取他人画像。

当前演示项目“基于机器学习的材料热物性预测”实际计算中，最高个人匹配为 78.2%，推荐三人团队为 98.0%。团队高分同时保留“材料热物性”等剩余知识缺口，不用总分掩盖未满足要求。

## V4.4 第二阶段：学生个人科研证据画像

```text
课程成绩 / 专业书阅读 / 科研项目任务
                ↓
        个人证据有效度
    + 自报 / 待核验 / 已核验
                ↓
          个人知识体系
                ↓
直接能力证据 + 知识准备度
                ↓
科研能力画像 + 知识缺口 + 导师评判
```

第二阶段新增：

- `student_evidence` 个人证据账本；
- 课程成绩、阅读完成度、项目独立度、成果质量、导师评分与核验状态；
- `/api/research-profile/profile` 个人知识体系与科研能力画像；
- `/api/research-profile/evidence` 个人证据录入；
- `/api/research-profile/evidence/{id}/verify` 老师核验；
- 普通学生只能查看自己，管理员/老师可切换查看学生；
- 前端新增“个人科研画像”，同时展示综合能力、直接证据、知识准备度与完整证据链；
- 自动识别影响当前能力链路的知识缺口，并给出标准库补齐资源。

能力分不允许学生直接填写。没有直接科研任务证据时，知识准备度只能按较低比例折算，避免“学过 = 会独立科研”的误判。

## V4.3 第一阶段：科研知识与能力标准库（继续作为底座）

新增四层标准结构：

```text
课程 / 专业书 / 项目任务
          ↓
      标准知识节点
   ↙ 先修 / 组成 / 相关 ↘
科研能力节点 ← 知识要求 / 支撑关系
          ↓
第二阶段：个人证据画像（已实现）
          ↓
第三阶段：项目人才匹配（已实现）
```

第一阶段新增：

- `knowledge_nodes`：标准知识点，可通过 `linked_term_id` 与原术语库对齐；
- `knowledge_relations`：知识点之间的先修、组成、相关、使能关系；
- `capabilities`：统一科研能力定义及 1–5 级能力量表；
- `capability_knowledge_links`：每项能力需要/受哪些知识支撑以及要求等级；
- `learning_resources`：统一课程、专业书和项目任务三类来源；
- `resource_knowledge_links`：来源到知识点的覆盖等级、权重和证据强度；
- `resource_capability_links`：来源到能力的贡献等级、权重和证据强度；
- `/api/capability-standards/simulate`：对选中的课程/书籍/项目任务执行标准映射演算，返回可追溯知识与能力路径；
- 前端新增“能力标准库”入口，可直接勾选来源并查看映射结果。

当前演算分数仍明确表示“标准映射强度”，不是学生能力分；学生成绩、项目独立度、导师评价、成果质量等个人证据已经由 V4.4 第二阶段叠加到“个人科研画像”。

## V4.2 核心架构（继续保留）

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

## 默认演示账号

```text
管理员：admin / admin123
普通学习用户：student / 123456
```

正式上线必须修改默认密码、数据库密码和 `SECRET_KEY`。

## 本阶段实际运行验收

V4.4 第二阶段实际完成并验证：

- 新数据库升级链：`v4_0_baseline → v4_1_foundation → v4_2_knowledge_system → v4_3_capability_standard_library → v4_4_student_research_profile → v4_5_project_talent_matching → v4_6_development_planning → v4_7_dynamic_development_loop`；
- 第二阶段个人科研画像专项测试 3/3 通过；
- 第一阶段能力标准库回归测试 2/2 通过；
- 原 V4.2 foundation/blocker 回归测试 5/5 通过；
- 原 V4 smoke matrix 1/1 通过；
- Python compile 与 JavaScript syntax 检查通过；
- 实际 API 运行版本 `4.5.0`；
- 演示学生默认 5 条个人证据，其中 3 条已核验，证据可信度 80.7%；
- 个人知识覆盖 12/15，覆盖率 80.0%；
- 实际能力画像：数值建模与求解 76.0、传热理论分析 74.4、Python 科研计算 74.0、科研数据分析 57.6；
- 系统识别出科研文献方法、机器学习基础、偏微分方程等当前知识缺口；
- 管理员/老师实际运行页面可直接看到学生证据、填写导师评分/成果质量并执行核验；
- 浏览器实际运行 console error 0、page error 0。

### V4.4 第二阶段运行预览

- `demo_outputs/v4_4_stage2_runtime_top.png`
- `demo_outputs/v4_4_stage2_evidence_teacher.png`
- `demo_outputs/v4_4_stage2_knowledge_system.png`
- `demo_outputs/v4_4_stage2_capability_matrix.png`
- `demo_outputs/v4_4_stage2_runtime_full.png`
- `demo_outputs/v4_4_stage2_runtime_preview.json`
- `demo_outputs/v4_4_stage2_profile_api.json`

第一阶段标准映射演算截图继续保留，用于验证“标准底座”和“个人画像”使用的是同一套知识/能力定义。

## 详细文档

- `docs/20_V4.4_学生科研能力个人证据画像_第二阶段.md`
- `CHANGELOG_V4.4_STAGE2.md`
- `docs/19_V4.3_科研知识与能力标准库_第一阶段.md`
- `CHANGELOG_V4.3_STAGE1.md`
- `docs/16_V4.2_阻断项修复与任务架构.md`
- `docs/17_V4.2_文献论文知识系统.md`
- `docs/18_V4.2_部署迁移与验收.md`
- `CHANGELOG_V4.2.md`
- V4.1 文档保留在 `docs/14_*`、`docs/15_*` 与 `CHANGELOG_V4.1.md`，用于历史追溯。
