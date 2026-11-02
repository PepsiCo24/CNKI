<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { aiApi, papersApi } from '@/api'
import { useAppStore } from '@/stores/app'
import type { PaperDetail } from '@/types'
import StatusTag from './StatusTag.vue'
import AnalysisView from './AnalysisView.vue'
import PdfViewer from './PdfViewer.vue'

const props = defineProps<{ modelValue: boolean; paperId: string | null }>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'updated'): void
}>()

const app = useAppStore()
const detail = ref<PaperDetail | null>(null)
const loading = ref(false)
const activeTab = ref<'overview' | 'pdf' | 'notes' | 'history'>('overview')
const pdfRef = ref<InstanceType<typeof PdfViewer> | null>(null)
const pdfPage = ref(1)
const editVisible = ref(false)
const tagVisible = ref(false)
const analysisEditVisible = ref(false)
const noteDraft = ref('')
const noteType = ref('general')
const noteBusy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedTags = ref<string[]>([])
const saving = ref(false)

const metadataForm = reactive({
  title: '',
  authors: '',
  journal: '',
  doi: '',
  publication_date: '',
  abstract: '',
  keywords: '',
  source_url: '',
})

const analysisForm = reactive({
  one_sentence_summary: '',
  research_problem: '',
  main_method: '',
  innovation_summary: '',
  research_value: '',
  screening_reason: '',
  screening_score: 0,
})

const tagOptions = computed(() => app.tags.map((tag) => ({ label: tag.name, value: tag.name })))
const pdfUrl = computed(() => (detail.value?.primary_file ? papersApi.fileUrl(detail.value.id) : ''))
const canAnalyze = computed(() => Boolean(detail.value?.abstract || detail.value?.text_info))
const analysis = computed(() => detail.value?.analysis || null)

const visible = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})

async function load() {
  if (!props.paperId) return
  loading.value = true
  try {
    detail.value = await papersApi.get(props.paperId)
    selectedTags.value = detail.value.tags.map((tag) => tag.name)
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.modelValue, props.paperId],
  ([open, id]) => {
    if (open && id) {
      activeTab.value = 'overview'
      pdfPage.value = 1
      load()
    }
  },
  { immediate: true },
)

function refresh() {
  load()
  emit('updated')
  app.loadTags()
}

async function analyze(force = false) {
  if (!detail.value) return
  await papersApi.analyze(detail.value.id, force)
  ElMessage.success(force ? '已提交重新分析' : '已提交 AI 分析')
  setTimeout(refresh, 1200)
}

async function parseFulltext() {
  if (!detail.value) return
  await papersApi.parse(detail.value.id)
  ElMessage.success('全文解析任务已排队')
  setTimeout(refresh, 1200)
}

function openEdit() {
  if (!detail.value) return
  Object.assign(metadataForm, {
    title: detail.value.title,
    authors: detail.value.authors.join('; '),
    journal: detail.value.journal,
    doi: detail.value.doi || '',
    publication_date: detail.value.publication_date || '',
    abstract: detail.value.abstract,
    keywords: detail.value.keywords.join('; '),
    source_url: detail.value.source_url,
  })
  editVisible.value = true
}

async function saveMetadata() {
  if (!detail.value) return
  saving.value = true
  try {
    await papersApi.update(detail.value.id, {
      title: metadataForm.title,
      authors: metadataForm.authors.split(/[;；,，]/).map((item) => item.trim()).filter(Boolean),
      journal: metadataForm.journal,
      doi: metadataForm.doi || null,
      publication_date: metadataForm.publication_date || null,
      abstract: metadataForm.abstract,
      keywords: metadataForm.keywords.split(/[;；,，]/).map((item) => item.trim()).filter(Boolean),
      source_url: metadataForm.source_url,
    })
    editVisible.value = false
    ElMessage.success('文献信息已更新')
    refresh()
  } finally {
    saving.value = false
  }
}

function openTags() {
  selectedTags.value = detail.value?.tags.map((tag) => tag.name) || []
  tagVisible.value = true
}

async function saveTags() {
  if (!detail.value) return
  saving.value = true
  try {
    await papersApi.addTags(detail.value.id, selectedTags.value, true)
    tagVisible.value = false
    ElMessage.success('标签已更新')
    refresh()
  } finally {
    saving.value = false
  }
}

async function addNote() {
  if (!detail.value || !noteDraft.value.trim()) return
  noteBusy.value = true
  try {
    await papersApi.addNote(detail.value.id, noteDraft.value.trim(), noteType.value)
    noteDraft.value = ''
    ElMessage.success('笔记已保存')
    refresh()
  } finally {
    noteBusy.value = false
  }
}

async function deleteNote(noteId: string) {
  await ElMessageBox.confirm('删除这条笔记？', '删除笔记', { type: 'warning' })
  await papersApi.deleteNote(noteId)
  ElMessage.success('笔记已删除')
  refresh()
}

async function saveAnalysisEdit() {
  if (!detail.value?.analysis) return
  saving.value = true
  try {
    await aiApi.editResult(detail.value.analysis.id, { ...analysisForm })
    analysisEditVisible.value = false
    ElMessage.success('分析结果已保存，原始版本已保留')
    refresh()
  } finally {
    saving.value = false
  }
}

function openAnalysisEdit() {
  if (!detail.value?.analysis) return
  Object.assign(analysisForm, {
    one_sentence_summary: detail.value.analysis.one_sentence_summary,
    research_problem: detail.value.analysis.research_problem,
    main_method: detail.value.analysis.main_method,
    innovation_summary: detail.value.analysis.innovation_summary,
    research_value: detail.value.analysis.research_value,
    screening_reason: detail.value.analysis.screening_reason,
    screening_score: detail.value.analysis.screening_score,
  })
  analysisEditVisible.value = true
}

function triggerAttach() {
  fileInput.value?.click()
}

async function onAttachFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !detail.value) return
  try {
    const result = await papersApi.attachFile(detail.value.id, file)
    ElMessage.success(result.message || '全文已关联')
    refresh()
  } finally {
    input.value = ''
  }
}

async function jumpToPage(page: number) {
  pdfPage.value = page
  activeTab.value = 'pdf'
  await nextTick()
  await nextTick()
  pdfRef.value?.jumpToPage(page)
}

async function resolveDuplicate(action: 'keep_separate' | 'confirm_duplicate') {
  if (!detail.value) return
  await papersApi.resolveDuplicate(detail.value.id, action)
  ElMessage.success(action === 'keep_separate' ? '已标记为不同文献' : '已确认重复关联')
  refresh()
}

async function removePaper() {
  if (!detail.value) return
  await ElMessageBox.confirm(
    `将《${detail.value.title}》移出文献列表？原始文件仍保留在磁盘，可在数据目录中找回。`,
    '移出文献',
    { type: 'warning', confirmButtonText: '移出' },
  )
  await papersApi.remove(detail.value.id)
  ElMessage.success('文献已移出')
  visible.value = false
  emit('updated')
}

function formatDate(value?: string | null) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

function openOriginal() {
  if (detail.value?.primary_file) window.open(papersApi.fileUrl(detail.value.id), '_blank')
}
</script>

<template>
  <el-drawer v-model="visible" size="920px" :with-header="true" destroy-on-close>
    <template #header>
      <div class="flex w-full items-start gap-3 pr-4">
        <div class="min-w-0 flex-1">
          <div class="line-clamp-2 pr-3 text-[15px] font-semibold leading-6">{{ detail?.title || '文献详情' }}</div>
          <div v-if="detail" class="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
            <span>{{ detail.authors_text || '作者未知' }}</span>
            <span>·</span>
            <span>{{ detail.journal || '期刊未知' }} {{ detail.year || '' }}</span>
            <span v-if="detail.doi">· DOI {{ detail.doi }}</span>
          </div>
        </div>
        <div v-if="detail" class="flex shrink-0 flex-col items-end gap-1.5">
          <StatusTag type="review" :status="detail.review_status" />
          <div class="flex gap-1">
            <StatusTag type="fulltext" :status="detail.fulltext_status" />
            <StatusTag type="ai" :status="detail.ai_status" />
          </div>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="h-full">
      <template v-if="detail">
        <el-alert
          v-if="detail.duplicate_status === 'suspected'"
          type="warning"
          :closable="false"
          show-icon
          class="!mb-3"
        >
          <template #title>
            <div class="flex flex-wrap items-center gap-2">
              <span>标题与已有文献高度相似，但全文文件不同，系统未自动删除。</span>
              <el-button size="small" @click="resolveDuplicate('keep_separate')">确认不是重复</el-button>
              <el-button size="small" type="warning" plain @click="resolveDuplicate('confirm_duplicate')">标记为重复关联</el-button>
            </div>
          </template>
        </el-alert>

        <div class="mb-3 flex flex-wrap gap-2">
          <el-button size="small" type="primary" :disabled="!canAnalyze" @click="analyze(false)">
            <el-icon class="mr-1"><MagicStick /></el-icon>AI 分析
          </el-button>
          <el-button size="small" :disabled="!detail.analysis" @click="analyze(true)">重新分析</el-button>
          <el-button size="small" @click="parseFulltext"><el-icon class="mr-1"><Document /></el-icon>解析全文</el-button>
          <el-button size="small" @click="triggerAttach"><el-icon class="mr-1"><Paperclip /></el-icon>{{ detail.primary_file ? '替换全文' : '关联全文' }}</el-button>
          <el-button size="small" @click="openEdit"><el-icon class="mr-1"><EditPen /></el-icon>编辑信息</el-button>
          <el-button size="small" @click="openTags">标签</el-button>
          <el-button size="small" :disabled="!detail.primary_file" @click="openOriginal">打开原文件</el-button>
          <input ref="fileInput" type="file" accept=".pdf,.caj" class="hidden" @change="onAttachFile" />
          <el-button size="small" class="!ml-auto" type="danger" plain @click="removePaper">移出文献</el-button>
        </div>

        <el-tabs v-model="activeTab" class="paper-tabs">
          <el-tab-pane name="overview" label="概览与 AI 分析">
            <div class="grid gap-4 xl:grid-cols-[1fr_1.35fr]">
              <div class="space-y-3">
                <section class="panel p-4">
                  <div class="mb-2 flex items-center justify-between">
                    <div class="section-title">题录信息</div>
                    <StatusTag v-if="detail.publication_date_precision" :status="detail.publication_date_precision" type="job" :label="detail.publication_date_precision === 'day' ? '日期精确到日' : detail.publication_date_precision === 'month' ? '日期精确到月' : '日期精确到年'" />
                  </div>
                  <dl class="grid grid-cols-[72px_1fr] gap-x-3 gap-y-2 text-[12px]">
                    <dt class="text-slate-400">作者</dt><dd class="break-all">{{ detail.authors_text || '未明确说明' }}</dd>
                    <dt class="text-slate-400">期刊</dt><dd>{{ detail.journal || '未明确说明' }}</dd>
                    <dt class="text-slate-400">发表日期</dt><dd>{{ detail.publication_date_raw || detail.publication_date || '未明确说明' }}</dd>
                    <dt class="text-slate-400">DOI</dt><dd class="break-all">{{ detail.doi || '未明确说明' }}</dd>
                    <dt class="text-slate-400">来源</dt><dd>{{ detail.source }} · {{ detail.metadata_source || '—' }}</dd>
                    <dt class="text-slate-400">文件</dt><dd>{{ detail.primary_file ? `${detail.primary_file.file_format.toUpperCase()} · ${(detail.primary_file.size_bytes / 1024 / 1024).toFixed(2)} MB · ${detail.primary_file.page_count} 页` : '暂无全文' }}</dd>
                    <dt class="text-slate-400">解析</dt><dd>{{ detail.text_info ? `${detail.text_info.char_count} 字符 · ${detail.text_info.quality}` : '尚未解析' }}</dd>
                  </dl>
                  <div class="mt-3 flex flex-wrap gap-1.5">
                    <span v-for="tag in detail.tags" :key="tag.id" class="chip" :style="{ color: tag.color, borderColor: `${tag.color}44` }">{{ tag.name }}</span>
                    <span v-if="!detail.tags.length" class="text-[11px] text-slate-400">暂无标签</span>
                  </div>
                  <div v-if="detail.keywords.length" class="mt-3 flex flex-wrap gap-1.5">
                    <span v-for="keyword in detail.keywords" :key="keyword" class="rounded bg-slate-100 px-1.5 py-0.5 text-[10.5px] text-slate-500 dark:bg-slate-800">{{ keyword }}</span>
                  </div>
                </section>

                <section class="panel p-4">
                  <div class="mb-2 section-title">原始摘要</div>
                  <p class="max-h-[220px] overflow-y-auto whitespace-pre-line text-[12px] leading-5 text-slate-600 dark:text-slate-300">{{ detail.abstract || '该题录没有摘要。' }}</p>
                  <div v-if="detail.source_url" class="mt-2">
                    <a :href="detail.source_url" target="_blank" class="link !text-[11px]">查看文献详情页</a>
                  </div>
                </section>

                <section v-if="detail.text_info" class="panel p-4">
                  <div class="mb-2 section-title">章节定位</div>
                  <div class="space-y-1.5">
                    <button
                      v-for="section in detail.text_info.sections"
                      :key="section.name + section.page"
                      class="flex w-full items-center justify-between rounded px-2 py-1 text-left text-[11.5px] hover:bg-[var(--app-panel-soft)]"
                      @click="jumpToPage(section.page)"
                    >
                      <span>{{ section.label }}</span>
                      <span class="text-slate-400">第 {{ section.page }} 页</span>
                    </button>
                  </div>
                </section>
              </div>

              <div class="panel p-4">
                <AnalysisView
                  :analysis="analysis"
                  compact
                  editable
                  @jump-page="jumpToPage"
                  @edit="openAnalysisEdit"
                />
              </div>
            </div>
          </el-tab-pane>

          <el-tab-pane name="pdf" label="PDF 原文">
            <div v-if="detail.primary_file" class="h-[calc(100vh-240px)] min-h-[520px]">
              <PdfViewer ref="pdfRef" :url="pdfUrl" :initial-page="pdfPage" />
            </div>
            <div v-else class="flex h-[360px] flex-col items-center justify-center gap-2 rounded-lg border border-dashed" :style="{ borderColor: 'var(--app-border)' }">
              <el-icon :size="28" class="text-slate-300"><Document /></el-icon>
              <div class="text-[13px] text-slate-500">尚未关联全文文件</div>
              <el-button size="small" type="primary" @click="triggerAttach">关联本地 PDF / CAJ</el-button>
            </div>
          </el-tab-pane>

          <el-tab-pane name="notes" label="笔记与想法">
            <div class="grid gap-4 lg:grid-cols-[320px_1fr]">
              <section class="panel p-4">
                <div class="section-title">新增笔记</div>
                <el-select v-model="noteType" size="small" class="mt-3 w-full">
                  <el-option value="general" label="阅读笔记" />
                  <el-option value="idea" label="研究想法" />
                  <el-option value="reading" label="精读记录" />
                </el-select>
                <el-input v-model="noteDraft" type="textarea" :rows="6" class="mt-2" placeholder="记录方法复现要点、可迁移的创新点或个人判断…" />
                <el-button class="mt-2 w-full" type="primary" :loading="noteBusy" @click="addNote">保存笔记</el-button>
              </section>
              <section class="space-y-2">
                <div v-if="!detail.notes.length" class="panel p-6 text-center text-[12px] text-slate-400">暂无笔记</div>
                <div v-for="note in detail.notes" :key="note.id" class="panel p-3">
                  <div class="mb-1 flex items-center gap-2">
                    <span class="chip">{{ note.note_type === 'idea' ? '研究想法' : note.note_type === 'reading' ? '精读记录' : '阅读笔记' }}</span>
                    <span class="text-[10.5px] text-slate-400">{{ formatDate(note.created_at) }}</span>
                    <el-button class="ml-auto" link type="danger" size="small" @click="deleteNote(note.id)">删除</el-button>
                  </div>
                  <p class="whitespace-pre-line text-[12.5px] leading-5">{{ note.content }}</p>
                </div>
              </section>
            </div>
          </el-tab-pane>

          <el-tab-pane name="history" label="审核与分析记录">
            <div class="grid gap-4 lg:grid-cols-2">
              <section class="panel overflow-hidden">
                <div class="border-b px-4 py-3 section-title" :style="{ borderColor: 'var(--app-border)' }">人工审核记录</div>
                <div v-if="!detail.reviews.length" class="p-6 text-center text-[12px] text-slate-400">暂无审核记录</div>
                <div v-else class="divide-y" :style="{ borderColor: 'var(--app-border)' }">
                  <div v-for="review in detail.reviews" :key="review.id" class="px-4 py-2.5">
                    <div class="flex items-center gap-2 text-[11.5px]">
                      <span class="font-medium">{{ review.action === 'include' ? '入库' : review.action === 'exclude' ? '暂不采用' : review.action === 'defer' ? '待定' : review.action === 'undo' ? '撤销审核' : review.action }}</span>
                      <StatusTag :status="review.to_status" type="review" />
                      <span class="ml-auto text-[10px] text-slate-400">{{ formatDate(review.created_at) }}</span>
                    </div>
                    <div v-if="review.note" class="mt-1 text-[11.5px] text-slate-500">{{ review.note }}</div>
                  </div>
                </div>
              </section>
              <section class="panel overflow-hidden">
                <div class="border-b px-4 py-3 section-title" :style="{ borderColor: 'var(--app-border)' }">分析版本</div>
                <div class="divide-y" :style="{ borderColor: 'var(--app-border)' }">
                  <div v-for="item in detail.analysis_history" :key="item.id" class="px-4 py-2.5">
                    <div class="flex items-center gap-2 text-[11.5px]">
                      <span class="font-medium">{{ item.model }}</span>
                      <span class="chip">v{{ item.prompt_version }}</span>
                      <span v-if="item.is_mock" class="chip !text-amber-600">模拟</span>
                      <span v-if="item.is_edited" class="chip">人工编辑</span>
                      <span v-if="item.is_current" class="chip !text-emerald-600">当前</span>
                      <span class="ml-auto text-[10px] text-slate-400">{{ formatDate(item.created_at) }}</span>
                    </div>
                    <div class="mt-1 line-clamp-2 text-[11.5px] text-slate-500">{{ item.one_sentence_summary }}</div>
                  </div>
                </div>
              </section>
            </div>
          </el-tab-pane>
        </el-tabs>
      </template>
    </div>

    <!-- Metadata edit -->
    <el-dialog v-model="editVisible" title="编辑文献元数据" width="680px" append-to-body>
      <el-form label-position="top">
        <el-form-item label="标题"><el-input v-model="metadataForm.title" /></el-form-item>
        <div class="grid gap-3 sm:grid-cols-2">
          <el-form-item label="作者（分号分隔）"><el-input v-model="metadataForm.authors" /></el-form-item>
          <el-form-item label="期刊"><el-input v-model="metadataForm.journal" /></el-form-item>
          <el-form-item label="DOI"><el-input v-model="metadataForm.doi" /></el-form-item>
          <el-form-item label="发表日期">
            <el-date-picker v-model="metadataForm.publication_date" type="date" value-format="YYYY-MM-DD" class="!w-full" />
          </el-form-item>
        </div>
        <el-form-item label="关键词（分号分隔）"><el-input v-model="metadataForm.keywords" /></el-form-item>
        <el-form-item label="摘要"><el-input v-model="metadataForm.abstract" type="textarea" :rows="5" /></el-form-item>
        <el-form-item label="详情链接"><el-input v-model="metadataForm.source_url" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveMetadata">保存</el-button>
      </template>
    </el-dialog>

    <!-- Tags -->
    <el-dialog v-model="tagVisible" title="编辑标签" width="480px" append-to-body>
      <el-select v-model="selectedTags" multiple filterable allow-create default-first-option class="w-full" placeholder="选择或输入新标签">
        <el-option v-for="option in tagOptions" :key="option.value" :label="option.label" :value="option.value" />
      </el-select>
      <div class="mt-2 text-[11px] text-slate-400">可输入新的研究方向、方法、技术、数据集、实验类型或阅读优先级标签。</div>
      <template #footer>
        <el-button @click="tagVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveTags">保存标签</el-button>
      </template>
    </el-dialog>

    <!-- Analysis edit -->
    <el-dialog v-model="analysisEditVisible" title="人工编辑 AI 分析结果" width="720px" append-to-body>
      <el-alert type="info" :closable="false" show-icon class="!mb-3" title="保存后保留 AI 原始版本，并在结果上标记“人工已编辑”。审核判断以你的编辑为准。" />
      <el-form label-position="top">
        <el-form-item label="一句话总结"><el-input v-model="analysisForm.one_sentence_summary" type="textarea" :rows="2" /></el-form-item>
        <div class="grid gap-3 sm:grid-cols-2">
          <el-form-item label="研究问题"><el-input v-model="analysisForm.research_problem" type="textarea" :rows="3" /></el-form-item>
          <el-form-item label="研究方法"><el-input v-model="analysisForm.main_method" type="textarea" :rows="3" /></el-form-item>
        </div>
        <el-form-item label="创新点总结"><el-input v-model="analysisForm.innovation_summary" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="研究价值"><el-input v-model="analysisForm.research_value" type="textarea" :rows="3" /></el-form-item>
        <div class="grid gap-3 sm:grid-cols-[1fr_140px]">
          <el-form-item label="筛选理由"><el-input v-model="analysisForm.screening_reason" type="textarea" :rows="2" /></el-form-item>
          <el-form-item label="筛选参考分">
            <el-input-number v-model="analysisForm.screening_score" :min="0" :max="100" class="!w-full" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="analysisEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveAnalysisEdit">保存并保留原版</el-button>
      </template>
    </el-dialog>
  </el-drawer>
</template>
