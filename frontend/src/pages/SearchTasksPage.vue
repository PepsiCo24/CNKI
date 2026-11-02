<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { importsApi, tasksApi, type TaskPayload } from '@/api'
import type { PaperSummary, RetrievalGuide, SearchTask } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const tasks = ref<SearchTask[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const activeStatus = ref('')
const keyword = ref('')
const createVisible = ref(false)
const detailVisible = ref(false)
const editVisible = ref(false)
const saving = ref(false)
const currentTask = ref<SearchTask | null>(null)
const activeTaskId = ref('')
const guide = ref<RetrievalGuide | null>(null)
const logs = ref<any[]>([])
const papers = ref<PaperSummary[]>([])
const paperTotal = ref(0)
const paperPage = ref(1)
const taskLoading = ref(false)
const metadataInput = ref<HTMLInputElement | null>(null)
const importBusy = ref(false)
const pollTimer = window.setInterval(() => {
  if (detailVisible.value) refreshDetail(true)
}, 5000)

const dateRange = ref<[string, string] | null>(null)
const form = reactive<TaskPayload>({
  name: '',
  journal: '',
  keywords: '',
  match_mode: 'fuzzy',
  start_date: null,
  end_date: null,
  sort_by: 'publication_date',
  import_mode: 'metadata_import',
  paper_type: 'journal',
})

const statusTabs = [
  { value: '', label: '全部' },
  { value: 'pending', label: '待开始' },
  { value: 'awaiting_import', label: '等待导入' },
  { value: 'running', label: '执行中' },
  { value: 'paused', label: '已暂停' },
  { value: 'failed', label: '失败' },
]

const paperTypeOptions = [
  { value: 'journal', label: '期刊论文' },
  { value: 'dissertation', label: '学位论文（预留）' },
  { value: 'conference', label: '会议论文（预留）' },
]

const importModeOptions = [
  { value: 'metadata_import', label: '导入官方题录（推荐）' },
  { value: 'folder_watch', label: '本地全文目录接管' },
  { value: 'authorized_api', label: '授权数据接口（需单独许可）' },
]

const statusCounts = computed(() => {
  const counts: Record<string, number> = {}
  tasks.value.forEach((task) => {
    counts[task.status] = (counts[task.status] || 0) + 1
  })
  return counts
})

function resetForm() {
  Object.assign(form, {
    name: '',
    journal: '',
    keywords: '',
    match_mode: 'fuzzy',
    start_date: null,
    end_date: null,
    sort_by: 'publication_date',
    import_mode: 'metadata_import',
    paper_type: 'journal',
  })
  dateRange.value = null
}

function openCreate() {
  resetForm()
  createVisible.value = true
}

function openEdit() {
  if (!currentTask.value) return
  const task = currentTask.value
  Object.assign(form, {
    name: task.name,
    journal: task.journal,
    keywords: task.keywords,
    match_mode: task.match_mode,
    start_date: task.start_date,
    end_date: task.end_date,
    sort_by: task.sort_by,
    import_mode: task.import_mode,
    paper_type: task.paper_type,
  })
  dateRange.value = task.start_date && task.end_date ? [task.start_date, task.end_date] : null
  editVisible.value = true
}

watch(dateRange, (value) => {
  form.start_date = value?.[0] || null
  form.end_date = value?.[1] || null
})

async function loadTasks() {
  loading.value = true
  try {
    const result = await tasksApi.list({
      page: page.value,
      page_size: pageSize.value,
      status: activeStatus.value,
      q: keyword.value.trim(),
    })
    tasks.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写任务名称')
    return
  }
  if (!form.journal.trim() && !form.keywords.trim()) {
    ElMessage.warning('请至少填写期刊来源或主题关键词')
    return
  }
  if (form.start_date && form.end_date && form.start_date > form.end_date) {
    ElMessage.warning('起始日期不得晚于结束日期')
    return
  }
  saving.value = true
  try {
    const result = await tasksApi.create({ ...form })
    createVisible.value = false
    ElMessage.success('检索任务已创建')
    await loadTasks()
    openDetail(result.task.id)
  } finally {
    saving.value = false
  }
}

async function submitEdit() {
  if (!currentTask.value) return
  saving.value = true
  try {
    const result = await tasksApi.update(currentTask.value.id, { ...form })
    currentTask.value = result.task
    guide.value = result.guide
    editVisible.value = false
    ElMessage.success('任务条件已更新')
    await loadTasks()
  } finally {
    saving.value = false
  }
}

async function openDetail(taskId: string) {
  activeTaskId.value = taskId
  detailVisible.value = true
  currentTask.value = null
  papers.value = []
  logs.value = []
  await refreshDetail()
}

async function refreshDetail(silent = false) {
  const id = activeTaskId.value || currentTask.value?.id || (route.query.task as string)
  if (!id) return
  if (!silent) taskLoading.value = true
  try {
    const result = await tasksApi.get(id)
    currentTask.value = result.task
    guide.value = result.guide
    logs.value = result.logs
    await loadTaskPapers()
  } finally {
    taskLoading.value = false
  }
}

async function loadTaskPapers() {
  const id = currentTask.value?.id
  if (!id) return
  const result = await tasksApi.papers(id, { page: paperPage.value, page_size: 10 })
  papers.value = result.items
  paperTotal.value = result.total
}

async function runTask(mode?: string) {
  if (!currentTask.value) return
  try {
    await tasksApi.run(currentTask.value.id, mode)
    ElMessage.success('任务已启动')
    await refreshDetail()
    await loadTasks()
  } catch {
    /* handled globally */
  }
}

async function pauseTask() {
  if (!currentTask.value) return
  await tasksApi.pause(currentTask.value.id)
  ElMessage.success('任务已暂停')
  await refreshDetail()
  await loadTasks()
}

async function resumeTask() {
  if (!currentTask.value) return
  await tasksApi.resume(currentTask.value.id)
  ElMessage.success('任务已继续')
  await refreshDetail()
  await loadTasks()
}

async function cancelTask() {
  if (!currentTask.value) return
  await ElMessageBox.confirm('取消后已导入的文献会保留，确认取消该任务？', '取消任务', { type: 'warning' })
  await tasksApi.cancel(currentTask.value.id)
  ElMessage.success('任务已取消')
  await refreshDetail()
  await loadTasks()
}

async function retryTask() {
  if (!currentTask.value) return
  await tasksApi.retry(currentTask.value.id)
  ElMessage.success('任务已重新执行')
  await refreshDetail()
  await loadTasks()
}

async function removeTask(task: SearchTask) {
  await ElMessageBox.confirm(
    `删除任务“${task.name}”？已导入的文献与全文不会被删除。`,
    '删除检索任务',
    { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' },
  )
  await tasksApi.remove(task.id)
  ElMessage.success('任务已删除')
  if (currentTask.value?.id === task.id) detailVisible.value = false
  await loadTasks()
}

function triggerMetadataImport() {
  metadataInput.value?.click()
}

async function onMetadataFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !currentTask.value) return
  importBusy.value = true
  try {
    const result = await importsApi.metadata(file, currentTask.value.id)
    const skipped = result.detail?.skipped ?? 0
    ElMessage.success(
      `题录导入完成：导入 ${result.imported} 篇，重复 ${result.duplicates} 篇，条件不匹配跳过 ${skipped} 篇`,
    )
    await refreshDetail()
    await loadTasks()
  } finally {
    importBusy.value = false
    input.value = ''
  }
}

async function scanFolder() {
  if (!currentTask.value) return
  importBusy.value = true
  try {
    await importsApi.scan(null, currentTask.value.id)
    ElMessage.success('已加入目录扫描队列，可在“下载与导入”查看进度')
    await refreshDetail()
  } finally {
    importBusy.value = false
  }
}

async function copyConditions() {
  if (!guide.value) return
  const text = [
    `任务：${guide.value.task_name}`,
    `文献来源（期刊）：${guide.value.fields['文献来源']}`,
    `主题：${guide.value.fields['主题']}`,
    `发表时间：${JSON.stringify(guide.value.fields['发表时间'])}`,
    `文献类型：${guide.value.fields['文献类型']}`,
    `排序：${guide.value.fields['排序']}`,
    `官方入口：${guide.value.official_entry}`,
  ].join('\n')
  await navigator.clipboard.writeText(text)
  ElMessage.success('检索条件已复制，可粘贴到知网高级检索')
}

function goPaper(paper: PaperSummary) {
  if (paper.review_status === 'pending_review') router.push(`/review?paper=${paper.id}`)
  else router.push(`/library?paper=${paper.id}`)
}

function formatJson(value: unknown): string {
  if (value === null || value === undefined || value === '') return '不限'
  if (typeof value === 'object') {
    const object = value as Record<string, unknown>
    if ('start' in object || 'end' in object) return `${object.start || '不限'} ~ ${object.end || '不限'}`
    return JSON.stringify(value)
  }
  return String(value)
}

function openFromRoute() {
  if (route.query.create === '1') {
    openCreate()
    router.replace({ path: '/search-tasks', query: route.query.task ? { task: route.query.task } : {} })
  }
  if (route.query.task) openDetail(String(route.query.task))
}

onMounted(async () => {
  await loadTasks()
  openFromRoute()
  window.addEventListener('keydown', handleEsc)
})

onUnmounted(() => {
  window.clearInterval(pollTimer)
  window.removeEventListener('keydown', handleEsc)
})

function handleEsc(event: KeyboardEvent) {
  if (event.key === 'Escape') detailVisible.value = false
}
</script>

<template>
  <div>
    <PageHeader title="文献检索" subtitle="先限定“文献来源”期刊，再设置主题与发表日期；系统生成官方检索条件单" eyebrow="Search tasks">
      <template #actions>
        <el-button @click="router.push('/imports')"><el-icon class="mr-1"><Upload /></el-icon>导入题录 / 全文</el-button>
        <el-button type="primary" @click="openCreate"><el-icon class="mr-1"><Plus /></el-icon>新建检索任务</el-button>
      </template>
    </PageHeader>

    <div class="panel p-3">
      <div class="toolbar">
        <el-radio-group v-model="activeStatus" size="small" @change="page = 1; loadTasks()">
          <el-radio-button v-for="tab in statusTabs" :key="tab.value" :value="tab.value">
            {{ tab.label }}
          </el-radio-button>
        </el-radio-group>
        <div class="ml-auto flex items-center gap-2">
          <el-input v-model="keyword" placeholder="搜索任务名称 / 期刊" clearable style="width: 240px" @keyup.enter="page = 1; loadTasks()" />
          <el-button @click="page = 1; loadTasks()"><el-icon><Search /></el-icon></el-button>
        </div>
      </div>

      <div class="mt-3">
        <el-table v-loading="loading" :data="tasks" stripe style="width: 100%" @row-click="(row: SearchTask) => openDetail(row.id)">
          <el-table-column label="任务" min-width="260">
            <template #default="{ row }">
              <div class="flex items-center gap-2.5">
                <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent-500/10 text-accent-600">
                  <el-icon><Search /></el-icon>
                </div>
                <div class="min-w-0">
                  <div class="truncate text-[13px] font-medium">{{ row.name }}</div>
                  <div class="mt-0.5 truncate text-[11px] text-slate-400">{{ row.journal || '未限定期刊' }} · {{ row.keywords || '未限定主题' }}</div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="日期范围" width="190">
            <template #default="{ row }">
              <span class="text-[12px] text-slate-500">{{ row.start_date || '不限' }} ~ {{ row.end_date || '不限' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="进度" width="190">
            <template #default="{ row }">
              <div class="space-y-1">
                <div class="text-[11px] text-slate-500">发现 {{ row.discovered_count }} · 全文 {{ row.imported_count }} · 入库 {{ row.included_count }}</div>
                <el-progress :percentage="Math.round(row.progress || 0)" :stroke-width="5" :show-text="false" />
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110">
            <template #default="{ row }"><StatusTag type="task" :status="row.status" /></template>
          </el-table-column>
          <el-table-column label="更新时间" width="150">
            <template #default="{ row }"><span class="text-[11.5px] text-slate-400">{{ new Date(row.updated_at).toLocaleString('zh-CN') }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="150" align="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openDetail(row.id)">条件单</el-button>
              <el-button link size="small" @click.stop="removeTask(row)">删除</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <EmptyState title="还没有检索任务" description="创建任务后，系统会生成知网高级检索条件单，并支持导入官方题录与本地全文。" icon="Search">
              <el-button size="small" type="primary" @click="openCreate">新建第一个任务</el-button>
            </EmptyState>
          </template>
        </el-table>
      </div>
      <div class="mt-3 flex justify-end">
        <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" layout="total, prev, pager, next" background @current-change="loadTasks" />
      </div>
    </div>

    <!-- Create / edit dialog -->
    <el-dialog v-model="createVisible" title="新建检索任务" width="640px" destroy-on-close>
      <el-form label-position="top">
        <div class="grid gap-3 sm:grid-cols-2">
          <el-form-item label="任务名称" required class="sm:col-span-2">
            <el-input v-model="form.name" placeholder="例如：岩土力学期刊创新点调研" maxlength="120" show-word-limit />
          </el-form-item>
          <el-form-item label="数据来源">
            <el-input value="CNKI（官方检索 + 题录导入）" disabled />
          </el-form-item>
          <el-form-item label="文献类型">
            <el-select v-model="form.paper_type" class="w-full">
              <el-option v-for="option in paperTypeOptions" :key="option.value" :label="option.label" :value="option.value" :disabled="option.value !== 'journal'" />
            </el-select>
          </el-form-item>
          <el-form-item label="文献来源 / 期刊名称" class="sm:col-span-2">
            <el-input v-model="form.journal" placeholder="例如：岩土力学。注意：这是期刊来源，不是主题关键词" clearable />
          </el-form-item>
          <el-form-item label="主题关键词（可为空）" class="sm:col-span-2">
            <el-input v-model="form.keywords" placeholder="例如：边坡稳定性 随机森林；留空表示不额外限定主题" clearable />
          </el-form-item>
          <el-form-item label="关键词匹配方式">
            <el-select v-model="form.match_mode" class="w-full">
              <el-option value="fuzzy" label="模糊（推荐）" />
              <el-option value="exact" label="精确" />
            </el-select>
          </el-form-item>
          <el-form-item label="排序方式">
            <el-select v-model="form.sort_by" class="w-full">
              <el-option value="publication_date" label="发表时间" />
              <el-option value="relevance" label="相关度" />
            </el-select>
          </el-form-item>
          <el-form-item label="起止日期" class="sm:col-span-2">
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              range-separator="至"
              start-placeholder="起始日期"
              end-placeholder="截止日期"
              class="!w-full"
            />
          </el-form-item>
          <el-form-item label="导入方式" class="sm:col-span-2">
            <el-select v-model="form.import_mode" class="w-full">
              <el-option v-for="option in importModeOptions" :key="option.value" :label="option.label" :value="option.value" />
            </el-select>
            <div class="mt-1.5 text-[11px] leading-5 text-slate-400">
              授权接口模式只会在明确许可并配置官方文档端点后可用，系统不会自动绕过知网限制。
            </div>
          </el-form-item>
        </div>
        <div class="rounded-lg border border-dashed p-3 text-[11.5px] leading-5 text-slate-500" :style="{ borderColor: 'var(--app-border)' }">
          <span class="font-medium text-slate-600 dark:text-slate-300">示例：</span>
          期刊来源“岩土力学”、主题留空、起始 2023-01-01、截止 2025-12-31。系统会检索该期刊，而不是检索所有包含“岩土力学”字样的论文。
        </div>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">创建任务</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑检索条件" width="640px" destroy-on-close>
      <el-form label-position="top">
        <div class="grid gap-3 sm:grid-cols-2">
          <el-form-item label="任务名称" required class="sm:col-span-2"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="文献来源 / 期刊名称" class="sm:col-span-2"><el-input v-model="form.journal" /></el-form-item>
          <el-form-item label="主题关键词" class="sm:col-span-2"><el-input v-model="form.keywords" /></el-form-item>
          <el-form-item label="起止日期" class="sm:col-span-2">
            <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="起始日期" end-placeholder="截止日期" class="!w-full" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitEdit">保存条件</el-button>
      </template>
    </el-dialog>

    <!-- Detail drawer -->
    <el-drawer v-model="detailVisible" size="860px" :with-header="true" destroy-on-close>
      <template #header>
        <div class="flex w-full items-center gap-3 pr-4">
          <div class="min-w-0">
            <div class="truncate text-[15px] font-semibold">{{ currentTask?.name || '检索任务' }}</div>
            <div class="mt-0.5 text-[11px] text-slate-400">检索条件单 · 题录导入 · 本地全文接管</div>
          </div>
          <div class="ml-auto flex items-center gap-2">
            <StatusTag v-if="currentTask" type="task" :status="currentTask.status" />
            <el-button size="small" @click="openEdit">编辑条件</el-button>
          </div>
        </div>
      </template>

      <div v-loading="taskLoading" class="space-y-4">
        <template v-if="currentTask">
          <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div class="soft-panel p-3"><div class="micro">发现</div><div class="mt-1 text-[20px] font-semibold">{{ currentTask.discovered_count }}</div></div>
            <div class="soft-panel p-3"><div class="micro">全文</div><div class="mt-1 text-[20px] font-semibold">{{ currentTask.imported_count }}</div></div>
            <div class="soft-panel p-3"><div class="micro">已分析</div><div class="mt-1 text-[20px] font-semibold">{{ currentTask.analyzed_count }}</div></div>
            <div class="soft-panel p-3"><div class="micro">已入库</div><div class="mt-1 text-[20px] font-semibold">{{ currentTask.included_count }}</div></div>
          </div>

          <div class="flex flex-wrap gap-2">
            <el-button type="primary" size="small" :disabled="currentTask.status === 'running'" @click="runTask()">
              <el-icon class="mr-1"><VideoPlay /></el-icon>生成条件单 / 启动
            </el-button>
            <el-button size="small" :disabled="currentTask.status !== 'running'" @click="pauseTask">暂停</el-button>
            <el-button size="small" :disabled="currentTask.status !== 'paused'" @click="resumeTask">继续</el-button>
            <el-button size="small" :disabled="['cancelled', 'completed'].includes(currentTask.status)" @click="cancelTask">取消</el-button>
            <el-button size="small" :disabled="!['failed', 'cancelled', 'awaiting_import'].includes(currentTask.status)" @click="retryTask">重试</el-button>
            <el-button size="small" type="primary" plain :loading="importBusy" @click="triggerMetadataImport">
              <el-icon class="mr-1"><Upload /></el-icon>导入官方题录
            </el-button>
            <el-button size="small" :loading="importBusy" @click="scanFolder">
              <el-icon class="mr-1"><FolderOpened /></el-icon>抓取入库（下载目录）
            </el-button>
            <input ref="metadataInput" type="file" accept=".ris,.bib,.enw,.csv,.txt" class="hidden" @change="onMetadataFile" />
          </div>

          <el-alert v-if="currentTask.error_message" type="error" :closable="false" show-icon :title="currentTask.error_message" />
          <div class="rounded-md border border-dashed px-3 py-2 text-[11px] leading-5 text-slate-500" :style="{ borderColor: 'var(--app-border)' }">
            抓取入库说明：在知网官方页面登录，按条件单检索并使用官方导出/下载；系统自动读取导入目录中的题录与全文并按本任务过滤入库。
            系统不会自动登录知网、绕过验证码或调用未授权接口。
          </div>

          <section v-if="guide" class="panel p-4">
            <div class="mb-3 flex items-center justify-between">
              <div>
                <div class="section-title">知网官方检索条件单</div>
                <div class="mt-0.5 text-[11px] text-slate-400">在官方页面按以下字段检索，再用官方导出功能导出题录</div>
              </div>
              <el-button size="small" @click="copyConditions"><el-icon class="mr-1"><CopyDocument /></el-icon>复制条件</el-button>
            </div>
            <div class="grid gap-2 sm:grid-cols-2">
              <div v-for="(value, key) in guide.fields" :key="key" class="flex items-start gap-2 rounded-md bg-[var(--app-panel-soft)] px-3 py-2">
                <span class="w-16 shrink-0 text-[11px] text-slate-400">{{ key }}</span>
                <span class="break-all text-[12px]">{{ formatJson(value) }}</span>
              </div>
            </div>
            <div class="mt-3 rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-[11.5px] leading-5 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200">
              <div class="mb-1 font-medium">合规提示</div>
              <ul class="list-disc space-y-0.5 pl-4">
                <li v-for="notice in guide.notices" :key="notice">{{ notice }}</li>
              </ul>
            </div>
            <div class="mt-3 space-y-1.5">
              <div v-for="(step, index) in guide.steps" :key="index" class="flex gap-2 text-[12px] leading-5">
                <span class="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-accent-500/10 text-[10px] font-semibold text-accent-600">{{ index + 1 }}</span>
                <span class="text-slate-600 dark:text-slate-300">{{ step }}</span>
              </div>
            </div>
            <div class="mt-3 flex flex-wrap gap-2">
              <el-button size="small" @click="runTask('metadata_import')">使用题录导入模式</el-button>
              <el-button size="small" @click="runTask('folder_watch')">使用本地全文接管</el-button>
              <el-tooltip content="当前版本未内置未经确认的知网接口端点，需取得许可后扩展适配器">
                <span><el-button size="small" disabled>授权接口（未配置）</el-button></span>
              </el-tooltip>
              <a :href="guide.official_entry" target="_blank" class="el-button el-button--small el-button--primary is-plain">打开知网官方检索</a>
            </div>
          </section>

          <section class="panel overflow-hidden">
            <div class="flex items-center justify-between border-b px-4 py-3" :style="{ borderColor: 'var(--app-border)' }">
              <div class="section-title">任务文献（{{ paperTotal }}）</div>
              <el-button link size="small" @click="paperPage = 1; loadTaskPapers()">刷新</el-button>
            </div>
            <el-table :data="papers" size="small" style="width: 100%" @row-click="goPaper">
              <el-table-column label="标题" min-width="260">
                <template #default="{ row }">
                  <div class="line-clamp-2 text-[12.5px] font-medium">{{ row.title }}</div>
                  <div class="mt-0.5 text-[10.5px] text-slate-400">{{ row.authors_text || '作者未知' }} · {{ row.journal || '期刊未知' }} · {{ row.year || '—' }}</div>
                </template>
              </el-table-column>
              <el-table-column label="全文" width="108"><template #default="{ row }"><StatusTag type="fulltext" :status="row.fulltext_status" /></template></el-table-column>
              <el-table-column label="AI" width="100"><template #default="{ row }"><StatusTag type="ai" :status="row.ai_status" /></template></el-table-column>
              <el-table-column label="审核" width="118"><template #default="{ row }"><StatusTag type="review" :status="row.review_status" /></template></el-table-column>
            </el-table>
            <div class="flex justify-end p-3">
              <el-pagination v-model:current-page="paperPage" :page-size="10" :total="paperTotal" layout="prev, pager, next" small @current-change="loadTaskPapers" />
            </div>
          </section>

          <section class="panel p-4">
            <div class="mb-2 section-title">任务日志</div>
            <div v-if="!logs.length" class="text-[12px] text-slate-400">暂无日志</div>
            <div v-else class="max-h-[260px] space-y-2 overflow-y-auto pr-1">
              <div v-for="log in logs" :key="log.id" class="flex gap-2 text-[11.5px]">
                <span class="w-[120px] shrink-0 tabular-nums text-slate-400">{{ new Date(log.created_at).toLocaleString('zh-CN') }}</span>
                <span :class="log.level === 'error' ? 'text-rose-500' : log.level === 'warning' ? 'text-amber-500' : 'text-slate-600 dark:text-slate-300'">{{ log.message }}</span>
              </div>
            </div>
          </section>
        </template>
      </div>
    </el-drawer>
  </div>
</template>
