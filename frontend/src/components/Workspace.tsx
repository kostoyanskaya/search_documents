import { Icon } from './Icon'

const QUESTION_HINTS: { label: string; question: string }[] = [
  { 
    label: 'data by year', 
    question: 'Find data for 2023' 
  },
  { 
    label: 'financial indicators', 
    question: 'What revenue or profit is indicated?' 
  },
  { 
    label: 'market shares', 
    question: 'What market shares are indicated for companies?' 
  }
];

interface WorkspaceProps {
  question: string
  isLoading: boolean
  error: string | null
  onQuestionChange: (value: string) => void
  onAsk: () => void
}

export function Workspace({ question, isLoading, error, onQuestionChange, onAsk }: WorkspaceProps) {
  return (
    <main className="workspace">
      <header className="topbar">
        <div className="mobile-brand">DocMind</div>
        <div className="topbar-status">
          <span className="online-dot" />
          AI READY
        </div>
      </header>

      <div className="workspace-content">
        <section className="hero">
          <div className="hero-copy">
            <div className="hero-eyebrow">
              <Icon name="spark" size={14} />
              AI DOCUMENT INTELLIGENCE
            </div>

            <h1>
              Ask your
              <br />
              <span>documents.</span>
            </h1>

            <p>Upload documents, find the document you need, and get information on key questions</p>
          </div>

          <div className="hero-visual">
            <div className="orb orb-large" />
            <div className="orb orb-medium" />
            <div className="orb orb-small" />
            <div className="visual-grid" />
          </div>
        </section>

        <section className="search-section">
          <div className="search-label">
            <span>ASK AI</span>
            <span className="shortcut">ENTER ↵</span>
          </div>

          <div className={`search-box ${isLoading ? 'search-box--loading' : ''}`}>
            <Icon name="spark" size={20} />

            <input
              value={question}
              onChange={(e) => onQuestionChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onAsk()
              }}
              placeholder="Enter a key question to search for a document"
              disabled={isLoading}
            />

            <button className="ask-button" onClick={onAsk} disabled={isLoading || !question.trim()}>
              {isLoading ? 'Searching...' : 'Ask AI'}
              {!isLoading && <Icon name="arrow" size={16} />}
            </button>
          </div>

          <div className="search-hints">
            <span>Например:</span>
            {QUESTION_HINTS.map((hint) => (
              <button key={hint.label} onClick={() => onQuestionChange(hint.question)}>
                {hint.label}
              </button>
            ))}
          </div>
        </section>

        <section className="results-section">
          {isLoading && (
            <div className="loading-answer">
              <div className="loading-line loading-line--big" />
              <div className="loading-line" />
              <div className="loading-line loading-line--small" />
            </div>
          )}
        </section>

        {error && (
          <div className="error-message">
            <span>!</span>
            {error}
          </div>
        )}
      </div>

      <footer className="workspace-footer">
        <span>PRIVATE DOCUMENT SEARCH</span>
        <span>•</span>
        <span>GROUNDED AI</span>
      </footer>
    </main>
  )
}
