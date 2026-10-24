# V4.2 实际运行成果预览

## V4.2 文献与论文知识系统

- `v4_2_literature_dedup.png`：多来源文献适配与数据库 provenance 去重，3 条来源记录合并为 2 条主文献，其中 1 条为 OpenAlex + Crossref 跨源合并。
- `v4_2_pdf_structured_side_by_side.png`：实际 2 页 PDF 左侧原文与右侧章节、关键事实、页码证据并排预览；底部展示独立 Worker 的真实 `worker_id`、尝试次数和任务状态。
- `v4_2_table_extraction.png`：第 1 页 Table 1 的结构化二维表与 Markdown 结果。
- `v4_2_paper_qa_evidence.png`：四类论文问答与章节级证据卡片，覆盖激光功率、抗拉强度/参数组、母材与气孔形成解释。
- `v4_2_page_locator.png`：点击证据后的 PDF 物理页码定位示意，Results/Discussion 均定位到 P2。
- `v4_2_acceptance_preview.pdf`：以上五项验收预览汇总。
- `v4_2_runtime_preview.json`：独立 Worker、文献去重、论文结构化与问答的实际运行摘要。
- `v4_2_demo_paper.pdf`：用于 V4.2 实际解析验收的 2 页 PDF。

## 保留的历史成果

V4.1/V4.0 的预览、PPT、DOCX、视频分析和仿真输入包继续保留，用于回归验证旧功能兼容性。

所有 demo 文件都是验收样例，不应直接作为正式 WPS、最终论文结论或生产仿真模型。
