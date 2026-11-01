import { type Key, type Lang, setLang, useI18n } from '../i18n'
import { Icon } from './Icon'

interface WorkspaceProps {
  question: string
  isLoading: boolean
  liveStep: string | null
  error: string | null
  notice: string | null
  onQuestionChange: (value: string) => void
  onAsk: () => void
}

export function Workspace({ question, isLoading, liveStep, error, notice, onQuestionChange, onAsk }: WorkspaceProps) {
  const { t, lang } = useI18n()
  const hints = [1, 2, 3].map((n) => ({
    label: t(`hint${n}.label` as 'hint1.label'),
    question: t(`hint${n}.q` as 'hint1.q'),
  }))
  return (
    <main className="workspace">
      <header className="topbar">
        <div className="mobile-brand">DocMind</div>
        <div className="topbar-status">
          <span className="online-dot" />
          {t('status.online')}
          <span className="lang-switch" role="group" aria-label="Language">
            {(['ru', 'en'] as Lang[]).map((l) => (
              <button key={l} className={l === lang ? 'lang-active' : ''} onClick={() => setLang(l)} aria-pressed={l === lang}>
                {l.toUpperCase()}
              </button>
            ))}
          </span>
        </div>
      </header>

      <div className="workspace-content">
        <section className="hero">
          <div className="hero-copy">
            <div className="hero-eyebrow">
              {t('hero.eyebrow')}
            </div>

            <h1>
              {t('hero.title1')}
              <br />
              <span>{t('hero.title2')}</span>
            </h1>

            <p>{t('hero.text')}</p>
          </div>

          <div className="hero-visual">
            <div className="lens" aria-hidden="true">
              <svg viewBox="0 0 120 120" width="100%" height="100%" fill="none">
                <defs>
                  <linearGradient id="lens-ring" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0" stopColor="#3d2fa9" />
                    <stop offset="1" stopColor="#2fb4e6" />
                  </linearGradient>
                  <radialGradient id="lens-glass" cx="35%" cy="30%" r="75%">
                    <stop offset="0" stopColor="#ffffff" stopOpacity="0.85" />
                    <stop offset="1" stopColor="#b7adff" stopOpacity="0.18" />
                  </radialGradient>
                </defs>
                {/* ручка */}
                <line x1="77" y1="77" x2="108" y2="108" stroke="url(#lens-ring)" strokeWidth="11" strokeLinecap="round" />
                {/* стекло и оправа */}
                <circle cx="50" cy="50" r="36" fill="url(#lens-glass)" stroke="url(#lens-ring)" strokeWidth="8" />
                {/* блик */}
                <path d="M30 40 A22 22 0 0 1 44 28" stroke="#fff" strokeWidth="5" strokeLinecap="round" opacity="0.9" />
              </svg>
            </div>
            <div className="orb orb-medium" />
            <div className="orb orb-small" />
            <div className="visual-grid" />
          </div>
        </section>

        <section className="search-section">
          <div className="search-label">
            <span>{t('search.label')}</span>
            <span className="shortcut">ENTER ↵</span>
          </div>

          <div className={`search-box ${isLoading ? 'search-box--loading' : ''}`}>
            <input
              value={question}
              onChange={(e) => onQuestionChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.nativeEvent.isComposing) onAsk()
              }}
              placeholder={t('search.placeholder')}
              aria-label={t('search.placeholder')}
              maxLength={2000}
              disabled={isLoading}
            />

            <button className="ask-button" onClick={onAsk} disabled={isLoading || !question.trim()}>
              {isLoading ? t('search.loading') : t('search.button')}
              {!isLoading && <Icon name="arrow" size={16} />}
            </button>
          </div>

          <div className="search-hints">
            <span>{t('search.hintsLabel')}</span>
            {hints.map((hint) => (
              <button key={hint.label} onClick={() => onQuestionChange(hint.question)}>
                {hint.label}
              </button>
            ))}
          </div>
        </section>

        <section className="results-section">
          {isLoading && (
            <div className="loading-answer" role="status" aria-live="polite">
              <div className="live-step">{liveStep ? t(`step.${liveStep}` as Key) : t('search.loading')}…</div>
              <div className="loading-line loading-line--big" />
              <div className="loading-line" />
              <div className="loading-line loading-line--small" />
            </div>
          )}
        </section>

        {notice && <div className="info-message">{notice}</div>}

        {error && (
          <div className="error-message">
            <span>!</span>
            {error}
          </div>
        )}
      </div>

      <footer className="workspace-footer">
        <span>{t('footer.private')}</span>
        <span>•</span>
        <span>{t('footer.grounded')}</span>
      </footer>
    </main>
  )
}