import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'

import {
  ApiError,
  askQuestionStream,
  clearSession,
  deleteDocument,
  getSessionStatus,
  listDocuments,
  uploadDocuments,
} from './api/client'
import { AccessGate } from './components/AccessGate'
import { AnswerModal } from './components/AnswerModal'
import { DocumentSidebar } from './components/DocumentSidebar'
import { ProgressOverlay } from './components/ProgressOverlay'
import { Workspace } from './components/Workspace'
import { type Key, t } from './i18n'
import type { DocumentInfo, HistoryEntry, HistoryTurn } from './types'
import { isActiveDocument, overallProgress } from './utils/documents'

import './index.css'

const POLL_MS = 1500
const MAX_HISTORY_TURNS = 3

function App() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([])
  const [question, setQuestion] = useState('')
  const [lastResponse, setLastResponse] = useState<HistoryEntry | null>(null)
  const [history, setHistory] = useState<HistoryTurn[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [liveStep, setLiveStep] = useState<string | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [progressDismissed, setProgressDismissed] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [locked, setLocked] = useState(false)
  // ids of every document of the current upload batch (kept until the
  // whole batch is finished) so the progress is ONE overall percentage
  const [batchIds, setBatchIds] = useState<Set<string>>(new Set())
  const pollInFlight = useRef(false)

  const report = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.code === 'access_code_required') {
      setLocked(true)
      return
    }
    setError(err instanceof Error ? err.message : t('err.generic'))
  }, [])

  const loadDocuments = useCallback(async () => {
    if (pollInFlight.current) return
    pollInFlight.current = true
    try {
      setDocuments(await listDocuments())
    } catch (err) {
      report(err)
    } finally {
      pollInFlight.current = false
    }
  }, [report])

  useEffect(() => {
    getSessionStatus()
      .then((s) => (s.access_required && !s.unlocked ? setLocked(true) : loadDocuments()))
      .catch(report)
  }, [loadDocuments, report])

  const activeDocs = documents.filter(isActiveDocument)

  useEffect(() => {
    if (activeDocs.length === 0 || locked) return
    const id = setInterval(loadDocuments, POLL_MS)
    return () => clearInterval(id)
  }, [activeDocs.length, locked, loadDocuments])

  // Remember every document of the running batch; forget them when all are done.
  useEffect(() => {
    if (activeDocs.length > 0) {
      setBatchIds((prev) => {
        const missing = activeDocs.filter((d) => !prev.has(d.doc_id))
        if (missing.length === 0) return prev
        const next = new Set(prev)
        missing.forEach((d) => next.add(d.doc_id))
        return next
      })
    } else if (!isUploading) {
      setBatchIds((prev) => (prev.size === 0 ? prev : new Set()))
    }
  }, [activeDocs, isUploading])

  // Overall progress of the whole batch: finished documents count as 100 %,
  // the others contribute the real progress reported by the backend
  // (parsing / OCR / embedding). Result: one number that only grows.
  const batchDocs = documents.filter((d) => batchIds.has(d.doc_id))
  const progress = overallProgress(batchDocs, isUploading)
  const stageKey = activeDocs.find((d) => d.stage)?.stage

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (!files || files.length === 0) return
    setIsUploading(true)
    setError(null)
    setNotice(null)
    setProgressDismissed(false)
    try {
      const result = await uploadDocuments(Array.from(files))
      if (result.skipped_duplicates.length > 0) {
        setNotice(`${t('notice.duplicates')} ${result.skipped_duplicates.join(', ')}`)
      }
      await loadDocuments()
    } catch (err) {
      report(err)
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
      report(err)
    }
  }

  const handleAsk = async () => {
    if (!question.trim() || isLoading) return
    const asked = question.trim()
    setIsLoading(true)
    setLiveStep(null)
    setError(null)
    setNotice(null)
    try {
      const response = await askQuestionStream(asked, history.slice(-MAX_HISTORY_TURNS), setLiveStep)
      setLastResponse({ id: Date.now().toString(), question: asked, response })
      if (response.found) {
        setHistory((h) => [...h, { question: asked, answer: response.answer.slice(0, 1500) }].slice(-MAX_HISTORY_TURNS))
      }
      setIsModalOpen(true)
      setQuestion('')
    } catch (err) {
      report(err)
    } finally {
      setIsLoading(false)
      setLiveStep(null)
    }
  }

  const handleClearSession = async () => {
    try {
      await clearSession()
      setLastResponse(null)
      setHistory([])
      setNotice(null)
      await loadDocuments()
    } catch (err) {
      report(err)
    }
  }

  const showProgress = (isUploading || activeDocs.length > 0) && !progressDismissed
  const readyCount = documents.filter((d) => d.status === 'ready').length
  const stageLabel = stageKey ? t(`progress.stage.${stageKey}` as Key) : undefined

  return (
    <div className="app-shell">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />

      {locked && (
        <AccessGate
          onUnlocked={() => {
            setLocked(false)
            setError(null)
            loadDocuments()
          }}
        />
      )}

      {showProgress && !locked && (
        <ProgressOverlay
          percent={progress}
          filename={activeDocs[0]?.filename}
          done={batchDocs.length - activeDocs.length}
          total={batchDocs.length}
          stage={stageLabel}
          onDismiss={() => setProgressDismissed(true)}
        />
      )}

      {isModalOpen && lastResponse && <AnswerModal entry={lastResponse} onClose={() => setIsModalOpen(false)} />}

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
        liveStep={liveStep}
        error={error}
        notice={notice}
        onQuestionChange={setQuestion}
        onAsk={handleAsk}
      />
    </div>
  )
}

export default App
