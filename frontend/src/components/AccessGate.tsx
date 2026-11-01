import { useState } from 'react'

import { ApiError, unlockSession } from '../api/client'
import { useI18n } from '../i18n'

export function AccessGate({ onUnlocked }: { onUnlocked: () => void }) {
  const { t } = useI18n()
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    if (!code || busy) return
    setBusy(true)
    setError(null)
    try {
      await unlockSession(code)
      onUnlocked()
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? t('unlock.wrong') : err instanceof Error ? err.message : t('err.generic'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="answer-modal-overlay">
      <div className="answer-modal access-gate" role="dialog" aria-modal="true" aria-labelledby="gate-title">
        <h2 id="gate-title">{t('unlock.title')}</h2>
        <p>{t('unlock.text')}</p>
        <input
          type="password"
          autoFocus
          value={code}
          maxLength={200}
          placeholder={t('unlock.placeholder')}
          aria-label={t('unlock.placeholder')}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && submit()}
        />
        {error && <div className="error-message"><span>!</span>{error}</div>}
        <button className="ask-button" onClick={submit} disabled={busy || !code}>
          {t('unlock.button')}
        </button>
      </div>
    </div>
  )
}
