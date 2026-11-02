export type ReviewStatus =
  | 'pending_fulltext'
  | 'pending_ai'
  | 'analyzing'
  | 'pending_review'
  | 'included'
  | 'excluded'
  | 'deferred'
  | 'analysis_failed'

export type AiStatus = 'not_analyzed' | 'queued' | 'running' | 'completed' | 'failed' | 'cached'
export type TaskStatus = 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled' | 'awaiting_import'
export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'cancelling'

export interface Tag {
  id: string
  name: string
  category: string
  color: string
  paper_count?: number
}

export interface PaperFile {
  id: string
  original_filename: string
  stored_filename: string
  relative_path: string
  file_format: string
  mime_type: string
  size_bytes: number
  sha256: string
  is_primary: boolean
  origin: string
  parse_status: string
  parse_error: string
  page_count: number
  created_at: string | null
}

export interface InnovationPoint {
  name: string
  problem?: string
  method?: string
  difference?: string
  evidence?: string
  page?: number | null
  inferred?: boolean
}

export interface EvidenceItem {
  section?: string
  page?: number | null
  quote?: string
  supports?: string
}

export interface LimitationItem {
  type: 'claimed' | 'inferred' | string
  text: string
}

export interface KeyResultItem {
  metric?: string
  value?: string
  setting?: string
  conclusion?: string
}

export interface Analysis {
  id: string
  paper_id: string
  job_id?: string | null
  provider: string
  model: string
  is_mock: boolean
  prompt_version: number
  parameters: Record<string, unknown>
  analysis_scope: 'abstract' | 'fulltext' | 'fulltext_chunked' | 'metadata'
  input_chars: number
  one_sentence_summary: string
  research_problem: string
  main_method: string
  claimed_innovations: InnovationPoint[]
  inferred_contributions: InnovationPoint[]
  innovation_summary: string
  key_results: KeyResultItem[]
  research_value: string
  limitations: LimitationItem[]
  screening_score: number
  screening_reason: string
  evidence: EvidenceItem[]
  missing_information: string[]
  tags_suggestion: string[]
  is_current: boolean
  is_edited: boolean
  edited_at?: string | null
  original_result?: Record<string, unknown> | null
  created_at: string
  updated_at: string
  raw_response?: string
}

export interface PaperSummary {
  id: string
  title: string
  authors: string[]
  authors_text: string
  journal: string
  year: number | null
  publication_date: string | null
  publication_date_precision: string
  publication_date_raw: string
  doi: string | null
  source: string
  source_id: string | null
  source_url: string
  abstract: string
  keywords: string[]
  paper_type: string
  language: string
  fulltext_status: string
  parse_status: string
  ai_status: AiStatus
  review_status: ReviewStatus
  review_label: string
  duplicate_status: 'none' | 'suspected' | 'confirmed' | string
  duplicate_of_id: string | null
  metadata_source: string
  file_count: number
  has_fulltext: boolean
  primary_file: PaperFile | null
  tags: Tag[]
  created_at: string
  updated_at: string
  imported_at: string | null
  one_sentence_summary: string
  innovation_summary: string
  screening_score: number | null
  analysis_id: string | null
  is_mock: boolean
  task_names: string[]
  analysis?: Analysis | null
  evidence?: EvidenceItem[]
  review_history?: ReviewRecord[]
}

export interface TextInfo {
  char_count: number
  page_count: number
  quality: string
  extractor: string
  error: string
  sections: Array<{ name: string; label: string; page: number; char_start: number }>
}

export interface PaperDetail extends PaperSummary {
  files: PaperFile[]
  text_info: TextInfo | null
  analysis: Analysis | null
  analysis_history: Analysis[]
  notes: ResearchNote[]
  reviews: ReviewRecord[]
  task_ids: string[]
  raw_metadata: Record<string, unknown>
  online_first_date: string | null
  update_date: string | null
  library_warning?: string
}

export interface ResearchNote {
  id: string
  paper_id: string
  title: string
  content: string
  note_type: string
  created_at: string
  updated_at: string
}

export interface ReviewRecord {
  id: string
  paper_id: string
  action: string
  from_status: string
  to_status: string
  note: string
  reviewer: string
  snapshot: Record<string, unknown>
  previous_status: string | null
  is_undo: boolean
  created_at: string
  paper_title?: string
}

export interface SearchTask {
  id: string
  name: string
  source: string
  paper_type: string
  journal: string
  keywords: string
  match_mode: string
  start_date: string | null
  end_date: string | null
  sort_by: string
  import_mode: string
  status: TaskStatus
  progress: number
  discovered_count: number
  imported_count: number
  analyzed_count: number
  included_count: number
  error_message: string
  conditions_snapshot: Record<string, unknown>
  extra: Record<string, unknown>
  started_at: string | null
  finished_at: string | null
  last_run_at: string | null
  created_at: string
  updated_at: string
}

export interface RetrievalGuide {
  task_id: string
  task_name: string
  source: string
  mode: string
  official_entry: string
  fields: Record<string, unknown>
  steps: string[]
  notices: string[]
  import_modes: Array<{ id: string; label: string; available: boolean; description: string }>
  authorized_config?: { enabled: boolean; configured: boolean }
}

export interface BackgroundJob {
  id: string
  job_type: string
  status: JobStatus
  payload: Record<string, unknown>
  priority: number
  attempts: number
  max_attempts: number
  progress: number
  message: string
  error: string
  cancel_requested: boolean
  task_id: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface ImportJob {
  id: string
  job_type: string
  status: JobStatus
  source_path: string
  task_id: string | null
  background_job_id: string | null
  total: number
  processed: number
  imported: number
  duplicates: number
  failed: number
  errors: Array<Record<string, string>>
  detail: Record<string, any>
  started_at: string | null
  finished_at: string | null
  created_at: string
  updated_at: string
}

export interface AiJob {
  id: string
  paper_id: string
  status: AiStatus
  provider: string
  model: string
  prompt_version: number
  input_chars: number
  chunk_count: number
  analysis_scope: string
  tokens_prompt: number
  tokens_completion: number
  estimated_cost: number
  attempts: number
  max_attempts: number
  error: string
  result_id: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  paper?: { id: string; title: string } | null
  result?: Analysis | null
  progress?: number
  message?: string
}

export interface PromptTemplate {
  id: string
  name: string
  content: string
  version: number
  is_default: boolean
  is_active: boolean
  description: string
  created_at: string
  updated_at: string
}

export interface InnovationItem {
  id: string
  paper_id: string
  result_id: string
  seq: number
  name: string
  core_technique: string
  description: string
  evidence: string
  page: number | null
  note: string
  tags_snapshot: string[]
  created_at: string
  updated_at: string
  paper: {
    id: string
    title: string
    authors: string[]
    journal: string
    year: number | null
    doi: string | null
  } | null
}

export interface TreeNode {
  key: string
  label: string
  count: number
  icon?: string
  children?: TreeNode[]
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  [key: string]: unknown
}

export interface DashboardData {
  papers: {
    total: number
    fulltext: number
    analyzed: number
    pending_review: number
    included: number
    excluded: number
    pending_fulltext: number
    failed: number
    innovations: number
  }
  recent_tasks: SearchTask[]
  recent_papers: PaperSummary[]
  ai: {
    tokens_prompt: number
    tokens_completion: number
    estimated_cost: number
    job_count: number
    avg_score: number | null
    mock_results: number
  }
  activity: Array<{ date: string; count: number }>
  top_journals: Array<{ journal: string; count: number }>
  storage_bytes: number
}

export interface ProviderPreset {
  id: string
  label: string
  kind: string
  base_url: string
  default_model: string
  note: string
}

export interface PublicSettings {
  values: Record<string, any>
  providers: ProviderPreset[]
  ai_configured: boolean
  watcher: { running: boolean; path: string; last_result: string }
}

export interface SystemInfo {
  app: string
  version: string
  python: string
  platform: string
  sqlite: string
  data_dir: string
  database: string
  database_bytes: number
  papers: number
  files: number
  fulltext_bytes: number
  runner: { running: boolean; active: number; worker_concurrency: number; ai_concurrency: number }
  watcher: { running: boolean; path: string }
  ai: { configured: boolean; provider: string; model: string }
  paths: Record<string, string>
  permissions: Record<string, unknown>
}
