# Windows EXE 打包技术方案

第一阶段保持「Vue 前端 + FastAPI 后端 + 本地 HTTP」的解耦架构。第二阶段可以采用：

```
Electron 主进程 + Vue 构建产物 + PyInstaller FastAPI Sidecar + SQLite
```

本文给出可执行的打包路线、sidecar 生命周期、数据目录选择与验收清单。当前仓库尚未生成 Windows 安装包，也未在 Windows 真机验证；以下为实施蓝图。

---

## 1. 目标产物

```
CNKI Scholar AI Setup.exe
  └─ 安装目录/
     ├─ CNKI Scholar AI.exe        (Electron)
     ├─ resources/
     │  ├─ app.asar               (Electron 主进程 + preload)
     │  ├─ web/                   (Vue dist)
     │  └─ sidecar/
     │     ├─ cnki-sidecar.exe    (PyInstaller)
     │     └─ _internal/          (依赖)
     └─ ...
```

用户数据不放在安装目录：

```
%USERPROFILE%\Documents\CNKI Scholar AI\  (或用户自选)
  database/ papers/ imports/ metadata/ ai_results/ exports/ backups/ logs/ temp/ keys/
```

---

## 2. Sidecar 入口

仓库已提供 `backend/sidecar.py`：

- 在导入 `app.main` **之前**设置 `CNKI_DATA_DIR`，因为配置与数据库引擎在导入时创建。
- 参数：`--host 127.0.0.1 --port <free> --data-dir <path> --log-level INFO`。
- 使用 uvicorn 启动，不开启 access log，日志写入 `data/logs/app.log`。

本地验证：

```bash
.venv/bin/python backend/sidecar.py --port 8765 --data-dir ./data
curl http://127.0.0.1:8765/api/health
```

---

## 3. PyInstaller 打包

在 **Windows** 机器（或 Windows CI runner）上执行，macOS 不能交叉生成 Windows exe。

### 3.1 安装

```bat
py -3.12 -m venv .venv-win
call .venv-win\Scripts\activate
pip install -e ".[dev]" pyinstaller
```

### 3.2 `backend_sidecar.spec`

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], ["app"]
for package in ["pymupdf", "pdfplumber", "alembic", "uvicorn", "watchdog", "cryptography", "openpyxl"]:
    try:
        d, b, h = collect_all(package)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass
hiddenimports += collect_submodules("app")
hiddenimports += ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"]

a = Analysis(
    ["backend/sidecar.py"],
    pathex=["backend"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pandas", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="cnki-sidecar",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # 生产用 False；排障时可改 True 查看 stdout
    icon="assets/cnki.ico",
)
```

构建：

```bat
pyinstaller --noconfirm --clean backend_sidecar.spec
```

建议输出 one-folder（`dist/cnki-sidecar/`），启动更快、杀软误报更少；one-file 首次启动解压慢，不推荐。

### 3.3 常见打包问题

| 问题 | 处理 |
| --- | --- |
| `pymupdf` 缺 DLL | `collect_all("pymupdf")`，确认 `_internal/pymupdf` |
| Alembic 找不到脚本 | 将 `backend/alembic` 与 `alembic.ini` 作为 datas 打包，或改用 `init_db()` 建表（本项目启动会自动建表） |
| uvicorn 动态协议导入失败 | 显式 hiddenimports（见 spec） |
| SQLite FTS5 缺失 | 使用 Python 官方 Windows 安装包（自带 FTS5），不要用精简版 |
| 中文路径失败 | 全程使用 `Path`/`os.fspath`；测试含空格与中文用户名 |
| 杀软误报 | 代码签名；避免 UPX；提交误报 |

---

## 4. Electron 主进程

### 4.1 选择空闲端口

```js
// electron/main.js
const net = require('node:net')
function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
    server.on('error', reject)
  })
}
```

### 4.2 启动 sidecar + 健康检查

```js
const { app, BrowserWindow, dialog } = require('electron')
const { spawn } = require('node:child_process')
const path = require('node:path')
const fs = require('node:fs')
const http = require('node:http')

let sidecar = null
let dataDir = ''

async function waitForHealth(port, timeoutMs = 30000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const ok = await new Promise((resolve) => {
      const req = http.get({ host: '127.0.0.1', port, path: '/api/health', timeout: 1000 }, (res) => {
        res.resume()
        resolve(res.statusCode === 200)
      })
      req.on('error', () => resolve(false))
      req.on('timeout', () => { req.destroy(); resolve(false) })
    })
    if (ok) return true
    await new Promise((r) => setTimeout(r, 400))
  }
  throw new Error('sidecar health check timeout')
}

async function startSidecar() {
  const port = await getFreePort()
  const exe = app.isPackaged
    ? path.join(process.resourcesPath, 'sidecar', 'cnki-sidecar.exe')
    : path.join(__dirname, '..', 'dist-sidecar', 'cnki-sidecar.exe')
  dataDir = require('./data-dir').getDataDir(app) // 用户设置或默认 Document 目录
  sidecar = spawn(exe, ['--host', '127.0.0.1', '--port', String(port), '--data-dir', dataDir], {
    windowsHide: true,
    stdio: 'ignore',
  })
  sidecar.on('exit', (code) => console.log('sidecar exited', code))
  await waitForHealth(port)
  return `http://127.0.0.1:${port}`
}

app.whenReady().then(async () => {
  const apiBase = await startSidecar()
  const win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 720,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  })
  // 生产：加载打包的 Vue 静态文件，并把 API 指向随机端口
  await win.loadFile(path.join(process.resourcesPath, 'web', 'index.html'))
  win.webContents.executeJavaScript(`window.__CNKI_API_BASE__ = ${JSON.stringify(apiBase)}`)
})

app.on('before-quit', () => {
  if (sidecar && !sidecar.killed) sidecar.kill()
})
```

> 静态文件方式需要前端 Axios baseURL 支持 `window.__CNKI_API_BASE__`，或由 Electron 启动一个本地静态服务并反向代理 `/api`。更简单的方案：Electron 直接加载 `http://127.0.0.1:<port>`，由 FastAPI 提供已构建的 `frontend/dist`（本项目已支持），代价是页面刷新会重新加载，但实现最稳。

推荐 Electron 直接：

```js
await win.loadURL(apiBase)
```

这样 `/api` 同源、PDF iframe、下载、CORS 全部自然工作。

### 4.3 用户选择数据目录

首次启动显示向导：

1. 默认 `%USERPROFILE%\Documents\CNKI Scholar AI`。
2. 允许选择其他目录。
3. 写入 Electron `userData/settings.json`。
4. 若目录已有 `database/cnki_scholar.db`，提示“检测到已有文献库，是否继续使用”。

不要在安装目录写数据（Program Files 无写权限）。

### 4.4 退出与崩溃

- `before-quit`：先请求 `/api/system/info` 确认无任务，再 `sidecar.kill()`；或直接 kill，任务队列会在下次启动恢复（项目已实现）。
- 设置 10 秒兜底 `taskkill /PID /T /F`。
- 子进程崩溃时弹出错误并提供“查看日志”，日志路径 `<data-dir>/logs/app.log`。

---

## 5. electron-builder 配置

```json
{
  "appId": "com.local.cnki.scholar",
  "productName": "CNKI Scholar AI",
  "directories": { "output": "release" },
  "files": ["electron/**", "dist-web/**", "package.json"],
  "extraResources": [
    { "from": "dist/cnki-sidecar", "to": "sidecar" },
    { "from": "frontend/dist", "to": "web" }
  ],
  "win": {
    "target": [{ "target": "nsis", "arch": ["x64"] }],
    "icon": "assets/cnki.ico",
    "signAndEditExecutable": false
  },
  "nsis": {
    "oneClick": false,
    "allowToChangeInstallationDirectory": true,
    "perMachine": false,
    "createDesktopShortcut": true,
    "shortcutName": "CNKI Scholar AI"
  }
}
```

构建：

```bat
npm run build:web
pyinstaller --noconfirm --clean backend_sidecar.spec
npx electron-builder --win nsis
```

输出：`release/CNKI Scholar AI Setup x.y.z.exe`。

---

## 6. 数据与升级

- 应用升级不覆盖数据目录。
- 升级涉及 schema 时：
  - 启动 sidecar 前执行 `alembic upgrade head`（把 `alembic/` 与 `alembic.ini` 打包，或内置迁移执行器）；
  - 迁移前自动创建 `backups/pre_upgrade_<version>.zip`。
- 保留旧版本安装包与回滚说明。

本项目当前启动使用 `Base.metadata.create_all` + 幂等种子；正式发布前建议切换为“先迁移、后启动”，并保留 `create_all` 仅用于全新库。

---

## 7. Windows 验收清单

- [ ] 安装到含中文与空格的路径（如 `D:\科研工具\CNKI`）。
- [ ] 首次启动选择数据目录，权限正常。
- [ ] 冷启动 < 8 秒（SSD）。
- [ ] 导入 RIS 与 PDF，归档路径正确。
- [ ] 打开含中文的 PDF，文本层可复制。
- [ ] DeepSeek / Ollama 连接测试成功；Key 不出现在日志。
- [ ] 分析任务运行中关闭应用，重启后任务恢复。
- [ ] 目录监听在 Windows 上正常工作（含 OneDrive 目录）。
- [ ] 防火墙未拦截（仅 127.0.0.1 监听）。
- [ ] 杀毒软件扫描无隔离。
- [ ] 卸载后用户数据保留，重新安装可继续使用。

---

## 8. 当前状态

- 已提供 `backend/sidecar.py` 与前后端解耦架构。
- 尚未编写 Electron 工程、PyInstaller spec 文件与安装包；本文件为实现方案，不代表已完成 Windows 交付。
- 建议在 Windows 11 + Python 3.12 + Node 20 的干净虚拟机完成首次打包验证。
