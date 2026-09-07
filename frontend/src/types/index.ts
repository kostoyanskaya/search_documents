
export type DocStatus = 'queued' | 'processing' | 'ready' | 'failed'

export interface DocumentInfo {
  doc_id: string
  filename: string
  file_type: string
  size_bytes: number
  status: DocStatus
  chunks: number
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
  excerpt: string
  relevance: number
}

export interface QueryResponse {
  answer: string
  sources: SourceHit[]
  found: boolean
  elapsed_ms: number
}

export interface HistoryEntry {
  id: string
  question: string
  response: QueryResponse
}
