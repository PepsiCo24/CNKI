<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    subtitle?: string
    eyebrow?: string
  }>(),
  { subtitle: '', eyebrow: '' },
)
</script>

<template>
  <div class="page-heading">
    <div>
      <div v-if="eyebrow" class="micro mb-1">{{ eyebrow }}</div>
      <h1 class="page-title">{{ title }}</h1>
      <p v-if="subtitle" class="page-subtitle">{{ subtitle }}</p>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <slot name="actions" />
    </div>
  </div>
</template>
