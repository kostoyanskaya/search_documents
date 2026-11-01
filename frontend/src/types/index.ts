export type DocStatus = 'queued' | 'processing' | 'ready' | 'failed'

export interface DocumentInfo {
  doc_id: string
  filename: string
  file_type: string
  size_bytes: number
  status: DocStatus
  chunks: number
  progress: number
  stage: string
  uploaded_at: string
  error?: string | null
}

export interface UploadResponse {
  accepted: DocumentInfo[]
  skipped_duplicates: string[]
}

export interface SourceHit {
  doc_id: string
  filename: string
  location: string
  excerpt: string
  relevance: number
  quote_verified: boolean
  kind: 'text' | 'table'
}

export interface StepInfo {
  node: string
  ms: number
  info: string
}

export interface Calculation {
  sql: string
  columns: string[]
  rows: (string | number | null)[][]
  row_count: number
  truncated: boolean
}

export interface QueryResponse {
  answer: string
  sources: SourceHit[]
  found: boolean
  language: 'ru' | 'en'
  elapsed_ms: number
  route: 'text' | 'sql' | 'none'
  steps: StepInfo[]
  rewritten_query: string | null
  calculation: Calculation | null
}

export interface HistoryEntry {
  id: string
  question: string
  response: QueryResponse
}

export interface HistoryTurn {
  question: string
  answer: string
}

export interface SessionStatus {
  access_required: boolean
  unlocked: boolean
}
