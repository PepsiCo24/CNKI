import { expect, test, type Page } from '@playwright/test'

const consoleErrors: string[] = []

test.beforeEach(async ({ page }) => {
  consoleErrors.length = 0
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => consoleErrors.push(error.message))
})

test.afterEach(async () => {
  const fatal = consoleErrors.filter((message) => !message.includes('favicon'))
  expect(fatal, `浏览器控制台错误：\n${fatal.join('\n')}`).toEqual([])
})

test('九个主页面均能真实加载数据', async ({ page }) => {
  await page.goto('/dashboard')
  await expect(page.locator('h1')).toHaveText('研究总览')
  await expect(page.locator('.stat-card')).toHaveCount(6)

  const pages = [
    ['文献检索', '文献检索'],
    ['下载与导入', '下载与导入任务'],
    ['文件管理', '文件管理'],
    ['AI 分析中心', 'AI 分析中心'],
    ['待审核', '审核工作台'],
    ['我的文献库', '我的文献库'],
    ['创新点库', '创新点库'],
    ['设置', '设置中心'],
  ]
  for (const [nav, heading] of pages) {
    await page.getByRole('link', { name: nav, exact: true }).click()
    await expect(page.locator('h1')).toHaveText(heading)
  }
})

test('审核工作台：加载真实文献、PDF 渲染、快捷键入库', async ({ page, request }) => {
  const search = await request.get('/api/papers', { params: { q: '改进随机森林', page_size: 5 } })
  expect(search.ok()).toBeTruthy()
  const body = await search.json()
  const paper = body.data.items[0]
  expect(paper?.id).toBeTruthy()

  // Make the scenario repeatable: undo a previous inclusion if it exists.
  await request.post(`/api/review/${paper.id}/undo`, { data: {} })
  const reset = await request.get(`/api/papers/${paper.id}`)
  expect((await reset.json()).data.review_status).toBe('pending_review')

  await page.goto('/review')
  await expect(page.getByText(paper.title, { exact: false }).first()).toBeVisible()
  await expect(page.getByText('AI 快速筛选结论')).toBeVisible()
  await expect(page.getByText('待人工审核').first()).toBeVisible()

  await page.waitForFunction(() => {
    const canvas = document.querySelector('.pdf-page-shell canvas') as HTMLCanvasElement | null
    return Boolean(canvas && canvas.width > 300)
  })
  await page.waitForFunction(() => document.querySelectorAll('.pdf-text-layer span').length > 0)

  await page.locator('body').click({ position: { x: 5, y: 300 } })
  await page.keyboard.press('Control+Enter')
  await expect(page.locator('.el-message').filter({ hasText: '已入库' })).toBeVisible()
  await expect(page.getByText('没有待审核文献')).toBeVisible()

  await page.goto('/library')
  await expect(page.getByText(paper.title, { exact: false }).first()).toBeVisible()
})

test('文献详情抽屉：PDF 渲染与文本层可复制', async ({ page, request }) => {
  // Keep this test independent from ordering: ensure the sample paper is in the library.
  const search = await request.get('/api/papers', { params: { q: '改进随机森林', page_size: 5 } })
  const paper = (await search.json()).data.items[0]
  const detail = await request.get(`/api/papers/${paper.id}`)
  if ((await detail.json()).data.review_status !== 'included') {
    await request.post(`/api/review/${paper.id}/action`, { data: { action: 'include' } })
  }

  await page.goto('/library')
  await page.getByText('查看详情').first().click()
  await expect(page.locator('.el-drawer')).toBeVisible()
  await expect(page.locator('.el-drawer').getByText('一句话总结')).toBeVisible()
  await page.locator('.el-drawer').getByText('PDF 原文', { exact: true }).click()
  await page.waitForFunction(() => {
    const canvas = document.querySelector('.el-drawer .pdf-page-shell canvas') as HTMLCanvasElement | null
    return Boolean(canvas && canvas.width > 300)
  })
  await expect(page.locator('.el-drawer .pdf-text-layer span').first()).toBeAttached()
})

test('设置中心：Mock 模型连接测试与提示词版本页面', async ({ page }) => {
  await page.goto('/settings')
  await expect(page.getByText('离线演示模型（Mock）').first()).toBeVisible()
  await page.getByRole('button', { name: '测试连接' }).click()
  await expect(page.locator('.el-alert').filter({ hasText: '连接成功' }).first()).toBeVisible()
  await page.getByRole('tab', { name: '提示词版本' }).click()
  await expect(
    page.locator('.el-tab-pane').filter({ hasText: '分析提示词' }).getByText('默认科研论文分析提示词').last(),
  ).toBeVisible()
})

test('亮暗主题切换持久化', async ({ page }) => {
  await page.goto('/dashboard')
  const html = page.locator('html')
  const before = await html.getAttribute('class')
  const wasDark = (before || '').includes('dark')
  await page.getByRole('button', { name: wasDark ? '切换到亮色' : '切换到暗色' }).click()
  await expect(html).toHaveClass(wasDark ? /^(?!.*dark).*/ : /dark/)
  await page.reload()
  await expect(html).toHaveClass(wasDark ? /^(?!.*dark).*/ : /dark/)
})
