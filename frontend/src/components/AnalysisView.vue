<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Analysis } from '@/types'
import StatusTag from './StatusTag.vue'

const props = withDefaults(
  defineProps<{
    analysis: Analysis | null
    compact?: boolean
    editable?: boolean
  }>(),
  { compact: false, editable: false },
)
const emit = defineEmits<{
  (e: 'jump-page', page: number): void
  (e: 'edit'): void
}>()

const showAllEvidence = ref(false)
const showInferred = ref(false)

const scoreColor = computed(() => {
  const score = props.analysis?.screening_score ?? 0
  if (score >= 75) return '#16A34A'
  if (score >= 50) return '#D97706'
  return '#8A94A6'
})
const scopeLabel = computed(() => {
  const map: Record<string, string> = {
    abstract: '仅基于摘要',
    fulltext: '全文',
    fulltext_chunked: '全文（分块汇总）',
    metadata: '仅题录',
  }
  return map[props.analysis?.analysis_scope || ''] || props.analysis?.analysis_scope || ''
})
const limitationsClaimed = computed(() => (props.analysis?.limitations || []).filter((item) => item.type === 'claimed'))
const limitationsInferred = computed(() => (props.analysis?.limitations || []).filter((item) => item.type !== 'claimed'))
const evidence = computed(() => {
  const list = props.analysis?.evidence || []
  return showAllEvidence.value ? list : list.slice(0, 4)
})

function jump(page?: number | null) {
  if (page && page > 0) emit('jump-page', page)
}
</script>

<template>
  <div v-if="!analysis" class="flex h-full flex-col items-center justify-center gap-2 py-16 text-center">
    <el-icon :size="26" class="text-slate-300"><MagicStick /></el-icon>
    <div class="text-[13px] font-medium text-slate-500">尚无 AI 分析结果</div>
    <div class="text-[11px] text-slate-400">可在设置中配置真实模型，或使用离线 Mock 演示流程</div>
  </div>

  <div v-else class="space-y-4">
    <div class="flex flex-wrap items-center gap-2">
      <div class="flex items-center gap-2.5 rounded-lg border border-[var(--app-border)] bg-[var(--app-panel-soft)] px-3 py-2">
        <div class="flex h-10 w-10 flex-col items-center justify-center rounded-full" :style="{ border: `2px solid ${scoreColor}` }">
          <span class="text-[15px] font-semibold leading-none" :style="{ color: scoreColor }">{{ analysis.screening_score }}</span>
        </div>
        <div>
          <div class="text-[10px] font-medium uppercase tracking-wide text-slate-400">筛选参考分</div>
          <div class="text-[11px] text-slate-500">非学术质量评价</div>
        </div>
      </div>
      <StatusTag type="ai" :status="analysis.is_edited ? 'completed' : 'completed'" :label="scopeLabel" />
      <span class="chip">{{ analysis.provider }} / {{ analysis.model }}</span>
      <span class="chip">提示词 v{{ analysis.prompt_version }}</span>
      <span v-if="analysis.is_edited" class="chip">人工已编辑</span>
      <el-button v-if="editable" size="small" class="ml-auto" @click="emit('edit')">
        <el-icon class="mr-1"><EditPen /></el-icon>编辑分析
      </el-button>
    </div>

    <el-alert v-if="analysis.is_mock" type="warning" :closable="false" show-icon>
      <template #title>
        当前为离线 Mock 模拟分析，仅用于验证流程，不能作为科研判断依据。请配置真实模型后点击“重新分析”。
      </template>
    </el-alert>

    <div class="rounded-lg border-l-[3px] border-accent-500 bg-accent-50/60 px-3.5 py-3 dark:bg-accent-900/15">
      <div class="micro mb-1">一句话总结</div>
      <p class="text-[14px] font-medium leading-6 text-slate-800 dark:text-slate-100">{{ analysis.one_sentence_summary }}</p>
    </div>

    <section>
      <div class="mb-2 flex items-center gap-2">
        <el-icon class="text-accent-500"><Opportunity /></el-icon>
        <span class="section-title">核心创新点</span>
        <span class="chip">{{ analysis.claimed_innovations.length }} 条</span>
      </div>
      <div v-if="!analysis.claimed_innovations.length" class="text-[12px] text-slate-400">模型未提取到作者明确主张的创新点。</div>
      <div class="space-y-2">
        <div
          v-for="(item, index) in analysis.claimed_innovations"
          :key="index"
          class="rounded-lg border p-3"
          :style="{ borderColor: 'var(--app-border)', background: 'var(--app-panel-soft)' }"
        >
          <div class="flex items-start gap-2">
            <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded bg-accent-500/10 text-[10px] font-bold text-accent-600">{{ index + 1 }}</span>
            <div class="min-w-0 flex-1">
              <div class="text-[13px] font-semibold text-slate-800 dark:text-slate-100">{{ item.name || '未命名创新点' }}</div>
              <div class="mt-1 grid gap-1 text-[12px] leading-5 text-slate-600 dark:text-slate-300 sm:grid-cols-2">
                <div><span class="text-slate-400">针对问题：</span>{{ item.problem || '未明确说明' }}</div>
                <div><span class="text-slate-400">新方法：</span>{{ item.method || '未明确说明' }}</div>
                <div class="sm:col-span-2"><span class="text-slate-400">与常规方法差异：</span>{{ item.difference || '未明确说明' }}</div>
              </div>
              <div v-if="item.evidence" class="mt-2 rounded border-l-2 border-slate-300 bg-white/60 px-2 py-1 text-[11.5px] leading-5 text-slate-500 dark:border-slate-600 dark:bg-black/10">
                <span class="text-slate-400">原文依据：</span>{{ item.evidence }}
                <el-button v-if="item.page" link type="primary" size="small" class="!ml-1 !text-[11px]" @click="jump(item.page)">
                  第 {{ item.page }} 页
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div v-if="analysis.inferred_contributions.length" class="mt-2">
        <el-button link size="small" @click="showInferred = !showInferred">
          {{ showInferred ? '收起' : '展开' }} AI 推断的潜在贡献（{{ analysis.inferred_contributions.length }}）
        </el-button>
        <div v-if="showInferred" class="mt-2 space-y-2">
          <div v-for="(item, i) in analysis.inferred_contributions" :key="i" class="rounded border border-dashed p-2.5 text-[12px]" :style="{ borderColor: 'var(--app-border)' }">
            <div class="font-medium">{{ item.name }}</div>
            <div class="text-slate-500">{{ item.difference || item.method }}</div>
          </div>
        </div>
      </div>
    </section>

    <section>
      <div class="micro mb-1.5">创新点精炼总结</div>
      <p class="analysis-prose">{{ analysis.innovation_summary || '未明确说明' }}</p>
    </section>

    <div class="grid gap-3" :class="compact ? '' : 'sm:grid-cols-2'">
      <section class="soft-panel p-3">
        <div class="micro mb-1">研究问题</div>
        <p class="analysis-prose">{{ analysis.research_problem || '未明确说明' }}</p>
      </section>
      <section class="soft-panel p-3">
        <div class="micro mb-1">研究方法</div>
        <p class="analysis-prose">{{ analysis.main_method || '未明确说明' }}</p>
      </section>
    </div>

    <section v-if="analysis.key_results.length">
      <div class="mb-2 section-title">关键实验结果</div>
      <div class="overflow-hidden rounded-lg border" :style="{ borderColor: 'var(--app-border)' }">
        <table class="w-full text-left text-[12px]">
          <thead class="bg-[var(--app-panel-soft)] text-slate-500">
            <tr>
              <th class="px-3 py-2 font-medium">指标</th>
              <th class="px-3 py-2 font-medium">数值 / 结论</th>
              <th class="px-3 py-2 font-medium">实验设置</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in analysis.key_results" :key="i" class="border-t" :style="{ borderColor: 'var(--app-border)' }">
              <td class="px-3 py-2">{{ row.metric || '—' }}</td>
              <td class="px-3 py-2 font-medium">{{ row.value || '未明确说明' }}</td>
              <td class="px-3 py-2 text-slate-500">{{ row.setting || row.conclusion || '未明确说明' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    <section v-else class="soft-panel p-3">
      <div class="micro mb-1">关键实验结果</div>
      <p class="text-[12px] text-slate-500">模型未从可读文本中提取到带数值的结果，系统不会编造性能提升幅度。</p>
    </section>

    <section>
      <div class="micro mb-1">研究价值</div>
      <p class="analysis-prose">{{ analysis.research_value || '未明确说明' }}</p>
    </section>

    <section>
      <div class="mb-2 section-title">研究局限</div>
      <div class="space-y-1.5 text-[12px] leading-5">
        <div v-for="(item, i) in limitationsClaimed" :key="`c${i}`" class="flex gap-2">
          <span class="mt-1 shrink-0 rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-600">作者披露</span>
          <span>{{ item.text }}</span>
        </div>
        <div v-for="(item, i) in limitationsInferred" :key="`i${i}`" class="flex gap-2">
          <span class="mt-1 shrink-0 rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-600">分析推断</span>
          <span>{{ item.text }}</span>
        </div>
        <div v-if="!analysis.limitations.length" class="text-slate-400">未明确说明</div>
      </div>
    </section>

    <section>
      <div class="mb-2 flex items-center justify-between">
        <div class="section-title">原文证据</div>
        <el-button v-if="analysis.evidence.length > 4" link size="small" @click="showAllEvidence = !showAllEvidence">
          {{ showAllEvidence ? '收起' : `全部 ${analysis.evidence.length} 条` }}
        </el-button>
      </div>
      <div v-if="!analysis.evidence.length" class="text-[12px] text-slate-400">模型未提供可定位的原文证据。</div>
      <div v-else class="space-y-2">
        <div v-for="(item, i) in evidence" :key="i" class="soft-panel p-2.5">
          <div class="mb-1 flex items-center gap-2 text-[10.5px] text-slate-400">
            <span>{{ item.section || '原文' }}</span>
            <button v-if="item.page" class="link !text-[10.5px]" @click="jump(item.page)">第 {{ item.page }} 页</button>
          </div>
          <blockquote class="border-l-2 border-slate-300 pl-2 text-[12px] italic leading-5 text-slate-600 dark:border-slate-600 dark:text-slate-300">
            {{ item.quote || '（无引文）' }}
          </blockquote>
          <div v-if="item.supports" class="mt-1 text-[11px] text-slate-500">支持：{{ item.supports }}</div>
        </div>
      </div>
    </section>

    <section v-if="analysis.missing_information.length">
      <div class="micro mb-1">信息缺口</div>
      <ul class="list-disc space-y-0.5 pl-5 text-[11.5px] text-slate-500">
        <li v-for="(item, i) in analysis.missing_information" :key="i">{{ item }}</li>
      </ul>
    </section>

    <section class="soft-panel p-3">
      <div class="micro mb-1">筛选理由</div>
      <p class="text-[12px] leading-5 text-slate-600 dark:text-slate-300">{{ analysis.screening_reason || '未明确说明' }}</p>
      <div class="mt-2 text-[10px] text-slate-400">
        生成时间 {{ new Date(analysis.created_at).toLocaleString('zh-CN') }} · 输入 {{ analysis.input_chars.toLocaleString() }} 字符
      </div>
    </section>
  </div>
</template>
