import type { DocumentInfo } from '../types'

export const isActiveDocument = (doc: DocumentInfo): boolean =>
  doc.status === 'queued' || doc.status === 'processing'

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
