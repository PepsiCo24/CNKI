# 静默抓取与本地一键启动 — 设计文档

**日期：** 2026-11-02  
**状态：** 待用户审阅  
**仓库目标：** https://github.com/PepsiCo24/CNKI  

## 1. 背景与目标

在现有合规边界内强化「知网账号标识配置 + 检索条件（来源、时间段）→ 本地静默管道 → 任务库 → AI 创新点 → 人工审核入库」体验。用户点击「静默抓取」后，界面只显示分阶段进度条；不自动登录知网、不无头抓取官网、不调用未授权接口。

部署形态为**纯本地**：配置与数据在本机；提供 Windows `.bat` 与 macOS/Linux `.sh` 一键启动；源码推送到 GitHub。不使用 GitHub Pages 承载业务（Pages 无法运行 FastAPI / SQLite / 目录监听）。

## 2. 合规边界（硬约束）

允许：

- 设置中记录知网账号标识（用户名/机构/备注），仅作本机标识
- 生成检索条件单（文献来源、主题、发表时间段等）
- 监听/扫描用户配置的本地导入目录中的官方导出题录与合法下载全文
- 按任务条件过滤、去重、写入 SQLite 任务文献库，并排队 AI / 人工审核

禁止：

- 无头浏览器或脚本自动登录知网
- 验证码绕过、私有接口猜测、未授权批量下载
- 跳过人工审核自动进入正式文献库

数据来源：用户事先在知网官网按条件单检索并官方导出/下载到导入目录（或浏览器下载到该目录）。

## 3. 用户流程

```
设置账号标识 + 导入目录
        ↓
创建检索任务（必填：文献来源、起止日期）
        ↓
点击「静默抓取」
        ↓
进度：等待文件 → 扫描过滤 → 写入任务库 → 排队 AI
        ↓
人工审核 → 正式入库
```

成功标准：点击后无文件夹选择框打断；仅进度与计数变化；符合条件的题录/全文进入任务库；有全文且开启 `ai.auto_analyze` 时自动排队分析；正式库仍须人工审核。

## 4. 架构

### 4.1 编排层：CaptureSession

新建会话实体（表名建议 `capture_sessions`），挂在 `search_tasks` 下，负责编排与进度聚合；实际导入/解析/AI 仍走现有 `ImportJob`、`BackgroundJob`、文件服务与 AI 队列。

| 字段 | 说明 |
| --- | --- |
| id | 主键 |
| task_id | 关联检索任务 |
| status | 见阶段枚举 |
| stage | waiting_files / scanning / importing / ai_queued / ready_for_review / timed_out / cancelled / failed |
| progress | 0–100 聚合进度 |
| counts | JSON：discovered / imported / skipped / duplicates / failed / ai_queued / ai_completed |
| import_job_id | 当前或最近一次扫描任务 |
| error_message | 失败原因 |
| wait_timeout_seconds | 默认 1800（30 分钟） |
| started_at / finished_at | 时间戳 |

同一任务同时最多一个活跃会话（pending/running/waiting）；重复点击返回已有会话或先取消再开。

### 4.2 阶段语义

| 阶段 | 行为 | 进度示意 |
| --- | --- | --- |
| waiting_files | 确保目录监听开启；轮询/事件驱动发现新文件 | 不定/缓动 0–15% |
| scanning | 列出可导入文件 | 15–30% |
| importing | 题录解析 + 全文接管，按期刊/日期过滤 | 30–75% |
| ai_queued | 解析完成且 auto_analyze 时排队；聚合该任务下 AI 状态 | 75–95% |
| ready_for_review | 本轮导入结束，可去审核 | 100% |
| timed_out / cancelled / failed | 终态；已导入数据保留 | 保持或标记失败 |

空目录：停留在 `waiting_files` 直至超时或取消，**不**立即以「完成 0 条」结束。

### 4.3 与现有模块关系

- `queue_folder_scan` / `scan_directory`：执行扫描与导入
- `watch_service`：等待阶段保持监听；事件触发扫描时更新会话
- `ai.auto_analyze`：导入解析后自动排队（已有行为，会话只聚合进度）
- 审核工作台：不变；`review_status` 仍由人工决定是否正式入库

## 5. 设置与前置校验

静默抓取启动前必须满足，否则 HTTP 400 + 前端禁用按钮：

1. `cnki.account_username` 非空（账号标识）
2. 导入目录存在且为目录（`data.import_dir` 或默认 `data/imports`）
3. 任务 `journal`（文献来源）非空
4. 任务 `start_date` 与 `end_date` 均已设置且 `start_date <= end_date`

设置页「知网接入」展示已配置/未配置；保存后任务页按钮状态刷新。不新增知网密码字段（避免暗示自动登录）。

## 6. API

前缀建议：`/api/search-tasks/{task_id}/silent-capture`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `` | 校验前置 → 创建或复用活跃会话 → 开监听 → 进入 waiting_files |
| GET | `` | 返回会话：stage、progress、counts、error、updated_at |
| POST | `/cancel` | 取消等待/扫描；标记 cancelled |

可选：`GET .../silent-capture/history` 不在 MVP。

响应示例字段：`session_id`、`task_id`、`stage`、`status`、`progress`、`counts`、`message`（阶段人可读文案）。

## 7. 前端

- 检索任务详情主 CTA：「静默抓取」
- 点击后展示进度面板（非模态打断也可，但避免额外确认框与文件选择器）
- 轮询 GET（建议 1–2s）；阶段文案与百分比
- 终态 `ready_for_review`：提示「去审核」；`timed_out`/`failed`：可重试
- 条件单/打开知网链接保留为次要操作，不作为静默抓取必经弹窗

## 8. 一键启动脚本

| 平台 | 入口 | 行为 |
| --- | --- | --- |
| macOS / Linux | `scripts/start.sh` | 无 venv/前端构建则先 setup/build；启动 `127.0.0.1:8000`；支持 `OPEN_BROWSER=1` |
| Windows | `scripts/start.bat` | 创建 `.env`、venv、装依赖、build 前端、启动并打开浏览器 |
| 文档 | README | 克隆后执行上述脚本；数据在 `data/`；勿提交密钥 |

强化点：统一端口/数据目录提示、失败时可读错误、Mac 可说明 `OPEN_BROWSER=1 ./scripts/start.sh`。可选增加根目录 `start.command`（双击）——若增加须与 `start.sh` 行为一致。

## 9. GitHub 发布

1. 初始化 git（若尚未初始化）
2. `.gitignore` 排除：`.env`、`data/`（除示例说明）、`.venv`、`node_modules`、`frontend/dist` 可按现有策略、密钥目录
3. 推送到 `https://github.com/PepsiCo24/CNKI`
4. README 更新：静默抓取说明 + 一键启动；明确非 Pages 部署

不包含：公网后端、GitHub Pages 业务站、EXE 安装包（仍按现有 Windows 打包文档预留）。

## 10. 错误处理与恢复

- 校验失败：不创建会话
- 等待超时：`timed_out`；已导入保留；可再次静默抓取
- 单文件失败：计入 `failed`，不中断批次
- 取消：停止等待与新扫描；进行中 AI 遵循现有 cancel 语义
- 进程重启：从 SQLite 恢复未完成会话；监听按 `data.watch_enabled` 恢复

## 11. 测试与验收

**自动化**

- 前置校验（缺账号/目录/来源/日期）
- 空目录保持 waiting_files；放入符合条件 RIS/PDF 后进入导入并更新 counts
- 不符合来源/时间的记录跳过
- 取消与超时状态
- 回归：题录导入、扫描、auto_analyze、人工审核

**手工验收**

1. 配置账号与导入目录 → 建任务 → 静默抓取见「等待文件」
2. 放入官方导出样例 → 进度走完 → 审核页可见分析/待审
3. `start.sh` / `start.bat` 可启动本机服务
4. 仓库已推送到 PepsiCo24/CNKI

## 12. 非目标（本迭代不做）

- 知网自动登录 / 无头抓取 / 授权 API 真实端点实现
- 自动跳过人工审核入库
- GitHub Pages 或云端多租户部署
- 改写 AI 分析 Schema 或审核工作台主流程

## 13. 实现顺序建议

1. 数据模型 + Alembic/启动建表 + 会话服务
2. API + 与 scan/watch/AI 进度聚合
3. 前端静默抓取进度 UI + 设置联动
4. 脚本与 README 强化
5. 测试 + 推送 GitHub
