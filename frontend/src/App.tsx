import { useCallback, useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'

import { askQuestion, clearSession, deleteDocument, listDocuments, uploadDocuments } from './api/client'
import { AnswerModal } from './components/AnswerModal'
import { DocumentSidebar } from './components/DocumentSidebar'
import { ProgressOverlay } from './components/ProgressOverlay'
import { Workspace } from './components/Workspace'
import { useSimulatedProgress } from './hooks/useSimulatedProgress'
import type { DocumentInfo, HistoryEntry } from './types'
import { isActiveDocument } from './utils/documents'

import './index.css'

const DOCUMENT_POLL_INTERVAL_MS = 1500

function App() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [question, setQuestion] = useState('')
  const [lastResponse, setLastResponse] = useState<HistoryEntry | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isModalOpen, setIsModalOpen] = useState(false)

  const loadDocuments = useCallback(async () => {
    try {
      const docs = await listDocuments()
      setDocuments(docs)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load documents')
    }
  }, [])

  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  const activeDocs = documents.filter(isActiveDocument)

  useEffect(() => {
    if (activeDocs.length === 0) return
    const id = setInterval(loadDocuments, DOCUMENT_POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [activeDocs.length, loadDocuments])

  const progress = useSimulatedProgress(activeDocs.length > 0)

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (!files || files.length === 0) return

    setIsUploading(true)
    setError(null)

    try {
      const result = await uploadDocuments(Array.from(files))
      if (result.skipped_duplicates.length > 0) {
        setError(`Skipped duplicates: ${result.skipped_duplicates.join(', ')}`)
      }
      await loadDocuments()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload error')
    } finally {
      setIsUploading(false)
      event.target.value = ''
    }
  }

  const handleDelete = async (docId: string) => {
    try {
      await deleteDocument(docId)
      await loadDocuments()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Delete error')
    }
  }

  const handleAsk = async () => {
    if (!question.trim()) return
    const askedQuestion = question

    setIsLoading(true)
    setError(null)

    try {
      const response = await askQuestion(askedQuestion)
      setLastResponse({ id: Date.now().toString(), question: askedQuestion, response })
      setIsModalOpen(true)
      setQuestion('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request error')
    } finally {
      setIsLoading(false)
    }
  }

  const handleClearSession = async () => {
    if (!window.confirm('Delete all uploaded documents permanently?')) return

    try {
      await clearSession()
      await loadDocuments()
      setLastResponse(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to clear session')
    }
  }

  const showProgress = isUploading || activeDocs.length > 0
  const readyCount = documents.filter((d) => d.status === 'ready').length

  return (
    <div className="app-shell">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      {showProgress && <ProgressOverlay percent={progress} filename={activeDocs[0]?.filename} />}

      {isModalOpen && lastResponse && (
        <AnswerModal entry={lastResponse} onClose={() => setIsModalOpen(false)} />
      )}

      <DocumentSidebar
        documents={documents}
        readyCount={readyCount}
        isUploading={isUploading}
        onUpload={handleUpload}
        onDelete={handleDelete}
        onClearSession={handleClearSession}
      />

      <Workspace
        question={question}
        isLoading={isLoading}
        error={error}
        onQuestionChange={setQuestion}
        onAsk={handleAsk}
      />
    </div>
  )
}

export default App