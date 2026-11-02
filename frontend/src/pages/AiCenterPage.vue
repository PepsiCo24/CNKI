<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { aiApi, papersApi, systemApi } from '@/api'
import type { AiJob, PaperSummary } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'
import PaperDetailDrawer from '@/components/PaperDetailDrawer.vue'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const app = useAppStore()
const stats = ref<Awaited<ReturnType<typeof aiApi.stats>> | null>(null)
const jobs = ref<AiJob[]>([])
const jobsTotal = ref(0)
const pending = ref<PaperSummary[]>([])
const pendingTotal = ref(0)
const pendingSelected = ref<string[]>([])
const loading = ref(false)
const pendingLoading = ref(false)
const batchBusy = ref(false)
const statusFilter = ref('')
const drawerVisible = ref(false)
const drawerPaperId = ref<string | null>(null)
const page = ref(1)
const pageSize = ref(20)
let timer: number | undefined

const statusCounts = computed(() => stats.value?.status_counts || {})
const providerLabel = computed(() => {
  const provider = app.systemInfo?.ai.provider || ''
  if (provider === 'mock') return '离线 Mock 演示模型'
  return app.systemInfo?.ai.model || provider || '未配置'
})
const isMock = computed(() => app.systemInfo?.ai.provider === 'mock')
const completedCount = computed(() => (statusCounts.value.completed || 0) + (statusCounts.value.cached || 0))

async function loadStats() {
  stats.value = await aiApi.stats()
}

async function loadJobs() {
  loading.value = true
  try {
    const result = await aiApi.jobs({ page: page.value, page_size: pageSize.value, status: statusFilter.value })
    jobs.value = result.items
    jobsTotal.value = result.total
  } finally {
    loading.value = false
  }
}

async function loadPending() {
  pendingLoading.value = true
  try {
    const result = await papersApi.list({ folder: 'pending_analysis', page: 1, page_size: 20 })
    pending.value = result.items
    pendingTotal.value = result.total
    pendingSelected.value = pendingSelected.value.filter((id) => result.items.some((paper) => paper.id === id))
  } finally {
    pendingLoading.value = false
  }
}

async function analyzePending() {
  const ids = pendingSelected.value.length ? pendingSelected.value : pending.value.map((paper) => paper.id)
  if (!ids.length) {
    ElMessage.warning('没有待分析文献')
    return
  }
  batchBusy.value = true
  try {
    const result = await aiApi.analyze(ids, false)
    ElMessage.success(`已排队 ${result.jobs.length} 个分析任务`)
    pendingSelected.value = []
    await refreshAll()
  } finally {
    batchBusy.value = false
  }
}

async function analyzeAllPending() {
  batchBusy.value = true
  try {
    const result = await aiApi.analyzePending(50)
    if (result.jobs.length) ElMessage.success(`已排队 ${result.jobs.length} 个分析任务`)
    else ElMessage.info(result.message || '没有待分析文献')
    await refreshAll()
  } finally {
    batchBusy.value = false
  }
}

async function cancel(job: AiJob) {
  await aiApi.cancel(job.id)
  ElMessage.success('已请求取消分析任务')
  await refreshAll()
}

async function viewPaper(job: AiJob) {
  drawerPaperId.value = job.paper_id
  drawerVisible.value = true
}

function togglePending(paper: PaperSummary, checked: boolean) {
  if (checked) pendingSelected.value = Array.from(new Set([...pendingSelected.value, paper.id]))
  else pendingSelected.value = pendingSelected.value.filter((id) => id !== paper.id)
}

function selectAllPending() {
  pendingSelected.value = pending.value.map((paper) => paper.id)
}

async function refreshAll() {
  await Promise.all([loadStats(), loadJobs(), loadPending()])
  app.loadSystem()
}

async function viewLogs() {
  const result = await systemApi.logs(300)
  ElMessageBox.alert(
    `<pre style="max-height:420px;overflow:auto;font-size:11px;line-height:1.5;white-space:pre-wrap">${result.lines.join('\n')}</pre>`,
    '运行日志',
    { dangerouslyUseHTMLString: true, customClass: 'log-dialog' },
  )
}

onMounted(async () => {
  await refreshAll()
  timer = window.setInterval(() => {
    if (document.visibilityState === 'visible') {
      loadStats()
      loadJobs()
      loadPending()
    }
  }, 5000)
})
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div>
    <PageHeader title="AI 分析中心" subtitle="解析全文、调用模型、校验结构化输出并记录 Token 消耗" eyebrow="AI pipeline">
      <template #actions>
        <el-button size="small" @click="viewLogs"><el-icon class="mr-1"><Document /></el-icon>运行日志</el-button>
        <el-button size="small" @click="router.push('/settings')"><el-icon class="mr-1"><Setting /></el-icon>模型设置</el-button>
        <el-button type="primary" :loading="batchBusy" @click="analyzeAllPending">
          <el-icon class="mr-1"><MagicStick /></el-icon>分析全部待处理
        </el-button>
      </template>
    </PageHeader>

    <div class="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <div class="stat-card">
        <div class="flex items-center justify-between"><span class="micro">分析任务</span><el-icon class="text-accent-500"><MagicStick /></el-icon></div>
        <div class="stat-value">{{ Object.values(statusCounts).reduce((sum, value) => sum + Number(value), 0) }}</div>
        <div class="text-[11px] text-slate-400">完成 {{ completedCount }} · 失败 {{ statusCounts.failed || 0 }}</div>
      </div>
      <div class="stat-card">
        <div class="micro">输入 Token</div>
        <div class="stat-value">{{ (stats?.tokens_prompt || 0).toLocaleString() }}</div>
        <div class="text-[11px] text-slate-400">按服务商 usage 统计</div>
      </div>
      <div class="stat-card">
        <div class="micro">输出 Token</div>
        <div class="stat-value">{{ (stats?.tokens_completion || 0).toLocaleString() }}</div>
        <div class="text-[11px] text-slate-400">含结构化修复重试</div>
      </div>
      <div class="stat-card">
        <div class="micro">估算费用</div>
        <div class="stat-value">¥ {{ (stats?.estimated_cost || 0).toFixed(4) }}</div>
        <div class="text-[11px] text-slate-400">可在设置中配置单价</div>
      </div>
      <div class="stat-card">
        <div class="micro">待分析文献</div>
        <div class="stat-value">{{ pendingTotal }}</div>
        <div class="text-[11px] text-slate-400">已获取全文、尚未分析</div>
      </div>
    </div>

    <el-alert v-if="isMock" class="!mt-4" type="warning" :closable="false" show-icon>
      <template #title>
        当前使用离线 Mock 演示模型，分析结果会明确标注“模拟”，不能作为科研判断依据。请在设置中心配置 DeepSeek / 通义千问 / OpenAI 兼容接口或 Ollama 本地模型。
      </template>
    </el-alert>

    <div class="mt-4 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
      <section class="panel overflow-hidden">
        <div class="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3" :style="{ borderColor: 'var(--app-border)' }">
          <div>
            <div class="section-title">分析任务队列</div>
            <div class="mt-0.5 text-[11px] text-slate-400">当前模型：{{ providerLabel }}</div>
          </div>
          <div class="flex items-center gap-1.5">
            <el-select v-model="statusFilter" size="small" clearable placeholder="全部状态" style="width: 130px" @change="page = 1; loadJobs()">
              <el-option value="queued" label="排队中" />
              <el-option value="running" label="分析中" />
              <el-option value="completed" label="已完成" />
              <el-option value="failed" label="失败" />
            </el-select>
            <el-button size="small" @click="loadJobs"><el-icon><Refresh /></el-icon></el-button>
          </div>
        </div>
        <el-table v-loading="loading" :data="jobs" size="small" style="width: 100%">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="space-y-2 px-4 py-2 text-[11.5px]">
                <div v-if="row.error" class="rounded bg-rose-50 p-2 text-rose-600 dark:bg-rose-950/30">{{ row.error }}</div>
                <div class="grid gap-2 sm:grid-cols-2">
                  <div>分析范围：{{ row.analysis_scope }}</div>
                  <div>输入字符：{{ row.input_chars.toLocaleString() }}</div>
                  <div>分块数：{{ row.chunk_count }}</div>
                  <div>提示词版本：v{{ row.prompt_version }}</div>
                  <div>尝试次数：{{ row.attempts }} / {{ row.max_attempts }}</div>
                  <div>模型：{{ row.provider }} / {{ row.model }}</div>
                </div>
                <div v-if="row.message" class="text-slate-400">{{ row.message }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="文献" min-width="220">
            <template #default="{ row }">
              <div class="line-clamp-2 text-[12px] font-medium">{{ row.paper?.title || '—' }}</div>
              <div class="mt-0.5 text-[10px] text-slate-400">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100"><template #default="{ row }"><StatusTag type="ai" :status="row.status" /></template></el-table-column>
          <el-table-column label="进度" width="110">
            <template #default="{ row }">
              <el-progress :percentage="row.status === 'completed' ? 100 : row.progress || 0" :stroke-width="5" :show-text="false" :status="row.status === 'failed' ? 'exception' : undefined" />
              <div class="mt-1 text-[9.5px] text-slate-400">{{ row.status === 'completed' ? '完成' : row.status === 'failed' ? '失败' : `${row.progress || 0}%` }}</div>
            </template>
          </el-table-column>
          <el-table-column label="Token" width="90" align="right">
            <template #default="{ row }"><span class="text-[10.5px] tabular-nums text-slate-500">{{ (row.tokens_prompt + row.tokens_completion).toLocaleString() }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="110" align="right">
            <template #default="{ row }">
              <el-button link size="small" @click="viewPaper(row)">查看</el-button>
              <el-button v-if="['queued', 'running'].includes(row.status)" link size="small" type="danger" @click="cancel(row)">取消</el-button>
            </template>
          </el-table-column>
          <template #empty><EmptyState compact title="暂无分析任务" description="在文件管理或待审核页面选择文献并触发 AI 分析。" icon="MagicStick" /></template>
        </el-table>
        <div class="flex justify-end border-t px-3 py-2" :style="{ borderColor: 'var(--app-border)' }">
          <el-pagination v-model:current-page="page" :page-size="pageSize" :total="jobsTotal" layout="prev, pager, next" small @current-change="loadJobs" />
        </div>
      </section>

      <div class="space-y-4">
        <section class="panel flex min-h-0 flex-col overflow-hidden">
          <div class="flex items-center justify-between border-b px-4 py-3" :style="{ borderColor: 'var(--app-border)' }">
            <div>
              <div class="section-title">待分析文献</div>
              <div class="text-[11px] text-slate-400">全文已归档，尚未生成分析</div>
            </div>
            <el-button link size="small" @click="selectAllPending">全选</el-button>
          </div>
          <div v-loading="pendingLoading" class="max-h-[360px] min-h-[180px] overflow-y-auto">
            <div v-if="!pending.length" class="p-4"><EmptyState compact title="没有待分析文献" icon="Checked" /></div>
            <div v-for="paper in pending" :key="paper.id" class="flex items-start gap-2 border-b px-3 py-2" :style="{ borderColor: 'var(--app-border)' }">
              <el-checkbox :model-value="pendingSelected.includes(paper.id)" @change="(val: boolean) => togglePending(paper, val)" />
              <div class="min-w-0 flex-1">
                <div class="line-clamp-2 text-[11.5px] font-medium leading-5">{{ paper.title }}</div>
                <div class="mt-0.5 text-[10px] text-slate-400">{{ paper.journal || '—' }} · {{ paper.year || '—' }} · {{ paper.tags.map((tag) => tag.name).join(' / ') || '无标签' }}</div>
              </div>
              <StatusTag type="parse" :status="paper.parse_status" />
            </div>
          </div>
          <div class="flex items-center gap-2 border-t p-2" :style="{ borderColor: 'var(--app-border)' }">
            <span class="text-[10.5px] text-slate-400">已选 {{ pendingSelected.length }} / {{ pendingTotal }}</span>
            <el-button class="ml-auto" size="small" type="primary" :loading="batchBusy" @click="analyzePending">分析所选</el-button>
          </div>
        </section>

        <section class="panel p-4">
          <div class="section-title">模型使用分布</div>
          <div v-if="!stats?.models?.length" class="py-6 text-center text-[11px] text-slate-400">暂无模型调用记录</div>
          <div v-else class="mt-3 space-y-2">
            <div v-for="item in stats.models" :key="item.model">
              <div class="mb-1 flex justify-between text-[11px]"><span class="truncate">{{ item.model || '未记录' }}</span><span class="text-slate-400">{{ item.count }}</span></div>
              <div class="h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                <div class="h-full rounded-full bg-violet-500/80" :style="{ width: `${(item.count / Math.max(1, stats.models[0]?.count || 1)) * 100}%` }"></div>
              </div>
            </div>
          </div>
        </section>

        <section class="panel p-4">
          <div class="section-title">分析质量守则</div>
          <ul class="mt-2 list-disc space-y-1.5 pl-4 text-[11px] leading-5 text-slate-500">
            <li>仅摘要分析会明确标记“仅基于摘要”，不会伪装成全文分析。</li>
            <li>长论文按页分块提取，再汇总；页码只能来自真实 PDF。</li>
            <li>模型输出必须通过 Pydantic 严格校验，失败最多修复 2 次。</li>
            <li>相同文件 / 提示词 / 模型参数会命中缓存，避免重复扣费。</li>
            <li>人工编辑保留 AI 原始版本，历史结果不会被覆盖。</li>
          </ul>
        </section>
      </div>
    </div>

    <PaperDetailDrawer v-model="drawerVisible" :paper-id="drawerPaperId" @updated="refreshAll" />
  </div>
</template>
