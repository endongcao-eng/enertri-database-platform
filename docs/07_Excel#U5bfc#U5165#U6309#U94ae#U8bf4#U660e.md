# V3.1 Excel 导入按钮说明

本版本已在前端管理后台接入后端现有的 Excel 导入接口。

## 使用方式

1. 启动项目并访问前端页面。
2. 使用管理员账号登录。
3. 进入“管理后台”。
4. 在“Excel 批量导入”区域选择 `.xlsx` 文件。
5. 点击“导入 Excel”。
6. 页面会显示成功导入数量、跳过数量，以及错误/警告明细。

## 接口

前端按钮调用后端已有接口：

```http
POST /api/import/excel
Content-Type: multipart/form-data
Authorization: Bearer <管理员 token>
```

表单字段名为：

```text
file
```

## Excel 表头要求

至少需要：

- 中文术语
- 英文术语

可选表头包括：

- 俄文术语（可选）
- 学术版术语解释
- 通俗版术语解释
- 简要英文解释
- 关键词（3–5个，用逗号分隔）
- 相关术语
- 应用场景
- 公式 / 模型（如有）
- 有无视频形式的示例或工程案例
- 参考文献（1–2篇）
- 填写本词条的学生姓名
- 填写本词条的学生研究方向
- 审核状态

## 本次修改文件

- `frontend_api_demo/app.js`
  - 添加“Excel 批量导入”面板
  - 添加文件选择、格式检查、上传、成功/失败提示逻辑
- `frontend_api_demo/api-client.js`
  - 添加 `importExcelApi(file)` 封装
- `frontend_api_demo/styles.css`
  - 添加导入面板和结果提示样式
