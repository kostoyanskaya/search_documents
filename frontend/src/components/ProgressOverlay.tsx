import { Icon } from './Icon'

interface ProgressOverlayProps {
  percent: number
  filename?: string
}

export function ProgressOverlay({ percent, filename }: ProgressOverlayProps) {
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

        <div className="progress-title">Indexing documents</div>
        <div className="progress-description">AI analyzes the content and creates a search index</div>

        {filename && (
          <div className="progress-file">
            <Icon name="file" size={14} />
            {filename}
          </div>
        )}
      </div>
    </div>
  )
}
