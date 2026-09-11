# EnerTri Railway（Railpack，无 Dockerfile）部署说明

本目录提供不依赖 Docker Desktop 的 Railway 部署方式。Railway 使用 Railpack 构建 Python 应用，`railway.json` 强制使用 Railpack，并在部署前执行一次数据库迁移/管理员初始化。

## 拓扑和限制

- Railway PostgreSQL：保存业务数据、审计、限流桶、任务队列和 AI 预算账本。
- 一个 Railway Web service：同时运行 FastAPI/Gunicorn 和数据库 Worker。
- 一个 Railway Volume：挂载到 `/data`，保存上传文件、视频、任务产物和仿真工作目录。
- FastAPI 直接提供 `frontend_api_demo` 静态网页；不再依赖 Caddy。

当前单服务设计是为了让 Web 和 Worker 共享本地文件卷，适合约 100 人试用。不要开启多个副本；如果需要横向扩展，应先把文件和产物迁移到 S3/R2/Railway Storage Bucket，再拆分 Worker service。

## Railway 控制台创建顺序

1. 创建 Railway Project。
2. 添加 PostgreSQL service。
3. 添加 GitHub Repository service，选择项目根目录作为 Root Directory。
4. 确认该 service 的 Builder 是 Railpack，不是 Dockerfile。
5. 添加一个 Volume，挂载路径填写 `/data`。
6. 将 PostgreSQL 的 `DATABASE_URL` 通过 Railway 变量引用注入 Web service：

   ```text
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   ```

## Web service 必填变量

```text
APP_ENV=production
TASK_EXECUTION_MODE=database_worker
APP_BOOTSTRAP_ON_STARTUP=false
SECRET_KEY=<随机至少32字符>
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_PASSWORD=<随机至少16字符>
DATABASE_URL=${{Postgres.DATABASE_URL}}
CORS_ORIGINS=https://<Railway域名或自定义域名>

MEDIA_DIR=/data/media
FILE_STORE_DIR=/data/media/files
ARTIFACT_DIR=/data/media/artifacts
WORKSPACE_DIR=/data/media/workspace

AI_BUDGET_ENABLED=false
SIMULATION_EXECUTION_ENABLED=false
WEB_CONCURRENCY=2
```

其余限流、任务和费用变量可从 `backend/.env.production.example` 复制。外部 AI 必须在价格核对和 5 人灰度后再打开。

如果 Volume 出现权限错误，可临时设置 `RAILWAY_RUN_UID=0`，然后检查 `/data` 权限；不要把这个变量当作权限设计的替代品。

## 部署行为

`railway.json` 中的 `preDeployCommand` 会执行：

```text
python backend/scripts/bootstrap.py
```

它会运行 Alembic 迁移并创建唯一的生产管理员，不会导入演示用户和演示数据。随后 `deploy/railway_start.sh` 启动 Worker 和 Gunicorn，Gunicorn 监听 Railway 提供的 `$PORT`。

健康检查为：

```text
/api/ready
```

只有数据库迁移版本与代码 HEAD 一致时才会返回就绪。

## 首次发布后的检查

```text
GET https://<域名>/api/health
GET https://<域名>/api/ready
```

在 Railway Logs 中确认：

- pre-deploy migration 成功；
- Gunicorn 已监听 `$PORT`；
- Worker 已启动并能连接 PostgreSQL；
- 上传目录位于 `/data/media`；
- 没有 SQLite fallback、SECRET_KEY 或数据库连接错误。

## 重要运维规则

- Railway Volume 是持久化文件卷，但部署和卷本身仍需纳入备份策略。
- 不要把数据库备份、`.env`、API key 或上传材料提交到 Git。
- 先做 `scripts/backup_bundle.py` 备份，再触发迁移或升级。
- 不要把 `uploads/` 中的历史演示文件直接复制到生产 Volume；先人工审核。
- Railway 试用阶段保持 1 个副本，避免本地文件卷和后台 Worker 出现分裂。
- 如果 Worker 退出，整个服务会按 Railway 重启策略重新启动；需在日志和队列指标中监控。

## Railway CLI 可选流程

安装并登录 Railway CLI 后，在项目根目录执行：

```bash
railway link
railway variables
railway up
railway logs
```

不要把真实密钥作为命令行参数提交到 shell 历史；优先在 Railway Variables 页面设置。
