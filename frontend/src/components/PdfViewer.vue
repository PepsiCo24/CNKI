<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

const props = withDefaults(
  defineProps<{
    url: string
    initialPage?: number
    highlightPages?: number[]
    compact?: boolean
  }>(),
  { initialPage: 1, highlightPages: () => [], compact: false },
)
const emit = defineEmits<{
  (e: 'loaded', pages: number): void
  (e: 'page-change', page: number): void
}>()

const container = ref<HTMLElement | null>(null)
// PDF.js objects use private class fields; deep Vue reactivity would proxy them and break rendering.
const doc = shallowRef<PDFDocumentProxy | null>(null)
const loading = ref(false)
const error = ref('')
const pageCount = ref(0)
const currentPage = ref(1)
const scale = ref(1.15)
const fitWidth = ref(true)
const sizes = ref<Array<{ w: number; h: number }>>([])
const shells = new Map<number, HTMLElement>()
const canvases = new Map<number, HTMLCanvasElement>()
const textLayers = new Map<number, HTMLElement>()
const rendered = new Set<number>()
const renderTasks = new Map<number, RenderTask>()
let observer: IntersectionObserver | null = null
let resizeObserver: ResizeObserver | null = null
let scrollFrame = 0

const highlighted = computed(() => new Set(props.highlightPages || []))

function shellStyle(page: number) {
  const size = sizes.value[page - 1]
  if (!size) return { width: '100%', height: '400px' }
  return { width: `${Math.floor(size.w * scale.value)}px`, height: `${Math.floor(size.h * scale.value)}px` }
}

function getShell(page: number): HTMLElement | null {
  return (
    container.value?.querySelector<HTMLElement>(`.pdf-page-shell[data-page="${page}"]`) || null
  )
}

function setShell(page: number, el: Element | null) {
  if (el) {
    shells.set(page, el as HTMLElement)
    if (observer) observer.observe(el as HTMLElement)
  } else {
    shells.delete(page)
  }
}

function setCanvas(page: number, el: Element | null) {
  if (el) canvases.set(page, el as HTMLCanvasElement)
  else canvases.delete(page)
}

function setTextLayer(page: number, el: Element | null) {
  if (el) textLayers.set(page, el as HTMLElement)
  else textLayers.delete(page)
}

async function destroyDocument() {
  observer?.disconnect()
  observer = null
  renderTasks.forEach((task) => {
    try {
      task.cancel()
    } catch {
      /* ignore */
    }
  })
  renderTasks.clear()
  rendered.clear()
  canvases.clear()
  textLayers.clear()
  shells.clear()
  if (doc.value) {
    try {
      await doc.value.destroy()
    } catch {
      /* ignore */
    }
    doc.value = null
  }
  pageCount.value = 0
  sizes.value = []
}

async function renderPage(page: number) {
  if (!doc.value || rendered.has(page) || renderTasks.has(page)) return
  const shell = getShell(page)
  const canvas = shell?.querySelector('canvas') || canvases.get(page)
  const textContainer = shell?.querySelector<HTMLElement>('.pdf-text-layer') || textLayers.get(page)
  if (!canvas) {
    // Refs can be invalidated during keyed re-renders; retry after the DOM settles.
    window.setTimeout(() => renderPage(page), 80)
    return
  }
  rendered.add(page)
  try {
    const pdfPage = await doc.value.getPage(page)
    const viewport = pdfPage.getViewport({ scale: scale.value })
    let dpr = Math.min(window.devicePixelRatio || 1, 1.75)
    const maxPixels = 8_000_000
    const requested = viewport.width * viewport.height * dpr * dpr
    if (requested > maxPixels) {
      dpr = Math.max(1, Math.sqrt(maxPixels / (viewport.width * viewport.height)))
    }
    canvas.width = Math.floor(viewport.width * dpr)
    canvas.height = Math.floor(viewport.height * dpr)
    canvas.style.width = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Canvas 初始化失败')
    const task = pdfPage.render({
      canvasContext: ctx,
      viewport,
      transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
    })
    renderTasks.set(page, task)
    await task.promise
    if (textContainer) {
      textContainer.replaceChildren()
      try {
        const textContent = await pdfPage.getTextContent()
        const textLayer = new pdfjsLib.TextLayer({
          textContentSource: textContent,
          container: textContainer,
          viewport,
        })
        await textLayer.render()
      } catch (err) {
        console.warn('text layer failed', err)
      }
    }
  } catch (err: any) {
    if (err?.name !== 'RenderingCancelledException') {
      console.warn('render page failed', page, err)
      error.value = `第 ${page} 页渲染失败：${err?.message || err}`
    }
    rendered.delete(page)
  } finally {
    renderTasks.delete(page)
  }
}

function setupObserver() {
  observer?.disconnect()
  if (!container.value) return
  observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const page = Number((entry.target as HTMLElement).dataset.page)
          if (page) renderPage(page)
        }
      })
    },
    { root: container.value, rootMargin: '700px 0px' },
  )
  container.value
    ?.querySelectorAll<HTMLElement>('.pdf-page-shell')
    .forEach((el) => observer?.observe(el))
}

async function calculateFitWidth() {
  if (!container.value || !sizes.value.length) return
  const available = container.value.clientWidth - 28
  if (available <= 0) return
  const target = available / sizes.value[0].w
  scale.value = Math.min(2.4, Math.max(0.45, target))
}

async function rerenderVisible() {
  renderTasks.forEach((task) => {
    try {
      task.cancel()
    } catch {
      /* ignore */
    }
  })
  renderTasks.clear()
  rendered.clear()
  textLayers.forEach((layer) => layer.replaceChildren())
  await nextTick()
  const page = currentPage.value
  for (let offset = -1; offset <= 1; offset += 1) {
    const target = page + offset
    if (target >= 1 && target <= pageCount.value) await renderPage(target)
  }
}

async function loadDocument() {
  await destroyDocument()
  if (!props.url) {
    error.value = '该文献尚未关联 PDF 全文'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const task = pdfjsLib.getDocument({
      url: props.url,
      useSystemFonts: true,
      enableXfa: true,
    })
    const loaded = await task.promise
    doc.value = loaded
    pageCount.value = loaded.numPages
    const collected: Array<{ w: number; h: number }> = []
    for (let i = 1; i <= loaded.numPages; i += 1) {
      const page = await loaded.getPage(i)
      const viewport = page.getViewport({ scale: 1 })
      collected.push({ w: viewport.width, h: viewport.height })
    }
    sizes.value = collected
    if (fitWidth.value) await calculateFitWidth()
    currentPage.value = Math.min(Math.max(props.initialPage || 1, 1), pageCount.value)
    await nextTick()
    setupObserver()
    await renderPage(currentPage.value)
    window.setTimeout(() => {
      for (let i = 1; i <= Math.min(3, pageCount.value); i += 1) void renderPage(i)
    }, 120)
    emit('loaded', pageCount.value)
    emit('page-change', currentPage.value)
    if (currentPage.value > 1) await jumpToPage(currentPage.value)
  } catch (err: any) {
    console.error(err)
    if (err?.name === 'PasswordException') error.value = 'PDF 已加密，无法打开'
    else error.value = `PDF 加载失败：${err?.message || err}`
  } finally {
    loading.value = false
  }
}

function onScroll() {
  if (scrollFrame) return
  scrollFrame = window.requestAnimationFrame(() => {
    scrollFrame = 0
    const element = container.value
    if (!element) return
    const marker = element.scrollTop + 90
    let best = currentPage.value
    element.querySelectorAll<HTMLElement>('.pdf-page-shell').forEach((shell) => {
      const page = Number(shell.dataset.page)
      if (page && shell.offsetTop <= marker) best = page
    })
    if (best !== currentPage.value) {
      currentPage.value = best
      emit('page-change', best)
    }
  })
}

async function jumpToPage(page: number) {
  const target = Math.min(Math.max(1, page), pageCount.value || 1)
  currentPage.value = target
  const shell = getShell(target)
  if (shell && container.value) {
    container.value.scrollTo({ top: Math.max(0, shell.offsetTop - 14), behavior: 'smooth' })
    await renderPage(target)
    emit('page-change', target)
  }
}

function go(delta: number) {
  jumpToPage(currentPage.value + delta)
}

function zoom(delta: number) {
  const next = Math.min(3, Math.max(0.4, scale.value + delta))
  if (Math.abs(next - scale.value) < 0.001) return
  scale.value = next
  fitWidth.value = false
  rerenderVisible()
}

async function fitToWidth() {
  fitWidth.value = true
  await calculateFitWidth()
  await rerenderVisible()
}

function onPageInput(event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  if (value >= 1) jumpToPage(value)
}

defineExpose({ jumpToPage, currentPage, pageCount })

watch(
  () => props.url,
  () => loadDocument(),
)
watch(
  () => props.initialPage,
  (page) => {
    if (page && page !== currentPage.value) jumpToPage(page)
  },
)

onMounted(async () => {
  await loadDocument()
  if (container.value) {
    container.value.addEventListener('scroll', onScroll, { passive: true })
    resizeObserver = new ResizeObserver(() => {
      if (fitWidth.value) {
        calculateFitWidth().then(() => rerenderVisible())
      }
    })
    resizeObserver.observe(container.value)
  }
})

onUnmounted(() => {
  container.value?.removeEventListener('scroll', onScroll)
  resizeObserver?.disconnect()
  observer?.disconnect()
  destroyDocument()
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border" :style="{ borderColor: 'var(--app-border)' }">
    <div class="flex shrink-0 flex-wrap items-center gap-1.5 border-b px-2 py-1.5" :style="{ borderColor: 'var(--app-border)', background: 'var(--app-panel-soft)' }">
      <el-button-group>
        <el-button size="small" :disabled="currentPage <= 1" @click="go(-1)"><el-icon><ArrowLeft /></el-icon></el-button>
        <el-button size="small" :disabled="currentPage >= pageCount" @click="go(1)"><el-icon><ArrowRight /></el-icon></el-button>
      </el-button-group>
      <div class="flex items-center gap-1 text-[11px] text-slate-500">
        <input
          :value="currentPage"
          type="number"
          min="1"
          :max="pageCount"
          class="h-6 w-11 rounded border bg-transparent px-1 text-center text-[11px] outline-none"
          :style="{ borderColor: 'var(--app-border)' }"
          @change="onPageInput"
        />
        <span>/ {{ pageCount || '—' }}</span>
      </div>
      <div class="mx-1 h-4 w-px" :style="{ background: 'var(--app-border)' }"></div>
      <button class="icon-btn !h-6 !w-6" title="缩小" @click="zoom(-0.15)"><el-icon><ZoomOut /></el-icon></button>
      <span class="w-10 text-center text-[11px] tabular-nums text-slate-500">{{ Math.round(scale * 100) }}%</span>
      <button class="icon-btn !h-6 !w-6" title="放大" @click="zoom(0.15)"><el-icon><ZoomIn /></el-icon></button>
      <button class="icon-btn !h-6 !w-6" title="适应宽度" @click="fitToWidth"><el-icon><FullScreen /></el-icon></button>
      <div class="ml-auto flex items-center gap-1">
        <a :href="url" target="_blank" class="icon-btn !h-6 !w-6" title="在新窗口打开原文件"><el-icon><TopRight /></el-icon></a>
        <a :href="url" download class="icon-btn !h-6 !w-6" title="下载原文件"><el-icon><Download /></el-icon></a>
      </div>
    </div>

    <div ref="container" class="pdf-scroll relative min-h-0 flex-1">
      <div v-if="loading" class="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-slate-900/60 text-white">
        <el-icon class="is-loading" :size="22"><Loading /></el-icon>
        <span class="text-[12px]">正在加载 PDF…</span>
      </div>
      <div v-if="error" class="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
        <el-icon :size="26" class="text-rose-400"><WarningFilled /></el-icon>
        <div class="text-[12px] text-slate-300">{{ error }}</div>
        <el-button size="small" @click="loadDocument">重试</el-button>
      </div>
      <div v-else class="pdf-pages py-2">
        <div
          v-for="page in pageCount"
          :key="`${url}-${page}-${scale}`"
          :ref="(el) => setShell(page, el as Element | null)"
          :data-page="page"
          class="pdf-page-shell"
          :class="highlighted.has(page) ? 'ring-2 ring-accent-400' : ''"
          :style="shellStyle(page)"
        >
          <canvas :ref="(el) => setCanvas(page, el as Element | null)" class="absolute inset-0"></canvas>
          <div :ref="(el) => setTextLayer(page, el as Element | null)" class="pdf-text-layer textLayer"></div>
          <div class="pdf-placeholder absolute inset-0 -z-0">第 {{ page }} 页</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pdf-page-shell .pdf-placeholder {
  z-index: -1;
}
:deep(.textLayer) {
  position: absolute;
  inset: 0;
  overflow: hidden;
  line-height: 1;
  text-align: initial;
  transform-origin: 0 0;
  -webkit-text-size-adjust: none;
  text-size-adjust: none;
  forced-color-adjust: none;
}
:deep(.textLayer span),
:deep(.textLayer br) {
  color: transparent;
  position: absolute;
  white-space: pre;
  cursor: text;
  transform-origin: 0% 0%;
}
:deep(.textLayer ::selection) {
  background: rgba(58, 104, 245, 0.35);
}
</style>
