# 开发进度记录

日期：2026-11-02  
环境：macOS 26.6（arm64）、Python 3.12.14、Node 24、npm、SQLite 3.53.1、Vue 3 + Vite 6

> 本文记录实际执行结果、遇到的问题与修复，不把计划写成已完成。

---

## 第一阶段：基础工程 ✅

- 建立 `backend/` 与 `frontend/` 目录、根 `pyproject.toml`、`.env.example`、`.gitignore`。
- FastAPI 应用、CORS、统一响应 envelope、异常处理、日志（轮转文件 + 控制台）。
- SQLAlchemy 2 模型 19 张表，WAL / 外键 / busy_timeout。
- SQLite FTS5 trigram 虚拟表。
- Alembic 自动生成初始迁移并手工加入 FTS 表；在全新临时库执行 `upgrade head` 验证 26 个对象（含 FTS 影子表），`alembic_version=de955d910552`。
- 默认提示词、7 个标签、默认设置种子。
- Vue 3 + TS + Vite + Element Plus + Tailwind + Pinia + Router 工程；亮/暗主题。
- 一键脚本：`setup.sh`、`start.sh`、`dev.sh`、`start.bat`、`dev.bat`。

## 第二阶段：文献管理 ✅

- 题录解析：RIS、BibTeX、EndNote ENW、CSV；BOM/GBK 兼容；日期精度保留。
- PDF 解析：PyMuPDF + pdfplumber 兜底；页映射、章节识别、扫描/加密/CAJ 标记。
- 文件服务：上传、拖拽、目录扫描、Watchdog 监听、期刊/年份归档、命名规则、SHA-256。
- 三级去重与疑似重复确认。
- 三栏文件管理、文件树、状态/期刊/年份/任务/自定义文件夹、批量分析/导出、PDF 阅读。
- 笔记、标签、元数据编辑、重复处理。

## 第三阶段：知网检索工作流 ✅（授权接口除外）

- 检索任务 CRUD、条件校验、条件快照。
- 区分期刊来源与主题关键词；导入时按期刊/日期/关键词过滤并记录不匹配原因。
- 官方检索条件单（不猜测接口地址，只链接 https://www.cnki.net）。
- 题录导入、任务关联、跳过明细、日志与计数。
- 暂停/继续/取消/重试/重新执行。
- 本地全文接管：手动扫描、上传、拖拽、目录监听。
- 授权接口适配器骨架：明确拒绝未配置端点，不调用任何未确认知网接口。

## 第四阶段：AI 分析 ✅

- Provider Adapter：OpenAI 兼容、DeepSeek、通义千问、Ollama、Mock。
- 本地 Fernet 密钥存储、掩码返回、日志脱敏。
- 提示词版本管理；内容变更创建新版本。
- 严格 Pydantic Schema；最多 2 次修复。
- 长文本分块提取 + 汇总；页码保留。
- 缓存、重新分析版本、人工编辑保留原版。
- Token/费用统计、AI 分析中心、批量分析待处理。
- 自动触发解析后分析（可关闭）。
- 后台队列并发、重试、取消、重启恢复。

## 第五阶段：审核与入库 ✅

- 审核工作台：左队列/中分析/右 PDF+证据+备注；亮暗主题；快捷键。
- 入库/暂不采用/待定/撤销；批量审核；标签；备注。
- 审核快照与历史。
- 正式文献库：FTS、期刊/年份/标签/作者筛选、卡片/表格、导出。
- 创新点库：关键词/论文/标签、备注、复制 Markdown、跳转论文。
- 自定义文件夹与标签管理。
- 导出 CSV/XLSX/JSON/Markdown/RIS/BibTeX/笔记；备份 zip。
- 仪表盘、导入记录、运行日志、系统状态。

## 第六阶段：测试与工程化 ✅（Windows 打包除外）

- 后端 48 项 pytest：解析、去重、PDF、AI、完整 API、恢复、导出、备份。
- 前端构建与 `vue-tsc` 类型检查通过。
- Playwright 5 项 E2E：九页面、审核入库、PDF、设置、主题；全部通过。
- 完整验收流程实际跑通，结果见 `docs/ACCEPTANCE.md`。
- README、架构、API、测试、验收、Windows 打包文档。

---

## 实际遇到的问题与修复

| 问题 | 表现 | 原因 | 修复 |
| --- | --- | --- | --- |
| pnpm 忽略构建脚本 | Vite/esbuild 不可用 | pnpm 12 默认拦截 postinstall | 改用 npm 安装（`package-lock.json`） |
| FTS 索引缺失 | 仅有题录、未分析的文献搜不到 | 只在分析/更新时建索引 | 创建题录与文件登记时也 `index_paper` |
| 搜索分页错位 | 带筛选时翻页条目数不对 | 先分页 FTS id 再套用其他筛选 | 先套用全部筛选再按 FTS 顺序内存分页（上限 1000） |
| PDF 空白 | 右侧阅读器只有白页 | Vue `ref` 深代理 PDF.js 对象，访问私有字段报 `Cannot read from private field` | 文档对象改用 `shallowRef` |
| PDF 文本层空 | canvas 渲染后无文本层 | keyed 重渲染使内联 `ref` 回调失效，Map 被清空 | 渲染与跳页改为 DOM 查询；DPR 上限 8M 像素 |
| 撤销后任务计数不更新 | `included_count` 仍为 1 | `SessionLocal(autoflush=False)`，聚合查询看不到未 flush 的状态 | `refresh_counters` 先 `db.flush()`；新增回归测试 |
| 撤销接口 422 | 空 body 调用失败 | `review_id` 在 Pydantic 中必填 | 改为可选，空 body 合法 |
| 审核操作按钮无选中仍可点 | 空队列仍显示入库 | 未绑定 disabled | 按钮绑定 `!current` |
| 侧栏待审核角标错误 | 显示总文献数 | 临时使用了 `papers` 总数 | 移除误导角标 |
| CSV 表头英文 | 导出列名为 id/title | CSV 与 XLSX 表头映射不一致 | 提取统一中文 `HEADER_LABELS` |
| 日期时区偏差 | 前端把 UTC 当本地时间 | SQLite 丢 tzinfo，ISO 无 Z | 序列化器为 naive datetime 补 UTC |
| 题录缺标题不报错 | 解析错误列表为空 | RIS flush 直接跳过无标题记录 | 保留记录，由导入层报告“缺少标题” |
| E2E 不稳定 | 同一文本匹配隐藏 tab | Playwright 匹配到隐藏 select/旧 tab | 缩小 locator 范围、改用可见容器、等待文本层 |
| Mock 模型显示 deepseek-chat | 设置页模型名不一致 | Mock 复用已保存 model 字段 | 后端 Mock 时返回 `deterministic-mock-v1` |
| 表格被裁切 | 文件管理右侧列不可见 | 中心栏宽度不足且列过多 | 移除冗余操作列、压缩列宽 |
| 设置页保存栏遮挡 | 底部输入被覆盖 | sticky 操作栏 | 内容区增加底部 padding |
| 目录监听启动卡死 | 开启监听请求不返回 | `start()` 持有 Lock 又调用 `stop()`，且 `join()` 在锁内 | 改用 RLock，`join()` 移到锁外 |
| 再次扫描失败 | `UNIQUE constraint failed: background_jobs.dedupe_key` | 去重键全局唯一，但只检查活动任务 | 入队时释放已完成任务的旧去重键；新增回归测试 |

---

## 最近一次验证结果

```
后端：48 passed, 8 warnings in 1.15s
前端：vue-tsc + vite build 成功（dist 约 3.5MB）
E2E：5 passed (6.0s)
完整流程：任务→5 条题录（3 导入/2 跳过）→PDF 合并→2 页/2047 字符→Mock 分析→审核入库→文库/创新点检索→重启保持
```

## 尚未完成 / 明确标注

1. **Windows EXE 未构建**：只有 `sidecar.py` 与打包方案，无 Electron 工程、无 PyInstaller spec、无安装包。
2. **知网授权 API 未实现**：无官方文档/许可，适配器仅拒绝并提示，不猜测端点。
3. **CAJ 不解析**、**扫描版 PDF 无 OCR**。
4. **无登录/多用户**：只监听 127.0.0.1。
5. **PDF.js 无批注/高亮编辑**，仅文本选择复制与页码跳转。
6. **自动备份依赖应用运行**，未做系统级计划任务。
7. 真实模型只使用 Mock 做过端到端验收；OpenAI 兼容/Ollama 代码路径已实现并有超时/错误处理，但未在没有 API Key 的环境中调用真实服务。

## 下一步优先级

1. 用真实 DeepSeek 或 Ollama 分析真实 PDF，校准提示词与页码证据质量。
2. 增加扫描版 PDF 的 OCR 可选流程。
3. 在 Windows 真机完成 PyInstaller + Electron 打包与升级迁移测试。
4. 增加真实环境的 PDF 大文件性能测试与失败恢复演练。
5. 若获得知网书面许可，按官方文档实现授权适配器（分页、限额、断点恢复）。
