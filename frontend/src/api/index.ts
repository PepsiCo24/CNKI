import http from './client'
import type {
  AiJob,
  Analysis,
  BackgroundJob,
  CaptureSession,
  DashboardData,
  ImportJob,
  InnovationItem,
  PageResult,
  PaperDetail,
  PaperSummary,
  PromptTemplate,
  PublicSettings,
  RetrievalGuide,
  SearchTask,
  SystemInfo,
  Tag,
  TreeNode,
} from '@/types'

export const dashboardApi = {
  get: () => http.get<never, DashboardData>('/dashboard'),
}

export interface PaperQuery {
  page?: number
  page_size?: number
  q?: string
  folder?: string
  tree_key?: string
  journal?: string
  year?: number | null
  tag?: string
  review_status?: string
  ai_status?: string
  fulltext_status?: string
  author?: string
  task_id?: string
  collection_id?: string
  paper_type?: string
  date_from?: string
  date_to?: string
  sort?: string
  order?: string
}

export const papersApi = {
  list: (params: PaperQuery) => http.get<never, PageResult<PaperSummary>>('/papers', { params }),
  tree: () => http.get<never, { nodes: TreeNode[] }>('/papers/tree'),
  get: (id: string) => http.get<never, PaperDetail>(`/papers/${id}`),
  update: (id: string, payload: Record<string, unknown>) => http.put<never, PaperDetail>(`/papers/${id}`, payload),
  remove: (id: string) => http.delete<never, { id: string }>(`/papers/${id}`),
  text: (id: string) => http.get<never, { content: string; page_map: any[]; sections: any[]; page_count: number; char_count: number; quality: string; available: boolean; error: string }>(`/papers/${id}/text`),
  parse: (id: string) => http.post<never, BackgroundJob>(`/papers/${id}/parse`),
  analyze: (id: string, force = false) => http.post<never, { jobs: AiJob[] }>(`/papers/${id}/analyze`, null, { params: { force } }),
  attachFile: (id: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http.post<never, { status: string; message: string }>(`/papers/${id}/attach-file`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  addTags: (id: string, tags: string[], replace = false) => http.post<never, { tags: Tag[] }>(`/papers/${id}/tags`, { tags, replace }),
  removeTag: (id: string, tagId: string) => http.delete(`/papers/${id}/tags/${tagId}`),
  notes: (id: string) => http.get<never, { items: any[] }>(`/papers/${id}/notes`),
  addNote: (id: string, content: string, noteType = 'general', title = '') =>
    http.post<never, any>(`/papers/${id}/notes`, { content, note_type: noteType, title }),
  updateNote: (noteId: string, payload: Record<string, unknown>) => http.put<never, any>(`/notes/${noteId}`, payload),
  deleteNote: (noteId: string) => http.delete(`/notes/${noteId}`),
  resolveDuplicate: (id: string, action: 'keep_separate' | 'confirm_duplicate') =>
    http.post<never, PaperDetail>(`/papers/${id}/duplicate`, { action }),
  reviews: (id: string) => http.get<never, { items: any[] }>(`/papers/${id}/reviews`),
  fileUrl: (id: string) => `/api/papers/${id}/file`,
}

export interface TaskPayload {
  name: string
  journal: string
  keywords: string
  match_mode: string
  start_date: string | null
  end_date: string | null
  sort_by: string
  import_mode: string
  paper_type: string
}

export const tasksApi = {
  list: (params: { page?: number; page_size?: number; status?: string; q?: string }) =>
    http.get<never, PageResult<SearchTask> & { status_counts: Record<string, number> }>('/search-tasks', { params }),
  create: (payload: TaskPayload) =>
    http.post<never, { task: SearchTask; guide: RetrievalGuide }>('/search-tasks', payload),
  get: (id: string) =>
    http.get<never, { task: SearchTask; guide: RetrievalGuide; logs: any[] }>(`/search-tasks/${id}`),
  update: (id: string, payload: Partial<TaskPayload>) =>
    http.put<never, { task: SearchTask; guide: RetrievalGuide }>(`/search-tasks/${id}`, payload),
  remove: (id: string) => http.delete<never, { id: string }>(`/search-tasks/${id}`),
  run: (id: string, mode?: string) => http.post<never, any>(`/search-tasks/${id}/run`, mode ? { mode } : {}),
  pause: (id: string) => http.post<never, SearchTask>(`/search-tasks/${id}/pause`),
  resume: (id: string) => http.post<never, any>(`/search-tasks/${id}/resume`),
  cancel: (id: string) => http.post<never, SearchTask>(`/search-tasks/${id}/cancel`),
  retry: (id: string) => http.post<never, any>(`/search-tasks/${id}/retry`),
  guide: (id: string) => http.get<never, RetrievalGuide>(`/search-tasks/${id}/guide`),
  papers: (id: string, params: { page?: number; page_size?: number; q?: string; review_status?: string }) =>
    http.get<never, PageResult<PaperSummary>>(`/search-tasks/${id}/papers`, { params }),
  logs: (id: string) => http.get<never, { items: any[] }>(`/search-tasks/${id}/logs`),
  associate: (id: string, paperIds: string[]) =>
    http.post<never, { added: number }>(`/search-tasks/${id}/papers`, { paper_ids: paperIds }),
  silentCaptureStart: (id: string) =>
    http.post<never, CaptureSession>(`/search-tasks/${id}/silent-capture`),
  silentCaptureGet: (id: string) =>
    http.get<never, CaptureSession>(`/search-tasks/${id}/silent-capture`),
  silentCaptureCancel: (id: string) =>
    http.post<never, CaptureSession>(`/search-tasks/${id}/silent-capture/cancel`),
}

export const importsApi = {
  metadata: (file: File, taskId?: string, format = 'auto') => {
    const form = new FormData()
    form.append('file', file)
    if (taskId) form.append('task_id', taskId)
    form.append('format', format)
    return http.post<never, ImportJob>('/imports/metadata', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  uploadFiles: (files: File[], taskId?: string) => {
    const form = new FormData()
    files.forEach((file) => form.append('files', file))
    if (taskId) form.append('task_id', taskId)
    return http.post<never, { outcomes: any[]; imported: number }>('/imports/files', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  scan: (path: string | null, taskId?: string) =>
    http.post<never, ImportJob>('/imports/scan', { path, task_id: taskId }),
  list: (params: { page?: number; page_size?: number; status?: string; task_id?: string }) =>
    http.get<never, PageResult<ImportJob>>('/imports', { params }),
  get: (id: string) => http.get<never, ImportJob>(`/imports/${id}`),
  retry: (id: string) => http.post<never, ImportJob>(`/imports/${id}/retry`),
  formats: () => http.get<never, { metadata: any[]; fulltext: any[] }>('/imports/formats'),
}

export const aiApi = {
  analyze: (paperIds: string[], force = false, promptTemplateId?: string) =>
    http.post<never, { jobs: AiJob[] }>('/ai/analyze', { paper_ids: paperIds, force, prompt_template_id: promptTemplateId }),
  analyzePending: (limit = 20, force = false) =>
    http.post<never, { jobs: AiJob[]; message?: string }>('/ai/analyze-pending', null, { params: { limit, force } }),
  jobs: (params: { page?: number; page_size?: number; status?: string }) =>
    http.get<never, PageResult<AiJob>>('/ai/jobs', { params }),
  job: (id: string) => http.get<never, AiJob>(`/ai/jobs/${id}`),
  cancel: (id: string) => http.post<never, AiJob>(`/ai/jobs/${id}/cancel`),
  stats: () =>
    http.get<never, {
      status_counts: Record<string, number>
      tokens_prompt: number
      tokens_completion: number
      estimated_cost: number
      models: Array<{ model: string; count: number }>
      recent_jobs: AiJob[]
    }>('/ai/stats'),
  result: (id: string) => http.get<never, Analysis & { raw_response: string }>(`/ai/results/${id}`),
  editResult: (id: string, payload: Record<string, unknown>) => http.put<never, Analysis>(`/ai/results/${id}`, payload),
  paperAnalysis: (paperId: string) =>
    http.get<never, { current: Analysis | null; history: Analysis[]; ai_status: string }>(`/ai/papers/${paperId}/analysis`),
}

export const reviewApi = {
  queue: (params: { status?: string; sort?: string; q?: string; page?: number; page_size?: number }) =>
    http.get<never, PageResult<PaperSummary> & { counts: Record<string, number> }>('/review/queue', { params }),
  detail: (paperId: string) => http.get<never, PaperDetail>(`/review/${paperId}`),
  action: (paperId: string, payload: { action: string; note?: string; tags?: string[]; expected_status?: string }) =>
    http.post<never, any>(`/review/${paperId}/action`, payload),
  undo: (paperId: string, reviewId?: string) =>
    http.post<never, any>(`/review/${paperId}/undo`, reviewId ? { review_id: reviewId } : {}),
  batch: (paperIds: string[], action: string, note = '', tags: string[] = []) =>
    http.post<never, any>('/review/batch', { paper_ids: paperIds, action, note, tags }),
  history: (paperId: string) => http.get<never, { items: any[] }>(`/review/history/${paperId}`),
  recent: () => http.get<never, { items: any[] }>('/review/recent'),
}

export const libraryApi = {
  papers: (params: PaperQuery) => http.get<never, PageResult<PaperSummary>>('/library/papers', { params }),
  detail: (id: string) => http.get<never, PaperDetail>(`/library/papers/${id}`),
  facets: () =>
    http.get<never, {
      total: number
      journals: Array<{ name: string; count: number }>
      years: Array<{ year: number; count: number }>
      tags: Array<{ name: string; category: string; color: string; count: number }>
    }>('/library/facets'),
}

export const innovationsApi = {
  list: (params: { q?: string; paper_id?: string; tag?: string; page?: number; page_size?: number; sort?: string }) =>
    http.get<never, PageResult<InnovationItem>>('/innovations', { params }),
  facets: () =>
    http.get<never, {
      papers: Array<{ id: string; title: string; journal: string }>
      tags: Array<{ name: string; color: string; category: string }>
    }>('/innovations/facets'),
  update: (id: string, payload: Record<string, unknown>) => http.put<never, InnovationItem>(`/innovations/${id}`, payload),
}

export const tagsApi = {
  list: () => http.get<never, { items: Tag[] }>('/tags'),
  create: (name: string, category = '通用', color = '#409EFF') => http.post<never, Tag>('/tags', { name, category, color }),
  update: (id: string, payload: Record<string, unknown>) => http.put<never, Tag>(`/tags/${id}`, payload),
  remove: (id: string) => http.delete(`/tags/${id}`),
}

export const collectionsApi = {
  list: () => http.get<never, { items: any[] }>('/collections'),
  create: (name: string, parentId?: string) => http.post<never, any>('/collections', { name, parent_id: parentId }),
  remove: (id: string) => http.delete(`/collections/${id}`),
  addPapers: (id: string, paperIds: string[]) => http.post(`/collections/${id}/papers`, { paper_ids: paperIds }),
  removePapers: (id: string, paperIds: string[]) => http.delete(`/collections/${id}/papers`, { data: { paper_ids: paperIds } }),
}

export const promptsApi = {
  list: () => http.get<never, { items: PromptTemplate[] }>('/prompts'),
  create: (payload: Record<string, unknown>) => http.post<never, PromptTemplate>('/prompts', payload),
  update: (id: string, payload: Record<string, unknown>) => http.put<never, PromptTemplate>(`/prompts/${id}`, payload),
  activate: (id: string) => http.post<never, PromptTemplate>(`/prompts/${id}/activate`),
  setDefault: (id: string) => http.post<never, PromptTemplate>(`/prompts/${id}/set-default`),
  duplicate: (id: string) => http.post<never, PromptTemplate>(`/prompts/${id}/duplicate`),
  archive: (id: string) => http.delete<never, PromptTemplate>(`/prompts/${id}`),
}

export const settingsApi = {
  get: () => http.get<never, PublicSettings>('/settings'),
  update: (values: Record<string, unknown>) =>
    http.put<never, { values: Record<string, any>; watcher: any; message: string }>('/settings', { values }),
  testAi: (payload: { provider?: string; base_url?: string; model?: string }) =>
    http.post<never, { ok: boolean; error?: string; model?: string; sample?: string; is_mock?: boolean }>('/settings/test-ai', payload),
  storage: () =>
    http.get<never, {
      data_dir: string
      database_bytes: number
      directories: Record<string, { path: string; bytes: number }>
      disk_total: number
      disk_free: number
    }>('/settings/storage'),
  watchStatus: () => http.get<never, { running: boolean; path: string }>('/settings/watch/status'),
  startWatch: () => http.post<never, any>('/settings/watch/start'),
  stopWatch: () => http.post<never, any>('/settings/watch/stop'),
}

export const exportsApi = {
  create: (payload: {
    format: string
    paper_ids?: string[]
    filters?: Record<string, unknown>
    include_notes?: boolean
    include_analysis?: boolean
  }) => http.post<never, any>('/exports', payload),
  list: () => http.get<never, { items: any[] }>('/exports'),
  backup: () => http.post<never, any>('/exports/backup'),
  backups: () => http.get<never, { items: any[] }>('/exports/backups'),
}

export const systemApi = {
  info: () => http.get<never, SystemInfo>('/system/info'),
  logs: (lines = 200) => http.get<never, { lines: string[]; path: string }>('/system/logs', { params: { lines } }),
  reindex: () => http.post<never, { indexed: number }>('/system/reindex'),
  jobs: (params: { page?: number; page_size?: number; status?: string; job_type?: string }) =>
    http.get<never, PageResult<BackgroundJob> & { runner: any }>('/system/jobs', { params }),
  cancelJob: (id: string) => http.post<never, BackgroundJob>(`/system/jobs/${id}/cancel`),
  duplicates: () => http.get<never, { items: any[] }>('/system/duplicates'),
}
