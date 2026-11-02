<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { exportsApi, promptsApi, settingsApi, systemApi, tagsApi } from '@/api'
import { useAppStore } from '@/stores/app'
import type { PromptTemplate, ProviderPreset } from '@/types'
import PageHeader from '@/components/PageHeader.vue'

const app = useAppStore()
const activeTab = ref('ai')
const loading = ref(false)
const saving = ref(false)
const values = reactive<Record<string, any>>({
  'review.shortcuts': { include: 'Ctrl+Enter', exclude: 'Ctrl+Backspace', defer: 'Ctrl+D' },
})
const providers = ref<ProviderPreset[]>([])
const prompts = ref<PromptTemplate[]>([])
const storage = ref<any>(null)
const watcher = ref<{ running: boolean; path: string }>({ running: false, path: '' })
const testResult = ref<{ ok: boolean; error?: string; model?: string; sample?: string; is_mock?: boolean } | null>(null)
const testing = ref(false)
const promptVisible = ref(false)
const promptSaving = ref(false)
const promptMode = ref<'edit' | 'create'>('edit')
const promptForm = reactive({ id: '', name: '', content: '', description: '' })
const logsVisible = ref(false)
const logLines = ref<string[]>([])
const tagVisible = ref(false)
const newTag = reactive({ name: '', category: '自定义', color: '#3A68F5' })
const maintenanceBusy = ref(false)

const SAVE_KEYS = [
  'ai.provider', 'ai.base_url', 'ai.model', 'ai.api_key', 'ai.temperature', 'ai.max_tokens',
  'ai.timeout', 'ai.max_input_chars', 'ai.concurrency', 'ai.reasoning_effort',
  'ai.cost_input_per_1k', 'ai.cost_output_per_1k', 'ai.auto_analyze', 'ai.prompt_template_id',
  'data.import_dir', 'data.watch_enabled', 'data.naming_pattern', 'data.auto_backup',
  'review.default_sort', 'review.shortcuts',
  'cnki.account_username', 'cnki.account_institution', 'cnki.account_note', 'cnki.auto_import_downloads',
  'cnki.authorized_enabled', 'cnki.authorized_base_url', 'cnki.authorized_permission_reference',
  'cnki.authorized_api_key', 'cnki.authorized_daily_limit',
  'app.theme',
]

const currentProvider = computed(() => providers.value.find((item) => item.id === values['ai.provider']))
const isMock = computed(() => values['ai.provider'] === 'mock')
const activePrompts = computed(() => prompts.value.filter((prompt) => prompt.is_active))
const accountConfigured = computed(() => Boolean(values['cnki.account_username']))
function openCnki() {
  window.open('https://www.cnki.net', '_blank', 'noopener,noreferrer')
}
const tags = computed(() => app.tags)
const storageTotal = computed(() => {
  if (!storage.value) return 0
  return Object.values(storage.value.directories as Record<string, { bytes: number }>).reduce(
    (sum, item) => sum + item.bytes,
    storage.value.database_bytes || 0,
  )
})

function formatBytes(bytes: number) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let index = 0
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024
    index += 1
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

async function loadSettings() {
  loading.value = true
  try {
    const result = await settingsApi.get()
    providers.value = result.providers
    watcher.value = result.watcher
    Object.keys(values).forEach((key) => delete values[key])
    Object.assign(values, result.values)
    if (!values['review.shortcuts'] || typeof values['review.shortcuts'] !== 'object') {
      values['review.shortcuts'] = { include: 'Ctrl+Enter', exclude: 'Ctrl+Backspace', defer: 'Ctrl+D' }
    }
  } finally {
    loading.value = false
  }
}

async function loadPrompts() {
  const result = await promptsApi.list()
  prompts.value = result.items
}

async function loadStorage() {
  storage.value = await settingsApi.storage()
}

async function loadAll() {
  await Promise.all([loadSettings(), loadPrompts(), loadStorage(), app.loadTags()])
}

function selectProvider(preset: ProviderPreset) {
  if (values['ai.provider'] === preset.id) return
  values['ai.provider'] = preset.id
  values['ai.base_url'] = preset.base_url
  values['ai.model'] = preset.default_model
  testResult.value = null
}

async function save() {
  saving.value = true
  try {
    const payload: Record<string, unknown> = {}
    SAVE_KEYS.forEach((key) => {
      if (values[key] !== undefined) payload[key] = values[key]
    })
    payload['app.theme'] = app.isDark ? 'dark' : 'light'
    const result = await settingsApi.update(payload)
    Object.assign(values, result.values)
    watcher.value = result.watcher
    ElMessage.success(result.message || '设置已保存')
    app.loadSystem()
    app.loadTags()
    await loadStorage()
  } finally {
    saving.value = false
  }
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await settingsApi.testAi({
      provider: values['ai.provider'],
      base_url: values['ai.base_url'],
      model: values['ai.model'],
    })
    if (testResult.value.ok) ElMessage.success('模型连接成功')
  } finally {
    testing.value = false
  }
}

async function toggleWatch(value: boolean) {
  values['data.watch_enabled'] = value
  if (value) await settingsApi.startWatch()
  else await settingsApi.stopWatch()
  watcher.value = await settingsApi.watchStatus()
  ElMessage.success(value ? '目录监听已启动' : '目录监听已停止')
}

async function showLogs() {
  const result = await systemApi.logs(400)
  logLines.value = result.lines
  logsVisible.value = true
}

async function reindex() {
  maintenanceBusy.value = true
  try {
    const result = await systemApi.reindex()
    ElMessage.success(`全文索引已重建：${result.indexed} 篇`)
  } finally {
    maintenanceBusy.value = false
  }
}

async function backupNow() {
  maintenanceBusy.value = true
  try {
    const result = await exportsApi.backup()
    ElMessage.success(`备份完成：${result.filename}（不含 PDF 全文）`)
    window.open(result.download_url, '_blank')
  } finally {
    maintenanceBusy.value = false
  }
}

function openPromptEdit(prompt: PromptTemplate) {
  promptMode.value = 'edit'
  Object.assign(promptForm, { id: prompt.id, name: prompt.name, content: prompt.content, description: prompt.description })
  promptVisible.value = true
}

function openPromptCreate() {
  promptMode.value = 'create'
  Object.assign(promptForm, { id: '', name: '', content: '', description: '' })
  promptVisible.value = true
}

async function savePrompt() {
  if (!promptForm.name.trim() || promptForm.content.trim().length < 20) {
    ElMessage.warning('请填写名称，提示词内容至少 20 字')
    return
  }
  promptSaving.value = true
  try {
    if (promptMode.value === 'create') {
      await promptsApi.create({
        name: promptForm.name,
        content: promptForm.content,
        description: promptForm.description,
        is_default: false,
      })
      ElMessage.success('提示词已创建')
    } else {
      const updated = await promptsApi.update(promptForm.id, {
        name: promptForm.name,
        content: promptForm.content,
        description: promptForm.description,
      })
      ElMessage.success(`提示词已保存${updated.version ? `（v${updated.version}）` : ''}`)
    }
    promptVisible.value = false
    await Promise.all([loadPrompts(), loadSettings()])
  } finally {
    promptSaving.value = false
  }
}

async function activatePrompt(prompt: PromptTemplate) {
  await promptsApi.activate(prompt.id)
  ElMessage.success('已设为当前分析提示词')
  await Promise.all([loadPrompts(), loadSettings()])
}

async function defaultPrompt(prompt: PromptTemplate) {
  await promptsApi.setDefault(prompt.id)
  ElMessage.success('已设为默认提示词')
  await Promise.all([loadPrompts(), loadSettings()])
}

async function duplicatePrompt(prompt: PromptTemplate) {
  await promptsApi.duplicate(prompt.id)
  ElMessage.success('提示词副本已创建')
  await loadPrompts()
}

async function archivePrompt(prompt: PromptTemplate) {
  await ElMessageBox.confirm('归档该提示词？历史分析结果仍保留原版本号与内容。', '归档提示词', { type: 'warning' })
  await promptsApi.archive(prompt.id)
  ElMessage.success('提示词已归档')
  await loadPrompts()
}

async function createTag() {
  if (!newTag.name.trim()) return
  await tagsApi.create(newTag.name.trim(), newTag.category, newTag.color)
  newTag.name = ''
  tagVisible.value = false
  await app.loadTags()
  ElMessage.success('标签已创建')
}

async function removeTag(tag: { id: string; name: string; paper_count?: number }) {
  await ElMessageBox.confirm(`删除标签“${tag.name}”？文献本身不会被删除。`, '删除标签', { type: 'warning' })
  await tagsApi.remove(tag.id)
  await app.loadTags()
  ElMessage.success('标签已删除')
}

onMounted(loadAll)
</script>

<template>
  <div>
    <PageHeader title="设置中心" subtitle="所有配置保存在本地；API Key 加密存储且不会明文返回前端" eyebrow="Settings">
      <template #actions>
        <el-button size="small" @click="showLogs"><el-icon class="mr-1"><Document /></el-icon>运行日志</el-button>
        <el-button type="primary" :loading="saving" @click="save"><el-icon class="mr-1"><Check /></el-icon>保存设置</el-button>
      </template>
    </PageHeader>

    <div v-loading="loading" class="panel p-4 pb-24">
      <el-tabs v-model="activeTab">
        <!-- AI -->
        <el-tab-pane name="ai" label="AI 模型">
          <div class="grid gap-5 xl:grid-cols-[1.25fr_1fr]">
            <div class="space-y-4">
              <section>
                <div class="section-title">模型服务商</div>
                <div class="mt-2 grid gap-2 sm:grid-cols-2">
                  <button
                    v-for="preset in providers"
                    :key="preset.id"
                    class="rounded-lg border p-3 text-left transition-colors"
                    :class="values['ai.provider'] === preset.id ? 'border-accent-500 bg-accent-500/5' : 'hover:border-slate-300'"
                    :style="{ borderColor: values['ai.provider'] === preset.id ? '#3A68F5' : 'var(--app-border)' }"
                    @click="selectProvider(preset)"
                  >
                    <div class="flex items-center gap-1.5">
                      <span class="h-1.5 w-1.5 rounded-full" :style="{ background: values['ai.provider'] === preset.id ? '#3A68F5' : '#C0C6D4' }"></span>
                      <span class="text-[12px] font-medium">{{ preset.label }}</span>
                    </div>
                    <div class="mt-1 line-clamp-2 text-[10.5px] leading-4 text-slate-400">{{ preset.note }}</div>
                  </button>
                </div>
              </section>

              <section class="grid gap-3 sm:grid-cols-2">
                <el-form-item label="Base URL" class="!mb-0 sm:col-span-2">
                  <el-input v-model="values['ai.base_url']" placeholder="https://api.deepseek.com/v1" :disabled="isMock" />
                </el-form-item>
                <el-form-item label="Model ID" class="!mb-0">
                  <el-input v-model="values['ai.model']" :placeholder="isMock ? 'deterministic-mock-v1' : 'deepseek-chat'" :disabled="isMock" />
                </el-form-item>
                <el-form-item label="API Key" class="!mb-0">
                  <el-input v-model="values['ai.api_key']" type="password" show-password placeholder="留空表示不修改" :disabled="isMock || values['ai.provider'] === 'ollama'" />
                </el-form-item>
                <el-form-item label="Temperature" class="!mb-0">
                  <el-input-number v-model="values['ai.temperature']" :min="0" :max="2" :step="0.1" class="!w-full" />
                </el-form-item>
                <el-form-item label="Max Tokens" class="!mb-0">
                  <el-input-number v-model="values['ai.max_tokens']" :min="256" :max="128000" :step="256" class="!w-full" />
                </el-form-item>
                <el-form-item label="超时（秒）" class="!mb-0">
                  <el-input-number v-model="values['ai.timeout']" :min="10" :max="600" class="!w-full" />
                </el-form-item>
                <el-form-item label="最大输入字符" class="!mb-0">
                  <el-input-number v-model="values['ai.max_input_chars']" :min="2000" :max="400000" :step="2000" class="!w-full" />
                </el-form-item>
                <el-form-item label="并发分析数" class="!mb-0">
                  <el-input-number v-model="values['ai.concurrency']" :min="1" :max="8" class="!w-full" />
                </el-form-item>
                <el-form-item label="推理强度（部分服务商）" class="!mb-0">
                  <el-select v-model="values['ai.reasoning_effort']" clearable class="w-full" placeholder="不设置">
                    <el-option value="low" label="low" />
                    <el-option value="medium" label="medium" />
                    <el-option value="high" label="high" />
                  </el-select>
                </el-form-item>
                <el-form-item label="输入单价（元 / 1K tokens）" class="!mb-0">
                  <el-input-number v-model="values['ai.cost_input_per_1k']" :min="0" :precision="4" :step="0.001" class="!w-full" />
                </el-form-item>
                <el-form-item label="输出单价（元 / 1K tokens）" class="!mb-0">
                  <el-input-number v-model="values['ai.cost_output_per_1k']" :min="0" :precision="4" :step="0.001" class="!w-full" />
                </el-form-item>
                <el-form-item label="自动分析新全文" class="!mb-0">
                  <el-switch v-model="values['ai.auto_analyze']" />
                </el-form-item>
                <el-form-item label="当前提示词" class="!mb-0 sm:col-span-2">
                  <el-select v-model="values['ai.prompt_template_id']" class="w-full" placeholder="使用默认提示词">
                    <el-option v-for="prompt in activePrompts" :key="prompt.id" :label="`${prompt.name} · v${prompt.version}`" :value="prompt.id" />
                  </el-select>
                </el-form-item>
              </section>

              <div class="flex flex-wrap items-center gap-2">
                <el-button type="primary" plain :loading="testing" @click="testConnection"><el-icon class="mr-1"><Connection /></el-icon>测试连接</el-button>
                <el-button @click="save">保存设置</el-button>
                <span class="text-[10.5px] text-slate-400">测试使用已保存的配置；如刚修改 Key，请先保存。</span>
              </div>

              <el-alert v-if="testResult" :type="testResult.ok ? 'success' : 'error'" :closable="false" show-icon>
                <template #title>
                  <div class="text-[12px]">
                    {{ testResult.ok ? `连接成功：${testResult.model || values['ai.model']}` : testResult.error }}
                    <span v-if="testResult.is_mock" class="ml-1">（Mock 不联网）</span>
                  </div>
                </template>
                <div v-if="testResult.sample" class="mt-1 break-all text-[10.5px] text-slate-500">响应样例：{{ testResult.sample }}</div>
              </el-alert>
            </div>

            <div class="space-y-3">
              <section class="soft-panel p-4">
                <div class="section-title">安全与成本</div>
                <ul class="mt-2 list-disc space-y-1.5 pl-4 text-[11.5px] leading-5 text-slate-500">
                  <li>API Key 使用本地 Fernet 密钥加密保存在 SQLite，前端只显示掩码。</li>
                  <li>日志不会记录 Key、Authorization 头或完整请求体。</li>
                  <li>长论文会分块提取并汇总，可能产生多次模型调用。</li>
                  <li>相同文件、提示词与模型参数会命中缓存，避免重复扣费。</li>
                  <li>Mock 模式不联网，仅用于流程验收，结果会明确标注。</li>
                </ul>
              </section>
              <section class="soft-panel p-4">
                <div class="section-title">本地模型（Ollama）</div>
                <div class="mt-2 text-[11.5px] leading-5 text-slate-500">
                  安装 Ollama 后执行 <code class="rounded bg-slate-100 px-1 py-0.5 text-[10.5px] dark:bg-slate-800">ollama pull qwen2.5:7b</code>，
                  将服务商切到 Ollama，Base URL 填 <code class="rounded bg-slate-100 px-1 py-0.5 text-[10.5px] dark:bg-slate-800">http://127.0.0.1:11434</code>。
                  本地模型完全断网可用，不需要 API Key。
                </div>
              </section>
              <section class="soft-panel p-4">
                <div class="section-title">当前模型</div>
                <div class="mt-2 space-y-1 text-[11.5px]">
                  <div class="flex justify-between"><span class="text-slate-400">服务商</span><span>{{ currentProvider?.label || values['ai.provider'] }}</span></div>
                  <div class="flex justify-between gap-4"><span class="text-slate-400">模型</span><span class="truncate">{{ isMock ? 'deterministic-mock-v1（离线）' : values['ai.model'] }}</span></div>
                  <div class="flex justify-between"><span class="text-slate-400">并发</span><span>{{ values['ai.concurrency'] }}</span></div>
                  <div class="flex justify-between"><span class="text-slate-400">自动分析</span><span>{{ values['ai.auto_analyze'] ? '开启' : '关闭' }}</span></div>
                </div>
              </section>
            </div>
          </div>
        </el-tab-pane>

        <!-- Data -->
        <el-tab-pane name="data" label="数据与存储">
          <div class="grid gap-5 xl:grid-cols-[1.2fr_1fr]">
            <div class="space-y-4">
              <section>
                <div class="section-title">目录设置</div>
                <el-form label-position="top" class="mt-2">
                  <el-form-item label="数据根目录（只读，修改需通过环境变量或启动脚本）">
                    <el-input :model-value="values['data.root_dir']" disabled />
                  </el-form-item>
                  <el-form-item label="导入 / 监听目录">
                    <el-input v-model="values['data.import_dir']" placeholder="例如：/Users/you/Documents/CNKI Downloads" />
                    <div class="mt-1 text-[10.5px] text-slate-400">支持绝对路径；目录必须存在或可创建。中文路径与空格可用。</div>
                  </el-form-item>
                  <el-form-item label="自动目录监听">
                    <div class="flex items-center gap-3">
                      <el-switch :model-value="Boolean(values['data.watch_enabled'])" @change="toggleWatch" />
                      <span class="text-[11.5px] text-slate-400">{{ watcher.running ? `监听中：${watcher.path}` : '已停止' }}</span>
                    </div>
                  </el-form-item>
                  <el-form-item label="文件命名规则">
                    <el-input v-model="values['data.naming_pattern']" placeholder="{year}_{title}_{first_author}" />
                    <div class="mt-1 text-[10.5px] text-slate-400">可用变量：{year}、{title}、{first_author}；系统会自动清理非法字符并控制长度。</div>
                  </el-form-item>
                  <el-form-item label="自动备份">
                    <el-switch v-model="values['data.auto_backup']" />
                    <span class="ml-2 text-[10.5px] text-slate-400">启用后可在数据目录的 backups 中手动触发；备份不包含 PDF 全文。</span>
                  </el-form-item>
                </el-form>
              </section>

              <section class="flex flex-wrap gap-2">
                <el-button :loading="maintenanceBusy" @click="backupNow"><el-icon class="mr-1"><Download /></el-icon>立即备份数据库</el-button>
                <el-button :loading="maintenanceBusy" @click="reindex"><el-icon class="mr-1"><Refresh /></el-icon>重建全文索引</el-button>
                <el-button @click="showLogs">查看日志</el-button>
              </section>

              <section class="soft-panel p-4">
                <div class="section-title">物理目录结构</div>
                <pre class="mt-2 whitespace-pre-wrap text-[11px] leading-5 text-slate-500">data/
  database/       SQLite 数据库
  papers/         期刊/年份 归档全文
  imports/        题录与原始导入文件
  metadata/       每题录 JSON 快照
  ai_results/     每篇 AI 分析 JSON 快照
  exports/        CSV / Excel / Markdown / RIS 导出
  backups/        数据库与元数据备份
  logs/           运行日志
  temp/           上传暂存</pre>
              </section>
            </div>

            <div class="space-y-3">
              <section class="soft-panel p-4">
                <div class="flex items-center justify-between">
                  <div class="section-title">存储占用</div>
                  <span class="chip">合计 {{ formatBytes(storageTotal) }}</span>
                </div>
                <div v-if="storage" class="mt-3 space-y-2">
                  <div class="flex items-center justify-between text-[11.5px]">
                    <span class="text-slate-400">SQLite 数据库</span><span class="tabular-nums">{{ formatBytes(storage.database_bytes) }}</span>
                  </div>
                  <div v-for="(item, key) in storage.directories" :key="key" class="flex items-center justify-between text-[11.5px]">
                    <span class="text-slate-400">{{ key }}</span><span class="tabular-nums">{{ formatBytes(item.bytes) }}</span>
                  </div>
                  <div class="divider !my-2"></div>
                  <div class="flex items-center justify-between text-[11px]">
                    <span class="text-slate-400">磁盘剩余</span><span>{{ formatBytes(storage.disk_free) }}</span>
                  </div>
                </div>
                <el-button class="mt-3" size="small" @click="loadStorage">刷新占用</el-button>
              </section>
              <section class="soft-panel p-4">
                <div class="section-title">数据安全</div>
                <ul class="mt-2 list-disc space-y-1.5 pl-4 text-[11.5px] leading-5 text-slate-500">
                  <li>断网时已有文献、PDF、分析结果仍可管理和阅读。</li>
                  <li>数据库使用 WAL 模式；进程中断后可恢复。</li>
                  <li>备份为 zip（数据库 + 元数据 + AI 结果），不包含受版权保护的全文。</li>
                  <li>所有路径均做越界校验，中文路径已测试。</li>
                </ul>
              </section>
            </div>
          </div>
        </el-tab-pane>

        <!-- CNKI -->
        <el-tab-pane name="cnki" label="知网接入">
          <div class="grid gap-5 xl:grid-cols-[1.2fr_1fr]">
            <div class="space-y-4">
              <el-alert type="info" :closable="false" show-icon>
                <template #title>
                  本系统不包含任何未公开知网接口、验证码绕过或自动批量下载实现。普通知网账号的全文下载权限不视为程序化接口许可。
                </template>
              </el-alert>

              <section>
                <div class="section-title">官方检索入口</div>
                <div class="mt-2 flex items-center gap-2">
                  <el-input model-value="https://www.cnki.net" disabled />
                  <el-button tag="a" href="https://www.cnki.net" target="_blank">打开知网</el-button>
                </div>
                <div class="mt-1 text-[10.5px] text-slate-400">在高级检索中把期刊名称填入“文献来源”，主题关键词填入“主题”。</div>
              </section>

              <section>
                <div class="flex flex-wrap items-center gap-2">
                  <div class="section-title">知网账号（浏览器手动登录）</div>
                  <span class="chip" :class="accountConfigured ? '!text-emerald-600' : ''">
                    {{ accountConfigured ? '已记录账号' : '未配置' }}
                  </span>
                </div>
                <div v-if="!accountConfigured" class="mt-1.5 text-[11px] leading-5 text-amber-700 dark:text-amber-300">
                  未填写账号标识时，文献检索页的「静默抓取」无法启动。请填写后保存；账号密码不会保存在本系统。
                </div>
                <div class="mt-2 grid gap-3 sm:grid-cols-2">
                  <el-form-item label="账号标识 / 用户名" class="!mb-0">
                    <el-input v-model="values['cnki.account_username']" placeholder="仅用于本机标识，例如：个人账号 / 机构账号尾号" />
                  </el-form-item>
                  <el-form-item label="机构 / 订阅说明" class="!mb-0">
                    <el-input v-model="values['cnki.account_institution']" placeholder="例如：XX大学图书馆" />
                  </el-form-item>
                  <el-form-item label="备注" class="!mb-0 sm:col-span-2">
                    <el-input v-model="values['cnki.account_note']" placeholder="例如：通过学校 VPN 访问；仅手动检索与导出" />
                  </el-form-item>
                </div>
                <div class="mt-2 flex flex-wrap items-center gap-2">
                  <el-button size="small" type="primary" plain @click="openCnki">
                    <el-icon class="mr-1"><TopRight /></el-icon>打开知网官方页面登录
                  </el-button>
                  <span class="text-[10.5px] text-slate-400">账号密码不会保存在本系统中，登录状态由浏览器管理。</span>
                </div>
                <div class="mt-2">
                  <div class="flex items-center gap-2">
                    <el-switch v-model="values['cnki.auto_import_downloads']" />
                    <span class="text-[12px]">自动导入下载目录中的题录与全文</span>
                  </div>
                  <div class="mt-1 text-[10.5px] leading-5 text-slate-400">
                    监听目录新增 RIS / BibTeX / EndNote / CSV 题录或 PDF / CAJ 全文时，系统自动解析、去重并按任务条件关联。
                    这依赖你在知网官方页面自行登录和下载，不进行自动登录、验证码绕过或私有接口抓取。
                  </div>
                </div>
              </section>

              <section>
                <div class="section-title">适配器状态</div>
                <div class="mt-2 space-y-2">
                  <div class="flex items-center justify-between rounded-md border px-3 py-2" :style="{ borderColor: 'var(--app-border)' }">
                    <div><div class="text-[12px] font-medium">官方题录导入</div><div class="text-[10.5px] text-slate-400">RIS / BibTeX / EndNote / CSV</div></div>
                    <span class="chip !text-emerald-600">可用</span>
                  </div>
                  <div class="flex items-center justify-between rounded-md border px-3 py-2" :style="{ borderColor: 'var(--app-border)' }">
                    <div><div class="text-[12px] font-medium">本地全文接管</div><div class="text-[10.5px] text-slate-400">PDF / CAJ 目录监听与哈希去重</div></div>
                    <span class="chip !text-emerald-600">可用</span>
                  </div>
                  <div class="flex items-center justify-between rounded-md border px-3 py-2" :style="{ borderColor: 'var(--app-border)' }">
                    <div><div class="text-[12px] font-medium">授权数据接口</div><div class="text-[10.5px] text-slate-400">需官方文档 + 书面许可，当前未内置端点</div></div>
                    <span class="chip !text-amber-600">待配置</span>
                  </div>
                  <div class="flex items-center justify-between rounded-md border px-3 py-2" :style="{ borderColor: 'var(--app-border)' }">
                    <div><div class="text-[12px] font-medium">程序化自动下载</div><div class="text-[10.5px] text-slate-400">未实现，且不会绕过访问限制</div></div>
                    <span class="chip">未启用</span>
                  </div>
                </div>
              </section>

              <section>
                <div class="section-title">经单独授权的数据接口（预留）</div>
                <el-form label-position="top" class="mt-2">
                  <el-form-item label="启用授权适配器">
                    <el-switch v-model="values['cnki.authorized_enabled']" />
                    <span class="ml-2 text-[10.5px] text-slate-400">仅在你已取得明确许可时启用</span>
                  </el-form-item>
                  <el-form-item label="服务 Base URL（以官方文档为准）">
                    <el-input v-model="values['cnki.authorized_base_url']" placeholder="不要填写猜测的知网私有接口地址" :disabled="!values['cnki.authorized_enabled']" />
                  </el-form-item>
                  <el-form-item label="许可编号 / 授权说明">
                    <el-input v-model="values['cnki.authorized_permission_reference']" placeholder="例如：合同编号或许可邮件编号" :disabled="!values['cnki.authorized_enabled']" />
                  </el-form-item>
                  <el-form-item label="接口凭证（加密存储）">
                    <el-input v-model="values['cnki.authorized_api_key']" type="password" show-password placeholder="仅授权接口需要时填写" :disabled="!values['cnki.authorized_enabled']" />
                  </el-form-item>
                  <el-form-item label="每日调用上限">
                    <el-input-number v-model="values['cnki.authorized_daily_limit']" :min="1" :max="100000" :disabled="!values['cnki.authorized_enabled']" />
                  </el-form-item>
                </el-form>
                <div class="rounded-md border border-amber-200 bg-amber-50/60 p-3 text-[11px] leading-5 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-200">
                  当前版本不会调用任何未经确认的知网端点。配置只用于记录授权信息与预留适配器；实际接入需依据官方文档实现并测试。
                </div>
              </section>
            </div>

            <div class="space-y-3">
              <section class="soft-panel p-4">
                <div class="section-title">推荐工作流</div>
                <ol class="mt-2 list-decimal space-y-2 pl-4 text-[11.5px] leading-5 text-slate-500">
                  <li>创建检索任务，填写期刊来源与起止日期。</li>
                  <li>按系统生成的检索条件单，在知网官方页面检索。</li>
                  <li>使用官方导出功能导出 RIS/BibTeX/EndNote。</li>
                  <li>在任务详情中导入题录，自动按期刊与日期过滤。</li>
                  <li>通过授权渠道下载 PDF/CAJ 到导入目录，系统自动归档。</li>
                  <li>AI 分析后进入审核工作台，由你决定是否入库。</li>
                </ol>
              </section>
              <section class="soft-panel p-4">
                <div class="section-title">权限与合规</div>
                <ul class="mt-2 list-disc space-y-1.5 pl-4 text-[11.5px] leading-5 text-slate-500">
                  <li>不逆向私有接口、不伪造认证状态、不规避访问限制。</li>
                  <li>不将演示数据标记为实时知网检索结果。</li>
                  <li>仅管理用户合法获取的文献文件。</li>
                  <li>导出不默认打包全文，避免版权风险。</li>
                </ul>
              </section>
            </div>
          </div>
        </el-tab-pane>

        <!-- Prompts -->
        <el-tab-pane name="prompts" label="提示词版本">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div class="section-title">分析提示词</div>
              <div class="mt-0.5 text-[11px] text-slate-400">修改内容会生成新版本；历史分析结果保留生成时的版本号，不会被覆盖。</div>
            </div>
            <el-button type="primary" plain @click="openPromptCreate"><el-icon class="mr-1"><Plus /></el-icon>新建提示词</el-button>
          </div>
          <div class="mt-3 space-y-2">
            <div v-for="prompt in prompts" :key="prompt.id" class="rounded-lg border p-3" :style="{ borderColor: prompt.is_active ? '#3A68F5' : 'var(--app-border)' }">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-[13px] font-medium">{{ prompt.name }}</span>
                <span class="chip">v{{ prompt.version }}</span>
                <span v-if="prompt.is_default" class="chip !text-accent-600">默认</span>
                <span v-if="prompt.is_active" class="chip !text-emerald-600">启用</span>
                <span v-else class="chip">归档</span>
                <span class="ml-auto text-[10px] text-slate-400">{{ new Date(prompt.updated_at).toLocaleString('zh-CN') }}</span>
              </div>
              <div v-if="prompt.description" class="mt-1 text-[11px] text-slate-400">{{ prompt.description }}</div>
              <pre class="mt-2 line-clamp-3 whitespace-pre-wrap text-[10.5px] leading-4 text-slate-500">{{ prompt.content }}</pre>
              <div class="mt-2 flex flex-wrap gap-1.5">
                <el-button size="small" @click="openPromptEdit(prompt)">查看 / 编辑</el-button>
                <el-button size="small" @click="activatePrompt(prompt)" :disabled="prompt.is_active && values['ai.prompt_template_id'] === prompt.id">设为当前</el-button>
                <el-button size="small" @click="defaultPrompt(prompt)" :disabled="prompt.is_default">设为默认</el-button>
                <el-button size="small" @click="duplicatePrompt(prompt)">复制</el-button>
                <el-button size="small" type="danger" plain @click="archivePrompt(prompt)" :disabled="prompt.is_default || !prompt.is_active">归档</el-button>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <!-- Review -->
        <el-tab-pane name="review" label="审核与界面">
          <div class="grid gap-5 xl:grid-cols-[1.15fr_1fr]">
            <div class="space-y-4">
              <section>
                <div class="section-title">审核偏好</div>
                <el-form label-position="top" class="mt-2">
                  <el-form-item label="AI 分析完成后进入待审核">
                    <el-switch model-value disabled />
                    <span class="ml-2 text-[10.5px] text-slate-400">固定开启：AI 结果不能替代人工审核，必须经用户确认才可入库。</span>
                  </el-form-item>
                  <el-form-item label="默认排序">
                    <el-select v-model="values['review.default_sort']" class="w-full">
                      <el-option value="score_desc" label="参考分从高到低" />
                      <el-option value="updated_desc" label="最近更新" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="审核快捷键">
                    <div class="grid w-full gap-2 text-[11.5px] sm:grid-cols-2">
                      <div>
                        <div class="mb-1 text-[10.5px] text-slate-400">入库</div>
                        <el-input v-model="values['review.shortcuts'].include" size="small" placeholder="Ctrl+Enter" />
                      </div>
                      <div>
                        <div class="mb-1 text-[10.5px] text-slate-400">暂不采用</div>
                        <el-input v-model="values['review.shortcuts'].exclude" size="small" placeholder="Ctrl+Backspace" />
                      </div>
                      <div>
                        <div class="mb-1 text-[10.5px] text-slate-400">待定</div>
                        <el-input v-model="values['review.shortcuts'].defer" size="small" placeholder="Ctrl+D" />
                      </div>
                      <div>
                        <div class="mb-1 text-[10.5px] text-slate-400">切换文献（固定）</div>
                        <el-input model-value="← / →" size="small" disabled />
                      </div>
                    </div>
                    <div class="mt-1 text-[10px] text-slate-400">格式示例：Ctrl+Enter、Alt+I、Ctrl+Shift+D；在输入框内输入时快捷键自动禁用。</div>
                  </el-form-item>
                  <el-form-item label="界面主题">
                    <el-radio-group :model-value="app.isDark ? 'dark' : 'light'" @change="(val: string) => { if ((val === 'dark') !== app.isDark) app.toggleTheme() }">
                      <el-radio-button value="light">亮色</el-radio-button>
                      <el-radio-button value="dark">暗色</el-radio-button>
                    </el-radio-group>
                  </el-form-item>
                </el-form>
              </section>
              <section class="soft-panel p-4">
                <div class="section-title">审核原则</div>
                <ul class="mt-2 list-disc space-y-1.5 pl-4 text-[11.5px] leading-5 text-slate-500">
                  <li>下载全文 ≠ 入库；AI 完成 ≠ 入库。</li>
                  <li>暂不采用会保留原始文件、分析结果和审核记录。</li>
                  <li>撤销审核会写入独立审计记录。</li>
                  <li>筛选参考分只用于排序，不是学术质量评价。</li>
                </ul>
              </section>
            </div>

            <div class="space-y-4">
              <section class="soft-panel p-4">
                <div class="flex items-center justify-between">
                  <div class="section-title">标签模板</div>
                  <el-button size="small" @click="tagVisible = true"><el-icon class="mr-1"><Plus /></el-icon>新建标签</el-button>
                </div>
                <div class="mt-3 space-y-1.5">
                  <div v-for="tag in tags" :key="tag.id" class="flex items-center gap-2 rounded-md border px-2 py-1.5" :style="{ borderColor: 'var(--app-border)' }">
                    <span class="h-2 w-2 rounded-full" :style="{ background: tag.color }"></span>
                    <span class="text-[11.5px]">{{ tag.name }}</span>
                    <span class="chip !py-0 !text-[9.5px]">{{ tag.category }}</span>
                    <span class="ml-auto text-[10px] text-slate-400">{{ tag.paper_count || 0 }} 篇</span>
                    <el-button link type="danger" size="small" @click="removeTag(tag)">删除</el-button>
                  </div>
                </div>
                <div class="mt-2 text-[10.5px] text-slate-400">可在文献详情、审核工作台或此处自由创建标签，不限定学科。</div>
              </section>
              <section class="soft-panel p-4">
                <div class="section-title">数据连续性</div>
                <div class="mt-2 space-y-1.5 text-[11.5px] leading-5 text-slate-500">
                  <div>数据库：SQLite WAL</div>
                  <div>任务：持久化队列，重启自动恢复未完成任务</div>
                  <div>备份：数据库 + 元数据 + AI 结果</div>
                  <div>全文：按“期刊/年份”物理归档，数据库保留 SHA-256</div>
                </div>
              </section>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <div class="sticky bottom-0 mt-3 flex justify-end gap-2 rounded-lg border p-3 backdrop-blur" :style="{ borderColor: 'var(--app-border)', background: 'color-mix(in srgb, var(--app-panel) 88%, transparent)' }">
      <span class="mr-auto self-center text-[10.5px] text-slate-400">API Key 加密存储，日志不记录明文；修改后请保存。</span>
      <el-button @click="loadAll">放弃修改</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存设置</el-button>
    </div>

    <el-dialog v-model="promptVisible" :title="promptMode === 'create' ? '新建提示词' : '编辑提示词'" width="760px">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="promptForm.name" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="promptForm.description" /></el-form-item>
        <el-form-item label="系统提示词">
          <el-input v-model="promptForm.content" type="textarea" :rows="16" class="font-mono" />
        </el-form-item>
        <el-alert type="info" :closable="false" show-icon title="修改内容会创建新版本，历史分析结果保留原版本号；输出字段由服务端 JSON Schema 强制校验。" />
      </el-form>
      <template #footer>
        <el-button @click="promptVisible = false">取消</el-button>
        <el-button type="primary" :loading="promptSaving" @click="savePrompt">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="tagVisible" title="新建标签" width="420px">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="newTag.name" /></el-form-item>
        <el-form-item label="类别">
          <el-select v-model="newTag.category" allow-create filterable class="w-full">
            <el-option value="研究方向" label="研究方向" />
            <el-option value="研究方法" label="研究方法" />
            <el-option value="关键技术" label="关键技术" />
            <el-option value="数据集" label="数据集" />
            <el-option value="实验类型" label="实验类型" />
            <el-option value="创新点类别" label="创新点类别" />
            <el-option value="阅读优先级" label="阅读优先级" />
            <el-option value="自定义" label="自定义" />
          </el-select>
        </el-form-item>
        <el-form-item label="颜色"><el-color-picker v-model="newTag.color" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tagVisible = false">取消</el-button>
        <el-button type="primary" @click="createTag">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="logsVisible" title="运行日志（最近 400 行）" width="900px">
      <pre class="max-h-[520px] overflow-auto whitespace-pre-wrap rounded bg-slate-950 p-3 text-[10.5px] leading-5 text-slate-300">{{ logLines.join('\n') }}</pre>
      <template #footer>
        <el-button @click="showLogs">刷新</el-button>
        <el-button type="primary" @click="logsVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
kbd {
  border: 1px solid var(--app-border);
  border-radius: 4px;
  padding: 1px 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
}
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
</style>
