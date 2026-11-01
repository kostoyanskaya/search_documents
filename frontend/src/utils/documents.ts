import type { DocumentInfo } from '../types'

export const isActiveDocument = (doc: DocumentInfo): boolean =>
  doc.status === 'queued' || doc.status === 'processing'

/**
 * One overall percentage for a whole upload batch: finished documents count
 * as 100, the others contribute the real progress reported by the backend.
 */
export function overallProgress(batchDocs: DocumentInfo[], isUploading: boolean): number {
  if (batchDocs.length === 0) return isUploading ? 0 : 100
  const sum = batchDocs.reduce((acc, d) => acc + (isActiveDocument(d) ? (d.progress ?? 0) : 100), 0)
  return sum / batchDocs.length
}

export function extensionOf(filename: string): string {
  const parts = filename.split('.')
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : 'file'
}

export function fileClassOf(ext: string): string {
  if (ext === 'pdf') return 'pdf'
  if (ext === 'docx' || ext === 'doc') return 'doc'
  if (ext === 'csv') return 'csv'
  if (ext === 'xlsx' || ext === 'xls') return 'xlsx'
  return 'other'
}
