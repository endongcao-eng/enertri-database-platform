# Excel 导入 Internal Server Error 修复说明

## 问题现象

在管理员后台点击“导入 Excel”后，前端提示：

```text
导入失败：Internal Server Error
```

## 原因

原后端 `/api/import/excel` 接口可以读取 Excel，但缺少以下容错逻辑：

1. 没有跳过数据库中已经存在的相同“中文术语 + 英文术语”词条；
2. 没有跳过同一个 Excel 文件内部重复的词条；
3. 如果 Excel 当前活动工作表不是导入表，可能无法正确识别表头；
4. 后端异常没有转换为可读的 400 错误信息，因此前端只能显示 Internal Server Error。

## 已修复内容

本版本修改了：

```text
backend/app/main.py
```

主要改动：

- 自动寻找包含“中文术语”和“英文术语”的工作表；
- 导入前检查必需表头；
- 已存在词条自动跳过；
- Excel 内部重复词条自动跳过；
- 后端异常转换为可读错误；
- 导入完成后返回 imported / skipped / errors。

## 使用方式

替换 `backend/app/main.py` 后，需要重建后端容器：

```bat
docker compose -f docker-compose.local.yml up -d --build --force-recreate
```

如果只重启 Caddy 不会生效，因为这次改的是后端 Python 代码。
