# 测试与验收

## 1. 自动化测试

### 1.1 后端（pytest，48 项）

```bash
cd 知网系统
.venv/bin/python -m pytest backend/tests -q
```

测试使用独立的临时数据目录与临时 SQLite，不会修改 `data/` 中的个人数据。

| 文件 | 覆盖内容 |
| --- | --- |
| `test_metadata_parsers.py` | RIS/BibTeX/EndNote/CSV、年份精度、非法日期、缺标题错误 |
| `test_dedup.py` | DOI、标题+作者+年份、SHA-256、模糊疑似重复、标题规范化 |
| `test_pdf_parser.py` | 示例 PDF 页映射、章节识别、页标记截断、CAJ/缺失文件 |
| `test_ai_pipeline.py` | Mock 分析、缓存、强制新版本、仅摘要范围、JSON 修复上限、Schema 分数边界 |
| `test_api_workflow.py` | 完整业务闭环、日期校验、题录过滤、PDF 合并、审核、撤销计数回归、PDF 流 |
| `test_tasks_export.py` | 进程恢复、去重入队、CSV/JSON/XLSX/RIS 导出、备份内容、重复确认 |
| `test_matching.py` | 期刊来源与主题区分、日期范围、年份精度、关键词命中 |
| `test_settings.py` | API Key 加密/掩码/不覆盖、未知键拒绝、设置往返 |
| `test_file_service.py` | 期刊/年份归档、同哈希复用、同题不同全文保留为疑似重复 |

最近运行结果：

```
48 passed, 8 warnings in 1.15s
```

警告来自 PyMuPDF 的 SWIG 类型与 Starlette TestClient 的 httpx 兼容提示，不影响功能。

### 1.2 前端构建与类型检查

```bash
cd frontend
npm run build      # vue-tsc -b && vite build
npm run typecheck
```

### 1.3 浏览器 E2E（Playwright，5 项）

前提：后端已启动在 `http://127.0.0.1:8000`，并已加载示例数据（至少一篇已入库文献）。使用本机 Chrome（`channel: chrome`），无需额外下载浏览器。

```bash
cd frontend
npx playwright test
# 或 npm run test:e2e
```

覆盖：

1. 九个主页面全部加载真实数据、无控制台错误。
2. 审核工作台：真实文献、PDF canvas 与文本层渲染、`Ctrl+Enter` 入库、文库同步。
3. 文献详情抽屉：PDF 渲染、文本层、AI 摘要。
4. 设置中心：Mock 模型连接测试、提示词版本页。
5. 亮/暗主题切换与刷新后持久化。

最近运行结果：

```
5 passed (6.0s)
```

> E2E 会通过 API 撤销/重新入库示例文献以保证可重复执行；它只应针对示例库运行，不要指向正式数据。

## 2. 人工验收清单

### 检索任务

- [x] 创建“岩土力学期刊创新点调研”，期刊来源=岩土力学，主题留空，2023-01-01 ~ 2025-12-31。
- [x] 起始日期晚于截止日期时返回 422。
- [x] 条件单明确显示“文献来源”与“主题”是两个字段。
- [x] 题录导入：5 条记录，导入 3 条，跳过 2 条（1 条期刊不匹配、1 条年份超范围）。
- [x] 任务计数：发现 3、全文 1、分析 1、入库 0/1 随审核变化。
- [x] 暂停/继续/取消/重试、日志可见。

### 文件与解析

- [x] 上传示例 PDF 后自动与既有题录合并，不产生重复论文。
- [x] 归档路径：`data/papers/岩土力学/2023/2023_基于..._张示例.pdf`。
- [x] 解析得到 2 页、2047 字符、章节含摘要/关键词/方法/实验/参考文献。
- [x] 文件 SHA-256 重复时复用原记录。
- [x] PDF 内联播放、页码跳转、文本层可选中复制。

### AI

- [x] 新全文自动排队分析（可关闭）。
- [x] Mock 结果带 `is_mock`、界面醒目提示、写入 `data/ai_results/{paper_id}.json`。
- [x] 结构化字段完整，参考分 0–100。
- [x] 相同参数再次分析命中缓存，不重复计费。
- [x] 强制重新分析生成新版本，旧版本 `is_current=false`。
- [x] 人工编辑保存 `original_result` 快照。

### 审核与入库

- [x] 待审核列表显示摘要、一句话总结、创新点、证据、参考分。
- [x] 点击“入库”后从待审核队列移除，出现在正式文献库。
- [x] 暂不采用 / 待定 / 撤销审核均写入审计记录。
- [x] 备注随审核记录保存，标签关联文献。
- [x] `Ctrl+Enter` 快捷键入库。

### 检索与导出

- [x] 文库按标题/摘要/创新点中文检索（FTS5 trigram）。
- [x] 创新点库能检索到 Mock 创新点并编辑备注。
- [x] CSV 中文表头、Excel 可打开、JSON 可解析、RIS/BibTeX 含标题与作者。
- [x] 导出不包含 PDF 全文。
- [x] 数据库备份 zip 含数据库、metadata、ai_results、manifest。

### 持久化

- [x] 重启 uvicorn 后，文献、文件、状态、AI 结果、审核记录、任务计数保持不变。
- [x] 后台任务运行中重启，`running` 被重置为 `pending` 并重新执行。

## 3. 手工回归建议

1. 用真实 DeepSeek / Ollama 模型分析一篇真实 PDF，核对创新点是否有页码证据。
2. 导入一篇扫描版 PDF，确认标记为“未提取到文本”，且只在明确提示下做摘要分析。
3. 导入一个超大 PDF（>100 页），确认分块汇总与进度显示。
4. 修改提示词内容，确认生成新版本且旧分析结果不变。
5. 关闭网络，确认已有文献、PDF、分析结果仍可阅读。
6. 使用含中文、空格和特殊字符的目录路径执行导入。
7. 在 Windows 上验证文件命名长度截断与路径分隔符。
