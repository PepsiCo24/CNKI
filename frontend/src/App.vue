<script setup lang="ts">
import { onMounted } from 'vue'
import { useAppStore } from '@/stores/app'
import MainLayout from '@/layouts/MainLayout.vue'

const app = useAppStore()
onMounted(() => app.init())
</script>

<template>
  <MainLayout />
</template>
