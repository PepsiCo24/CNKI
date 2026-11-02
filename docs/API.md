# API 参考

- 基础地址：`http://127.0.0.1:8000/api`
- 交互文档：`/docs`
- OpenAPI JSON：`/docs/openapi.json`，离线副本 `docs/openapi.json`（85 个路径）
- 认证：无（本地单用户，仅监听 127.0.0.1）
- 内容类型：JSON；上传接口使用 `multipart/form-data`

## 统一响应

成功：

```json
{ "success": true, "data": { }, "message": null }
```

分页数据位于 `data`：

```json
{ "items": [], "total": 0, "page": 1, "page_size": 20 }
```

失败：

```json
{
  "success": false,
  "error": {
    "code": "validation_error",
    "message": "输入校验失败：…",
    "detail": {}
  }
}
```

| HTTP | code | 说明 |
| --- | --- | --- |
| 400 | bad_request | 参数/业务状态错误 |
| 403 | permission_required | 未获得知网授权接口许可 |
| 404 | not_found | 资源不存在 |
| 409 | conflict | 状态冲突（如任务执行中修改条件） |
| 422 | validation_error | Pydantic 校验失败 |
| 502 | external_service_error | 外部模型/服务错误 |
| 500 | internal_error | 未处理异常，查看 `data/logs/app.log` |

---

## 系统与仪表盘

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查与 worker 状态 |
| GET | `/system/info` | 版本、数据目录、SQLite、文件统计、AI/监听状态 |
| GET | `/system/logs?lines=200` | 最近日志 |
| POST | `/system/reindex` | 同步重建 FTS |
| POST | `/system/backup` | 同步创建备份 zip |
| GET | `/system/duplicates` | 疑似重复文献 |
| GET | `/system/jobs?status=&job_type=&page=` | 持久化后台任务 |
| GET | `/system/jobs/{job_id}` | 单个任务 |
| POST | `/system/jobs/{job_id}/cancel` | 请求取消 |
| POST | `/system/jobs/retry-failed` | 重排全部失败任务 |
| GET | `/dashboard` | 仪表盘聚合数据 |

---

## 检索任务

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/search-tasks?status=&q=&page=` | 任务列表与状态计数 |
| POST | `/search-tasks` | 创建任务 |
| GET | `/search-tasks/{id}` | 任务详情、条件单、日志 |
| PUT | `/search-tasks/{id}` | 编辑条件（运行中拒绝） |
| DELETE | `/search-tasks/{id}` | 删除任务（文献保留） |
| POST | `/search-tasks/{id}/run` | 生成条件单 / 启动扫描 |
| POST | `/search-tasks/{id}/pause` | 暂停 |
| POST | `/search-tasks/{id}/resume` | 继续 |
| POST | `/search-tasks/{id}/cancel` | 取消 |
| POST | `/search-tasks/{id}/retry` | 重试 |
| GET | `/search-tasks/{id}/guide` | 官方检索条件单 |
| GET | `/search-tasks/{id}/papers` | 任务关联文献（分页） |
| POST | `/search-tasks/{id}/papers` | 手动关联文献 |
| GET | `/search-tasks/{id}/logs` | 任务日志 |

创建示例：

```bash
curl -X POST http://127.0.0.1:8000/api/search-tasks \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "岩土力学期刊创新点调研",
    "journal": "岩土力学",
    "keywords": "",
    "start_date": "2023-01-01",
    "end_date": "2025-12-31",
    "paper_type": "journal",
    "import_mode": "metadata_import"
  }'
```

`run` 请求体可指定模式：

```json
{ "mode": "metadata_import" | "folder_watch" | "authorized_api" }
```

授权接口模式在未配置许可时会返回 403/400 并给出明确说明。

---

## 导入

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/imports/formats` | 支持格式 |
| POST | `/imports/metadata` | 上传题录文件（`file`, `task_id?`, `format=auto`） |
| POST | `/imports/files` | 上传 PDF/CAJ（`files[]`, `task_id?`，最多 50 个） |
| POST | `/imports/scan` | 扫描目录（`path?`, `task_id?`） |
| GET | `/imports?status=&task_id=&page=` | 导入记录 |
| GET | `/imports/{id}` | 单条导入进度、错误、明细 |
| POST | `/imports/{id}/retry` | 重新导入/扫描 |
| DELETE | `/imports/{id}` | 删除记录（不删文件） |

题录导入响应包含 `total/processed/imported/duplicates/failed` 及 `detail.rows`（逐条匹配结果和跳过原因）。

---

## 文献与文件

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/papers?q=&tree_key=&journal=&year=&tag=&review_status=&task_id=&collection_id=&page=` | 文献列表（FTS 搜索） |
| GET | `/papers/tree` | 文件树节点与计数 |
| GET | `/papers/{id}` | 详情（文件、文本信息、当前分析、历史、笔记、审核） |
| PUT | `/papers/{id}` | 编辑元数据 |
| DELETE | `/papers/{id}` | 软删除（文件保留） |
| GET | `/papers/{id}/file` | PDF/CAJ 内联流（支持 Range） |
| GET | `/papers/{id}/text` | 解析正文、页映射、章节 |
| POST | `/papers/{id}/parse` | 入队重新解析 |
| POST | `/papers/{id}/analyze?force=` | 入队 AI 分析 |
| POST | `/papers/{id}/attach-file` | 为仅有题录的文献关联全文 |
| GET/POST | `/papers/{id}/notes` | 笔记列表/新增 |
| PUT/DELETE | `/notes/{note_id}` | 编辑/删除笔记 |
| POST | `/papers/{id}/tags` | 添加或替换标签 |
| DELETE | `/papers/{id}/tags/{tag_id}` | 移除标签 |
| POST | `/papers/{id}/duplicate` | `keep_separate` / `confirm_duplicate` |
| GET | `/papers/{id}/reviews` | 审核历史 |

列表参数 `tree_key` 取值：

```
all
task:<task_id>
journal:<期刊名>
year:<年份>
status:pending_analysis | pending_review | included | excluded | deferred | failed | duplicates
collection:<collection_id>
```

---

## AI

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/ai/analyze` | `{paper_ids, force, prompt_template_id}` |
| POST | `/ai/analyze-pending?limit=&force=` | 批量分析待处理 |
| GET | `/ai/jobs?status=&page=` | 分析任务（含后台进度） |
| GET | `/ai/jobs/{id}` | 单个任务与结果 |
| POST | `/ai/jobs/{id}/cancel` | 取消 |
| GET | `/ai/stats` | 状态、Token、费用、模型分布 |
| GET | `/ai/results/{id}` | 完整结果（含 raw_response） |
| PUT | `/ai/results/{id}` | 人工编辑，保留原版 |
| GET | `/ai/papers/{paper_id}/analysis` | 当前与历史版本 |

人工编辑请求示例：

```json
{
  "one_sentence_summary": "…",
  "screening_score": 72,
  "screening_reason": "…",
  "claimed_innovations": []
}
```

---

## 审核

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/review/queue?status=pending_review&sort=score_desc&q=&page=` | 待审核队列与各状态计数 |
| GET | `/review/{paper_id}` | 审核详情 |
| POST | `/review/{paper_id}/action` | `include` / `exclude` / `defer` / `reanalyze` |
| POST | `/review/{paper_id}/undo` | 撤销上一条审核（可传 `review_id`） |
| POST | `/review/batch` | 批量审核 |
| GET | `/review/history/{paper_id}` | 审核记录 |
| GET | `/review/recent` | 最近审核 |

审核请求：

```json
{
  "action": "include",
  "note": "方法可复现，值得精读",
  "tags": ["岩土工程", "机器学习"],
  "expected_status": "pending_review"
}
```

`expected_status` 可选，用于乐观并发校验；状态已变化时返回 409。

---

## 正式文献库与创新点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/library/papers?q=&journal=&year=&tag=&author=&sort=` | 仅已入库文献 |
| GET | `/library/papers/{id}` | 详情（未入库时附 warning） |
| GET | `/library/facets` | 期刊/年份/标签聚合 |
| GET | `/innovations?q=&paper_id=&tag=&page=` | 创新点库 |
| GET | `/innovations/facets` | 论文与标签筛选数据 |
| GET | `/innovations/{id}` | 单条 |
| PUT | `/innovations/{id}` | 修改备注/名称/标签快照 |

---

## 标签、文件夹、笔记

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/tags` | 列表（含计数）/创建 |
| PUT/DELETE | `/tags/{id}` | 更新/删除 |
| GET/POST | `/collections` | 自定义文件夹树/创建 |
| PUT/DELETE | `/collections/{id}` | 更新/删除 |
| POST/DELETE | `/collections/{id}/papers` | 加入/移除文献 |

---

## 提示词

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/prompts` | 列表/创建 |
| GET | `/prompts/{id}` | 详情 |
| PUT | `/prompts/{id}` | 内容变更创建新版本 |
| POST | `/prompts/{id}/activate` | 设为当前 |
| POST | `/prompts/{id}/set-default` | 设为默认 |
| POST | `/prompts/{id}/duplicate` | 复制 |
| DELETE | `/prompts/{id}` | 归档（默认提示词不可归档） |

---

## 设置与维护

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/settings` | 设置（密钥掩码）、服务商预设、监听状态 |
| PUT | `/settings` | 保存设置（`{values:{...}}`） |
| GET | `/settings/providers` | Provider 预设 |
| POST | `/settings/test-ai` | 连接测试 |
| GET | `/settings/storage` | 数据目录占用 |
| POST | `/settings/watch/start` / `stop` | 目录监听启停 |
| GET | `/settings/watch/status` | 监听状态 |

设置项键名与默认值见 `backend/app/database/init_db.py` 的 `DEFAULT_SETTINGS`。

---

## 导出与备份

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/exports` | 同步导出（csv/xlsx/json/markdown/ris/bibtex/notes_md） |
| POST | `/exports/async` | 将批量导出放入持久化后台队列 |
| GET | `/exports` | 导出历史 |
| GET | `/exports/files/{filename}` | 下载 |
| POST | `/exports/backup` | 同步备份 |
| POST | `/exports/backup/async` | 入队备份 |
| GET | `/exports/backups` | 备份列表 |
| GET | `/exports/backups/{filename}` | 下载备份 |

导出请求：

```json
{
  "format": "markdown",
  "paper_ids": [],
  "filters": { "review_status": "included", "year": 2024, "q": "边坡" },
  "include_notes": true,
  "include_analysis": true
}
```

`paper_ids` 非空时优先；否则按 filters 选择。导出不包含 PDF 全文。
