import type { HistoryEntry } from '../types'
import { Icon } from './Icon'
import { SourceCard } from './SourceCard'

interface AnswerModalProps {
  entry: HistoryEntry
  onClose: () => void
}

export function AnswerModal({ entry, onClose }: AnswerModalProps) {
  const sortedSources = [...entry.response.sources].sort((a, b) => b.relevance - a.relevance)

  return (
    <div className="answer-modal-overlay" onClick={onClose}>
      <div className="answer-modal" onClick={(e) => e.stopPropagation()}>
        <button className="answer-modal-close" onClick={onClose} aria-label="Закрыть">
          <Icon name="close" size={20} />
        </button>

        <div className="answer-modal-content">
          <div className="question-row">
            <div className="question-avatar">YOU</div>
            <div className="question-text">{entry.question}</div>
          </div>

          <div className="ai-answer">
            <div className="answer-header">
              <div className="ai-avatar">
                <Icon name="spark" size={16} />
              </div>
              <span>AI ANSWER</span>
              <span className="answer-time">{entry.response.elapsed_ms} ms</span>
            </div>

            <p className={entry.response.found ? '' : 'not-found'}>{entry.response.answer}</p>
          </div>

          {sortedSources.length > 0 && (
            <div className="sources-block">
              <div className="sources-heading">
                <span>ДАННЫЕ НАЙДЕНЫ В ЭТИХ ДОКУМЕНТАХ</span>
                <span>{String(sortedSources.length).padStart(2, '0')}</span>
              </div>
              <div className="sources-list">
                {sortedSources.map((s) => (
                  <SourceCard key={s.doc_id} source={s} />
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
