<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    description?: string
    icon?: string
    compact?: boolean
  }>(),
  { title: '暂无数据', description: '', icon: 'Files', compact: false },
)
</script>

<template>
  <div class="flex flex-col items-center justify-center text-center" :class="compact ? 'py-8' : 'py-16'">
    <div class="mb-3 flex h-11 w-11 items-center justify-center rounded-xl border border-dashed border-slate-300 text-slate-400 dark:border-slate-700">
      <el-icon :size="20"><component :is="icon" /></el-icon>
    </div>
    <div class="text-[13px] font-medium text-slate-600 dark:text-slate-300">{{ title }}</div>
    <div v-if="description" class="mt-1 max-w-sm text-[12px] leading-5 text-slate-400">{{ description }}</div>
    <div class="mt-3"><slot /></div>
  </div>
</template>
