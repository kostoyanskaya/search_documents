import { useI18n } from '../i18n'
import type { SourceHit } from '../types'
import { extensionOf, fileClassOf } from '../utils/documents'
import { Icon } from './Icon'

export function SourceCard({ source }: { source: SourceHit }) {
  const { t } = useI18n()
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
          <span className="source-location">{source.kind === 'table' ? `Σ ${source.location}` : source.location}</span>
        </div>

        <p
          className={`source-excerpt ${source.quote_verified ? 'source-excerpt--verified' : ''}`}
          title={source.quote_verified ? t('answer.verified') : t('answer.unverified')}
        >
          {source.quote_verified && <span aria-hidden="true">“</span>}
          {source.excerpt}
          {source.quote_verified && <span aria-hidden="true">”</span>}
        </p>
      </div>
    </div>
  )
}
