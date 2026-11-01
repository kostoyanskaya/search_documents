import type { ChangeEvent } from 'react'

import { useI18n } from '../i18n'
import type { DocumentInfo } from '../types'
import { extensionOf, fileClassOf } from '../utils/documents'
import { Icon } from './Icon'

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
  const { t } = useI18n()
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <Icon name="spark" size={20} />
        </div>
        <div>
          <div className="brand-name">DocMind</div>
          <div className="brand-version">{t('sidebar.brand')}</div>
        </div>
      </div>

      <div className="sidebar-section">
        <div className="sidebar-label">
          {t('sidebar.documents')}
          <span>{documents.length}</span>
        </div>

        <label className="upload-button">
          <Icon name="upload" size={17} />
          <span>{t('sidebar.add')}</span>
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
              <span>{t('sidebar.empty')}</span>
            </div>
          ) : (
            documents.map((doc) => {
              const ext = extensionOf(doc.filename)

              return (
                <div className="document-item" key={doc.doc_id}>
                  <div className={`document-type document-type--${fileClassOf(ext)}`}>{ext}</div>

                  <div className="document-info">
                    <div className="document-name">{doc.filename}</div>
                    {doc.status === 'failed' && doc.error && <div className="document-error">{doc.error}</div>}
                    <div className="document-status">
                      <span className={`status-dot status-dot--${doc.status}`} />
                      {t(`status.${doc.status}` as 'status.ready')}
                    </div>
                  </div>

                  <button
                    className="delete-button"
                    onClick={() => onDelete(doc.doc_id)}
                    aria-label={`${t('sidebar.delete')} ${doc.filename}`}
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
            <strong>{t('sidebar.online')}</strong>
            <small>{readyCount} {t('sidebar.indexed')}</small>
          </div>
        </div>

        <button className="clear-session-button" onClick={onClearSession}>
          <Icon name="trash" size={15} />
          {t('sidebar.clear')}
        </button>
      </div>
    </aside>
  )
}
