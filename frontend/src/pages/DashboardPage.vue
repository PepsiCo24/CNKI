<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { dashboardApi } from '@/api'
import type { DashboardData } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const app = useAppStore()
const data = ref<DashboardData | null>(null)
const loading = ref(true)
let timer: number | undefined

const stats = computed(() => {
  const p = data.value?.papers
  if (!p) return []
  return [
    { label: '总文献', value: p.total, icon: 'Files', hint: `${p.pending_fulltext} 篇待获取全文`, color: '#3A68F5' },
    { label: '已获取全文', value: p.fulltext, icon: 'DocumentChecked', hint: p.total ? `覆盖率 ${Math.round((p.fulltext / p.total) * 100)}%` : '暂无文献', color: '#0D9488' },
    { label: 'AI 已完成分析', value: p.analyzed, icon: 'MagicStick', hint: `${p.failed} 篇分析失败`, color: '#7C6BD6' },
    { label: '待人工审核', value: p.pending_review, icon: 'View', hint: 'AI 结果需人工确认', color: '#D97706' },
    { label: '已入库', value: p.included, icon: 'Collection', hint: `${p.excluded} 篇暂不采用`, color: '#16A34A' },
    { label: '创新点条目', value: p.innovations, icon: 'Opportunity', hint: '来自当前分析版本', color: '#DB2777' },
  ]
})

const maxActivity = computed(() => Math.max(1, ...(data.value?.activity.map((item) => item.count) || [1])))
const mockWarning = computed(() => (data.value?.ai.mock_results || 0) > 0)

async function load() {
  loading.value = true
  try {
    data.value = await dashboardApi.get()
  } finally {
    loading.value = false
  }
}

function goReview() {
  router.push('/review')
}

onMounted(() => {
  load()
  timer = window.setInterval(() => {
    if (document.visibilityState === 'visible') load()
  }, 20_000)
})
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div>
    <PageHeader title="研究总览" subtitle="本地文献库、AI 分析进度与待审核队列" eyebrow="Dashboard">
      <template #actions>
        <el-button @click="router.push('/imports')"><el-icon class="mr-1"><Upload /></el-icon>导入文献</el-button>
        <el-button type="primary" @click="router.push('/search-tasks?create=1')">
          <el-icon class="mr-1"><Plus /></el-icon>新建检索任务
        </el-button>
      </template>
    </PageHeader>

    <div v-loading="loading && !data" class="min-h-[300px]">
      <template v-if="data">
        <div class="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
          <div v-for="stat in stats" :key="stat.label" class="stat-card">
            <div class="flex items-center justify-between">
              <span class="micro">{{ stat.label }}</span>
              <span class="flex h-7 w-7 items-center justify-center rounded-md" :style="{ background: `${stat.color}14`, color: stat.color }">
                <el-icon :size="15"><component :is="stat.icon" /></el-icon>
              </span>
            </div>
            <div class="stat-value" :style="{ color: stat.color }">{{ stat.value }}</div>
            <div class="text-[11px] text-slate-400">{{ stat.hint }}</div>
          </div>
        </div>

        <el-alert v-if="mockWarning" class="!mt-4" type="warning" :closable="false" show-icon>
          <template #title>
            检测到离线 Mock 模拟分析结果（{{ data.ai.mock_results }} 条）。这些结果已明确标记，仅用于流程验收；
            在正式科研筛选前请在设置中配置真实模型并重新分析。
          </template>
        </el-alert>

        <div class="mt-4 grid gap-4 xl:grid-cols-[1.45fr_1fr]">
          <div class="space-y-4">
            <section class="panel p-4">
              <div class="mb-4 flex items-center justify-between">
                <div>
                  <div class="section-title">近 7 天新增文献</div>
                  <div class="mt-0.5 text-[11px] text-slate-400">按导入日期统计，鼠标悬停查看数量</div>
                </div>
                <span class="chip">合计 {{ data.activity.reduce((sum, item) => sum + item.count, 0) }} 篇</span>
              </div>
              <div class="flex h-[150px] items-end gap-2 sm:gap-4">
                <div v-for="item in data.activity" :key="item.date" class="group flex flex-1 flex-col items-center gap-2">
                  <div class="text-[10px] tabular-nums text-slate-400 opacity-0 transition-opacity group-hover:opacity-100">{{ item.count }}</div>
                  <div
                    class="w-full max-w-[46px] rounded-t-md bg-accent-500/85 transition-all group-hover:bg-accent-500"
                    :style="{ height: `${Math.max(6, (item.count / maxActivity) * 108)}px` }"
                    :title="`${item.date}: ${item.count} 篇`"
                  ></div>
                  <div class="text-[10px] text-slate-400">{{ item.date.slice(5) }}</div>
                </div>
              </div>
            </section>

            <section class="panel overflow-hidden">
              <div class="flex items-center justify-between border-b px-4 py-3" :style="{ borderColor: 'var(--app-border)' }">
                <div class="section-title">近期检索任务</div>
                <button class="link" @click="router.push('/search-tasks')">全部任务</button>
              </div>
              <div v-if="!data.recent_tasks.length">
                <EmptyState title="还没有检索任务" description="按期刊来源与日期建立第一个检索任务，导入官方题录或本地全文。" icon="Search">
                  <el-button size="small" type="primary" @click="router.push('/search-tasks?create=1')">新建任务</el-button>
                </EmptyState>
              </div>
              <div v-else class="divide-y" :style="{ borderColor: 'var(--app-border)' }">
                <div
                  v-for="task in data.recent_tasks"
                  :key="task.id"
                  class="flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-[var(--app-panel-soft)]"
                  @click="router.push(`/search-tasks?task=${task.id}`)"
                >
                  <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500 dark:bg-slate-800">
                    <el-icon><Search /></el-icon>
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="truncate text-[13px] font-medium">{{ task.name }}</div>
                    <div class="mt-0.5 truncate text-[11px] text-slate-400">
                      {{ task.journal || '未限定期刊' }} · {{ task.start_date || '不限' }} ~ {{ task.end_date || '不限' }} ·
                      发现 {{ task.discovered_count }} / 全文 {{ task.imported_count }} / 入库 {{ task.included_count }}
                    </div>
                  </div>
                  <StatusTag type="task" :status="task.status" />
                </div>
              </div>
            </section>

            <section class="panel overflow-hidden">
              <div class="flex items-center justify-between border-b px-4 py-3" :style="{ borderColor: 'var(--app-border)' }">
                <div class="section-title">最近导入文献</div>
                <button class="link" @click="router.push('/files')">文件管理</button>
              </div>
              <div v-if="!data.recent_papers.length">
                <EmptyState title="文献库为空" description="可先导入官方导出的 RIS / BibTeX 题录，再关联本地 PDF 全文。" icon="Files" compact />
              </div>
              <div v-else class="divide-y" :style="{ borderColor: 'var(--app-border)' }">
                <div
                  v-for="paper in data.recent_papers"
                  :key="paper.id"
                  class="flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors hover:bg-[var(--app-panel-soft)]"
                  @click="router.push(`/library?paper=${paper.id}`)"
                >
                  <div class="min-w-0 flex-1">
                    <div class="line-clamp-1 text-[13px] font-medium">{{ paper.title }}</div>
                    <div class="mt-0.5 truncate text-[11px] text-slate-400">
                      {{ paper.authors_text || '作者未知' }} · {{ paper.journal || '期刊未知' }} · {{ paper.year || '年份未知' }}
                    </div>
                  </div>
                  <div class="flex shrink-0 flex-col items-end gap-1">
                    <StatusTag type="review" :status="paper.review_status" />
                    <span v-if="paper.screening_score !== null" class="text-[10.5px] tabular-nums text-slate-400">参考分 {{ paper.screening_score }}</span>
                  </div>
                </div>
              </div>
            </section>
          </div>

          <div class="space-y-4">
            <section class="panel p-4">
              <div class="mb-3 flex items-center justify-between">
                <div class="section-title">AI 使用统计</div>
                <button class="link" @click="router.push('/ai')">分析中心</button>
              </div>
              <div class="grid grid-cols-2 gap-3">
                <div class="soft-panel p-3">
                  <div class="micro">输入 Token</div>
                  <div class="mt-1 text-[18px] font-semibold tabular-nums">{{ data.ai.tokens_prompt.toLocaleString() }}</div>
                </div>
                <div class="soft-panel p-3">
                  <div class="micro">输出 Token</div>
                  <div class="mt-1 text-[18px] font-semibold tabular-nums">{{ data.ai.tokens_completion.toLocaleString() }}</div>
                </div>
                <div class="soft-panel p-3">
                  <div class="micro">估算费用</div>
                  <div class="mt-1 text-[18px] font-semibold tabular-nums">¥ {{ data.ai.estimated_cost.toFixed(4) }}</div>
                </div>
                <div class="soft-panel p-3">
                  <div class="micro">平均参考分</div>
                  <div class="mt-1 text-[18px] font-semibold tabular-nums">{{ data.ai.avg_score ?? '—' }}</div>
                </div>
              </div>
              <div class="mt-3 flex items-center gap-2 text-[11px] text-slate-400">
                <el-icon><InfoFilled /></el-icon>
                费用依据设置中的单价估算；参考分不是学术质量评价。
              </div>
            </section>

            <section class="panel p-4">
              <div class="mb-3 section-title">待办快速入口</div>
              <div class="space-y-2">
                <button class="soft-panel flex w-full items-center gap-3 p-3 text-left transition-colors hover:border-accent-400" @click="goReview">
                  <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/10 text-amber-600"><el-icon><View /></el-icon></span>
                  <span class="flex-1">
                    <span class="block text-[12.5px] font-medium">待人工审核 {{ data.papers.pending_review }} 篇</span>
                    <span class="block text-[11px] text-slate-400">快捷键筛选，逐篇决定入库</span>
                  </span>
                  <el-icon class="text-slate-400"><ArrowRight /></el-icon>
                </button>
                <button class="soft-panel flex w-full items-center gap-3 p-3 text-left transition-colors hover:border-accent-400" @click="router.push('/ai')">
                  <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-500/10 text-violet-600"><el-icon><MagicStick /></el-icon></span>
                  <span class="flex-1">
                    <span class="block text-[12.5px] font-medium">AI 分析队列</span>
                    <span class="block text-[11px] text-slate-400">批量分析已获取全文的文献</span>
                  </span>
                  <el-icon class="text-slate-400"><ArrowRight /></el-icon>
                </button>
                <button class="soft-panel flex w-full items-center gap-3 p-3 text-left transition-colors hover:border-accent-400" @click="router.push('/imports')">
                  <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-500/10 text-teal-600"><el-icon><Download /></el-icon></span>
                  <span class="flex-1">
                    <span class="block text-[12.5px] font-medium">本地全文接管</span>
                    <span class="block text-[11px] text-slate-400">监听下载目录，自动去重归档</span>
                  </span>
                  <el-icon class="text-slate-400"><ArrowRight /></el-icon>
                </button>
              </div>
            </section>

            <section class="panel p-4">
              <div class="mb-2 flex items-center justify-between">
                <div class="section-title">来源期刊分布</div>
                <span class="chip">Top {{ data.top_journals.length }}</span>
              </div>
              <div v-if="!data.top_journals.length" class="py-4 text-center text-[12px] text-slate-400">暂无期刊数据</div>
              <div v-else class="space-y-2.5">
                <div v-for="item in data.top_journals" :key="item.journal">
                  <div class="mb-1 flex items-center justify-between text-[12px]">
                    <span class="truncate">{{ item.journal }}</span>
                    <span class="tabular-nums text-slate-400">{{ item.count }}</span>
                  </div>
                  <div class="h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div class="h-full rounded-full bg-accent-500/80" :style="{ width: `${(item.count / (data.top_journals[0]?.count || 1)) * 100}%` }"></div>
                  </div>
                </div>
              </div>
            </section>

            <section class="panel flex items-center gap-3 p-4">
              <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-500 dark:bg-slate-800">
                <el-icon><Monitor /></el-icon>
              </div>
              <div class="min-w-0 flex-1">
                <div class="text-[12px] font-medium">本地服务状态</div>
                <div class="truncate text-[11px] text-slate-400">
                  {{ app.systemInfo?.runner.running ? '任务执行器运行中' : '任务执行器未运行' }} ·
                  {{ app.systemInfo?.watcher.running ? '目录监听中' : '目录监听关闭' }} ·
                  SQLite {{ app.systemInfo?.sqlite }}
                </div>
              </div>
              <button class="link" @click="router.push('/settings')">设置</button>
            </section>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
