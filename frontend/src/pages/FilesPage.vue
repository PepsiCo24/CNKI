<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { aiApi, collectionsApi, exportsApi, papersApi } from '@/api'
import type { PaperDetail, PaperSummary, TreeNode } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'
import PaperDetailDrawer from '@/components/PaperDetailDrawer.vue'

const router = useRouter()
const nodes = ref<TreeNode[]>([])
const papers = ref<PaperSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(25)
const loading = ref(false)
const keyword = ref('')
const treeKey = ref('all')
const selectedNode = ref<TreeNode | null>(null)
const selectedIds = ref<string[]>([])
const selectedPaper = ref<PaperSummary | null>(null)
const selectedDetail = ref<PaperDetail | null>(null)
const detailLoading = ref(false)
const drawerVisible = ref(false)
const detailPaperId = ref<string | null>(null)
const pageSizeOptions = [25, 50, 100]
const viewMode = ref<'table' | 'cards'>('table')
const sort = ref('created_at')
const order = ref('desc')
const exportVisible = ref(false)
const exportFormat = ref('xlsx')
const exportBusy = ref(false)
const collectionVisible = ref(false)
const collectionName = ref('')
let timer: number | undefined

const collections = computed(() => {
  const parent = nodes.value.find((node) => node.key === 'collections')
  const flat: Array<{ id: string; name: string }> = []
  const walk = (list: TreeNode[]) => {
    list.forEach((node) => {
      if (node.key.startsWith('collection:')) flat.push({ id: node.key.split(':')[1], name: node.label })
      if (node.children?.length) walk(node.children)
    })
  }
  walk(parent?.children || [])
  return flat
})

const currentTitle = computed(() => {
  const node = selectedNode.value
  if (!node) return '全部文献'
  return node.label
})

async function loadTree() {
  const result = await papersApi.tree()
  nodes.value = result.nodes
}

async function loadPapers() {
  loading.value = true
  try {
    const result = await papersApi.list({
      page: page.value,
      page_size: pageSize.value,
      q: keyword.value.trim(),
      tree_key: treeKey.value === 'all' ? '' : treeKey.value,
      sort: sort.value,
      order: order.value,
    })
    papers.value = result.items
    total.value = result.total
    if (papers.value.length && !selectedPaper.value) selectPaper(papers.value[0])
    if (!papers.value.length) {
      selectedPaper.value = null
      selectedDetail.value = null
    }
  } finally {
    loading.value = false
  }
}

function handleNodeClick(data: TreeNode) {
  if (data.children?.length) {
    selectedNode.value = data
    selectedIds.value = []
    page.value = 1
    // Parent nodes like "检索任务" expand rather than filter all papers.
    if (['tasks', 'journals', 'years', 'collections'].includes(data.key)) return
  }
  selectedNode.value = data
  treeKey.value = data.key
  page.value = 1
  selectedPaper.value = null
  selectedDetail.value = null
  selectedIds.value = []
  loadPapers()
}

async function selectPaper(paper: PaperSummary) {
  selectedPaper.value = paper
  detailPaperId.value = paper.id
  detailLoading.value = true
  try {
    selectedDetail.value = await papersApi.get(paper.id)
  } catch {
    selectedDetail.value = null
  } finally {
    detailLoading.value = false
  }
}

function openFullDetail() {
  if (!selectedPaper.value) return
  detailPaperId.value = selectedPaper.value.id
  drawerVisible.value = true
}

function openPaper(paper: PaperSummary) {
  detailPaperId.value = paper.id
  drawerVisible.value = true
}

async function analyzeSelected() {
  const ids = selectedIds.value.length ? selectedIds.value : selectedPaper.value ? [selectedPaper.value.id] : []
  if (!ids.length) {
    ElMessage.warning('请先选择文献')
    return
  }
  await ElMessageBox.confirm(
    `将为 ${ids.length} 篇文献创建 AI 分析任务。仅当摘要或全文可用时才会分析，确认继续？`,
    '批量 AI 分析',
  )
  await aiApi.analyze(ids, false)
  ElMessage.success('分析任务已排队，可在 AI 分析中心查看进度')
}

async function parseSelected() {
  const ids = selectedIds.value.length ? selectedIds.value : selectedPaper.value ? [selectedPaper.value.id] : []
  if (!ids.length) return
  for (const id of ids) await papersApi.parse(id)
  ElMessage.success(`${ids.length} 个解析任务已排队`)
}

async function exportPapers() {
  exportBusy.value = true
  try {
    const result = await exportsApi.create({
      format: exportFormat.value,
      paper_ids: selectedIds.value.length ? selectedIds.value : papers.value.map((paper) => paper.id),
      filters: { tree_key: treeKey.value === 'all' ? '' : treeKey.value, q: keyword.value.trim() },
      include_notes: true,
      include_analysis: true,
    })
    ElMessage.success(`导出完成：${result.filename}`)
    window.open(result.download_url, '_blank')
    exportVisible.value = false
  } finally {
    exportBusy.value = false
  }
}

async function createCollection() {
  if (!collectionName.value.trim()) return
  await collectionsApi.create(collectionName.value.trim())
  collectionName.value = ''
  collectionVisible.value = false
  await loadTree()
  ElMessage.success('自定义文件夹已创建')
}

async function addSelectionToCollection(collectionId: string) {
  if (!selectedIds.value.length) {
    ElMessage.warning('请先在列表中多选文献')
    return
  }
  await collectionsApi.addPapers(collectionId, selectedIds.value)
  await loadTree()
  ElMessage.success('已加入自定义文件夹')
}

function openOriginalFile(paper: PaperSummary | null) {
  if (!paper?.has_fulltext) return
  window.open(papersApi.fileUrl(paper.id), '_blank')
}

function toggleCardSelection(paper: PaperSummary, checked: boolean) {
  if (checked) selectedIds.value = Array.from(new Set([...selectedIds.value, paper.id]))
  else selectedIds.value = selectedIds.value.filter((id) => id !== paper.id)
}

async function handleNodeCommand(command: string, data: TreeNode) {
  if (command === 'delete' && data.key.startsWith('collection:')) {
    await ElMessageBox.confirm(`删除文件夹“${data.label}”？文献不会被删除。`, '删除文件夹', { type: 'warning' })
    await collectionsApi.remove(data.key.split(':')[1])
    await loadTree()
    ElMessage.success('文件夹已删除')
  }
}

function onSelectionChange(rows: PaperSummary[]) {
  selectedIds.value = rows.map((row) => row.id)
}

function refreshAfterDrawer() {
  loadPapers()
  loadTree()
}

watch([keyword], () => {
  page.value = 1
  loadPapers()
})

onMounted(async () => {
  await Promise.all([loadTree(), loadPapers()])
  timer = window.setInterval(() => {
    if (document.visibilityState === 'visible' && !loading.value) {
      loadPapers()
      loadTree()
    }
  }, 15_000)
})
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div>
    <PageHeader title="文件管理" subtitle="三栏式文献文件树：状态、任务、期刊、年份与自定义文件夹" eyebrow="Files">
      <template #actions>
        <el-button size="small" @click="router.push('/imports')"><el-icon class="mr-1"><Upload /></el-icon>导入</el-button>
        <el-button size="small" @click="collectionVisible = true"><el-icon class="mr-1"><FolderAdd /></el-icon>新建文件夹</el-button>
        <el-button size="small" @click="exportVisible = true"><el-icon class="mr-1"><Download /></el-icon>导出</el-button>
      </template>
    </PageHeader>

    <div class="grid gap-3 xl:grid-cols-[232px_minmax(0,1fr)_312px]">
      <!-- Tree -->
      <aside class="panel flex h-[calc(100vh-238px)] min-h-[520px] flex-col overflow-hidden">
        <div class="border-b px-3 py-2.5" :style="{ borderColor: 'var(--app-border)' }">
          <div class="flex items-center gap-2">
            <span class="text-[12px] font-semibold">文献目录</span>
            <el-button class="ml-auto" link size="small" @click="loadTree"><el-icon><Refresh /></el-icon></el-button>
          </div>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto p-2">
          <el-tree
            :data="nodes"
            node-key="key"
            :props="{ label: 'label', children: 'children' }"
            :default-expanded-keys="['tasks', 'journals', 'years']"
            highlight-current
            :expand-on-click-node="true"
            @node-click="handleNodeClick"
          >
            <template #default="{ data }">
              <div class="group flex w-full min-w-0 items-center gap-1.5 pr-1">
                <el-icon :size="14" class="shrink-0 text-slate-400"><component :is="data.icon || 'Document'" /></el-icon>
                <span class="min-w-0 flex-1 truncate text-[12px]">{{ data.label }}</span>
                <span class="shrink-0 rounded-full bg-slate-100 px-1.5 text-[10px] tabular-nums text-slate-500 dark:bg-slate-800">{{ data.count }}</span>
                <el-dropdown v-if="String(data.key).startsWith('collection:')" trigger="click" @command="(cmd: string) => handleNodeCommand(cmd, data)">
                  <el-icon class="hidden shrink-0 text-slate-400 group-hover:block"><MoreFilled /></el-icon>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="delete">删除文件夹</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </template>
          </el-tree>
        </div>
        <div class="border-t p-2" :style="{ borderColor: 'var(--app-border)' }">
          <button class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[11px] text-slate-500 hover:bg-[var(--app-panel-soft)]" @click="collectionVisible = true">
            <el-icon><FolderAdd /></el-icon>新建自定义文件夹
          </button>
        </div>
      </aside>

      <!-- List -->
      <section class="panel flex h-[calc(100vh-238px)] min-h-[520px] flex-col overflow-hidden">
        <div class="flex flex-wrap items-center gap-2 border-b px-3 py-2.5" :style="{ borderColor: 'var(--app-border)' }">
          <div class="min-w-0">
            <div class="truncate text-[12.5px] font-semibold">{{ currentTitle }}</div>
            <div class="text-[10.5px] text-slate-400">共 {{ total }} 篇 · 已选 {{ selectedIds.length }} 篇</div>
          </div>
          <div class="ml-auto flex items-center gap-1.5">
            <el-input v-model="keyword" size="small" placeholder="搜索标题 / 摘要 / 创新点" clearable style="width: 200px" @keyup.enter="page = 1; loadPapers()">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-select v-model="sort" size="small" style="width: 112px" @change="loadPapers">
              <el-option value="created_at" label="导入时间" />
              <el-option value="publication_date" label="发表日期" />
              <el-option value="screening_score" label="筛选参考分" />
              <el-option value="title" label="标题" />
            </el-select>
            <el-button-group>
              <el-button size="small" :type="viewMode === 'table' ? 'primary' : 'default'" @click="viewMode = 'table'"><el-icon><List /></el-icon></el-button>
              <el-button size="small" :type="viewMode === 'cards' ? 'primary' : 'default'" @click="viewMode = 'cards'"><el-icon><Grid /></el-icon></el-button>
            </el-button-group>
          </div>
        </div>

        <div v-if="selectedIds.length" class="flex flex-wrap items-center gap-2 border-b bg-accent-500/5 px-3 py-1.5" :style="{ borderColor: 'var(--app-border)' }">
          <span class="text-[11px] text-accent-700 dark:text-accent-300">已选择 {{ selectedIds.length }} 篇</span>
          <el-button size="small" type="primary" plain @click="analyzeSelected">批量 AI 分析</el-button>
          <el-button size="small" @click="parseSelected">批量解析</el-button>
          <el-button size="small" @click="exportVisible = true">批量导出</el-button>
          <el-dropdown trigger="click" @command="addSelectionToCollection">
            <el-button size="small">加入文件夹<el-icon class="ml-1"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="collection in collections" :key="collection.id" :command="collection.id">{{ collection.name }}</el-dropdown-item>
                <el-dropdown-item v-if="!collections.length" disabled>请先新建自定义文件夹</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button size="small" @click="selectedIds = []">取消选择</el-button>
        </div>

        <div v-loading="loading" class="min-h-0 flex-1 overflow-auto">
          <el-table
            v-if="viewMode === 'table'"
            :data="papers"
            size="small"
            row-key="id"
            highlight-current-row
            style="width: 100%"
            @selection-change="onSelectionChange"
            @row-click="selectPaper"
          >
            <el-table-column type="selection" width="34" />
            <el-table-column label="文献" min-width="200">
              <template #default="{ row }">
                <div class="py-1">
                  <div class="line-clamp-2 text-[12.5px] font-medium leading-5">{{ row.title }}</div>
                  <div class="mt-0.5 truncate text-[10.5px] text-slate-400">{{ row.authors_text || '作者未知' }}</div>
                  <div class="mt-1 flex flex-wrap gap-1">
                    <span class="chip !py-0">{{ row.journal || '期刊未知' }}</span>
                    <span v-if="row.year" class="chip !py-0">{{ row.year }}</span>
                    <span v-if="row.duplicate_status === 'suspected'" class="chip !py-0 !text-amber-600">疑似重复</span>
                  </div>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="108">
              <template #default="{ row }">
                <div class="flex flex-col gap-1 py-1">
                  <StatusTag type="review" :status="row.review_status" />
                  <StatusTag type="ai" :status="row.ai_status" />
                </div>
              </template>
            </el-table-column>
            <el-table-column label="参考分" width="56" align="center">
              <template #default="{ row }">
                <span class="text-[12px] font-semibold tabular-nums" :class="row.screening_score >= 70 ? 'text-emerald-600' : row.screening_score !== null ? 'text-amber-600' : 'text-slate-300'">
                  {{ row.screening_score ?? '—' }}
                </span>
              </template>
            </el-table-column>
            <template #empty>
              <EmptyState title="当前目录没有文献" description="导入官方题录或拖入本地 PDF，系统会自动归档到期刊/年份目录。" icon="Folder">
                <el-button size="small" type="primary" @click="router.push('/imports')">去导入</el-button>
              </EmptyState>
            </template>
          </el-table>

          <div v-else class="grid gap-3 p-3 sm:grid-cols-2">
            <div v-for="paper in papers" :key="paper.id" class="soft-panel cursor-pointer p-3 transition-colors hover:border-accent-400" @click="selectPaper(paper)">
              <div class="flex items-start gap-2">
                <div class="line-clamp-2 flex-1 text-[12.5px] font-medium leading-5">{{ paper.title }}</div>
                <el-checkbox :model-value="selectedIds.includes(paper.id)" @click.stop @change="(val: boolean) => toggleCardSelection(paper, val)" />
              </div>
              <div class="mt-1 text-[10.5px] text-slate-400">{{ paper.authors_text || '作者未知' }} · {{ paper.journal || '—' }} · {{ paper.year || '—' }}</div>
              <div class="mt-2 flex flex-wrap items-center gap-1.5">
                <StatusTag type="review" :status="paper.review_status" />
                <span v-if="paper.screening_score !== null" class="chip">参考分 {{ paper.screening_score }}</span>
              </div>
            </div>
            <div v-if="!papers.length" class="sm:col-span-2"><EmptyState title="当前目录没有文献" icon="Folder" /></div>
          </div>
        </div>

        <div class="flex items-center justify-between border-t px-3 py-2" :style="{ borderColor: 'var(--app-border)' }">
          <el-select v-model="pageSize" size="small" style="width: 100px" @change="page = 1; loadPapers()">
            <el-option v-for="size in pageSizeOptions" :key="size" :label="`${size} / 页`" :value="size" />
          </el-select>
          <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" small background @current-change="loadPapers" />
        </div>
      </section>

      <!-- Detail -->
      <aside class="panel hidden h-[calc(100vh-238px)] min-h-[520px] flex-col overflow-hidden xl:flex">
        <div class="flex items-center justify-between border-b px-3 py-2.5" :style="{ borderColor: 'var(--app-border)' }">
          <span class="text-[12px] font-semibold">文献信息</span>
          <el-button v-if="selectedPaper" link size="small" type="primary" @click="openFullDetail">完整详情</el-button>
        </div>
        <div v-if="!selectedPaper" class="flex flex-1 items-center justify-center p-4 text-center">
          <EmptyState compact title="选择一篇文献" description="点击列表中的文献查看摘要、AI 结论与快捷操作。" icon="Document" />
        </div>
        <div v-else v-loading="detailLoading" class="min-h-0 flex-1 overflow-y-auto p-3">
          <div class="text-[13px] font-semibold leading-5">{{ selectedPaper.title }}</div>
          <div class="mt-1 text-[10.5px] text-slate-400">{{ selectedPaper.authors_text }} · {{ selectedPaper.journal }} · {{ selectedPaper.year }}</div>
          <div class="mt-2 flex flex-wrap gap-1.5">
            <StatusTag type="review" :status="selectedPaper.review_status" />
            <StatusTag type="fulltext" :status="selectedPaper.fulltext_status" />
            <StatusTag type="parse" :status="selectedPaper.parse_status" />
          </div>
          <div v-if="selectedPaper.duplicate_status === 'suspected'" class="mt-2 rounded border border-amber-300 bg-amber-50 px-2 py-1.5 text-[10.5px] text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
            疑似重复文献，请在完整详情中确认。系统未删除任何文件。
          </div>
          <div class="divider"></div>
          <div class="micro mb-1">摘要</div>
          <p class="line-clamp-[10] text-[11.5px] leading-5 text-slate-600 dark:text-slate-300">{{ selectedPaper.abstract || '无摘要' }}</p>
          <div v-if="selectedPaper.one_sentence_summary" class="mt-3 rounded-md bg-accent-500/5 p-2.5">
            <div class="micro mb-1">AI 一句话总结</div>
            <p class="text-[11.5px] leading-5">{{ selectedPaper.one_sentence_summary }}</p>
          </div>
          <div v-if="selectedPaper.screening_score !== null" class="mt-2 flex items-center gap-2 text-[11px]">
            <span class="text-slate-400">筛选参考分</span>
            <span class="text-[16px] font-semibold" :class="selectedPaper.screening_score >= 70 ? 'text-emerald-600' : 'text-amber-600'">{{ selectedPaper.screening_score }}</span>
            <span class="text-slate-400">/ 100</span>
          </div>
          <div v-if="selectedPaper.tags.length" class="mt-3 flex flex-wrap gap-1">
            <span v-for="tag in selectedPaper.tags" :key="tag.id" class="chip" :style="{ color: tag.color, borderColor: `${tag.color}44` }">{{ tag.name }}</span>
          </div>
          <div class="mt-3 grid grid-cols-2 gap-2">
            <el-button size="small" type="primary" @click="openFullDetail"><el-icon class="mr-1"><View /></el-icon>打开</el-button>
            <el-button size="small" :disabled="!selectedPaper.has_fulltext" @click="openOriginalFile(selectedPaper)"><el-icon class="mr-1"><Document /></el-icon>原文</el-button>
          </div>
          <div class="mt-2 grid grid-cols-2 gap-2">
            <el-button size="small" :disabled="!selectedPaper.abstract && !selectedPaper.has_fulltext" @click="analyzeSelected">AI 分析</el-button>
            <el-button size="small" @click="selectedIds = [selectedPaper.id]; exportVisible = true">导出</el-button>
          </div>
          <div v-if="selectedDetail?.text_info" class="mt-3 rounded-md border p-2 text-[10.5px] text-slate-500" :style="{ borderColor: 'var(--app-border)' }">
            全文 {{ selectedDetail.text_info.char_count }} 字符 · {{ selectedDetail.text_info.page_count }} 页 · {{ selectedDetail.text_info.quality }}
          </div>
        </div>
      </aside>
    </div>

    <PaperDetailDrawer v-model="drawerVisible" :paper-id="detailPaperId" @updated="refreshAfterDrawer" />

    <el-dialog v-model="exportVisible" title="导出文献" width="440px">
      <el-form label-position="top">
        <el-form-item label="导出范围">
          <el-input :value="selectedIds.length ? `已选 ${selectedIds.length} 篇` : `当前筛选结果（${total} 篇）`" disabled />
        </el-form-item>
        <el-form-item label="导出格式">
          <el-select v-model="exportFormat" class="w-full">
            <el-option value="xlsx" label="Excel 清单（.xlsx）" />
            <el-option value="csv" label="CSV 清单（.csv）" />
            <el-option value="json" label="JSON 数据备份（.json）" />
            <el-option value="markdown" label="Markdown 综述素材" />
            <el-option value="ris" label="RIS 题录" />
            <el-option value="bibtex" label="BibTeX 题录" />
          </el-select>
        </el-form-item>
        <div class="text-[11px] leading-5 text-slate-400">导出包含元数据、标签、个人笔记与 AI 分析；默认不打包受版权保护的全文。</div>
      </el-form>
      <template #footer>
        <el-button @click="exportVisible = false">取消</el-button>
        <el-button type="primary" :loading="exportBusy" @click="exportPapers">开始导出</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="collectionVisible" title="新建自定义文件夹" width="420px">
      <el-input v-model="collectionName" placeholder="例如：待复现方法、重点创新点" @keyup.enter="createCollection" />
      <template #footer>
        <el-button @click="collectionVisible = false">取消</el-button>
        <el-button type="primary" @click="createCollection">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>
