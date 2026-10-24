# 安全与运维实施顺序

本文件把“可由代码完成”和“必须由部署负责人完成”分开。顺序不能颠倒：依赖漏洞和匿名入口未关闭时，不应先邀请试用用户。

## 0. 先冻结放行

在完成第 1–5 步前，保持域名只允许内部访问，`AI_BUDGET_ENABLED=false`，`SIMULATION_EXECUTION_ENABLED=false`，不导入真实论文、学生材料或 API key。保存当前镜像、数据库备份和源码版本，保证可以回退。

## 1. 依赖安全升级

### 已由本项目完成

- `python-multipart` 从 0.0.9 升至 0.0.32，越过已确认的 `<0.0.18` DoS 修复边界。
- JWT 从 `python-jose` 切换至 `PyJWT==2.13.0`，移除 ecdsa/rsa 依赖链。
- FastAPI/Pydantic/Starlette/python-dotenv 版本更新并通过静态编译；requirements 已固定目标版本。
- CI 增加 `pip-audit`，但当前环境没有完成最终远程索引扫描。

### 必须由部署负责人执行

1. 在干净构建机运行：

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install --upgrade pip
   .venv/bin/pip install -r backend/requirements.txt
   .venv/bin/pip-audit -r backend/requirements.txt
   ```

2. 扫描必须没有未接受的漏洞；若报告新漏洞，升级相关包、运行 `python scripts/run_regression.py`，再重新构建镜像。不要只修改容器内已安装版本而不更新 requirements。
3. 执行 `docker compose build --pull`，保存镜像 SBOM/扫描结果。镜像应固定到经过扫描的 digest；不要用 `latest` 作为生产发布标识。
4. 重点验证 multipart/PDF/OCR：上传正常 PDF、损坏 PDF、超大请求、异常 multipart boundary、压缩文档和超长页数；都应被限制、拒绝或在可控时间内失败。

## 2. 登录限流、改密和会话

### 已由本项目完成

- 登录按账号和来源地址使用数据库窗口桶限流，默认 5 次/账号、120 次/来源/15 分钟，返回 429 和 Retry-After。
- 0010 迁移使旧 token 失效并要求账号首次登录改密；改密后 token_version 递增，登出撤销全部旧 token。
- 新增 `/api/auth/password`、`/api/auth/logout`、管理员交互式 `backend/scripts/reset_password.py`。
- 试用账号脚本设置 `must_change_password=true`，不覆盖已有账号、不授予管理员角色、不输出密码。

### 必须由部署负责人执行

1. 迁移前备份数据库和文件；确认所有现有账号都能通过受控渠道获得临时密码。
2. 使用目标域名预发布环境连续错误登录，验证账号桶和来源桶均返回 429；确认 Caddy/反代不会把所有用户错误地合并为一个来源。当前应用只信任内部反代传入的 `request.client.host`，不要把后端端口暴露公网。
3. 用两个浏览器登录同一账号，改密后确认两边都失效；首次登录确认只能访问改密/登出/账号信息，完成改密后才能访问其他业务。
4. 明确账号的有效期、重置负责人和凭据发送渠道。代码不发送密码，也不代替组织的身份核验。
5. 如需 SSO、邮箱找回、MFA 或 HttpOnly Cookie，另行设计完整会话和 CSRF 方案；不要只把 Bearer token 改成 Cookie。

## 3. 任务和 AI 配额

### 已由本项目完成

- 任务创建前按用户活动任务、全局活动任务和 UTC 日次数准入；Worker 按全局/用户运行槽位抢占。
- AI 调用必须启用预算开关、指定模型和正数输入/输出费率；调用前预留用户/全局预算，调用结束记录 provider usage，失败或不确定结果不自动退款。
- 文件/图像外部 AI 暂时拒绝；本地解析/OCR仍可用，避免无法可靠估算多模态费用时产生失控账单。

### 必须由部署负责人执行

1. 先保持 `AI_BUDGET_ENABLED=false`。从提供商控制台确认准确模型、输入/输出费率、税费/组织上限，再填 `AI_BUDGET_MODEL`、`AI_INPUT_USD_PER_MILLION`、`AI_OUTPUT_USD_PER_MILLION`。
2. 设定并书面批准预算：建议试用初始每用户 1 USD/UTC 日、全局 10 USD/UTC 日、每用户 20 次/日、全局 200 次/日、用户并发 1、全局并发 2；这些是安全默认，不是产品承诺。
3. 先用测试 key 或供应商的低额度项目做 5 人灰度；对一次文本请求比较本地估算、API 返回 usage 和供应商账单，误差超过可接受范围就关闭外部 AI。
4. 观察 `ai_budget_reservations` 与供应商账单。当前预留账本是保守上限，不是会计发票；进程崩溃的预留会继续占用当日预算，需管理员在确认账单后另行清理或等待日界切换。
5. 禁止把 OpenAI/API key 写入源码、前端、日志、工单或聊天。更换 key 后重启 backend/worker 并验证旧 key 不再有效。

## 4. 权限全面验收

### 已由本项目完成

新增 `tests/test_trial_controls.py`，覆盖匿名路由、学生/科研/审核/管理员角色、文件所有权、个人画像、成长目标、个人知识库、登录、改密、登出、任务和 AI 入口。还可输出 `/tmp/enertri-permission-inventory.json` 作为路由审计底稿。

### 必须由部署负责人执行

建立至少五个隔离账号：学生 A、学生 B、科研用户、审核专家、管理员。逐项按下表操作并保存 HTTP 状态和页面截图：

| 对象 | A 自有 | B 访问 A | 科研/审核 | 管理员 |
|---|---|---|---|---|
| 文件下载/删除 | 允许 | 拒绝 | 按 `file.other.*` 明确验证 | 按管理权限允许 |
| 个人画像/证据 | 允许 | 拒绝 | 拒绝跨用户 | 允许核验 |
| 个人知识库文档 | 允许 | 404/拒绝 | 仅 `allow_team_search` 且具共享权限 | 管理权限 |
| 成长目标/路线 | 允许 | 拒绝 | 拒绝跨用户 | 允许管理 |
| 项目匹配/组队 | 拒绝普通入口 | 拒绝 | 按项目角色 | 允许 |
| AI/论文接口 | 按角色和预算 | 拒绝 | 允许但受预算 | 允许但同受预算 |
| 审计、用户角色、迁移 | 拒绝 | 拒绝 | 拒绝 | 允许 |

重点测 ID 改写（把 URL 中的 A 的 id 换成 B）、下载 URL 复用、被停用账号旧 token、跨知识库文档、导出接口和错误响应是否泄露存在性。任何“返回 200 但内容为空”都要人工确认是否符合策略，不能仅看状态码。

## 5. 备份、恢复和回滚

### 已由本项目完成

- `scripts/backup_bundle.py` 提供配对 PostgreSQL custom dump + uploads tar、SHA-256 manifest、路径安全检查和临时数据库恢复演练。
- 旧脚本不再静默忽略文件打包错误，SQL 恢复启用 `ON_ERROR_STOP`。

### 必须由部署负责人执行

1. 在维护窗口停止 Caddy、backend、worker，确认无写请求和外部 AI/仿真任务：

   ```bash
   python3 scripts/backup_bundle.py backup /secure/backups/enertri-$(date -u +%Y%m%dT%H%M%SZ)
   python3 scripts/backup_bundle.py verify /secure/backups/enertri-实际时间
   ```

2. 将备份加密复制到异机/不同故障域；备份目录权限 0700、文件权限 0600。不要把 SQL、上传包或 manifest 上传到公开文件服务。
3. 至少每月在隔离主机执行恢复演练：

   ```bash
   python3 scripts/backup_bundle.py drill /secure/backups/enertri-实际时间
   ```

   该演练会创建临时 PostgreSQL 容器，恢复后核对数据库版本、用户/术语/证据数量及每个已登记文件的哈希。它不会写入生产数据库。
4. 记录 RPO/RTO、演练耗时、失败项和责任人。初始可提出 RPO 24 小时、RTO 2 小时，但必须以实测为准。
5. 回滚应用时使用固定的旧镜像和匹配源码/迁移版本。不要对生产直接执行 `down -v`，不要在未知数据状态下盲目 `downgrade`。

## 6. 推荐放行顺序

1. 依赖扫描为零未接受漏洞，Docker 镜像可重建。
2. 新空库迁移、readiness、网关 HTTPS、私有文件路径和安全响应头通过。
3. 登录/改密/停用/限流和五角色权限矩阵通过。
4. 备份、校验、隔离恢复演练通过。
5. AI 仍关闭，5 人内部测试；之后启用已核对预算的文本 AI，再做 20 人测试。
6. 运行只读 20/100 并发探针和真实混合负载；无 5xx、配额有效、费用可对账后才邀请约 100 人。

任何一步失败都回到上一步修复，不以“用户数量少”跳过安全和恢复验收。
