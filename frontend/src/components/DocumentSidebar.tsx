import type { ChangeEvent } from 'react'

import type { DocumentInfo } from '../types'
import { extensionOf, fileClassOf } from '../utils/documents'
import { Icon } from './Icon'

const STATUS_LABELS: Record<DocumentInfo['status'], string> = {
  ready: 'Indexed',
  processing: 'Processing',
  queued: 'Queued',
  failed: 'Failed',
}

interface DocumentSidebarProps {
  documents: DocumentInfo[]
  readyCount: number
  isUploading: boolean
  onUpload: (event: ChangeEvent<HTMLInputElement>) => void
  onDelete: (docId: string) => void
  onClearSession: () => void
}

export function DocumentSidebar({
  documents,
  readyCount,
  isUploading,
  onUpload,
  onDelete,
  onClearSession,
}: DocumentSidebarProps) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <Icon name="spark" size={20} />
        </div>
        <div>
          <div className="brand-name">DocMind</div>
          <div className="brand-version">AI DOCUMENT AGENT</div>
        </div>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-label">
          DOCUMENTS
          <span>{documents.length}</span>
        </div>

        <label className="upload-button">
          <Icon name="upload" size={17} />
          <span>Add the documents</span>
          <input
            type="file"
            multiple
            accept=".pdf,.docx,.csv,.xlsx,.xls"
            onChange={onUpload}
            disabled={isUploading}
          />
        </label>

        <div className="document-list">
          {documents.length === 0 ? (
            <div className="documents-empty">
              <div className="empty-icon">
                <Icon name="file" size={19} />
              </div>
              <span>Your documents will appear here</span>
            </div>
          ) : (
            documents.map((doc) => {
              const ext = extensionOf(doc.filename)

              return (
                <div className="document-item" key={doc.doc_id}>
                  <div className={`document-type document-type--${fileClassOf(ext)}`}>{ext}</div>

                  <div className="document-info">
                    <div className="document-name">{doc.filename}</div>
                    <div className="document-status">
                      <span className={`status-dot status-dot--${doc.status}`} />
                      {STATUS_LABELS[doc.status]}
                    </div>
                  </div>

                  <button
                    className="delete-button"
                    onClick={() => onDelete(doc.doc_id)}
                    aria-label={`Удалить ${doc.filename}`}
                  >
                    <Icon name="trash" size={15} />
                  </button>
                </div>
              )
            })
          )}
        </div>
      </div>

      <div className="sidebar-bottom">
        <div className="system-status">
          <span className="online-dot" />
          <div>
            <strong>AI system online</strong>
            <small>{readyCount} indexed</small>
          </div>
        </div>

        <button className="clear-session-button" onClick={onClearSession}>
          <Icon name="trash" size={15} />
          Delete my data
        </button>
      </div>
    </aside>
  )
}
