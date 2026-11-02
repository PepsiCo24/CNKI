import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { settingsApi, systemApi, tagsApi } from '@/api'
import type { SystemInfo, Tag } from '@/types'

export const useAppStore = defineStore('app', () => {
  const theme = ref<'light' | 'dark'>(localStorage.getItem('cnki-theme') === 'dark' ? 'dark' : 'light')
  const sidebarCollapsed = ref(localStorage.getItem('cnki-sidebar') === 'collapsed')
  const systemInfo = ref<SystemInfo | null>(null)
  const backendOnline = ref(true)
  const tags = ref<Tag[]>([])
  const refreshTick = ref(0)
  const globalSearch = ref('')

  const isDark = computed(() => theme.value === 'dark')

  function applyTheme() {
    document.documentElement.classList.toggle('dark', theme.value === 'dark')
    localStorage.setItem('cnki-theme', theme.value)
  }

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
    applyTheme()
    // Persist the preference locally and to the local settings table.
    settingsApi.update({ 'app.theme': theme.value }).catch(() => {
      /* theme switching must work offline */
    })
  }

  function toggleSidebar() {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem('cnki-sidebar', sidebarCollapsed.value ? 'collapsed' : 'expanded')
  }

  async function loadSystem() {
    try {
      systemInfo.value = await systemApi.info()
      backendOnline.value = true
    } catch {
      backendOnline.value = false
    }
  }

  async function loadTags() {
    try {
      const result = await tagsApi.list()
      tags.value = result.items
    } catch {
      /* global handler shows the error */
    }
  }

  function bumpRefresh() {
    refreshTick.value += 1
  }

  async function init() {
    const stored = localStorage.getItem('cnki-theme')
    if (!stored) {
      try {
        const settings = await settingsApi.get()
        if (settings.values['app.theme'] === 'dark') theme.value = 'dark'
      } catch {
        /* backend may still be starting */
      }
    }
    applyTheme()
    loadSystem()
    loadTags()
  }

  return {
    theme,
    isDark,
    sidebarCollapsed,
    systemInfo,
    backendOnline,
    tags,
    refreshTick,
    globalSearch,
    toggleTheme,
    toggleSidebar,
    loadSystem,
    loadTags,
    bumpRefresh,
    init,
  }
})
