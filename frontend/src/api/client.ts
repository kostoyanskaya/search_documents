import type { DocumentInfo, QueryResponse, UploadResponse } from '../types'

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `Ошибка запроса (${res.status})`
    try {
      const body = await res.json()
      message = body.detail ?? message
    } catch {
      // тело не JSON — оставляем сообщение по умолчанию
    }
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

export async function uploadDocuments(files: File[]): Promise<UploadResponse> {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))

  const res = await fetch(`${BASE_URL}/api/documents/upload`, {
    method: 'POST',
    body: formData,
    credentials: 'include',
  })
  return handle<UploadResponse>(res)
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const res = await fetch(`${BASE_URL}/api/documents`, { credentials: 'include' })
  return handle<DocumentInfo[]>(res)
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/documents/${docId}`, {
    method: 'DELETE',
    credentials: 'include',
  })
  await handle(res)
}

export async function askQuestion(question: string): Promise<QueryResponse> {
  const res = await fetch(`${BASE_URL}/api/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
    credentials: 'include',
  })
  return handle<QueryResponse>(res)
}

export async function clearSession(): Promise<void> {
  const res = await fetch(`${BASE_URL}/api/session`, {
    method: 'DELETE',
    credentials: 'include',
  })
  await handle(res)
}

export function getDocumentFileUrl(docId: string): string {
  return `${BASE_URL}/api/documents/${docId}/file`
}
