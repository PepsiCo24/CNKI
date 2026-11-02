# 系统架构

## 1. 总览

CNKI Scholar AI 是单用户、本地优先的两层应用：

```
Vue 3 SPA (frontend/)
        │  Axios / JSON / multipart
        ▼
FastAPI (backend/app)
  ├─ api/          HTTP 端点、参数校验、统一响应
  ├─ services/     业务编排（无 HTTP 依赖）
  ├─ adapters/     数据源适配器（CNKI 手动/授权）
  ├─ parsers/      RIS/BibTeX/ENW/CSV、PDF
  ├─ ai/           Provider Adapter、提示词、分析器
  ├─ tasks/        持久化任务队列 + worker + handlers
  ├─ models/       SQLAlchemy 2 模型
  ├─ schemas/      Pydantic 输入/输出/AI Schema
  ├─ database/     Session、FTS5、初始化种子
  └─ core/         配置、常量、加密、日志、工具
        │
        ▼
data/  (SQLite + 原始文件 + JSON 快照 + 备份 + 日志)
```

前后端只通过 HTTP 通信，不共享进程或内存，为 Electron + sidecar 打包保留边界。

## 2. 关键设计决策

### 2.1 四种状态分离

`papers` 表将业务状态拆成四个字段：

| 字段 | 取值 | 含义 |
| --- | --- | --- |
| `fulltext_status` | not_available / imported / downloading / failed | 是否取得全文 |
| `parse_status` | not_parsed / pending / parsed / partial / failed / unsupported | 全文是否可解析 |
| `ai_status` | not_analyzed / queued / running / completed / failed / cached | AI 分析进度 |
| `review_status` | pending_fulltext / pending_ai / analyzing / pending_review / included / excluded / deferred / analysis_failed | 人工审核业务状态 |

`included` 只能由 `POST /api/review/{paper_id}/action` 的显式 `include` 产生。导入文件、AI 完成、重新分析都不会写入该状态。

### 2.2 持久化任务队列

`background_jobs` 表是唯一队列：

- `status`：pending / running / completed / failed / cancelled / cancelling
- `dedupe_key` 唯一，防止同一篇文献重复解析或重复 AI 调用
- `attempts` / `max_attempts`：失败重试
- `cancel_requested`：协作式取消
- `payload`：handler 参数
- 领域任务（`ai_analysis_jobs`、`import_jobs`）记录业务状态，与队列表通过 `background_job_id` 关联

worker（`app/tasks/runner.py`）在 FastAPI lifespan 中启动：

1. 进程启动时把遗留 `running` 任务重置为 `pending`（`recover()`）。
2. 每 0.6 秒领取任务，`worker_concurrency` 限制总并发，AI 并发数从设置表每 5 秒缓存读取。
3. 同步 handler 放到线程池；AI handler 在事件循环中执行异步 HTTP。
4. 失败按 `max_attempts` 重排；完成后写入领域结果与日志。
5. 关闭时把仍在运行的任务重置为 pending，保证重启后续跑。

已完成结果在 handler 内即时提交，因此进程崩溃不会丢失已完成的分析或导入结果。

### 2.3 去重策略

`services/dedup.py`：

1. **DOI**：规范化（去 `https://doi.org/` 前缀、小写）。
2. **标题 + 作者 + 年份**：
   - 规范化标题（全半角、标点、空格、HTML）。
   - 完全相同直接命中。
   - 相似度 ≥ 0.94，或作者与年份均一致时 ≥ 0.88，标记为 `title_fuzzy`。
3. **SHA-256**：原始文件内容哈希，唯一文件只保存一份。

命中强匹配（DOI/标题）且已有全文时，复用原记录；仅有题录时合并全文。模糊匹配会创建新记录、设置 `duplicate_status=suspected` 与 `duplicate_of_id`，审核详情页提供“确认不是重复 / 标记为重复关联”，**系统不自动删除文件**。

### 2.4 文件归档

`services/file_service.py`：

```
data/papers/{安全期刊名}/{年份或"未知年份"}/{year}_{title}_{first_author}.pdf
```

- 文件名按 UTF-8 字节长度截断，保留扩展名；清理 Windows 非法字符。
- 同名但 SHA 不同自动追加 `_2`。
- 数据库保存原始文件名、规范化文件名、相对路径、SHA-256、来源、页数、解析状态。
- 原文件不会被删除；上传暂存文件在归档后可清理。

### 2.5 PDF 解析

`parsers/pdf_parser.py`：

- PyMuPDF 读取每页文本与内嵌元数据。
- 文本总量过低时尝试 pdfplumber；仍为空则标记 `scanned`。
- 重复页眉页脚（出现在 ≥60% 页面）被清理，页码噪声与知网水印行被过滤。
- 记录每页 `char_start/char_end`，生成 `【第N页】` 渲染文本供模型引用。
- 章节识别：摘要、关键词、引言、相关工作、方法、实验、结果、讨论、结论、参考文献。
- 加密、损坏、CAJ 均返回明确错误而不是伪造正文。

### 2.6 AI 分析流水线

```
PaperText / Abstract
   │
   ├─ 全文 <= max_input_chars ──► 单次全文分析（fulltext）
   └─ 全文 >  max_input_chars ──► 按页分块提取要点 ──► 汇总分析（fulltext_chunked）
   │
   ▼
System prompt (版本化) + JSON Schema 指令
   ▼
Provider Adapter (OpenAI 兼容 / Ollama / Mock)
   ▼
JSON 提取 → Pydantic 严格校验
   ├─ 成功 → 保存结果、创新点条目、JSON 快照、FTS 索引
   └─ 失败 → 最多 2 次修复重试 → 仍失败则记录错误
```

缓存键：`sha256(内容 + prompt_id + prompt_version + provider + model + temperature + max_tokens + scope)`。同文献同参数再次分析会复用结果并标记 `cached`；`force=true` 强制生成新版本。

分析结果保存模型、Provider、提示词版本、参数、输入字符数、Token、费用估算、分析范围、是否 Mock、原始响应。新结果将旧结果 `is_current=false`，历史版本仍可读取。

### 2.7 检索与任务匹配

`services/matching.py` 对每条题录核对：

- 期刊来源：规范化后比较，硬条件。
- 日期范围：按 `publication_date_precision` 比较，只有年份的记录不会虚构月日。
- 主题关键词：命中标题、摘要或关键词。
- 匹配分数与不匹配原因写入导入任务明细，前端可展开查看。

### 2.8 全文检索

SQLite FTS5 `paper_fts`，使用 `trigram` tokenizer（SQLite ≥3.34），适合中文子串检索。索引列：标题、作者、期刊、摘要、AI 创新点、笔记与正文片段。查询长度 <3 时回退 `LIKE`。每次文献、分析、笔记更新都会重建对应 FTS 行；`/api/system/reindex` 可全量重建。

## 3. 数据模型

| 表 | 作用 | 关键约束/索引 |
| --- | --- | --- |
| papers | 文献元数据与四类状态 | DOI、标题规范化、期刊+年份、状态索引 |
| paper_files | 原始文件、哈希、解析状态 | paper_id、sha256 索引 |
| paper_texts | 解析正文、页映射、章节 | paper_id 唯一 |
| search_tasks | 检索条件、状态、计数 | status 索引 |
| search_task_papers | 任务-文献多对多、匹配状态 | (task_id, paper_id) 唯一 |
| import_jobs | 题录/目录导入进度与错误 | status、task_id |
| background_jobs | 持久化任务队列 | dedupe_key 唯一、status+priority+created_at |
| ai_analysis_jobs | AI 领域任务、Token、模型、错误 | paper_id、status、cache_key |
| ai_analysis_results | 结构化结果、版本、人工编辑原版 | (paper_id,is_current)、cache_key |
| prompt_templates | 提示词与版本 | 默认/启用标记 |
| paper_reviews | 审核审计（含撤销） | paper_id+created_at |
| tags / paper_tags | 自定义标签 | name 唯一、复合主键 |
| research_notes | 个人笔记 | paper_id 索引 |
| innovation_items | 创新点条目 | (result_id, seq) 唯一 |
| collections / collection_papers | 自定义文件夹 | 父子关系、复合主键 |
| app_settings | 非敏感设置（密钥加密） | key 唯一 |
| task_logs | 任务/后台日志 | task_id、job_id、created_at |

所有表均有字符串 UUID 主键、`created_at`、`updated_at`（部分审计表只有 `created_at`），外键开启 `ON DELETE CASCADE/SET NULL`。

## 4. 安全设计

- API Key：Fernet 对称加密；密钥 `data/keys/master.key` 由系统生成，权限 `0600`。前端只拿到掩码。
- 日志：不记录请求头、Key 或完整模型请求体；异常信息截断。
- 路径：所有文件访问使用 `data/` 相对路径 + `resolve()` 越界校验。
- 网络：默认监听 `127.0.0.1`；CORS 白名单为本地 Vite 地址。
- 知网：无自动登录、无验证码绕过、无私有接口调用；授权适配器未配置端点时明确拒绝。
- 导出：默认不包含 PDF 全文。

## 5. 扩展点

| 扩展 | 位置 |
| --- | --- |
| 新增学术数据库 | 实现 `SourceAdapter` 并注册到 `adapters/` |
| 新增知网授权接口 | 扩展 `CNKIAuthorizedAdapter`，加入分页/限额/断点 |
| 新增 LLM 服务商 | 若兼容 OpenAI 协议，仅需添加 Profile；否则实现 `LLMProvider` |
| OCR | 新增 `parsers/ocr.py`，在 `extract_document` 中接入扫描分支 |
| CAJ 转换 | 在文件服务中调用用户已授权的外部转换器，再走 PDF 解析 |
| 向量检索 | 在 `innovation_items` 上增加 embedding 表与服务；不影响现有 FTS |

## 6. 前端结构

- `MainLayout.vue`：固定侧栏 + 顶栏 + 内容区；暗色主题通过 `html.dark` + Element Plus CSS 变量。
- `PdfViewer.vue`：PDF.js 4.x，worker 由 Vite 打包；懒渲染、页导航、缩放、文本层可复制、页码跳转。
- `AnalysisView.vue`：结构化展示 AI 结果，Mock 警示、证据页码联动。
- `PaperDetailDrawer.vue`：概览/PDF/笔记/审核记录；元数据与 AI 结果编辑；标签与重复确认。
- 页面均为真实 API 数据，无静态假按钮；轮询任务进度并处理空状态、加载状态与错误提示。
