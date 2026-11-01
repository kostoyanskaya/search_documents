import { useI18n } from '../i18n'
import { Icon } from './Icon'

interface ProgressOverlayProps {
  percent: number
  filename?: string
  stage?: string
  done?: number
  total?: number
  onDismiss: () => void
}

export function ProgressOverlay({ percent, filename, stage, done = 0, total = 0, onDismiss }: ProgressOverlayProps) {
  const { t } = useI18n()
  return (
    <div className="progress-overlay">
      <div className="progress-window">
        <div className="progress-orbit">
          <div className="progress-glow" />
          <div className="progress-number">
            {Math.round(percent)}
            <span>%</span>
          </div>
        </div>

        <div className="progress-title">{t('progress.title')}</div>
        <div className="progress-description">{stage ?? t('progress.text')}</div>

        {total > 1 && (
          <div className="progress-count">
            {t('progress.files')} {Math.min(Math.max(done, 0), total)} / {total}
          </div>
        )}

        {filename && (
          <div className="progress-file">
            <Icon name="file" size={14} />
            {filename}
          </div>
        )}

        <button className="progress-dismiss" onClick={onDismiss}>
          {t('progress.hide')}
        </button>
      </div>
    </div>
  )
}
