# 百人试用部署操作手册

> 如果使用 Railway 且不使用 Docker Desktop，请先阅读 [`RAILWAY_DEPLOYMENT.md`](RAILWAY_DEPLOYMENT.md)。本文件保留 Docker Compose 部署流程。

本文件针对现有 FastAPI/PostgreSQL/本地文件卷架构。当前状态：**准备候选版，不可直接公网放行**。先阅读 `review/ARCHITECTURE_REVIEW.md` 中 P0 清单和 `review/SECURITY_AND_OPERATIONS_RUNBOOK.md`。没有创建公网网站、域名或云服务器。

## 1. 上线前必须通过

- 修复并扫描 Python/系统依赖漏洞，生成经过回归的生产锁文件和固定镜像版本；当前 requirements 有已知受影响版本。
- 在干净构建机执行最终 `pip-audit -r backend/requirements.txt`；本地运行时无法完成远程索引扫描，不能把源码版本变更当成扫描证明。
- 实现登录限流、账号改密/重置和任务/AI/磁盘配额，验证跨用户访问隔离。
- 确认试用内容、100 名具名账号、数据使用/删除与外部 AI 传输规则；首批不要开放商业仿真执行。
- 准备域名、DNS、Linux 主机、Docker Engine + Compose 插件；4 vCPU/8GB 只是初始压测配置。
- 以下命令均在项目根目录执行；命令中的域名是示例，必须替换为自己的预发布域名。

## 2. 环境配置

复制模板，不要提交密钥文件：

```bash
cp deploy/trial.env.example .env
cp backend/.env.production.example backend/.env
chmod 600 .env backend/.env
```

使用密码管理器生成独立随机凭据。根目录 `.env` 填 `SITE_DOMAIN`（仅域名）及不少于 32 位十六进制随机 `DB_PASSWORD`。`backend/.env` 中数据库 URL 必须使用同一个数据库密码；SECRET_KEY 至少 32 字符；初始管理员密码至少 16 字符，不超过 bcrypt 的 72 个 UTF-8 字节。

`CORS_ORIGINS` 填同一 HTTPS 源。所有 media/artifacts/workspace/files 路径均指向 `/app/media` 下目录。AI key 默认留空，商业仿真执行默认 false。不能把生产配置改为 development 来跳过检查。

```bash
python3 scripts/preflight.py
```

preflight 不打印秘密值，也不连接服务器。它仅校验配置，不能替代漏洞、证书、权限和压测验收。模板未填写时应返回 BLOCKED。

## 3. 在隔离服务器构建与验收

确认上面的 P0 条件已完成再启动预发布。数据库用新卷，上传目录使用新环境目录；源码包附带的历史示例 uploads 不应不加审核地复制到正式试用数据卷。可以先将它移至离线归档位置，再创建空 uploads。

```bash
docker compose config --quiet
docker compose build
docker compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile
docker compose up -d
```

顺序是 DB 健康 → init 执行迁移/创建管理员 → backend/worker → Caddy。Caddy 自动申请证书，需要正确 DNS、网络和 80/443 入站。保持数据库/API 不对公网映射；限制 SSH 到管理员网络。

新生产库只创建管理员，不导入演示学生、课程、画像、项目或路线。先使用管理员导入经过审核的术语 Excel，并配置真实标准资源、能力映射、项目需求；演示 seed 不代表真实数据，应仅在开发环境用来复现页面。

```bash
docker compose ps
docker compose logs --tail=100 init backend worker
curl --fail https://trial.example.org/api/health
curl --fail https://trial.example.org/api/ready
```

`/api/ready` 核对数据库和 revision；必须另外检查 Worker、上传和任务完成/下载。不得将生产 .env 或含密钥的 compose 展开结果复制到工单。

0010 迁移会让已有账号的旧 token 失效并要求改密；请预先通知用户并准备临时凭据。若升级中途失败，保留数据库备份和旧镜像，先在隔离副本修复迁移，不要重复执行未知状态的 SQL。

## 4. 试用账号

准备受限访问的 CSV，列名 `username,display_name,password,role`，每人独立随机密码；role 默认为 learning_user。不要给学生 researcher 权限来绕过 AI 门槛，是否开放 AI 应按试用范围明确分配。

```bash
chmod 600 trial-accounts.csv
docker compose exec -T backend python scripts/create_trial_users.py < trial-accounts.csv
```

导入最多 150 条，不覆盖已存在账号，不批量创建管理员。重复或不合法输入使整批回滚。脚本没有替你向任何人发送密码。通过受控渠道分配个人凭据，并按组织规则安全处置 CSV。自助首次改密/找回和管理员重置仍需开发，未完成前不向百人放行。

## 5. 必做验证

安装项目依赖后：

```bash
python scripts/run_regression.py
```

先在预发布上运行只读探针：

```bash
python scripts/load_probe.py https://trial.example.org --users 20 --requests 400
python scripts/load_probe.py https://trial.example.org --users 100 --requests 1000
```

外部 AI 费用保护默认关闭。只有在供应商计价已经核对后，才在 `backend/.env` 填写 `AI_BUDGET_MODEL`、输入/输出费率并设置 `AI_BUDGET_ENABLED=true`；文件和图像外部 AI 在当前版本仍会被拒绝，避免无法可靠估算费用。

脚本报告错误率、p95/p99 和吞吐，出现错误或 p95 > 1 秒则失败。它**不覆盖登录、写操作、PDF/OCR、AI、真实思考时间和用户会话**。须另做真实账号混合负载、跨用户隔离、双 API 进程测验及多 Worker 抢占测试。没有运行结果前不得声称支持百人并发。

浏览器验收至少包括桌面和手机：登录、会话过期、搜索分页、学习记录、小测、上传、任务进度/取消/失败/下载、证据提交与核验、成长路线完成回流，检查控制台、错误提示和键盘可用性。

## 6. 备份、恢复和回滚

源码版本、数据库、uploads 必须可关联。`scripts/backup.sh` 对 SQL 和文件分别备份，**在线运行时不保证相同时间点**。维护窗口内先停止写入及 Worker，确认没有仍在执行的外部任务，再备份：

```bash
docker compose stop caddy backend worker
bash scripts/backup.sh
docker compose start backend worker caddy
```

备份失败时先修复和重做，不要因为启动成功就忽略。SQL 中含个人数据及散列密码，文件备份含上传内容，应加密异机保存。按试用容忍度设定 RPO/RTO，例如 RPO 24h、RTO 2h 作为初始目标，必须演练验证。

恢复必须先在空的隔离数据库和空 uploads 上演练，不能往已有数据的生产库盲目执行 SQL：

```bash
bash scripts/restore_db.sh backups/enertri_实际时间.sql
```

配对恢复同一轮 uploads 归档，然后检查文件哈希、登录、证据/任务链和受控下载。不要使用 `docker compose down -v` 作为常规重启命令。

新增 0009 只增加 quiz_sessions；回退到旧应用时应安排维护窗口并评估旧应用的双进程测验缺陷，不要机械 downgrade。涉及真实业务数据迁移时优先使用经演练的备份恢复与固定旧镜像，保留回滚所需文件版本。

## 7. 运行责任与成本

指定唯一值班/联系渠道，监控 API 延迟/5xx、数据库连接、磁盘余量、备份年龄、Worker 心跳、队列长度/等待时间、任务失败及 AI 费用。现有 queue_stats 不是完整监控平台；容器 healthcheck 也不会自动恢复所有 unhealthy 状态。

分批放行：5 人内部 → 20 人 → 100 人。扩 Worker 前先测数据库连接和磁盘/OCR竞争；多个 Worker 会增加外部调用并发与费用。共享文件卷是单机方案，多主机扩展需要重新设计共享存储与任务部署。
