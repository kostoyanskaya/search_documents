import { describe, expect, it } from 'vitest'

import type { DocumentInfo } from '../types'
import { overallProgress } from './documents'

const doc = (status: DocumentInfo['status'], progress: number): DocumentInfo => ({
  doc_id: String(Math.random()),
  filename: 'a.pdf',
  file_type: 'pdf',
  size_bytes: 1,
  status,
  chunks: 0,
  progress,
  stage: '',
  uploaded_at: '',
})

describe('overallProgress', () => {
  it('is one percentage for the whole batch, not per document', () => {
    const batch = [doc('ready', 100), doc('processing', 50), doc('queued', 0), doc('processing', 50)]
    expect(overallProgress(batch, false)).toBe(50)
  })

  it('does not drop when a document finishes', () => {
    const before = overallProgress([doc('processing', 80), doc('processing', 40)], false)
    const after = overallProgress([doc('ready', 100), doc('processing', 40)], false)
    expect(after).toBeGreaterThanOrEqual(before)
  })

  it('shows 0 while uploading and 100 when there is nothing to do', () => {
    expect(overallProgress([], true)).toBe(0)
    expect(overallProgress([], false)).toBe(100)
  })
})
