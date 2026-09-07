import type { SourceHit } from '../types'
import { extensionOf, fileClassOf } from '../utils/documents'
import { Icon } from './Icon'

export function SourceCard({ source }: { source: SourceHit }) {
  const ext = extensionOf(source.filename)
  const type = fileClassOf(ext)

  return (
    <div className="source-card">
      <div className={`source-icon source-icon--${type}`}>
        <Icon name="file" size={17} />
      </div>

      <div className="source-main">
        <div className="source-top">
          <span className="source-name">{source.filename}</span>
          <span className="source-score">{Math.round(source.relevance * 100)}%</span>
        </div>

        <p className="source-excerpt">{source.excerpt}</p>
      </div>
    </div>
  )
}
