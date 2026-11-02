/**
 * Record an end-to-end product demo with Playwright page video.
 *
 * Output: docs/demo/cnki-scholar-ai-demo.webm
 * Requires: backend at http://127.0.0.1:8000 and Chrome installed.
 */
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:8000'
const ROOT = resolve(import.meta.dirname, '..', '..')
const OUT_DIR = resolve(ROOT, 'docs', 'demo')
const WEBM = resolve(OUT_DIR, 'cnki-scholar-ai-demo.webm')
mkdirSync(OUT_DIR, { recursive: true })

async function api(path, options = {}) {
  const response = await fetch(`${BASE}/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!response.ok && response.status !== 404) {
    console.warn('API warning', path, response.status, await response.text())
  }
  return response.status === 204 ? null : response.json().catch(() => null)
}

async function prepareDemoState() {
  await api('/settings', {
    method: 'PUT',
    body: JSON.stringify({ values: { 'app.theme': 'light' } }),
  })
  const list = await api('/papers?q=' + encodeURIComponent('改进随机森林') + '&page_size=5')
  const paper = list?.data?.items?.[0]
  if (!paper) return null
  const detailBefore = await api(`/papers/${paper.id}`)
  if (detailBefore?.data?.review_status === 'included') {
    await api(`/review/${paper.id}/undo`, { method: 'POST', body: '{}' })
  }
  const detail = await api(`/papers/${paper.id}`)
  if (detail?.data?.review_status !== 'pending_review') {
    console.warn('Paper is not in pending_review; demo queue may be empty:', detail?.data?.review_status)
  }
  return paper
}

function installOverlay() {
  const install = () => {
    if (document.getElementById('__demo_caption')) return
    const style = document.createElement('style')
    style.textContent = `
      #__demo_caption {
        position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
        z-index: 2147483647; display: flex; align-items: center; gap: 10px;
        max-width: min(780px, 82vw); padding: 8px 16px 8px 9px;
        background: rgba(15, 23, 42, 0.94); color: #f8fafc;
        border: 1px solid rgba(255,255,255,.14); border-radius: 10px;
        box-shadow: 0 12px 40px rgba(0,0,0,.38); pointer-events: none;
        font: 500 13px/1.45 -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
        backdrop-filter: blur(8px);
      }
      #__demo_step {
        flex: none; background: #3a68f5; color: white; border-radius: 6px;
        padding: 2px 7px; font-size: 10.5px; font-weight: 700; letter-spacing: .04em;
      }
      #__demo_text { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      #__demo_cursor {
        position: fixed; left: 0; top: 0; width: 17px; height: 17px;
        margin-left: -8.5px; margin-top: -8.5px; border-radius: 50%;
        border: 2px solid #fff; background: rgba(58,104,245,.75);
        box-shadow: 0 0 0 4px rgba(58,104,245,.22), 0 2px 8px rgba(0,0,0,.3);
        z-index: 2147483647; pointer-events: none;
        transition: left .34s ease, top .34s ease, transform .1s ease, background .1s ease;
      }
      #__demo_cursor.click { transform: scale(.68); background: #f59e0b; }
    `
    document.head.appendChild(style)
    const caption = document.createElement('div')
    caption.id = '__demo_caption'
    caption.innerHTML = '<span id="__demo_step">DEMO</span><span id="__demo_text"></span>'
    document.body.appendChild(caption)
    const cursor = document.createElement('div')
    cursor.id = '__demo_cursor'
    document.body.appendChild(cursor)
    window.__demo = {
      caption(step, text) {
        const stepEl = document.getElementById('__demo_step')
        const textEl = document.getElementById('__demo_text')
        if (stepEl) stepEl.textContent = step
        if (textEl) textEl.textContent = text
      },
      move(x, y) {
        const el = document.getElementById('__demo_cursor')
        if (!el) return
        el.style.left = `${x}px`
        el.style.top = `${y}px`
        el.classList.remove('click')
      },
      pulse() {
        const el = document.getElementById('__demo_cursor')
        if (!el) return
        el.classList.add('click')
        setTimeout(() => el.classList.remove('click'), 130)
      },
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install)
  } else {
    install()
  }
}

async function setCaption(page, step, text) {
  await page.evaluate(({ step, text }) => window.__demo?.caption(step, text), { step, text })
}

async function moveTo(page, locator) {
  try {
    await locator.scrollIntoViewIfNeeded({ timeout: 3000 })
    const box = await locator.boundingBox({ timeout: 3000 })
    if (!box) return
    await page.evaluate(
      ({ x, y }) => window.__demo?.move(x, y),
      { x: box.x + box.width / 2, y: box.y + box.height / 2 },
    )
    await page.waitForTimeout(420)
  } catch {
    /* best-effort cursor animation */
  }
}

async function click(page, locator, wait = 700) {
  await moveTo(page, locator)
  await page.evaluate(() => window.__demo?.pulse())
  await locator.click()
  await page.waitForTimeout(wait)
}

async function pause(page, ms) {
  await page.waitForTimeout(ms)
}

async function main() {
  const paper = await prepareDemoState()
  if (!paper) throw new Error('No sample paper found; import examples/sample_metadata.ris first.')

  const browser = await chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--hide-scrollbars', '--force-device-scale-factor=1'],
  })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    recordVideo: { dir: OUT_DIR, size: { width: 1440, height: 900 } },
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  })
  const page = await context.newPage()
  const video = page.video()
  page.on('pageerror', (error) => console.warn('PAGE ERROR:', error.message))
  await page.addInitScript(installOverlay)

  try {
    await page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle' })
    await page.waitForSelector('.stat-card')
    await page.waitForTimeout(1400)
    await setCaption(page, '01', '本地科研工作台：文献、全文、AI 分析与待审核总览')
    await pause(page, 2400)

    await click(page, page.getByRole('link', { name: '文献检索', exact: true }), 900)
    await setCaption(page, '02', '文献检索：期刊来源与主题关键词严格区分')
    await pause(page, 1300)
    await click(page, page.getByRole('button', { name: '条件单', exact: true }), 1200)
    await setCaption(page, '03', '条件单：岩土力学作为“文献来源”，2023–2025 完整日期范围')
    await pause(page, 1800)
    const drawer = page.locator('.el-drawer')
    await drawer.evaluate((el) => el.querySelector('.el-drawer__body')?.scrollBy({ top: 280 }))
    await pause(page, 1600)
    await click(page, page.locator('.el-drawer__close-btn').first(), 900)

    await click(page, page.getByRole('link', { name: '下载与导入', exact: true }), 900)
    await setCaption(page, '04', '题录导入 + 本地全文接管：官方导出 RIS，PDF 自动归档')
    await pause(page, 2200)

    await click(page, page.getByRole('link', { name: '文件管理', exact: true }), 900)
    await setCaption(page, '05', '三栏文件管理：期刊 / 年份目录树，状态与详情联动')
    await pause(page, 1500)
    await click(page, page.getByText(paper.title, { exact: false }).first(), 900)
    await click(page, page.getByRole('button', { name: '完整详情', exact: true }), 1400)
    await setCaption(page, '06', '元数据、原始摘要、AI 分析与人工笔记集中在同一文献详情')
    await pause(page, 1900)
    await click(page, page.locator('.el-drawer__close-btn').first(), 800)

    await click(page, page.getByRole('link', { name: 'AI 分析中心', exact: true }), 900)
    await setCaption(page, '07', 'AI 分析中心：结构化结果、缓存、Token 与费用统计')
    await pause(page, 2200)

    await click(page, page.getByRole('link', { name: '待审核', exact: true }), 1000)
    await setCaption(page, '08', '人工审核：AI 只提供参考，入库必须由人确认')
    await pause(page, 1200)
    await click(page, page.getByText(paper.title, { exact: false }).first(), 1200)
    await setCaption(page, '09', '一句话总结、创新点、研究局限与原文 PDF 同屏核对')
    await pause(page, 1800)
    const rightPanel = page.locator('aside.panel').last()
    await click(page, rightPanel.getByRole('button', { name: '入库', exact: true }), 800)
    await setCaption(page, '10', '点击“入库”后进入正式文献库，并保留审核记录')
    await pause(page, 900)

    await click(page, page.getByRole('link', { name: '我的文献库', exact: true }), 900)
    await setCaption(page, '11', '正式文献库：仅显示人工审核通过的文献')
    await pause(page, 1200)
    const searchInput = page.getByPlaceholder('搜索标题、作者、摘要、AI 创新点（全文索引）')
    await click(page, searchInput, 300)
    await page.keyboard.type('随机森林', { delay: 130 })
    await pause(page, 1300)
    await setCaption(page, '12', '标题 / 摘要 / AI 创新点全文检索（SQLite FTS5）')
    await pause(page, 1000)
    await click(page, page.getByText('查看详情', { exact: true }).first(), 1200)
    await click(page, page.locator('.el-drawer .el-tabs__item').filter({ hasText: 'PDF 原文' }).first(), 900)
    await page.waitForFunction(
      () => {
        const canvas = document.querySelector('.el-drawer .pdf-page-shell canvas')
        return Boolean(canvas && canvas.width > 300)
      },
      null,
      { timeout: 15000 },
    )
    await setCaption(page, '13', 'PDF.js 在线阅读：页码跳转、缩放与文本层复制')
    await pause(page, 2200)
    await click(page, page.locator('.el-drawer__close-btn').first(), 800)

    await click(page, page.getByRole('link', { name: '创新点库', exact: true }), 900)
    await setCaption(page, '14', '创新点库：逐条证据、页码、标签与个人备注')
    await pause(page, 2200)

    await click(page, page.getByRole('link', { name: '设置', exact: true }), 900)
    await setCaption(page, '15', '设置中心：DeepSeek / 通义千问 / OpenAI 兼容 / Ollama')
    await pause(page, 1200)
    await click(page, page.getByRole('button', { name: '测试连接', exact: true }), 1000)
    await pause(page, 1400)
    await setCaption(page, '16', 'API Key 本地加密存储；支持离线 Mock 与真实模型')
    await pause(page, 1400)
    const themeButton = page.getByRole('button', { name: '切换到暗色' })
    if (await themeButton.count()) {
      await click(page, themeButton.first(), 1500)
      await setCaption(page, '17', '亮色 / 暗色主题即时切换')
      await pause(page, 2400)
      await click(page, page.getByRole('button', { name: '切换到亮色' }).first(), 1200)
      await setCaption(page, '18', '所有文献、分析结果与审核记录均保存在本地')
      await pause(page, 1200)
    }

    await click(page, page.getByRole('link', { name: '仪表盘', exact: true }), 1200)
    await setCaption(page, '✓', '完整闭环：检索 → 导入 → 解析 → AI 分析 → 人工审核 → 入库 → 检索')
    await pause(page, 3200)
  } finally {
    await context.close()
    if (video) {
      await video.saveAs(WEBM)
      console.log(`Saved ${WEBM}`)
    }
    await browser.close()
  }
}

main().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
