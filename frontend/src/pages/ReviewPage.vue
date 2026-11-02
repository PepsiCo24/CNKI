<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { papersApi, reviewApi, settingsApi } from '@/api'
import { useAppStore } from '@/stores/app'
import type { PaperDetail, PaperSummary } from '@/types'
import StatusTag from '@/components/StatusTag.vue'
import AnalysisView from '@/components/AnalysisView.vue'
import PdfViewer from '@/components/PdfViewer.vue'
import EmptyState from '@/components/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const app = useAppStore()

const queueStatus = ref('pending_review')
const sort = ref('score_desc')
const keyword = ref('')
const items = ref<PaperSummary[]>([])
const counts = ref<Record<string, number>>({})
const total = ref(0)
const loadingQueue = ref(false)
const selectedId = ref<string>('')
const detail = ref<PaperDetail | null>(null)
const loadingDetail = ref(false)
const reviewNote = ref('')
const selectedTags = ref<string[]>([])
const rightTab = ref<'pdf' | 'evidence' | 'notes'>('pdf')
const pdfPage = ref(1)
const pdfRef = ref<InstanceType<typeof PdfViewer> | null>(null)
const actionBusy = ref(false)
const batchMode = ref(false)
const batchSelected = ref<string[]>([])
const lastReviewed = ref<string>('')
const showShortcuts = ref(false)
const notesSaving = ref(false)
const shortcuts = ref({ include: 'Ctrl+Enter', exclude: 'Ctrl+Backspace', defer: 'Ctrl+D' })
let pollTimer: number | undefined

const current = computed(() => items.value.find((item) => item.id === selectedId.value) || null)
const analysis = computed(() => detail.value?.analysis || current.value?.analysis || null)
const reviewStatuses = [
  { value: 'pending_review', label: '待审核' },
  { value: 'deferred', label: '待定' },
  { value: 'included', label: '已入库' },
  { value: 'analysis_failed', label: '分析失败' },
]
const statusCount = computed(() => counts.value[queueStatus.value] || 0)
const pdfUrl = computed(() => (detail.value?.primary_file ? papersApi.fileUrl(detail.value.id) : ''))
const tagOptions = computed(() => app.tags.map((tag) => ({ value: tag.name, label: tag.name })))
const canUndo = computed(() => Boolean(lastReviewed.value))

watch(queueStatus, () => {
  selectedId.value = ''
  detail.value = null
  batchSelected.value = []
  loadQueue()
})

watch(selectedId, async (id) => {
  if (!id) return
  await loadDetail(id)
  rightTab.value = detail.value?.primary_file ? 'pdf' : 'evidence'
  pdfPage.value = 1
  reviewNote.value = ''
  selectedTags.value = []
})

async function loadQueue(keepSelection = true) {
  loadingQueue.value = true
  try {
    const result = await reviewApi.queue({
      status: queueStatus.value,
      sort: sort.value,
      q: keyword.value.trim(),
      page: 1,
      page_size: 100,
    })
    items.value = result.items
    total.value = result.total
    counts.value = result.counts
    if (!items.value.length) {
      selectedId.value = ''
      detail.value = null
      return
    }
    if (!keepSelection || !items.value.some((item) => item.id === selectedId.value)) {
      const routePaper = String(route.query.paper || '')
      const target = items.value.find((item) => item.id === routePaper) || items.value[0]
      selectedId.value = target.id
    }
  } finally {
    loadingQueue.value = false
  }
}

async function loadDetail(id: string) {
  loadingDetail.value = true
  try {
    detail.value = await reviewApi.detail(id)
  } finally {
    loadingDetail.value = false
  }
}

function select(id: string) {
  if (selectedId.value === id) return
  selectedId.value = id
  router.replace({ path: '/review', query: { paper: id } })
}

function move(delta: number) {
  const index = items.value.findIndex((item) => item.id === selectedId.value)
  const next = items.value[index + delta]
  if (next) select(next.id)
}

async function performAction(action: 'include' | 'exclude' | 'defer') {
  if (!current.value || actionBusy.value) return
  actionBusy.value = true
  const paperId = current.value.id
  const title = current.value.title
  try {
    await reviewApi.action(paperId, {
      action,
      note: reviewNote.value.trim(),
      tags: action === 'include' ? selectedTags.value : [],
    })
    lastReviewed.value = paperId
    const labels = { include: '已入库', exclude: '已标记为暂不采用', defer: '已标记为待定' }
    ElMessage.success(`${labels[action]}：${title.slice(0, 30)}${title.length > 30 ? '…' : ''}`)
    const index = items.value.findIndex((item) => item.id === paperId)
    reviewNote.value = ''
    selectedTags.value = []
    await loadQueue(false)
    const next = items.value[Math.min(index, items.value.length - 1)]
    if (next) selectedId.value = next.id
    else {
      selectedId.value = ''
      detail.value = null
    }
  } finally {
    actionBusy.value = false
  }
}

async function reanalyze() {
  if (!current.value) return
  await ElMessageBox.confirm('使用当前提示词与模型重新分析这篇文献？历史结果会保留。', '重新分析')
  await papersApi.analyze(current.value.id, true)
  ElMessage.success('已提交重新分析，完成后会重新进入待审核')
  await loadQueue()
}

async function undoLast() {
  if (!lastReviewed.value) return
  await reviewApi.undo(lastReviewed.value)
  ElMessage.success('已撤销上一条审核操作')
  lastReviewed.value = ''
  await loadQueue()
}

async function saveNoteOnly() {
  if (!current.value || !reviewNote.value.trim()) {
    ElMessage.warning('请先输入备注内容')
    return
  }
  notesSaving.value = true
  try {
    await papersApi.addNote(current.value.id, reviewNote.value.trim(), 'reading')
    ElMessage.success('备注已保存到文献笔记')
  } finally {
    notesSaving.value = false
  }
}

async function batchAct(action: 'include' | 'exclude' | 'defer') {
  if (!batchSelected.value.length) {
    ElMessage.warning('请先在左侧勾选文献')
    return
  }
  await ElMessageBox.confirm(`将对 ${batchSelected.value.length} 篇文献执行此审核操作，确认继续？`, '批量审核')
  const result = await reviewApi.batch(batchSelected.value, action, '批量审核')
  ElMessage.success(`批量操作完成：成功 ${result.count} 篇`)
  batchSelected.value = []
  await loadQueue()
}

function toggleBatch(id: string, checked: boolean) {
  if (checked) batchSelected.value = Array.from(new Set([...batchSelected.value, id]))
  else batchSelected.value = batchSelected.value.filter((item) => item !== id)
}

function toggleAllBatch(checked: boolean) {
  batchSelected.value = checked ? items.value.map((item) => item.id) : []
}

async function jumpToPage(page: number) {
  rightTab.value = 'pdf'
  pdfPage.value = page
  await nextTick()
  await nextTick()
  pdfRef.value?.jumpToPage(page)
}

function matchesShortcut(event: KeyboardEvent, spec: string): boolean {
  if (!spec) return false
  const tokens = spec.split('+').map((token) => token.trim().toLowerCase()).filter(Boolean)
  const key = tokens.pop() || ''
  if (!key) return false
  const needCtrl = tokens.some((token) => ['ctrl', 'cmd', 'meta', '⌘'].includes(token))
  const needShift = tokens.includes('shift')
  const needAlt = tokens.includes('alt')
  const eventKey = event.key.toLowerCase()
  const expectedKey = key === 'del' ? 'delete' : key
  if (eventKey !== expectedKey) return false
  if (needCtrl !== (event.ctrlKey || event.metaKey)) return false
  if (needShift !== event.shiftKey) return false
  if (needAlt !== event.altKey) return false
  return true
}

function onKeydown(event: KeyboardEvent) {
  const target = event.target as HTMLElement
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable) return
  if (matchesShortcut(event, shortcuts.value.include)) {
    event.preventDefault()
    performAction('include')
  } else if (matchesShortcut(event, shortcuts.value.exclude)) {
    event.preventDefault()
    performAction('exclude')
  } else if (matchesShortcut(event, shortcuts.value.defer)) {
    event.preventDefault()
    performAction('defer')
  } else if (event.key === 'ArrowRight' || event.key === 'j') {
    move(1)
  } else if (event.key === 'ArrowLeft' || event.key === 'k') {
    move(-1)
  } else if (event.key === '?' || (event.shiftKey && event.key === '/')) {
    showShortcuts.value = true
  }
}

onMounted(async () => {
  try {
    const pref = await settingsApi.get()
    const preferred = pref.values['review.default_sort']
    if (preferred === 'updated_desc' || preferred === 'score_desc') sort.value = preferred
    if (pref.values['review.shortcuts'] && typeof pref.values['review.shortcuts'] === 'object') {
      shortcuts.value = {
        include: pref.values['review.shortcuts'].include || 'Ctrl+Enter',
        exclude: pref.values['review.shortcuts'].exclude || 'Ctrl+Backspace',
        defer: pref.values['review.shortcuts'].defer || 'Ctrl+D',
      }
    }
  } catch {
    /* defaults are fine */
  }
  const routePaper = String(route.query.paper || '')
  if (routePaper) selectedId.value = routePaper
  await loadQueue(false)
  window.addEventListener('keydown', onKeydown)
  pollTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible' && !actionBusy.value) loadQueue(true)
  }, 12_000)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <div class="flex h-[calc(100vh-132px)] min-h-[620px] flex-col">
    <div class="mb-2 flex flex-wrap items-center gap-2">
      <div>
        <div class="flex items-center gap-2">
          <h1 class="text-[20px] font-semibold tracking-tight">审核工作台</h1>
          <span class="chip">{{ statusCount }} 篇</span>
          <span class="chip !text-amber-600">AI 辅助 · 人工决定</span>
        </div>
        <div class="mt-0.5 text-[11.5px] text-slate-400">快速判断创新性与研究价值，决定入库、暂不采用或待定</div>
      </div>
      <div class="ml-auto flex items-center gap-1.5">
        <el-select v-model="sort" size="small" style="width: 130px" @change="loadQueue()">
          <el-option value="score_desc" label="参考分从高到低" />
          <el-option value="score_asc" label="参考分从低到高" />
          <el-option value="updated_desc" label="最近更新" />
        </el-select>
        <el-button size="small" :disabled="!canUndo" @click="undoLast"><el-icon class="mr-1"><RefreshLeft /></el-icon>撤销上一步</el-button>
        <el-button size="small" @click="showShortcuts = true"><el-icon class="mr-1"><Keyboard /></el-icon>快捷键</el-button>
      </div>
    </div>

    <div class="grid min-h-0 flex-1 gap-3 xl:grid-cols-[240px_minmax(0,1fr)_440px]">
      <!-- Queue -->
      <aside class="panel flex min-h-0 flex-col overflow-hidden">
        <div class="border-b p-2" :style="{ borderColor: 'var(--app-border)' }">
          <el-radio-group v-model="queueStatus" size="small" class="!flex">
            <el-radio-button v-for="tab in reviewStatuses" :key="tab.value" :value="tab.value" class="flex-1">
              <span class="text-[11px]">{{ tab.label }}</span>
            </el-radio-button>
          </el-radio-group>
          <div class="mt-2 flex gap-1.5">
            <el-input v-model="keyword" size="small" placeholder="筛选待审核文献" clearable @keyup.enter="loadQueue(false)">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-tooltip content="批量审核模式">
              <el-button size="small" :type="batchMode ? 'primary' : 'default'" @click="batchMode = !batchMode"><el-icon><Finished /></el-icon></el-button>
            </el-tooltip>
          </div>
          <div v-if="batchMode" class="mt-2 flex items-center gap-2 rounded bg-[var(--app-panel-soft)] px-2 py-1.5">
            <el-checkbox :model-value="batchSelected.length === items.length && items.length > 0" @change="(val: boolean) => toggleAllBatch(val)">全选</el-checkbox>
            <span class="text-[10.5px] text-slate-400">已选 {{ batchSelected.length }}</span>
          </div>
        </div>

        <div v-loading="loadingQueue" class="min-h-0 flex-1 overflow-y-auto">
          <div v-if="!items.length" class="p-4">
            <EmptyState compact :title="queueStatus === 'pending_review' ? '没有待审核文献' : '当前队列为空'" description="完成全文解析与 AI 分析后，文献会出现在这里。" icon="View" />
          </div>
          <button
            v-for="item in items"
            :key="item.id"
            class="block w-full border-b px-3 py-2.5 text-left transition-colors"
            :class="selectedId === item.id ? 'bg-accent-500/10' : 'hover:bg-[var(--app-panel-soft)]'"
            :style="{ borderColor: 'var(--app-border)' }"
            @click="select(item.id)"
          >
            <div class="flex items-start gap-2">
              <el-checkbox v-if="batchMode" :model-value="batchSelected.includes(item.id)" @click.stop @change="(val: boolean) => toggleBatch(item.id, val)" />
              <div class="min-w-0 flex-1">
                <div class="line-clamp-2 text-[12px] font-medium leading-5">{{ item.title }}</div>
                <div class="mt-1 flex items-center gap-1.5 text-[10px] text-slate-400">
                  <span class="truncate">{{ item.journal || '—' }}</span>
                  <span>·</span>
                  <span>{{ item.year || '—' }}</span>
                  <span v-if="item.analysis?.is_mock" class="rounded bg-amber-500/10 px-1 text-amber-600">模拟</span>
                </div>
                <div class="mt-1.5 flex items-center gap-1.5">
                  <span class="flex h-5 min-w-[26px] items-center justify-center rounded px-1 text-[10px] font-semibold" :class="(item.screening_score || 0) >= 70 ? 'bg-emerald-500/10 text-emerald-600' : 'bg-amber-500/10 text-amber-600'">
                    {{ item.screening_score ?? '—' }}
                  </span>
                  <StatusTag type="review" :status="item.review_status" />
                  <span v-if="item.tags.length" class="ml-auto truncate text-[9.5px] text-slate-400">{{ item.tags.map((tag) => tag.name).join(' / ') }}</span>
                </div>
              </div>
            </div>
          </button>
        </div>

        <div v-if="batchMode" class="border-t p-2" :style="{ borderColor: 'var(--app-border)' }">
          <div class="grid grid-cols-3 gap-1.5">
            <el-button size="small" type="success" plain :disabled="!batchSelected.length" @click="batchAct('include')">入库</el-button>
            <el-button size="small" :disabled="!batchSelected.length" @click="batchAct('defer')">待定</el-button>
            <el-button size="small" type="danger" plain :disabled="!batchSelected.length" @click="batchAct('exclude')">不采用</el-button>
          </div>
        </div>
        <div class="border-t px-3 py-2 text-[10px] text-slate-400" :style="{ borderColor: 'var(--app-border)' }">
          共 {{ total }} 篇 · 键盘 ← → 切换
        </div>
      </aside>

      <!-- Center -->
      <main class="panel flex min-h-0 flex-col overflow-hidden">
        <div v-if="!current" class="flex flex-1 items-center justify-center">
          <EmptyState title="选择左侧文献开始审核" description="系统不会自动入库；每条 AI 结论都需经过你的确认。" icon="Checked" />
        </div>
        <template v-else>
          <div class="flex flex-wrap items-center gap-1.5 border-b px-3 py-2" :style="{ borderColor: 'var(--app-border)' }">
            <el-button size="small" type="success" :loading="actionBusy" @click="performAction('include')">
              <el-icon class="mr-1"><FolderChecked /></el-icon>入库
            </el-button>
            <el-button size="small" :loading="actionBusy" @click="performAction('defer')">
              <el-icon class="mr-1"><Clock /></el-icon>待定
            </el-button>
            <el-button size="small" type="danger" plain :loading="actionBusy" @click="performAction('exclude')">
              <el-icon class="mr-1"><FolderDelete /></el-icon>暂不采用
            </el-button>
            <el-button size="small" @click="reanalyze"><el-icon class="mr-1"><Refresh /></el-icon>重新分析</el-button>
            <div class="ml-auto flex items-center gap-1">
              <el-button size="small" :disabled="items.findIndex((item) => item.id === selectedId) <= 0" @click="move(-1)">上一篇</el-button>
              <el-button size="small" :disabled="items.findIndex((item) => item.id === selectedId) >= items.length - 1" @click="move(1)">下一篇</el-button>
            </div>
          </div>

          <div v-loading="loadingDetail" class="min-h-0 flex-1 overflow-y-auto p-4">
            <div class="flex flex-wrap items-start gap-2">
              <div class="min-w-0 flex-1">
                <h2 class="text-[16px] font-semibold leading-6">{{ detail?.title || current.title }}</h2>
                <div class="mt-1 text-[11.5px] text-slate-500">
                  {{ detail?.authors_text || current.authors_text || '作者未知' }} ·
                  {{ detail?.journal || current.journal || '期刊未知' }} ·
                  {{ detail?.publication_date_raw || detail?.publication_date || current.year || '日期未知' }}
                  <span v-if="detail?.doi" class="ml-1 text-slate-400">DOI {{ detail.doi }}</span>
                </div>
              </div>
              <div class="flex flex-col items-end gap-1">
                <StatusTag type="review" :status="detail?.review_status || current.review_status" />
                <div class="text-[10px] text-slate-400">{{ detail?.publication_date_precision === 'year' ? '日期仅精确到年' : '' }}</div>
              </div>
            </div>

            <div class="mt-2 flex flex-wrap gap-1.5">
              <StatusTag type="fulltext" :status="detail?.fulltext_status || current.fulltext_status" />
              <StatusTag type="parse" :status="detail?.parse_status || current.parse_status" />
              <StatusTag type="ai" :status="detail?.ai_status || current.ai_status" />
              <span v-for="tag in detail?.tags || current.tags" :key="tag.id" class="chip" :style="{ color: tag.color, borderColor: `${tag.color}44` }">{{ tag.name }}</span>
            </div>

            <el-alert
              v-if="analysis?.is_mock"
              class="!mt-3"
              type="warning"
              :closable="false"
              show-icon
              title="这是离线 Mock 模拟分析，仅用于验收流程，不能作为科研判断依据。请在设置中配置真实模型。"
            />

            <div class="mt-3 rounded-lg border-l-[3px] border-accent-500 bg-accent-500/5 px-3 py-3">
              <div class="micro mb-1">AI 快速筛选结论</div>
              <p class="text-[14px] font-medium leading-6">{{ analysis?.one_sentence_summary || current.one_sentence_summary || '暂无 AI 总结' }}</p>
              <p v-if="analysis?.screening_reason" class="mt-1.5 text-[11.5px] leading-5 text-slate-500">{{ analysis.screening_reason }}</p>
            </div>

            <div class="mt-3 grid gap-3 sm:grid-cols-2">
              <section class="soft-panel p-3">
                <div class="micro mb-1">原始摘要</div>
                <p class="line-clamp-[8] whitespace-pre-line text-[12px] leading-5 text-slate-600 dark:text-slate-300">{{ detail?.abstract || '该文献没有摘要' }}</p>
              </section>
              <section class="soft-panel p-3">
                <div class="micro mb-1">研究问题与价值</div>
                <p class="line-clamp-3 text-[12px] leading-5">{{ analysis?.research_problem || '未明确说明' }}</p>
                <p class="mt-1 line-clamp-3 text-[12px] leading-5 text-slate-500">{{ analysis?.research_value || '' }}</p>
                <div class="mt-2 flex items-center gap-2">
                  <span class="text-[10px] text-slate-400">AI 参考分</span>
                  <span class="text-[18px] font-semibold" :class="(analysis?.screening_score || 0) >= 70 ? 'text-emerald-600' : 'text-amber-600'">{{ analysis?.screening_score ?? '—' }}</span>
                  <span class="text-[10px] text-slate-400">/ 100 · 仅辅助</span>
                </div>
              </section>
            </div>

            <div class="divider"></div>
            <div class="flex items-center justify-between">
              <div class="section-title">AI 分析详情</div>
              <span class="text-[10.5px] text-slate-400">所有结论均需回到原文核对</span>
            </div>
            <div class="mt-3">
              <AnalysisView :analysis="analysis" compact editable @jump-page="jumpToPage" @edit="ElMessage.info('请打开文献完整详情编辑分析')" />
            </div>
          </div>
        </template>
      </main>

      <!-- Right panel -->
      <aside class="panel flex min-h-0 flex-col overflow-hidden">
        <el-tabs v-model="rightTab" class="review-right-tabs px-2 pt-1">
          <el-tab-pane name="pdf" label="原文 PDF">
            <div class="h-[calc(100vh-300px)] min-h-[420px]">
              <PdfViewer v-if="pdfUrl" ref="pdfRef" :url="pdfUrl" :initial-page="pdfPage" compact />
              <div v-else class="flex h-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-6 text-center" :style="{ borderColor: 'var(--app-border)' }">
                <el-icon :size="26" class="text-slate-300"><Document /></el-icon>
                <div class="text-[12.5px] font-medium text-slate-500">尚未获取全文</div>
                <div class="text-[11px] leading-5 text-slate-400">题录与摘要仍可审核；系统不会把“仅摘要分析”标记为全文分析。</div>
                <el-button size="small" @click="router.push('/imports')">去导入全文</el-button>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane name="evidence" label="原文证据">
            <div class="h-[calc(100vh-300px)] min-h-[420px] overflow-y-auto pr-1">
              <div v-if="!analysis?.evidence?.length && !analysis?.claimed_innovations?.length" class="p-4 text-center text-[12px] text-slate-400">没有可定位的证据</div>
              <div class="space-y-2">
                <div v-for="(item, index) in analysis?.evidence || []" :key="`e${index}`" class="soft-panel p-2.5">
                  <div class="mb-1 flex items-center justify-between text-[10px] text-slate-400">
                    <span>{{ item.section || '原文' }}</span>
                    <button v-if="item.page" class="link !text-[10px]" @click="jumpToPage(item.page)">第 {{ item.page }} 页 →</button>
                  </div>
                  <blockquote class="border-l-2 border-slate-300 pl-2 text-[11.5px] italic leading-5 text-slate-600 dark:border-slate-600 dark:text-slate-300">{{ item.quote }}</blockquote>
                  <div v-if="item.supports" class="mt-1 text-[10.5px] text-slate-500">支持：{{ item.supports }}</div>
                </div>
                <div v-for="(item, index) in analysis?.claimed_innovations || []" :key="`i${index}`" class="soft-panel p-2.5">
                  <div class="mb-1 flex items-center justify-between text-[10px]">
                    <span class="font-medium text-accent-600">创新点 {{ index + 1 }}</span>
                    <button v-if="item.page" class="link !text-[10px]" @click="jumpToPage(item.page)">第 {{ item.page }} 页 →</button>
                  </div>
                  <div class="text-[11.5px] font-medium">{{ item.name }}</div>
                  <div class="mt-1 text-[11px] text-slate-500">{{ item.evidence || '模型未提供原文引文' }}</div>
                </div>
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane name="notes" label="备注 / 标签">
            <div class="h-[calc(100vh-300px)] min-h-[420px] space-y-3 overflow-y-auto pr-1">
              <div>
                <div class="micro mb-1">审核备注（随审核记录保存）</div>
                <el-input v-model="reviewNote" type="textarea" :rows="4" placeholder="例如：方法可复现，创新点适合迁移到我的第 2 章；实验数据不足。" />
                <el-button class="mt-1.5" size="small" :loading="notesSaving" @click="saveNoteOnly">另存为长期笔记</el-button>
              </div>
              <div>
                <div class="micro mb-1">入库标签</div>
                <el-select v-model="selectedTags" multiple filterable allow-create default-first-option class="w-full" placeholder="选择或输入标签">
                  <el-option v-for="option in tagOptions" :key="option.value" :label="option.label" :value="option.value" />
                </el-select>
                <div class="mt-1 text-[10px] text-slate-400">标签会随审核一起保存，可在文献库中组合筛选。</div>
              </div>
              <div class="rounded-md border p-2.5 text-[10.5px] leading-5 text-slate-500" :style="{ borderColor: 'var(--app-border)' }">
                <div class="mb-1 font-medium text-slate-600 dark:text-slate-300">快捷键</div>
                <div>{{ shortcuts.include }}：入库</div>
                <div>{{ shortcuts.exclude }}：暂不采用</div>
                <div>{{ shortcuts.defer }}：待定 · ← →：切换文献</div>
              </div>
              <div>
                <div class="micro mb-1">审核记录</div>
                <div v-if="!detail?.reviews?.length" class="text-[11px] text-slate-400">暂无审核记录</div>
                <div v-for="review in detail?.reviews || []" :key="review.id" class="mb-1.5 rounded border px-2 py-1.5 text-[10.5px]" :style="{ borderColor: 'var(--app-border)' }">
                  <div class="flex items-center gap-1.5">
                    <span class="font-medium">{{ review.action === 'include' ? '入库' : review.action === 'exclude' ? '暂不采用' : review.action === 'defer' ? '待定' : '撤销' }}</span>
                    <span class="text-slate-400">{{ new Date(review.created_at).toLocaleString('zh-CN') }}</span>
                  </div>
                  <div v-if="review.note" class="mt-0.5 text-slate-500">{{ review.note }}</div>
                </div>
              </div>
            </div>
          </el-tab-pane>
        </el-tabs>

        <div class="mt-auto border-t p-2.5" :style="{ borderColor: 'var(--app-border)' }">
          <div class="grid grid-cols-3 gap-1.5">
            <el-button type="success" :loading="actionBusy" :disabled="!current" @click="performAction('include')"><el-icon class="mr-1"><FolderChecked /></el-icon>入库</el-button>
            <el-button :loading="actionBusy" :disabled="!current" @click="performAction('defer')">待定</el-button>
            <el-button type="danger" plain :loading="actionBusy" :disabled="!current" @click="performAction('exclude')">不采用</el-button>
          </div>
          <div class="mt-1 text-center text-[9.5px] text-slate-400">入库是人工确认后的业务状态，下载全文不会自动入库</div>
        </div>
      </aside>
    </div>

    <el-dialog v-model="showShortcuts" title="审核快捷键" width="420px">
      <div class="space-y-2 text-[12.5px]">
        <div class="flex justify-between"><span>入库</span><kbd class="soft-panel px-2 py-0.5 font-mono text-[11px]">{{ shortcuts.include }}</kbd></div>
        <div class="flex justify-between"><span>暂不采用</span><kbd class="soft-panel px-2 py-0.5 font-mono text-[11px]">{{ shortcuts.exclude }}</kbd></div>
        <div class="flex justify-between"><span>待定</span><kbd class="soft-panel px-2 py-0.5 font-mono text-[11px]">{{ shortcuts.defer }}</kbd></div>
        <div class="flex justify-between"><span>上一篇 / 下一篇</span><kbd class="soft-panel px-2 py-0.5 font-mono text-[11px]">← / →</kbd></div>
        <div class="flex justify-between"><span>帮助</span><kbd class="soft-panel px-2 py-0.5 font-mono text-[11px]">?</kbd></div>
      </div>
      <div class="mt-3 text-[11px] leading-5 text-slate-400">在输入框内输入时快捷键自动禁用，避免误操作。</div>
    </el-dialog>
  </div>
</template>

<style scoped>
.review-right-tabs :deep(.el-tabs__header) {
  margin-bottom: 6px;
}
.review-right-tabs :deep(.el-tabs__content) {
  overflow: visible;
}
kbd {
  border: 1px solid var(--app-border);
}
</style>
