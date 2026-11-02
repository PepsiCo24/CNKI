<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { innovationsApi } from '@/api'
import type { InnovationItem } from '@/types'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'

const router = useRouter()
const items = ref<InnovationItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(12)
const loading = ref(false)
const keyword = ref('')
const paperId = ref('')
const tag = ref('')
const sort = ref('created_at')
const facets = ref<{
  papers: Array<{ id: string; title: string; journal: string }>
  tags: Array<{ name: string; color: string; category: string }>
}>({ papers: [], tags: [] })
const noteVisible = ref(false)
const editing = ref<InnovationItem | null>(null)
const noteDraft = ref('')
const saving = ref(false)
let searchTimer: number | undefined

const activeFilters = computed(() => Boolean(keyword.value || paperId.value || tag.value))

async function loadFacets() {
  facets.value = await innovationsApi.facets()
}

async function load() {
  loading.value = true
  try {
    const result = await innovationsApi.list({
      q: keyword.value.trim(),
      paper_id: paperId.value,
      tag: tag.value,
      page: page.value,
      page_size: pageSize.value,
      sort: sort.value,
    })
    items.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function onInput() {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(search, 350)
}

function reset() {
  keyword.value = ''
  paperId.value = ''
  tag.value = ''
  page.value = 1
  load()
}

function openNote(item: InnovationItem) {
  editing.value = item
  noteDraft.value = item.note
  noteVisible.value = true
}

async function saveNote() {
  if (!editing.value) return
  saving.value = true
  try {
    const updated = await innovationsApi.update(editing.value.id, { note: noteDraft.value })
    const index = items.value.findIndex((item) => item.id === updated.id)
    if (index >= 0) items.value[index] = updated
    noteVisible.value = false
    ElMessage.success('创新点备注已保存')
  } finally {
    saving.value = false
  }
}

async function copyItem(item: InnovationItem) {
  const text = [
    `## ${item.name}`,
    item.paper ? `论文：${item.paper.title}（${item.paper.journal || '期刊未知'}，${item.paper.year || '年份未知'}）` : '',
    item.core_technique ? `核心技术：${item.core_technique}` : '',
    item.description ? `描述：${item.description}` : '',
    item.evidence ? `原文证据：${item.evidence}` : '',
    item.page ? `页码：第 ${item.page} 页` : '',
    item.note ? `个人备注：${item.note}` : '',
  ].filter(Boolean).join('\n')
  await navigator.clipboard.writeText(text)
  ElMessage.success('创新点已复制为 Markdown')
}

function openPaper(item: InnovationItem) {
  if (!item.paper) return
  router.push({ path: '/library', query: { paper: item.paper.id } })
}

watch([paperId, tag, sort], () => {
  page.value = 1
  load()
})

onMounted(async () => {
  await Promise.all([load(), loadFacets()])
})
</script>

<template>
  <div>
    <PageHeader title="创新点库" subtitle="每条创新点对应论文中的一项主张，保留证据、页码与个人备注" eyebrow="Innovation library">
      <template #actions>
        <el-button size="small" @click="router.push('/library')"><el-icon class="mr-1"><Collection /></el-icon>进入文献库</el-button>
      </template>
    </PageHeader>

    <div class="panel mb-3 p-3">
      <div class="flex flex-wrap items-center gap-2">
        <el-input v-model="keyword" placeholder="搜索创新点名称、核心技术、描述、证据或论文标题" clearable style="width: min(420px, 100%)" @input="onInput" @keyup.enter="search">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="paperId" placeholder="全部论文" clearable filterable style="width: 240px">
          <el-option v-for="paper in facets.papers" :key="paper.id" :label="paper.title" :value="paper.id" />
        </el-select>
        <el-select v-model="tag" placeholder="全部标签" clearable style="width: 140px">
          <el-option v-for="item in facets.tags" :key="item.name" :label="item.name" :value="item.name" />
        </el-select>
        <el-select v-model="sort" style="width: 140px">
          <el-option value="created_at" label="最近分析" />
          <el-option value="paper_year" label="按论文年份" />
        </el-select>
        <el-button v-if="activeFilters" link @click="reset">清除筛选</el-button>
        <span class="ml-auto text-[11px] text-slate-400">共 {{ total }} 条创新点</span>
      </div>
      <div v-if="facets.tags.length" class="mt-2 flex flex-wrap gap-1.5">
        <button
          v-for="item in facets.tags"
          :key="item.name"
          class="chip transition-colors"
          :class="tag === item.name ? '!border-accent-400 !text-accent-600' : ''"
          @click="tag = tag === item.name ? '' : item.name"
        >
          <span class="h-1.5 w-1.5 rounded-full" :style="{ background: item.color }"></span>{{ item.name }}
        </button>
      </div>
    </div>

    <div v-loading="loading" class="min-h-[300px]">
      <EmptyState
        v-if="!items.length && !loading"
        title="没有匹配的创新点"
        :description="activeFilters ? '尝试清除筛选条件。' : '完成 AI 分析并入库后，创新点会自动汇总到这里。'"
        icon="Opportunity"
      />
      <div v-else class="grid gap-3 lg:grid-cols-2">
        <article v-for="item in items" :key="item.id" class="panel flex flex-col p-4 transition-colors hover:border-accent-400">
          <div class="flex items-start gap-2.5">
            <span class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent-500/10 text-[11px] font-bold text-accent-600">#{{ item.seq }}</span>
            <div class="min-w-0 flex-1">
              <h3 class="text-[14px] font-semibold leading-5">{{ item.name }}</h3>
              <div v-if="item.core_technique" class="mt-1 flex items-start gap-1 text-[11px] text-slate-500">
                <el-icon class="mt-0.5 shrink-0"><Cpu /></el-icon>
                <span class="line-clamp-2">{{ item.core_technique }}</span>
              </div>
            </div>
            <el-dropdown trigger="click">
              <button class="icon-btn !h-7 !w-7"><el-icon><MoreFilled /></el-icon></button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="openNote(item)">编辑备注</el-dropdown-item>
                  <el-dropdown-item @click="copyItem(item)">复制 Markdown</el-dropdown-item>
                  <el-dropdown-item divided @click="openPaper(item)">查看所属论文</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>

          <p class="mt-2 line-clamp-3 text-[12px] leading-5 text-slate-600 dark:text-slate-300">{{ item.description || '暂无描述' }}</p>

          <blockquote v-if="item.evidence" class="mt-2 line-clamp-2 border-l-2 border-slate-300 pl-2 text-[11px] italic leading-5 text-slate-500 dark:border-slate-600">
            {{ item.evidence }}
            <button v-if="item.page" class="link !text-[10px]" @click="openPaper(item)">第 {{ item.page }} 页</button>
          </blockquote>

          <div v-if="item.note" class="mt-2 rounded-md bg-amber-500/5 px-2 py-1.5 text-[11px] leading-5 text-amber-700 dark:text-amber-300">
            <span class="font-medium">我的备注：</span>{{ item.note }}
          </div>

          <div class="mt-2 flex flex-wrap gap-1.5">
            <span v-for="name in item.tags_snapshot" :key="name" class="chip">{{ name }}</span>
          </div>

          <div class="mt-auto flex items-end justify-between gap-2 border-t pt-2.5" :style="{ borderColor: 'var(--app-border)' }">
            <button class="min-w-0 text-left" @click="openPaper(item)">
              <div class="line-clamp-1 text-[11px] font-medium hover:text-accent-600">{{ item.paper?.title || '所属论文未知' }}</div>
              <div class="mt-0.5 text-[10px] text-slate-400">{{ item.paper?.journal || '—' }} · {{ item.paper?.year || '—' }}</div>
            </button>
            <div class="flex shrink-0 gap-1">
              <el-button size="small" @click="openNote(item)">备注</el-button>
              <el-button size="small" type="primary" plain @click="openPaper(item)">论文</el-button>
            </div>
          </div>
        </article>
      </div>
    </div>

    <div class="mt-4 flex justify-end">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[12, 24, 48]" layout="total, sizes, prev, pager, next" background @current-change="load" @size-change="page = 1; load()" />
    </div>

    <el-dialog v-model="noteVisible" title="创新点备注" width="520px">
      <div v-if="editing" class="mb-3 rounded-md bg-[var(--app-panel-soft)] p-2.5">
        <div class="text-[12.5px] font-medium">{{ editing.name }}</div>
        <div class="mt-0.5 line-clamp-2 text-[11px] text-slate-500">{{ editing.description }}</div>
      </div>
      <el-input v-model="noteDraft" type="textarea" :rows="5" placeholder="记录复现计划、可迁移到哪个研究方向、需要核对的实验条件…" />
      <template #footer>
        <el-button @click="noteVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveNote">保存备注</el-button>
      </template>
    </el-dialog>
  </div>
</template>
