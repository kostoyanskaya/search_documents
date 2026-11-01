import { t } from '../i18n'
import type { DocumentInfo, HistoryTurn, QueryResponse, SessionStatus, UploadResponse } from '../types'

// Empty by default: same-origin requests (Vite dev proxy / reverse proxy in production),
// which keeps the session cookie first-party.
const BASE_URL = import.meta.env.VITE_API_URL ?? ''

export class ApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

/** FastAPI returns `detail` as a string (our errors) or as a list of validation issues. */
function detailToMessage(detail: unknown): string | null {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : null))
      .filter(Boolean)
    return msgs.length ? msgs.join('; ') : null
  }
  return null
}

async function failFrom(res: Response): Promise<never> {
  let body: { detail?: unknown; code?: string } = {}
  try {
    body = await res.json()
  } catch {
    // body is not JSON - keep the generic message
  }
  if (res.status === 429) throw new ApiError(t('err.rate'), 429)
  if (res.status === 503) throw new ApiError(t('err.busy'), 503)
  const message = detailToMessage(body.detail) ?? `${t('err.status')} (${res.status})`
  throw new ApiError(message, res.status, body.code)
}

async function send(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${BASE_URL}${url}`, { credentials: 'include', ...init })
  } catch {
    throw new ApiError(t('err.network'), 0)
  }
}

async function request<T>(url: string, init: RequestInit): Promise<T> {
  const res = await send(url, init)
  if (!res.ok) await failFrom(res)
  return res.json() as Promise<T>
}

export function uploadDocuments(files: File[]): Promise<UploadResponse> {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  return request<UploadResponse>('/api/documents/upload', { method: 'POST', body: formData })
}

export const listDocuments = (): Promise<DocumentInfo[]> => request('/api/documents', {})

export async function deleteDocument(docId: string): Promise<void> {
  await request(`/api/documents/${encodeURIComponent(docId)}`, { method: 'DELETE' })
}

const jsonPost = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export function askQuestion(question: string, history: HistoryTurn[] = []): Promise<QueryResponse> {
  return request<QueryResponse>('/api/query', jsonPost({ question, history }))
}

/**
 * Streams the agent's progress: `onStep(node)` fires as each graph node finishes, the promise resolves
 * with the final answer. Falls back to the plain endpoint if the browser cannot stream.
 */
export async function askQuestionStream(
  question: string,
  history: HistoryTurn[],
  onStep: (node: string) => void,
  signal?: AbortSignal,
): Promise<QueryResponse> {
  const res = await send('/api/query/stream', { ...jsonPost({ question, history }), signal })
  if (!res.ok) await failFrom(res)
  if (!res.body) return askQuestion(question, history)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const event = /^event: (.*)$/m.exec(raw)?.[1]
      const data = /^data: (.*)$/m.exec(raw)?.[1]
      if (!event || !data) continue
      const payload = JSON.parse(data)
      if (event === 'step') onStep(payload.node)
      else if (event === 'result') return payload as QueryResponse
      else if (event === 'error') throw new ApiError(payload.message ?? t('err.generic'), payload.status ?? 500)
    }
  }
  throw new ApiError(t('err.network'), 0)
}

export const getSessionStatus = (): Promise<SessionStatus> => request('/api/session', {})

export async function unlockSession(code: string): Promise<void> {
  await request('/api/session/unlock', jsonPost({ code }))
}

export async function clearSession(): Promise<void> {
  await request('/api/session', { method: 'DELETE' })
}
