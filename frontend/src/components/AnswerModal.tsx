import { useEffect, useRef } from 'react'

import { type Key, useI18n } from '../i18n'
import type { HistoryEntry } from '../types'
import { Icon } from './Icon'
import { SourceCard } from './SourceCard'

interface AnswerModalProps {
  entry: HistoryEntry
  onClose: () => void
}

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

export function AnswerModal({ entry, onClose }: AnswerModalProps) {
  const { t } = useI18n()
  const dialogRef = useRef<HTMLDivElement>(null)
  const { response } = entry
  // Keep the latest callback in a ref so the focus-trap effect below runs
  // once per open; App passes a new closure on every render.
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  })

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCloseRef.current()
        return
      }
      if (e.key !== 'Tab' || !dialogRef.current) return
      const items = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE))
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      previouslyFocused?.focus()
    }
  }, [])

  const sortedSources = [...response.sources].sort((a, b) => b.relevance - a.relevance)
  const calc = response.calculation

  return (
    <div className="answer-modal-overlay" onClick={onClose}>
      <div ref={dialogRef} className="answer-modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <button className="answer-modal-close" onClick={onClose} aria-label={t('answer.close')}>
          <Icon name="close" size={20} />
        </button>

        <div className="answer-modal-content">
          <div className="question-row">
            <div className="question-avatar">{t('answer.you')}</div>
            <div className="question-text">{entry.question}</div>
          </div>

          <div className="ai-answer">
            <div className="answer-header">
              <div className="ai-avatar">
                <Icon name="spark" size={16} />
              </div>
              <span>{t('answer.ai')}</span>
              <span className="answer-time">{response.elapsed_ms} ms</span>
            </div>

            <p className={response.found ? '' : 'not-found'}>{response.answer}</p>
          </div>

          {calc && (
            <div className="calc-block">
              <div className="sources-heading">
                <span>{t('answer.calculation')}</span>
                <span>
                  {calc.row_count} {t('answer.rows')}
                  {calc.truncated ? ` · ${t('answer.truncated')}` : ''}
                </span>
              </div>
              <pre className="calc-sql">{calc.sql}</pre>
              <div className="calc-table-wrap">
                <table className="calc-table">
                  <thead>
                    <tr>
                      {calc.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {calc.rows.map((row, i) => (
                      <tr key={i}>
                        {row.map((v, j) => (
                          <td key={j}>{v === null ? '—' : String(v)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {sortedSources.length > 0 && (
            <div className="sources-block">
              <div className="sources-heading">
                <span>{t('answer.sources')}</span>
                <span>{String(sortedSources.length).padStart(2, '0')}</span>
              </div>
              <div className="sources-list">
                {sortedSources.map((s, i) => (
                  <SourceCard key={`${s.doc_id}-${s.location}-${i}`} source={s} />
                ))}
              </div>
            </div>
          )}

          {response.steps.length > 0 && (
            <details className="how-block">
              <summary>{t('answer.how')}</summary>
              {response.rewritten_query && (
                <p className="how-rewritten">
                  {t('answer.rewritten')} <em>{response.rewritten_query}</em>
                </p>
              )}
              <ol className="how-steps">
                {response.steps.map((s, i) => (
                  <li key={i}>
                    <strong>{t(`step.${s.node}` as Key)}</strong>
                    <span>{s.info}</span>
                    <small>{s.ms} ms</small>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      </div>
    </div>
  )
}
