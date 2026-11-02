<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAppStore } from '@/stores/app'
import { settingsApi } from '@/api'

const app = useAppStore()
const route = useRoute()
const router = useRouter()
const search = ref('')
const mainEl = ref<HTMLElement | null>(null)
const providerLabel = ref('Mock 演示模型')
let timer: number | undefined

const navigation = [
  { path: '/dashboard', label: '仪表盘', icon: 'Odometer' },
  { path: '/search-tasks', label: '文献检索', icon: 'Search' },
  { path: '/imports', label: '下载与导入', icon: 'Download' },
  { path: '/files', label: '文件管理', icon: 'Folder' },
  { path: '/ai', label: 'AI 分析中心', icon: 'MagicStick' },
  { path: '/review', label: '待审核', icon: 'View' },
  { path: '/library', label: '我的文献库', icon: 'Collection' },
  { path: '/innovations', label: '创新点库', icon: 'Opportunity' },
  { path: '/settings', label: '设置', icon: 'Setting' },
]

const title = computed(() => (route.meta.title as string) || '工作台')
const subtitle = computed(() => (route.meta.subtitle as string) || '')
const collapsed = computed(() => app.sidebarCollapsed)
const online = computed(() => app.backendOnline)

async function loadProvider() {
  try {
    const data = await settingsApi.get()
    const provider = data.values['ai.provider']
    const preset = data.providers.find((item) => item.id === provider)
    providerLabel.value = preset ? preset.label : provider || '未配置'
  } catch {
    providerLabel.value = '模型未配置'
  }
}

function submitSearch() {
  const q = search.value.trim()
  if (!q) return
  router.push({ path: '/library', query: { q } })
}

function openDocs() {
  window.open('/docs', '_blank')
}

function handleKeydown(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    const input = document.querySelector<HTMLInputElement>('#global-search')
    input?.focus()
  }
}

watch(
  () => route.fullPath,
  () => {
    nextTick(() => {
      mainEl.value?.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior })
    })
  },
)

onMounted(() => {
  loadProvider()
  window.addEventListener('keydown', handleKeydown)
  timer = window.setInterval(() => {
    app.loadSystem()
    loadProvider()
  }, 30_000)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <aside
      class="flex shrink-0 flex-col border-r border-white/5 transition-[width] duration-200"
      :class="collapsed ? 'w-[76px]' : 'w-[232px]'"
      :style="{ background: 'var(--app-nav)' }"
    >
      <div class="flex h-[68px] items-center gap-3 px-4">
        <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-500 text-white shadow-lg shadow-accent-900/30">
          <span class="text-[15px] font-bold">C</span>
        </div>
        <div v-if="!collapsed" class="min-w-0">
          <div class="truncate text-[13.5px] font-semibold tracking-tight text-white">CNKI Scholar AI</div>
          <div class="truncate text-[10.5px] text-slate-400">本地科研文献工作台</div>
        </div>
      </div>

      <nav class="mt-2 flex-1 space-y-0.5 overflow-y-auto px-2.5">
        <el-tooltip v-for="item in navigation" :key="item.path" :content="item.label" placement="right" :disabled="!collapsed">
          <router-link :to="item.path" class="nav-link" :class="collapsed ? 'justify-center !px-0' : ''" :aria-label="item.label">
            <el-icon :size="18"><component :is="item.icon" /></el-icon>
            <span v-if="!collapsed" class="truncate">{{ item.label }}</span>
          </router-link>
        </el-tooltip>
      </nav>

      <div class="border-t border-white/5 p-3">
        <div v-if="!collapsed" class="rounded-lg bg-white/[0.04] p-2.5">
          <div class="flex items-center gap-2 text-[11px] text-slate-300">
            <span class="h-1.5 w-1.5 rounded-full" :class="online ? 'bg-emerald-400' : 'bg-rose-500'"></span>
            {{ online ? '本地服务正常' : '后端未连接' }}
          </div>
          <div class="mt-1.5 flex items-center gap-1.5 truncate text-[10.5px] text-slate-500">
            <el-icon><Cpu /></el-icon>
            <span class="truncate">{{ providerLabel }}</span>
          </div>
          <div class="mt-1 flex items-center gap-1.5 truncate text-[10.5px] text-slate-500">
            <el-icon><Lock /></el-icon>
            <span>数据仅存本地 · SQLite</span>
          </div>
        </div>
        <el-tooltip :content="collapsed ? '展开侧栏' : '收起侧栏'" placement="right">
          <button class="icon-btn mt-1 w-full !text-slate-400 hover:!bg-white/5 hover:!text-white" title="切换侧栏" aria-label="切换侧栏" @click="app.toggleSidebar()">
            <el-icon :size="16"><component :is="collapsed ? 'Expand' : 'Fold'" /></el-icon>
          </button>
        </el-tooltip>
      </div>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <header
        class="flex h-[60px] shrink-0 items-center gap-4 border-b px-5"
        :style="{ background: 'var(--app-panel)', borderColor: 'var(--app-border)' }"
      >
        <div class="min-w-0">
          <div class="truncate text-[14px] font-semibold tracking-tight">{{ title }}</div>
          <div class="hidden truncate text-[11px] text-slate-500 sm:block">{{ subtitle }}</div>
        </div>

        <div class="ml-auto flex items-center gap-2">
          <div class="relative hidden md:block">
            <el-input
              id="global-search"
              v-model="search"
              placeholder="搜索标题 / 摘要 / 创新点  ⌘K"
              clearable
              class="!w-[260px]"
              @keyup.enter="submitSearch"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </div>
          <el-tooltip content="API 文档">
            <button class="icon-btn" title="API 文档" aria-label="API 文档" @click="openDocs"><el-icon><Document /></el-icon></button>
          </el-tooltip>
          <el-tooltip content="刷新全局状态">
            <button class="icon-btn" title="刷新状态" aria-label="刷新状态" @click="app.loadSystem(); app.loadTags(); ElMessage.success('状态已刷新')">
              <el-icon><Refresh /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip :content="app.isDark ? '切换到亮色' : '切换到暗色'">
            <button class="icon-btn" :title="app.isDark ? '切换到亮色' : '切换到暗色'" :aria-label="app.isDark ? '切换到亮色' : '切换到暗色'" @click="app.toggleTheme()">
              <el-icon><component :is="app.isDark ? 'Sunny' : 'Moon'" /></el-icon>
            </button>
          </el-tooltip>
          <div class="ml-1 flex h-8 w-8 items-center justify-center rounded-full bg-accent-50 text-[11px] font-semibold text-accent-700 dark:bg-accent-900/40 dark:text-accent-200">
            本地
          </div>
        </div>
      </header>

      <div v-if="!online" class="border-b border-amber-200 bg-amber-50 px-5 py-2 text-[12px] text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-200">
        无法连接后端 API。请确认 FastAPI 服务已启动，然后
        <button class="font-semibold underline" @click="app.loadSystem()">重试连接</button>。
      </div>

      <main ref="mainEl" class="min-h-0 flex-1 overflow-y-auto">
        <div class="page-wrap p-5 lg:p-6">
          <router-view v-slot="{ Component }">
            <transition name="fade" mode="out-in">
              <component :is="Component" :key="route.path" />
            </transition>
          </router-view>
        </div>
      </main>
    </div>
  </div>
</template>
