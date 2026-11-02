<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { exportsApi, libraryApi } from '@/api'
import type { PaperSummary } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import EmptyState from '@/components/EmptyState.vue'
import PaperDetailDrawer from '@/components/PaperDetailDrawer.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const papers = ref<PaperSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref(String(route.query.q || ''))
const journal = ref('')
const year = ref<number | null>(null)
const tag = ref('')
const sort = ref('updated_at')
const order = ref('desc')
const viewMode = ref<'cards' | 'table'>('cards')
const selectedIds = ref<string[]>([])
const drawerVisible = ref(false)
const detailPaperId = ref<string | null>(null)
const exportVisible = ref(false)
const exportFormat = ref('markdown')
const exportBusy = ref(false)
const facets = ref<{
  total: number
  journals: Array<{ name: string; count: number }>
  years: Array<{ year: number; count: number }>
  tags: Array<{ name: string; category: string; color: string; count: number }>
}>({ total: 0, journals: [], years: [], tags: [] })
let searchTimer: number | undefined

const hasFilters = computed(() => Boolean(journal.value || year.value || tag.value || keyword.value))

async function loadFacets() {
  try {
    facets.value = await libraryApi.facets()
  } catch {
    /* ignore */
  }
}

async function loadPapers() {
  loading.value = true
  try {
    const result = await libraryApi.papers({
      page: page.value,
      page_size: pageSize.value,
      q: keyword.value.trim(),
      journal: journal.value,
      year: year.value,
      tag: tag.value,
      sort: sort.value,
      order: order.value,
    })
    papers.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  keyword.value = ''
  journal.value = ''
  year.value = null
  tag.value = ''
  page.value = 1
  loadPapers()
}

function openPaper(paper: PaperSummary) {
  detailPaperId.value = paper.id
  drawerVisible.value = true
  router.replace({ path: '/library', query: { ...route.query, paper: paper.id } })
}

function toggleSelect(paper: PaperSummary, checked: boolean) {
  if (checked) selectedIds.value = Array.from(new Set([...selectedIds.value, paper.id]))
  else selectedIds.value = selectedIds.value.filter((id) => id !== paper.id)
}

async function exportPapers() {
  exportBusy.value = true
  try {
    const result = await exportsApi.create({
      format: exportFormat.value,
      paper_ids: selectedIds.value,
      filters: selectedIds.value.length
        ? {}
        : { q: keyword.value.trim(), journal: journal.value, year: year.value, tag: tag.value },
      include_notes: true,
      include_analysis: true,
    })
    window.open(result.download_url, '_blank')
    ElMessage.success(`导出完成：${result.filename}`)
    exportVisible.value = false
  } finally {
    exportBusy.value = false
  }
}

function onSearchInput() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    page.value = 1
    loadPapers()
  }, 350)
}

watch(
  () => route.query.q,
  (value) => {
    const q = String(value || '')
    if (q !== keyword.value) {
      keyword.value = q
      page.value = 1
      loadPapers()
    }
  },
)

watch([journal, year, tag, sort], () => {
  page.value = 1
  loadPapers()
})

watch(
  () => route.query.paper,
  (value) => {
    if (value) {
      detailPaperId.value = String(value)
      drawerVisible.value = true
    }
  },
)

onMounted(async () => {
  await Promise.all([loadPapers(), loadFacets()])
  if (route.query.paper) {
    detailPaperId.value = String(route.query.paper)
    drawerVisible.value = true
  }
})

onUnmounted(() => {
  if (searchTimer) window.clearTimeout(searchTimer)
})
</script>

<template>
  <div>
    <PageHeader title="我的文献库" subtitle="仅展示已通过人工审核的正式文献；支持全文 / 摘要 / AI 创新点检索" eyebrow="Library">
      <template #actions>
        <el-button @click="exportVisible = true"><el-icon class="mr-1"><Download /></el-icon>导出</el-button>
        <el-button type="primary" @click="router.push('/review')"><el-icon class="mr-1"><View /></el-icon>去审核</el-button>
      </template>
    </PageHeader>

    <div class="panel mb-3 p-3">
      <div class="flex flex-wrap items-center gap-2">
        <el-input v-model="keyword" placeholder="搜索标题、作者、摘要、AI 创新点（全文索引）" clearable style="width: min(420px, 100%)" @input="onSearchInput" @keyup.enter="page = 1; loadPapers()">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="journal" placeholder="全部期刊" clearable style="width: 160px">
          <el-option v-for="item in facets.journals" :key="item.name" :label="`${item.name} (${item.count})`" :value="item.name" />
        </el-select>
        <el-select v-model="year" placeholder="全部年份" clearable style="width: 130px">
          <el-option v-for="item in facets.years" :key="item.year" :label="`${item.year} (${item.count})`" :value="item.year" />
        </el-select>
        <el-select v-model="tag" placeholder="全部标签" clearable style="width: 140px">
          <el-option v-for="item in facets.tags" :key="item.name" :label="`${item.name} (${item.count})`" :value="item.name" />
        </el-select>
        <el-select v-model="sort" style="width: 140px">
          <el-option value="updated_at" label="最近更新" />
          <el-option value="publication_date" label="发表日期" />
          <el-option value="screening_score" label="筛选参考分" />
          <el-option value="title" label="标题" />
        </el-select>
        <el-button v-if="hasFilters" link @click="resetFilters">清除筛选</el-button>
        <div class="ml-auto flex items-center gap-1">
          <el-button-group>
            <el-button size="small" :type="viewMode === 'cards' ? 'primary' : 'default'" @click="viewMode = 'cards'"><el-icon><Grid /></el-icon></el-button>
            <el-button size="small" :type="viewMode === 'table' ? 'primary' : 'default'" @click="viewMode = 'table'"><el-icon><List /></el-icon></el-button>
          </el-button-group>
        </div>
      </div>
      <div v-if="facets.tags.length" class="mt-2 flex flex-wrap gap-1.5">
        <button
          v-for="item in facets.tags.slice(0, 14)"
          :key="item.name"
          class="chip transition-colors"
          :class="tag === item.name ? '!border-accent-400 !text-accent-600' : ''"
          @click="tag = tag === item.name ? '' : item.name"
        >
          {{ item.name }} <span class="opacity-60">{{ item.count }}</span>
        </button>
      </div>
    </div>

    <div v-if="selectedIds.length" class="mb-3 flex items-center gap-2 rounded-lg border border-accent-300/60 bg-accent-500/5 px-3 py-2">
      <span class="text-[12px] text-accent-700 dark:text-accent-300">已选 {{ selectedIds.length }} 篇</span>
      <el-button size="small" @click="exportVisible = true">导出所选</el-button>
      <el-button size="small" @click="selectedIds = []">取消</el-button>
    </div>

    <div v-loading="loading" class="min-h-[300px]">
      <EmptyState
        v-if="!papers.length && !loading"
        :title="hasFilters ? '没有匹配的已入库文献' : '文献库还是空的'"
        :description="hasFilters ? '尝试清除筛选条件，或在待审核页面将符合条件的文献入库。' : '在审核工作台点击“入库”后，文献会进入正式文献库。'"
        icon="Collection"
      >
        <el-button size="small" type="primary" @click="router.push('/review')">去审核</el-button>
      </EmptyState>

      <div v-else-if="viewMode === 'cards'" class="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
        <article
          v-for="paper in papers"
          :key="paper.id"
          class="panel group cursor-pointer p-4 transition-colors hover:border-accent-400"
          @click="openPaper(paper)"
        >
          <div class="flex items-start gap-2">
            <el-checkbox :model-value="selectedIds.includes(paper.id)" @click.stop @change="(val: boolean) => toggleSelect(paper, val)" />
            <div class="min-w-0 flex-1">
              <h3 class="line-clamp-2 text-[13.5px] font-semibold leading-5 group-hover:text-accent-600">{{ paper.title }}</h3>
              <div class="mt-1 truncate text-[11px] text-slate-400">{{ paper.authors_text || '作者未知' }}</div>
            </div>
            <div class="flex flex-col items-end">
              <span class="text-[18px] font-semibold tabular-nums" :class="(paper.screening_score || 0) >= 70 ? 'text-emerald-600' : 'text-amber-600'">{{ paper.screening_score ?? '—' }}</span>
              <span class="text-[9px] text-slate-400">参考分</span>
            </div>
          </div>
          <div class="mt-2 flex flex-wrap items-center gap-1.5">
            <span class="chip">{{ paper.journal || '期刊未知' }}</span>
            <span v-if="paper.year" class="chip">{{ paper.year }}</span>
            <span v-if="paper.is_mock" class="chip !text-amber-600">模拟分析</span>
            <span v-for="item in paper.tags.slice(0, 3)" :key="item.id" class="chip" :style="{ color: item.color, borderColor: `${item.color}44` }">{{ item.name }}</span>
          </div>
          <p class="mt-2 line-clamp-3 text-[11.5px] leading-5 text-slate-600 dark:text-slate-300">
            {{ paper.one_sentence_summary || paper.abstract || '暂无摘要' }}
          </p>
          <div class="mt-2 flex items-center gap-1.5 text-[10px] text-slate-400">
            <el-icon><MagicStick /></el-icon>
            <span class="line-clamp-1">{{ paper.innovation_summary || '暂无创新点总结' }}</span>
          </div>
          <div class="mt-2 flex items-center justify-between border-t pt-2" :style="{ borderColor: 'var(--app-border)' }">
            <span class="text-[10px] text-slate-400">{{ paper.publication_date || paper.year || '日期未知' }}</span>
            <span class="link !text-[11px]">查看详情</span>
          </div>
        </article>
      </div>

      <div v-else class="panel overflow-hidden">
        <el-table :data="papers" size="small" @row-click="openPaper">
          <el-table-column width="38">
            <template #default="{ row }">
              <el-checkbox :model-value="selectedIds.includes(row.id)" @click.stop @change="(val: boolean) => toggleSelect(row, val)" />
            </template>
          </el-table-column>
          <el-table-column label="标题" min-width="300">
            <template #default="{ row }">
              <div class="line-clamp-2 text-[12.5px] font-medium">{{ row.title }}</div>
              <div class="mt-0.5 text-[10.5px] text-slate-400">{{ row.authors_text }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="journal" label="期刊" width="150" />
          <el-table-column prop="year" label="年份" width="70" />
          <el-table-column label="标签" width="160">
            <template #default="{ row }">
              <div class="flex flex-wrap gap-1">
                <span v-for="item in row.tags.slice(0, 2)" :key="item.id" class="chip !py-0" :style="{ color: item.color, borderColor: `${item.color}44` }">{{ item.name }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="参考分" width="75" align="center">
            <template #default="{ row }"><span class="font-semibold tabular-nums">{{ row.screening_score ?? '—' }}</span></template>
          </el-table-column>
          <el-table-column label="入库时间" width="120">
            <template #default="{ row }"><span class="text-[10.5px] text-slate-400">{{ new Date(row.updated_at).toLocaleDateString('zh-CN') }}</span></template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <div class="mt-4 flex justify-end">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" background @current-change="loadPapers" @size-change="page = 1; loadPapers()" />
    </div>

    <PaperDetailDrawer v-model="drawerVisible" :paper-id="detailPaperId" @updated="loadPapers(); loadFacets()" />

    <el-dialog v-model="exportVisible" title="导出正式文献库" width="480px">
      <el-form label-position="top">
        <el-form-item label="导出范围">
          <el-input :value="selectedIds.length ? `已选 ${selectedIds.length} 篇` : `当前筛选结果（${total} 篇）`" disabled />
        </el-form-item>
        <el-form-item label="格式">
          <el-select v-model="exportFormat" class="w-full">
            <el-option value="markdown" label="Markdown 综述素材（含分析）" />
            <el-option value="xlsx" label="Excel 清单" />
            <el-option value="csv" label="CSV 清单" />
            <el-option value="json" label="JSON 数据备份" />
            <el-option value="ris" label="RIS 题录" />
            <el-option value="bibtex" label="BibTeX 题录" />
            <el-option value="notes_md" label="仅科研笔记 Markdown" />
          </el-select>
        </el-form-item>
        <el-alert type="info" :closable="false" show-icon title="导出包含元数据、标签、笔记与 AI 分析，不默认打包受版权保护的 PDF 全文。" />
      </el-form>
      <template #footer>
        <el-button @click="exportVisible = false">取消</el-button>
        <el-button type="primary" :loading="exportBusy" @click="exportPapers">导出</el-button>
      </template>
    </el-dialog>
  </div>
</template>
