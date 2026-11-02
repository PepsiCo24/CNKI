<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    status: string
    type?: 'review' | 'ai' | 'task' | 'job' | 'parse' | 'fulltext'
    label?: string
  }>(),
  { type: 'review', label: '' },
)

const MAPS: Record<string, Record<string, { label: string; color: string }>> = {
  review: {
    pending_fulltext: { label: '待获取全文', color: '#909399' },
    pending_ai: { label: '待 AI 分析', color: '#E6A23C' },
    analyzing: { label: 'AI 分析中', color: '#3A68F5' },
    pending_review: { label: '待人工审核', color: '#D97706' },
    included: { label: '已入库', color: '#16A34A' },
    excluded: { label: '暂不采用', color: '#8A94A6' },
    deferred: { label: '待定', color: '#7C6BD6' },
    analysis_failed: { label: '分析失败', color: '#DC2626' },
  },
  ai: {
    not_analyzed: { label: '未分析', color: '#909399' },
    queued: { label: '排队中', color: '#E6A23C' },
    running: { label: '分析中', color: '#3A68F5' },
    completed: { label: '已完成', color: '#16A34A' },
    failed: { label: '分析失败', color: '#DC2626' },
    cached: { label: '缓存命中', color: '#0D9488' },
  },
  task: {
    pending: { label: '待开始', color: '#909399' },
    running: { label: '执行中', color: '#3A68F5' },
    paused: { label: '已暂停', color: '#E6A23C' },
    completed: { label: '已完成', color: '#16A34A' },
    failed: { label: '失败', color: '#DC2626' },
    cancelled: { label: '已取消', color: '#8A94A6' },
    awaiting_import: { label: '等待导入', color: '#D97706' },
  },
  job: {
    pending: { label: '排队中', color: '#909399' },
    running: { label: '执行中', color: '#3A68F5' },
    completed: { label: '已完成', color: '#16A34A' },
    failed: { label: '失败', color: '#DC2626' },
    cancelled: { label: '已取消', color: '#8A94A6' },
    cancelling: { label: '取消中', color: '#E6A23C' },
  },
  parse: {
    not_parsed: { label: '未解析', color: '#909399' },
    pending: { label: '待解析', color: '#E6A23C' },
    parsed: { label: '已解析', color: '#16A34A' },
    partial: { label: '部分解析', color: '#D97706' },
    failed: { label: '解析失败', color: '#DC2626' },
    unsupported: { label: '格式不支持', color: '#8A94A6' },
  },
  fulltext: {
    not_available: { label: '无全文', color: '#909399' },
    imported: { label: '全文已获取', color: '#16A34A' },
    downloading: { label: '获取中', color: '#3A68F5' },
    failed: { label: '获取失败', color: '#DC2626' },
  },
}

const info = computed(() => {
  const map = MAPS[props.type] ?? {}
  return map[props.status] ?? { label: props.label || props.status || '未知', color: '#909399' }
})
const displayLabel = computed(() => props.label || info.value.label)
const style = computed(() => ({
  color: info.value.color,
  backgroundColor: `${info.value.color}16`,
  borderColor: `${info.value.color}38`,
}))
</script>

<template>
  <span class="inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-[1px] text-[11px] font-medium" :style="style">
    <span class="h-1.5 w-1.5 rounded-full" :style="{ backgroundColor: info.color }"></span>
    {{ displayLabel }}
  </span>
</template>
