<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { importsApi, settingsApi, tasksApi } from '@/api'
import type { ImportJob, SearchTask } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'

const jobs = ref<ImportJob[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const tasks = ref<SearchTask[]>([])
const taskId = ref('')
const metadataInput = ref<HTMLInputElement | null>(null)
const fulltextInput = ref<HTMLInputElement | null>(null)
const metadataFormat = ref('auto')
const metadataBusy = ref(false)
const uploadBusy = ref(false)
const scanBusy = ref(false)
const scanPath = ref('')
const watch = ref({ running: false, path: '' })
const pendingFiles = ref<File[]>([])
const dragActive = ref(false)
const lastOutcomes = ref<any[]>([])
const outcomeVisible = ref(false)
const activeTab = ref<'jobs' | 'watch'>('jobs')
let timer: number | undefined

const formats = [
  { value: 'auto', label: '自动识别格式' },
  { value: 'ris', label: 'RIS' },
  { value: 'bibtex', label: 'BibTeX' },
  { value: 'endnote', label: 'EndNote ENW' },
  { value: 'csv', label: 'CSV' },
]

const activeJobs = computed(() => jobs.value.filter((job) => ['running', 'pending'].includes(job.status)).length)

async function loadJobs() {
  loading.value = true
  try {
    const result = await importsApi.list({ page: page.value, page_size: 20 })
    jobs.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}

async function loadTasks() {
  const result = await tasksApi.list({ page: 1, page_size: 100 })
  tasks.value = result.items
}

async function loadWatch() {
  try {
    const result = await settingsApi.watchStatus()
    watch.value = result
  } catch {
    /* ignore */
  }
}

function onMetadataPick(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) importMetadata(file)
  input.value = ''
}

async function importMetadata(file: File) {
  metadataBusy.value = true
  try {
    const result = await importsApi.metadata(file, taskId.value || undefined, metadataFormat.value)
    const skipped = result.detail?.skipped ?? 0
    ElMessage.success(`题录导入：导入 ${result.imported}，重复 ${result.duplicates}，条件不匹配 ${skipped}`)
    await loadJobs()
  } finally {
    metadataBusy.value = false
  }
}

function onFulltextPick(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  if (files.length) {
    pendingFiles.value = files
    uploadFulltext()
  }
  input.value = ''
}

function onDrop(event: DragEvent) {
  dragActive.value = false
  const files = Array.from(event.dataTransfer?.files || []).filter((file) => /\.(pdf|caj)$/i.test(file.name))
  if (!files.length) {
    ElMessage.warning('请拖入 PDF 或 CAJ 文件')
    return
  }
  pendingFiles.value = files
  uploadFulltext()
}

async function uploadFulltext() {
  if (!pendingFiles.value.length) return
  uploadBusy.value = true
  try {
    const result = await importsApi.uploadFiles(pendingFiles.value, taskId.value || undefined)
    lastOutcomes.value = result.outcomes
    outcomeVisible.value = true
    const failed = result.outcomes.filter((item) => item.status === 'failed').length
    if (failed) ElMessage.warning(`${result.imported} 个文件已归档，${failed} 个失败`)
    else ElMessage.success(`已导入 ${result.imported} 个全文文件`)
    await loadJobs()
  } finally {
    uploadBusy.value = false
    pendingFiles.value = []
  }
}

async function scan() {
  scanBusy.value = true
  try {
    await importsApi.scan(scanPath.value.trim() || null, taskId.value || undefined)
    ElMessage.success('目录扫描已加入后台队列')
    await loadJobs()
  } finally {
    scanBusy.value = false
  }
}

async function retry(job: ImportJob) {
  await importsApi.retry(job.id)
  ElMessage.success('已重新提交')
  await loadJobs()
}

async function toggleWatch() {
  if (watch.value.running) {
    await settingsApi.stopWatch()
    ElMessage.success('目录监听已停止')
  } else {
    await settingsApi.startWatch()
    ElMessage.success('目录监听已启动')
  }
  await loadWatch()
}

function statusColor(job: ImportJob) {
  if (job.status === 'completed') return '#16A34A'
  if (job.status === 'failed') return '#DC2626'
  return '#3A68F5'
}

onMounted(async () => {
  await Promise.all([loadJobs(), loadTasks(), loadWatch()])
  timer = window.setInterval(() => {
    if (document.visibilityState === 'visible') {
      loadJobs()
      loadWatch()
    }
  }, 4000)
})
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div>
    <PageHeader title="下载与导入任务" subtitle="题录导入、本地全文接管、目录监听与后台任务进度" eyebrow="Ingest">
      <template #actions>
        <el-button :loading="scanBusy" @click="scan"><el-icon class="mr-1"><FolderOpened /></el-icon>扫描目录</el-button>
        <el-button type="primary" :loading="uploadBusy" @click="fulltextInput?.click()"><el-icon class="mr-1"><Upload /></el-icon>导入全文</el-button>
      </template>
    </PageHeader>

    <div class="mb-4 grid gap-3 lg:grid-cols-3">
      <section class="panel p-4">
        <div class="flex items-center gap-2">
          <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-500/10 text-teal-600"><el-icon><Document /></el-icon></span>
          <div>
            <div class="section-title">导入官方题录</div>
            <div class="text-[11px] text-slate-400">RIS / BibTeX / EndNote / CSV</div>
          </div>
        </div>
        <div class="mt-3 space-y-2">
          <el-select v-model="metadataFormat" size="small" class="w-full">
            <el-option v-for="option in formats" :key="option.value" :label="option.label" :value="option.value" />
          </el-select>
          <el-button class="w-full" type="primary" plain :loading="metadataBusy" @click="metadataInput?.click()">
            <el-icon class="mr-1"><Upload /></el-icon>选择题录文件
          </el-button>
          <input ref="metadataInput" type="file" accept=".ris,.bib,.enw,.csv,.txt" class="hidden" @change="onMetadataPick" />
          <div class="text-[10.5px] leading-4 text-slate-400">在知网官方结果页使用“导出/参考文献”功能生成文件。系统不会自动登录或抓取。</div>
        </div>
      </section>

      <section class="panel p-4">
        <div class="flex items-center gap-2">
          <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-500/10 text-accent-600"><el-icon><UploadFilled /></el-icon></span>
          <div>
            <div class="section-title">本地全文接管</div>
            <div class="text-[11px] text-slate-400">拖拽 PDF/CAJ，自动去重归档</div>
          </div>
        </div>
        <div
          class="mt-3 flex h-[104px] cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed text-center transition-colors"
          :class="dragActive ? 'border-accent-500 bg-accent-500/5' : 'border-slate-300 hover:border-accent-400 dark:border-slate-700'"
          @click="fulltextInput?.click()"
          @dragover.prevent="dragActive = true"
          @dragleave.prevent="dragActive = false"
          @drop.prevent="onDrop"
        >
          <el-icon :size="20" class="text-slate-400"><UploadFilled /></el-icon>
          <div class="mt-1 text-[11.5px] text-slate-500">拖入文件，或点击选择（支持多选）</div>
          <div class="text-[10px] text-slate-400">单文件 ≤ 300MB · 最多 50 个</div>
          <input ref="fulltextInput" type="file" accept=".pdf,.caj" multiple class="hidden" @change="onFulltextPick" />
        </div>
      </section>

      <section class="panel p-4">
        <div class="flex items-center gap-2">
          <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-500/10 text-violet-600"><el-icon><Monitor /></el-icon></span>
          <div class="flex-1">
            <div class="section-title">导入目录监听</div>
            <div class="truncate text-[11px] text-slate-400">{{ watch.path || '尚未配置目录' }}</div>
          </div>
          <el-switch :model-value="watch.running" @change="toggleWatch" />
        </div>
        <div class="mt-3 flex gap-2">
          <el-input v-model="scanPath" size="small" placeholder="留空则扫描默认导入目录" clearable />
          <el-button size="small" :loading="scanBusy" @click="scan">扫描</el-button>
        </div>
        <div class="mt-2 text-[10.5px] leading-4 text-slate-400">
          监听目录中有新增 PDF/CAJ 时自动触发去重归档；路径可在设置中心修改。
        </div>
      </section>
    </div>

    <div class="panel p-3">
      <div class="toolbar">
        <el-radio-group v-model="activeTab" size="small">
          <el-radio-button value="jobs">导入记录（{{ total }}）</el-radio-button>
          <el-radio-button value="watch">目录监听</el-radio-button>
        </el-radio-group>
        <div class="ml-auto flex items-center gap-2">
          <el-select v-model="taskId" size="small" clearable placeholder="关联检索任务（可选）" style="width: 240px">
            <el-option v-for="task in tasks" :key="task.id" :label="task.name" :value="task.id" />
          </el-select>
          <el-button size="small" @click="loadJobs"><el-icon><Refresh /></el-icon></el-button>
        </div>
      </div>

      <div v-if="activeTab === 'jobs'" class="mt-3">
        <el-table v-loading="loading" :data="jobs" stripe style="width: 100%">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="space-y-3 px-4 py-2">
                <div v-if="row.errors?.length">
                  <div class="micro mb-1 text-rose-500">错误</div>
                  <div v-for="(error, index) in row.errors" :key="index" class="text-[11.5px] text-rose-500">
                    {{ error.file || error.title || '记录' }}：{{ error.error }}
                  </div>
                </div>
                <div v-if="row.detail?.rows?.length" class="max-h-[220px] overflow-y-auto">
                  <div class="micro mb-1">处理明细</div>
                  <div v-for="(item, index) in row.detail.rows" :key="index" class="flex gap-2 border-b py-1 text-[11px] last:border-0" :style="{ borderColor: 'var(--app-border)' }">
                    <span class="w-[70px] shrink-0" :class="item.status === 'failed' || item.status === 'skipped' ? 'text-rose-500' : 'text-emerald-600'">{{ item.status }}</span>
                    <span class="min-w-0 flex-1 truncate">{{ item.title || item.file }}</span>
                    <span class="text-slate-400">{{ item.message || (item.mismatches || []).join('；') }}</span>
                  </div>
                </div>
                <div class="text-[11px] text-slate-400">源路径：{{ row.source_path }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="130">
            <template #default="{ row }">
              <div class="flex items-center gap-2">
                <el-icon class="text-slate-400"><component :is="row.job_type === 'metadata_import' ? 'Document' : 'Folder'" /></el-icon>
                <span class="text-[12px]">{{ row.job_type === 'metadata_import' ? '题录导入' : '目录扫描' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="进度" min-width="210">
            <template #default="{ row }">
              <div class="w-full max-w-[260px]">
                <div class="mb-1 flex items-center justify-between text-[10.5px] text-slate-400">
                  <span>{{ row.processed }} / {{ row.total || '—' }}</span>
                  <span>{{ row.total ? Math.round((row.processed / row.total) * 100) : 0 }}%</span>
                </div>
                <el-progress :percentage="row.total ? Math.round((row.processed / row.total) * 100) : row.status === 'completed' ? 100 : 0" :stroke-width="5" :show-text="false" :color="statusColor(row)" />
              </div>
            </template>
          </el-table-column>
          <el-table-column label="结果" width="230">
            <template #default="{ row }">
              <div class="flex flex-wrap gap-1.5 text-[10.5px]">
                <span class="chip !text-emerald-600">导入 {{ row.imported }}</span>
                <span class="chip">重复 {{ row.duplicates }}</span>
                <span v-if="row.detail?.skipped" class="chip !text-amber-600">跳过 {{ row.detail.skipped }}</span>
                <span v-if="row.failed" class="chip !text-rose-500">失败 {{ row.failed }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="110"><template #default="{ row }"><StatusTag type="job" :status="row.status" /></template></el-table-column>
          <el-table-column label="时间" width="150">
            <template #default="{ row }"><span class="text-[11px] text-slate-400">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="90" align="right">
            <template #default="{ row }">
              <el-button v-if="row.status === 'failed' || row.status === 'completed'" link size="small" @click="retry(row)">重新执行</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <EmptyState title="暂无导入记录" description="导入题录或全文后，这里会显示处理进度、去重数量与错误明细。" icon="Download">
              <el-button size="small" @click="metadataInput?.click()">导入题录</el-button>
            </EmptyState>
          </template>
        </el-table>
        <div class="mt-3 flex justify-end">
          <el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" background @current-change="loadJobs" />
        </div>
      </div>

      <div v-else class="mt-3 grid gap-3 sm:grid-cols-2">
        <div class="soft-panel p-4">
          <div class="section-title">监听状态</div>
          <div class="mt-3 space-y-2 text-[12px]">
            <div class="flex justify-between"><span class="text-slate-400">运行状态</span><StatusTag :status="watch.running ? 'completed' : 'cancelled'" type="job" :label="watch.running ? '监听中' : '已停止'" /></div>
            <div class="flex justify-between gap-4"><span class="text-slate-400">监听目录</span><span class="break-all text-right">{{ watch.path || '未配置' }}</span></div>
            <div class="flex justify-between"><span class="text-slate-400">活跃导入任务</span><span>{{ activeJobs }}</span></div>
          </div>
          <el-button class="mt-4" :type="watch.running ? 'default' : 'primary'" @click="toggleWatch">
            {{ watch.running ? '停止监听' : '启动监听' }}
          </el-button>
        </div>
        <div class="soft-panel p-4">
          <div class="section-title">使用建议</div>
          <ul class="mt-3 list-disc space-y-2 pl-4 text-[12px] leading-5 text-slate-500">
            <li>通过知网官方页面、知网研学或其他授权渠道下载 PDF/CAJ。</li>
            <li>将文件放入导入目录，系统会自动发现、计算哈希、去重并归档到“期刊/年份”目录。</li>
            <li>同一 SHA-256 只保存一份全文；标题相似但文件不同会提示人工确认，不会自动删除。</li>
            <li>CAJ 保留原文件并标记“未解析”，可导入你有权转换得到的 PDF。</li>
          </ul>
        </div>
      </div>
    </div>

    <el-dialog v-model="outcomeVisible" title="全文导入结果" width="560px">
      <div class="space-y-2">
        <div v-for="(item, index) in lastOutcomes" :key="index" class="flex items-start gap-2 rounded-md border px-3 py-2 text-[12px]" :style="{ borderColor: 'var(--app-border)' }">
          <StatusTag :status="item.status" type="job" :label="item.status" />
          <div class="min-w-0">
            <div class="truncate font-medium">{{ item.filename }}</div>
            <div class="mt-0.5 text-[11px] text-slate-400">{{ item.message }}</div>
          </div>
        </div>
      </div>
      <template #footer><el-button type="primary" @click="outcomeVisible = false">知道了</el-button></template>
    </el-dialog>
  </div>
</template>
