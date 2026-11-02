import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: '/', redirect: '/dashboard' },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/pages/DashboardPage.vue'),
      meta: { title: '仪表盘', subtitle: '本地文献库与 AI 分析总览' },
    },
    {
      path: '/search-tasks',
      name: 'search-tasks',
      component: () => import('@/pages/SearchTasksPage.vue'),
      meta: { title: '文献检索', subtitle: '按期刊来源、主题与日期创建检索任务' },
    },
    {
      path: '/imports',
      name: 'imports',
      component: () => import('@/pages/ImportTasksPage.vue'),
      meta: { title: '下载与导入任务', subtitle: '题录文件、本地全文接管与目录监听' },
    },
    {
      path: '/files',
      name: 'files',
      component: () => import('@/pages/FilesPage.vue'),
      meta: { title: '文件管理', subtitle: '期刊 / 年份目录树与文献状态管理' },
    },
    {
      path: '/ai',
      name: 'ai',
      component: () => import('@/pages/AiCenterPage.vue'),
      meta: { title: 'AI 分析中心', subtitle: '模型调用、分块解析与结构化结果' },
    },
    {
      path: '/review',
      name: 'review',
      component: () => import('@/pages/ReviewPage.vue'),
      meta: { title: '待审核', subtitle: 'AI 辅助筛选，人工决定是否入库' },
    },
    {
      path: '/library',
      name: 'library',
      component: () => import('@/pages/LibraryPage.vue'),
      meta: { title: '我的文献库', subtitle: '已通过人工审核的正式文献' },
    },
    {
      path: '/innovations',
      name: 'innovations',
      component: () => import('@/pages/InnovationsPage.vue'),
      meta: { title: '创新点库', subtitle: '逐条浏览、检索与备注论文创新点' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/pages/SettingsPage.vue'),
      meta: { title: '设置', subtitle: '数据目录、知网接入、模型与审核偏好' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || 'CNKI Scholar AI'
  document.title = `${title} · CNKI Scholar AI`
})

export default router
