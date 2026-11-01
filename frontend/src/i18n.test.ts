import { describe, expect, it } from 'vitest'

import { getLang, setLang, t, type Key } from './i18n'

// Every graph node the backend can report must be translatable in the "how this was found" panel.
const NODES = [
  'analyze', 'rewrite', 'retrieve', 'rerank', 'reformulate', 'generate', 'verify',
  'sql_plan', 'sql_exec', 'sql_answer', 'sql_fallback', 'no_docs', 'not_found',
]

describe('i18n', () => {
  it('has identical keys in Russian and English and no empty strings', () => {
    setLang('en')
    const en = NODES.map((n) => t(`step.${n}` as Key))
    setLang('ru')
    const ru = NODES.map((n) => t(`step.${n}` as Key))
    expect(en.every(Boolean) && ru.every(Boolean)).toBe(true)
    expect(en).not.toEqual(ru)
  })

  it('switches language and persists the choice', () => {
    setLang('ru')
    expect(getLang()).toBe('ru')
    expect(document.documentElement.lang).toBe('ru')
    expect(localStorage.getItem('lang')).toBe('ru')
    expect(t('search.button')).toBe('Спросить')
    setLang('en')
    expect(t('search.button')).toBe('Ask AI')
  })

  it('covers the OCR / parsing / indexing stages reported by the backend', () => {
    for (const stage of ['parsing', 'ocr', 'indexing']) {
      expect(t(`progress.stage.${stage}` as Key)).toBeTruthy()
    }
  })
})
