# 本次验证记录（2026-09-11）

环境：Python 3.12、隔离 SQLite、FastAPI TestClient。项目依赖 pip check 通过。

| 测试模块 | 数量 | 结果 |
|---|---:|---|
| test_v4_1_foundation | 5 | 通过 |
| test_v4_3_capability_standards | 2 | 通过 |
| test_v4_4_research_profile | 3 | 通过 |
| test_v4_5_project_matching | 3 | 通过 |
| test_v4_6_development_planning | 3 | 通过 |
| test_v4_7_dynamic_development_loop | 3 | 通过 |
| test_v4_smoke | 1 | 通过，内部含 34 项检查 |
| test_web_trial | 6 | 通过 |
| 合计（原始模块 + trial controls） | 36 | 通过（控制测试在依赖切换前的兼容环境执行） |

Python compileall、前端所有 JS 的 node --check、Compose 与 CI YAML 解析通过。离线 preflight 在缺少真实配置时正确拒绝启动准备。

最近的控制测试还验证了 0010 迁移、跨进程账号限流、改密/会话撤销、任务准入、Worker 运行槽位、AI 预算预留、匿名受保护路由和跨用户资源矩阵；这些测试共 10 项。随后将 JWT 运行时从 python-jose 切换到 PyJWT 并升级依赖；本地只完成编译和 JS 语法检查，依赖切换后的完整回归需要在目标构建环境重新执行。

复现：安装 backend/requirements.txt 后执行 `python scripts/run_regression.py`，各模块分进程运行；原始日志见 regression.log。

实际业务输出见 runtime-preview.json：内置开发数据下生成 10 个成长路线项、五类资源、1 个快照，私有下载匿名访问返回 401。该文件未包含登录 token。

没有执行：PostgreSQL 和 Docker/Caddy/HTTPS 部署、生产新库初始化端到端、浏览器 UI、负载脚本、远程 CI、实时漏洞扫描或真实 AI/OpenAlex/商业仿真服务。现有自动测试中的外部调用使用替身，不能作为外部服务验收。周期租约回收、备份恢复及账号批量导入还需在目标环境做操作验收。

新增 Railway/Railpack 部署入口：`railway.json`、`railpack.json`、根目录 `requirements.txt`、`.python-version`、`.railwayignore` 和 `deploy/railway_start.sh`。该版本把 Web 与数据库 Worker 合并在一个 Railway service，以共享单个 `/data` Volume；未在 Railway 真实项目中执行构建、迁移、Volume、域名或运行时验收，不能将配置文件视为上线证明。

生产依赖已更新至 `python-multipart==0.0.32`、`PyJWT==2.13.0`、`FastAPI==0.141.1`、`python-dotenv==1.2.3`；本环境的最终远程漏洞扫描因包索引连接超时未完成。目标服务器必须重新执行 `pip-audit -r backend/requirements.txt`，并将结果归档后才可放行。

新增 0010 迁移后，旧账号的 token_version 会失效并要求首次登录改密；这是有意的安全行为。新增的 `tests/test_trial_controls.py` 覆盖登录限流、跨进程桶、改密/登出撤销、任务准入、AI 预留、匿名路由和跨用户资源矩阵，共 10 项；在完整依赖环境中已通过。
